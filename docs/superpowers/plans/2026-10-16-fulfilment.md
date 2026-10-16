# Fulfilment and cancellation — implementation plan

> For agentic workers: executed natively in one session (superpowers:executing-plans), test-first.

**Goal:** staff move their store's orders to completion, support can move them too, and an order can be cancelled
(T4) with its stock and money given back, all audited (R7, R11).

**Architecture:** two new database rules (a widened BR14 and BR21) carry the money invariants; one new service
module `app/services/fulfilment.py` holds the queue, the status move and T4; a thin router; two admin pages and
one storefront component.

**Tech stack:** PostgreSQL 18, FastAPI + psycopg2 (hand-written SQL), pytest; Next.js 16, openapi-typescript.

**Spec:** `docs/superpowers/specs/2026-10-16-fulfilment-design.md`

## Global constraints

- Run from `/Users/ethan/orca/workspaces/JBhifi/blobfish`. Tests: `/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/pytest`
  (rebuilds `jbhifi_test_sp2`). API on 8002, web on 3002. No `docker compose`.
- New SQL appended under `-- ===== SP2: fulfilment & cancellation =====`; the one changed object (the payment CHECK)
  is edited in place and listed in the PR.
- Triggers raise `USING ERRCODE = 'check_violation', CONSTRAINT = 'brNN_…'`. `%s` parameters only.
- Lock the order `FOR UPDATE` first, call `get_order` last. Route handlers are `def`.
- Team docs and code comments in English; no AI attribution anywhere.

## Review focus

1. A retried request after a lost answer (same `from_status`) → 409 `status_changed` with `{status}`, never a second
   history row or refund. *(Task 2/3 tests: repeat a move / a cancel.)*
2. A cancel on a zero-total order → no refund row, still cancelled. *(Task 3.)*
3. A delivery order restocks the warehouse it ships from, not a retail store. *(Task 3.)*
4. Support asking for a store that doesn't exist → 404, other callers 403 first. *(Task 2.)*
5. Status filter with an unknown value → 422, not a 500. *(Task 2.)*

---

### Task 1: Database rules (BR14 widened, BR21)

**Files:** modify `sql/01_tables.sql` (payment CHECK), `sql/02_rules.sql` (append), `tests/test_business_rules.py`.

- [ ] Write failing tests in `tests/test_business_rules.py` (helpers `place_order`, `pay`, `advance` exist):
  - `test_br14_a_refund_without_a_return_is_only_for_cancelling`: a paid order takes a refund without a return
    (allowed); the `collected_order` fixture refuses one with `br14_refund_without_return_is_cancellation`; after
    the paid order is refunded and cancelled, a second one is refused with the same name.
  - `test_br21_an_order_is_cancelled_only_when_fully_refunded`: a paid order can't move to cancelled
    (`br21_cancelled_order_refunded`); refunded 0.01 short, still refused; refunded in full, it moves. A zero-total
    order is cancelled with no refund.
  - In `test_br14_refunds`: line 355's expected name becomes `br14_refund_without_return_is_cancellation`; line 359's
    becomes `br14_charge_has_no_return`.
- [ ] Run, expect failures on the names.
- [ ] `01_tables.sql`: replace `br14_refund_has_return CHECK ((kind = 'refund') = (return_id IS NOT NULL))` with
  `br14_charge_has_no_return CHECK (kind = 'refund' OR return_id IS NULL)` and a comment.
- [ ] Append to `02_rules.sql`:

```sql
-- ===== SP2: fulfilment & cancellation =====

-- BR14: a refund without a return is the order's cancellation refund. It is taken only while the order can still
-- be cancelled (BR09's transition table), so a completed or cancelled order can't take one. The order row is
-- locked first, as br14_refunds_within_charged does, so this can't race a status move.
CREATE FUNCTION br14_check_cancellation_refund() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind = 'refund' AND NEW.return_id IS NULL
       AND NOT EXISTS (SELECT 1
                       FROM customer_order o
                       JOIN order_status_transition t
                         ON t.fulfilment_method = o.fulfilment_method AND t.from_status = o.status
                       WHERE o.order_id = NEW.order_id AND t.to_status = 'cancelled'
                       FOR UPDATE OF o) THEN
        RAISE EXCEPTION 'Order % can''t be refunded without a return: only an order being cancelled can',
                        NEW.order_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'br14_refund_without_return_is_cancellation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br14_refund_without_return_is_cancellation
    BEFORE INSERT ON payment
    FOR EACH ROW EXECUTE FUNCTION br14_check_cancellation_refund();

-- BR21: a cancelled order keeps none of the customer's money: it moves to cancelled only when its refunds equal
-- its charges (the mirror of BR20). Named br21_…, so it fires after the br09_ triggers. The UPDATE holds the order
-- row, and every payment INSERT locks that row first (BR14, BR20), so no payment can slip in before COMMIT.
CREATE FUNCTION br21_check_cancelled_refunded() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    held NUMERIC(10,2);
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status IS DISTINCT FROM 'cancelled' THEN
        SELECT balance INTO held FROM v_order_payment WHERE order_id = NEW.order_id;
        IF held <> 0 THEN
            RAISE EXCEPTION 'Order % can''t be cancelled while % of its payment is still held', NEW.order_id, held
                USING ERRCODE = 'check_violation', CONSTRAINT = 'br21_cancelled_order_refunded';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER br21_cancelled_order_refunded
    BEFORE UPDATE OF status ON customer_order
    FOR EACH ROW EXECUTE FUNCTION br21_check_cancelled_refunded();
```

- [ ] Run the full `tests/test_business_rules.py`; expect PASS. Commit
  `Fulfilment: a refund without a return is a cancellation refund (BR14), and a cancelled order keeps no money (BR21)`.

### Task 2: Store queue and status moves

**Files:** create `app/schemas/fulfilment.py`, `app/services/fulfilment.py`, `app/routers/fulfilment.py`,
`tests/fulfilment_support.py`, `tests/test_fulfilment.py`; modify `app/main.py` (one router), `tests/test_permissions.py`.

**Produces:** `fulfilment.list_store_orders(cur, actor, store_id, statuses: list[str] | None) -> list[dict]`;
`fulfilment.advance_order(cur, actor, order_id, body: StatusMove) -> dict`; `_lock_order(cur, order_id) -> dict | None`;
schemas `OrderStatus` (Literal of the 8 statuses), `StatusMove {from_status: OrderStatus, to_status: Literal[picking,
ready, shipped, collected, delivered]}`, `CancelRequest {from_status: OrderStatus}` (both `extra="forbid"`).
Test helper `bought(*, quantity=2, method="click_collect", store_id=1, stock=5) -> Bought(order_id, email,
product_id, store_id)`: a committed product stocked at the store, a new customer (one address), and a real checkout
(`tests.checkout_support.checkout_request`), so stock really is taken.

- [ ] Tests (`tests/test_fulfilment.py`, through `TestClient`, signing in with `as_staff(14)` Aiden store 1,
  `as_staff(16)` Isla store 2, `as_staff(40)` Nora support, `as_customer(email)`):
  - `test_a_collection_order_moves_paid_picking_ready_collected` and
    `test_a_delivery_order_moves_paid_picking_shipped_delivered` (a warehouse order moved by Nora, since tests
    can sign in only as the four seeded staff): each move 200, `status` updated, the history row's
    `changed_by_staff_id` is the mover.
  - `test_support_moves_an_order_and_the_history_names_them` (Nora → `changed_by_staff_id == 40`).
  - `test_an_illegal_move_is_refused_by_br09` (paid → ready on C&C; paid → shipped on C&C) → 409 br09, nothing logged.
  - `test_paid_and_cancelled_are_not_moves` → 422.
  - `test_another_stores_staff_and_customers_cannot_move_an_order` → 403 `other_store` / `staff_only`; a missing
    order → 403 `other_store` for Isla, 404 for Nora.
  - `test_a_stale_screen_is_told_the_current_status` (from_status paid when it is picking) → 409 `status_changed`,
    detail `{"status": "picking"}`; and the same move sent twice → second 409, one history row.
  - `test_the_queue_lists_the_stores_orders_oldest_first_with_a_status_filter`, `test_the_queue_is_for_that_stores_staff_and_support`
    (Isla on store 1 → 403; customer → 403; Nora on store 99 → 404; `status=bogus` → 422).
- [ ] Run, expect 404s (no routes).
- [ ] Implement. Service sketch:

```python
def _lock_order(cur, order_id):
    cur.execute("""SELECT order_id, customer_id, status, fulfilment_method, fulfilling_store_id
                   FROM customer_order WHERE order_id = %s FOR UPDATE""", (order_id,))
    return cur.fetchone()

def _require_mover(actor, order):            # store staff of the fulfilling store, or support
    actor = require_staff(actor)
    if actor.is_support:
        if order is None: raise NotFound("Order", ...)
        return actor
    if order is None or order["fulfilling_store_id"] != actor.store_id:
        raise ApiError(403, "other_store", "That order is fulfilled by another store.")
    return actor

def _check_from_status(order, from_status):
    if order["status"] != from_status:
        raise ApiError(409, "status_changed", f"This order is already {order['status']}.", {"status": order["status"]})

def _set_status(cur, actor, order_id, status):
    staff_id = str(actor.id) if actor.kind == "staff" else ""
    cur.execute("SELECT set_config('app.staff_id', %s, true)", (staff_id,))
    cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))
```

  `advance_order`: `require_actor` → `_lock_order` → `_require_mover` → `_check_from_status` → `_set_status` →
  `get_order`. `list_store_orders`: `require_store_or_support_reader`, then store exists (404), then
  `SUMMARY_SELECT + WHERE fulfilling_store_id = %s [AND status = ANY(%s)] ORDER BY placed_at, order_id`.
  Router: `GET /stores/{store_id}/orders` (`status: list[OrderStatus] | None = Query(None)`), `POST /orders/{order_id}/status`.
- [ ] Permission rows: `("GET", "/stores/1/orders", None, {"aiden", "olivia", "nora"})`,
  `("POST", "/orders/999999/status", {"from_status": "paid", "to_status": "picking"}, {"nora"})` (store staff: 403
  for a missing order; Nora gets 404).
- [ ] Run `tests/test_fulfilment.py tests/test_permissions.py`; PASS. Commit
  `Fulfilment: a store's order queue, and its staff or support move an order along (R7, R11)`.

### Task 3: T4 cancel

**Files:** modify `app/services/fulfilment.py`, `app/routers/fulfilment.py`, `tests/test_permissions.py`; create
`tests/test_cancellation.py`.

**Produces:** `fulfilment.cancel_order(cur, actor, order_id, body: CancelRequest) -> dict`; `_restock(cur, order)`,
`_refund(cur, order_id)` (module-level so tests can monkeypatch).

- [ ] Tests: `test_a_customer_cancels_a_paid_order_and_gets_stock_and_money_back` (refund = charge; `refunded`
  equals `charged`, `balance` 0; stock back to its starting quantity; last history row `paid → cancelled`, staff
  NULL); `test_a_customer_cannot_cancel_once_picking_has_started` (ready → 403 `customer_cancel_before_picking`);
  `test_store_staff_cancel_an_uncollected_order` (Aiden, ready → 200, staff 14 logged, stock back);
  `test_store_staff_cannot_cancel_while_picking` (409 br09, nothing changed); `test_support_cannot_cancel`;
  `test_only_the_customer_and_the_fulfilling_store_cancel` (other customer 403 `not_your_order`, Isla 403
  `other_store`); `test_a_zero_total_order_is_cancelled_without_a_refund`; `test_a_delivery_restocks_the_warehouse_it_ships_from`;
  `test_cancelling_twice_is_told_it_is_already_cancelled` (second → 409 `status_changed` `{status: cancelled}`, one refund).
- [ ] Run, expect 404/405.
- [ ] Implement `cancel_order`: `require_actor` → `_lock_order` → who (customer: own else 403 `not_your_order`;
  support: 403 `support_cannot_cancel`; store staff: fulfilling store else 403 `other_store`) → `_check_from_status`
  → customer and status not in (placed, paid) → 403 `customer_cancel_before_picking` → if status in (paid, ready):
  `_restock` (lines by ascending product_id; per line `INSERT INTO inventory (store_id, product_id, quantity)
  VALUES (%s, %s, 0) ON CONFLICT DO NOTHING`, then `UPDATE inventory SET quantity = quantity + %s WHERE store_id = %s
  AND product_id = %s`, as T3) → `_refund` (`INSERT … SELECT order_id, 'refund', balance FROM v_order_payment WHERE order_id = %s
  AND balance > 0`) → `_set_status(…, 'cancelled')` → `get_order`. Router `POST /orders/{order_id}/cancel`.
  Module docstring: T4 steps and the lock order (spec §3).
- [ ] Permission row: `("POST", "/orders/999999/cancel", {"from_status": "paid"}, set())` — everyone is refused
  for a missing order (customers `not_your_order`, store staff `other_store`, support `support_cannot_cancel`).
- [ ] Run; PASS. Commit `Fulfilment: cancel an order in one transaction (T4): restock, refund, cancelled`.

### Task 4: Concurrency and rollback evidence

**Files:** create `tests/test_fulfilment_transactions.py` (service-level, own connections, `run_together`).

- [ ] Tests: `test_two_clerks_making_the_same_move_at_once_one_wins` (one result, one `status_changed`, one new
  history row); `test_a_cancel_and_a_move_at_once_have_one_winner`; `test_the_customer_and_the_store_cancelling_at_once_refund_once`
  (one refund row, stock back once); `test_a_failed_refund_rolls_back_the_whole_cancellation` (monkeypatch `_refund`
  to raise: status, stock, payments, history unchanged); `test_a_short_refund_is_refused_by_br21_and_the_restock_rolls_back`
  (monkeypatch `_refund` to refund balance − 0.01).
- [ ] Run five times (`for i in 1 2 3 4 5; do pytest tests/test_fulfilment_transactions.py -q; done`); all PASS.
  Commit `Fulfilment: concurrent moves and cancellations have one winner, and a failed cancellation changes nothing`.

### Task 5: Web

**Files:** regenerate `web/src/lib/api/schema.d.ts` (API on 8002); create `web/src/app/admin/orders/page.tsx`,
`web/src/app/admin/orders/[id]/page.tsx`, `web/src/components/shop/cancel-order.tsx`; one line each in
`web/src/components/sidebar.tsx` and `web/src/app/(shop)/orders/[id]/page.tsx`; add `OrderStatus` type export if needed.

- [ ] Start the API: `/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/fastapi dev app/main.py --port 8002`
  (background); `cd web && npx openapi-typescript http://127.0.0.1:8002/openapi.json -o src/lib/api/schema.d.ts`.
- [ ] Admin queue: filters "To do" (paid, picking, ready, shipped) / "All" / one status; support picks a store
  (inventory page's StoreSelect pattern); rows link to the detail. Detail: header, lines, payment, `OrderTimeline`;
  forward-move buttons from `allowed_next_statuses` minus `cancelled`; cancel (two-step) for store staff when
  `cancelled` is allowed; `status_changed` → notice and reload.
- [ ] Storefront `CancelOrder({ order, onCancelled })`: shown when `status === "paid"`; inline confirm; on success or
  `status_changed`, `onCancelled()` reloads.
- [ ] `npm --prefix web run typecheck`, `lint`, `build`, `test:unit`; all clean. Commit
  `Fulfilment: the admin order queue and order page, and a cancel button on the customer's order`.

### Task 6: Docs and PR

- [ ] Full `pytest`. `doc/progress.md` entry at the top (English): what's on the branch, decisions, verification
  actually run, browser walk-through not done.
- [ ] Commit, push, open the PR to `main` with "Changed existing objects" (the payment CHECK, `test_br14_refunds`)
  and "Plan changes" (BR14 wording, BR21, T4, R7 notes, §4 payment row, §8 test files). Send the link and numbers to
  `jbhifi-35`.

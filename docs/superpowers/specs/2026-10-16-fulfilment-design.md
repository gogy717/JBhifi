# Sub-project 2: Fulfilment and cancellation — design

Status: approved on 2026-10-16. Branch `gogy717/sp2-order-fulfilment-cancellation`, from `main` at `2e9ee2e` plus
`d8a836f`. Requirements R7 (staff move their store's orders to completion) and R11 (every move is audited).
Sub-project 1 (orders, `2026-10-02-orders-design.md`) left these out: staff status moves, the store queue and
cancellation. Reuses ideas from Yuhang's branch (`transition_order`, `cancel_order`, the admin order pages), but
not its `order_cancellation` table, deferred BR14 triggers or `flush_deferred`.

## 1. Decisions

| Question | Choice |
|---|---|
| Refund on cancelling a paid order? | Yes, in the same transaction. Every committed order is `paid` (T1 moves placed → paid before it commits), so "cancel only `placed`" would cancel nothing |
| How a cancellation refund is recorded | A refund **without** a `return_id` is the order's cancellation refund (no new table; who and when are in BR09's history) |
| Restock | Yes: each line's quantity goes back to `fulfilling_store_id`, where T1 took it. Only when the order is `paid` or `ready`: T1 takes stock and pays in one transaction, so a `placed` order took none. Committed orders are never `placed`, but the service still decides from the actual status. No `stock_adjustment` row (T-7 logs manual changes only; checkout's stock change isn't logged either) |
| Who cancels | The order's customer while it is `placed` or `paid` (before picking starts); the fulfilling store's staff whenever BR09 allows (`placed`, `paid`, `ready` — "not collected in time"); support never |
| Who moves an order forward | The fulfilling store's staff, **and support** (the user's choice); the history records the mover's `staff_id` |
| Concurrency guard | Each request carries the `from_status` the screen showed; the service compares it under the row lock |

## 2. Database (appended under `-- ===== SP2: fulfilment & cancellation =====`)

- **Changed (listed in the PR):** in `payment`, `br14_refund_has_return CHECK ((kind = 'refund') = (return_id IS
  NOT NULL))` becomes `br14_charge_has_no_return CHECK (kind = 'refund' OR return_id IS NULL)`. A refund with a
  `return_id` (SP3) is still valid.
- **New trigger `br14_refund_without_return_is_cancellation`** (`BEFORE INSERT` on `payment`): a refund with no
  return locks its order `FOR UPDATE` and needs a `(method, status, 'cancelled')` row in the transition table. So
  a completed or already cancelled order can't take one, and a second one can't follow the cancellation.
- **New rule BR21 `br21_cancelled_order_refunded`** (`BEFORE UPDATE OF status` on `customer_order`): a move to
  `cancelled` needs charges − refunds = 0. It mirrors BR20 (paid only when charged exactly the total). It is named
  `br21_…` so it fires after the `br09_…` triggers, so an illegal move is reported as BR09 first. It holds under
  concurrency: the UPDATE holds the order row, and every payment INSERT locks that row first (the BR14 and BR20
  triggers), so no payment can arrive between the check and the COMMIT.
- Only the service guarantees that a refund without a return is followed by the cancellation (same transaction,
  with rollback tests). Without deferred triggers, one direction of the pair has to rest on the service. BR21
  keeps the direction that protects the customer: a cancelled order never keeps their money.

## 3. Transactions (`app/services/fulfilment.py`; one call = one transaction, `READ COMMITTED`)

**T4 — cancel an order** (the second multi-step transaction with rollback, report §4):
1. `SELECT … FROM customer_order WHERE order_id = %s FOR UPDATE`. Lock first, `get_order` last (plan §5).
2. Who: customer (own order) / store staff (fulfilling store) / support (refused). 403 comes before any 404.
3. `from_status` ≠ current status → 409 `status_changed`, detail `{status}`.
4. A customer may cancel only a `placed` or `paid` order, else 403 `customer_cancel_before_picking`.
5. Restock (status `paid` or `ready`): `UPDATE inventory SET quantity = quantity + %s WHERE store_id = %s AND
   product_id = %s`, in ascending `product_id`. The row exists: T1 took the stock from it, and inventory rows are
   never deleted.
6. Refund (`_refund`, its own function so a test can make it fail): `INSERT INTO payment (order_id, kind, amount)
   SELECT order_id, 'refund', balance FROM v_order_payment WHERE order_id = %s AND balance > 0`.
7. `set_config('app.staff_id', <staff id, or '' for the customer>, true)`, then `UPDATE … SET status =
   'cancelled'`. BR09 checks the move and logs who made it; BR21 checks the refund.
8. `get_order`. Any failure → ROLLBACK: no status change, stock change, refund or history.

**Lock order and deadlocks.** T4 locks: order `FOR UPDATE` → inventory rows by ascending `product_id` → the order
again in the payment triggers (already held) → `get_order`'s `FOR SHARE` (already held). T1 also locks inventory
by ascending `product_id`, and the only order it locks is its own new, uncommitted row, which no other
transaction can wait for. So T1 never waits for a lock T4 holds. Two T4s lock shared products in the same order.
T4 and a status move on the same order both lock the order row first, so one waits for the other.

**Advance an order**: lock `FOR UPDATE` → who (fulfilling store's staff, or support) → `from_status` check →
`set_config('app.staff_id', …)` → `UPDATE … SET status = %s`. BR09 decides whether the move is legal (409
`br09_order_status_transition`); the service doesn't repeat the rule. **Two clerks, one move:** the second waits
on the row lock and then reads the committed status (`READ COMMITTED` re-reads the row after the wait). That
status differs from its `from_status`, so it gets 409 `status_changed`: one success, one history row.

**Why `from_status`, not an `Idempotency-Key`:** a status move or a cancellation can happen at most once from a
given status, so the status the screen showed is enough as a retry key. A retry after a lost answer gets 409
`status_changed` with the current status, and the page refreshes to show the result. The same check stops a stale
screen from cancelling an order that has moved on (e.g. `paid` on screen, `ready` in the database).

## 4. API (`app/routers/fulfilment.py`, `app/schemas/fulfilment.py`; `OrderDetail` and `get_order` unchanged)

| Endpoint | Caller | Errors |
|---|---|---|
| `GET /stores/{store_id}/orders?status=…` (repeatable) → `OrderSummary[]`, oldest first | that store's staff, support | 401; 403 `staff_only` / `other_store`; 404 (support: no such store, as `list_adjustments`); 422 |
| `POST /orders/{id}/status` `{from_status, to_status}` → `OrderDetail`; `to_status` ∈ picking, ready, shipped, collected, delivered (else 422: `paid` is T1's, `cancelled` is T4's) | fulfilling store's staff, support | 401; 403 `staff_only` / `other_store` (also for a missing id); 404 (support); 409 `status_changed`, `br09_order_status_transition` |
| `POST /orders/{id}/cancel` `{from_status}` → `OrderDetail` | the order's customer, the fulfilling store's staff | 401; 403 `not_your_order` / `other_store` (also for a missing id), `customer_cancel_before_picking`, `support_cannot_cancel`; 409 `status_changed`, `br09_order_status_transition`, `br21_cancelled_order_refunded` |

The permission helpers are private to `fulfilment.py`. Pages choose their buttons from `allowed_next_statuses`
and the signed-in caller; the service is still the authority.

## 5. Web

- `/admin/orders`: the store's queue. Filters: "To do" (paid, picking, ready, shipped), "All", or one status.
  Staff see their own store; support picks a store (the inventory page's store select). Each row links to:
- `/admin/orders/[id]`: header, lines, payment, timeline (`components/shop/order-timeline`). One button per
  forward move in `allowed_next_statuses`. A cancel button for the store's staff when `cancelled` is allowed.
  On 409 `status_changed`: a notice, then a reload.
- One "Orders" line in `components/sidebar.tsx`. Storefront: `components/shop/cancel-order.tsx`, shown while the
  order is `paid`, with an inline two-step confirm; one line in `(shop)/orders/[id]/page.tsx`.

## 6. Tests

- `test_business_rules.py`: `test_br14_a_refund_without_a_return_is_only_for_cancelling`,
  `test_br21_an_order_is_cancelled_only_when_fully_refunded`; `test_br14_refunds` moves to the new names.
- `test_fulfilment.py`: every legal forward move of both methods, with the mover's `staff_id` in the history
  (support's too); an illegal move → 409 br09; `paid` / `cancelled` → 422; another store → 403; a customer → 403;
  stale → 409 `status_changed` `{status}`; the queue: listing, filter, callers.
- `test_cancellation.py`: a customer cancels `paid` (refund = charge, stock back at the fulfilling store,
  history staff NULL); a customer can't cancel `ready` (403); staff cancel `ready`; staff can't cancel `picking`
  (409 br09); support 403; another customer 403; a zero total has no refund row; a delivery restocks the
  warehouse it ships from.
- `test_fulfilment_transactions.py`: two clerks, same move at once → one 200 and one 409, one new history row;
  cancel vs. move → one winner; customer and clerk cancel at once → one refund, stock back once; `_refund` raises
  → nothing changed; `_refund` refunds 0.01 short → BR21 refuses and the restock rolls back too.
- `test_permissions.py`: rows for the three endpoints. Web: `typecheck`, `lint`, `build`, `test:unit`. The
  browser walk-through needs the user's Clerk password, so it is left for after the merge and noted in the PR.

## 7. Out of scope

Returns (SP3), reports and support lookup (SP4), seed data. A seed that cancels a paid order must insert its
refund before the status change (BR21).

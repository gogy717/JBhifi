# Sub-project 1: Orders — design

Status: approved in conversation on 2026-10-02 (sections 1–3 and four follow-up choices). Branch: `ethan/orders`,
from `main` at `37d331e` (Clerk sign-in merged). This is the first of four sub-projects that finish the Phase 1
business logic by reusing Yuhang's branch (`4a69838`), which was written against a demo login:
**1 Orders** → 2 Fulfilment & cancellation → 3 Returns (T2) → 4 Reports & support lookup, then a short
concurrency-evidence step.

## 1. Goal and approach

Customers browse with a price filter and per-store stock, check out (T1) for delivery or Click & Collect, follow
their orders with a status timeline, and manage delivery addresses — on the real sign-in. Yuhang's code for this
slice is **ported and adapted**, not rewritten: his endpoint and page structure are kept, wired to main's
`app/auth.py`, with his over-engineering removed and the bugs found in review fixed.

**Database features.** The user's goal is to use as many database features as genuinely serve a requirement.
Checked against the course documents and the official 2026 S2 outline (Week 10 is the cut-off; Weeks 11–12 are
indexing and query processing): the rubric credits an "appropriate range of techniques" and "comprehensive"
integrity "within the Week 10 scope", says its descriptors are not additive checkboxes, and that strong
presentation cannot compensate for serious technical errors. So every feature below serves an R#/BR#; Week-10
features are the backbone, and four beyond-Week-10 features are kept **optional and explained** (trade-off T-8),
each backing up a Week-10 mechanism rather than replacing it.

| Decision | Choice |
|---|---|
| Scope of this sub-project | T1 checkout, my orders + order detail with timeline, addresses, price filter + per-store stock, and their pages |
| Moved later | staff status moves, store queue, cancellation (SP2); returns (SP3); reports, support lookup, the relational-division store query, indexes + `EXPLAIN` (SP4); isolation-level / lost-update / deadlock demonstrations (final evidence step) |
| Yuhang's schema | selective: keep sound pieces; drop request fingerprints, deferred BR14 triggers, `SECURITY DEFINER`, `05_permissions.sql`, checkout's product lock, the `OperationalError → 503` mapping, the recursive category tree |
| Beyond-Week-10 extras | integrity extras (deferred constraint trigger, partial unique index, `pg_trigger_depth` guard) now; indexes + `EXPLAIN` in SP4 |
| BR06 gap | keep the order-side trigger, add a store-side `BEFORE UPDATE OF store_type` guard (not a generated column, which would break BCNF) |
| Retry after an address is retired | look the key up before claiming it |
| BR06 race | the order-side trigger reads the store `FOR SHARE`, with a race test |
| Delivery ships from | the warehouse by default; the customer may switch to any store with stock |

## 2. Database (sql/)

All rule names follow `brNN_<what>`; triggers raise `USING ERRCODE = 'check_violation', CONSTRAINT = '<name>'`.
"Beyond" marks the optional beyond-Week-10 features (T-8).

### 2.1 Rules

| Name | Kind | Rule | Behaviour |
|---|---|---|---|
| `br20_paid_in_full` | trigger fn `br20_check_paid_in_full()`, `BEFORE UPDATE OF status` on `customer_order` | BR20 (new) | `placed → paid` is refused unless the order has ≥ 1 line and `COALESCE(sum of its charges, 0) = v_order_total.total`. An assertion over three tables, emulated by a trigger (as BR12). |
| `br20_charge_while_placed` | trigger fn `br20_check_charge()`, `BEFORE INSERT` on `payment` | BR20 | Locks the order `FOR UPDATE`; a `charge` is accepted only while the order is `placed`. Refunds untouched. A missing order is left to the FK. |
| `br20_one_charge_per_order` | partial unique index `ON payment (order_id) WHERE kind = 'charge'` | BR20 | At most one charge per order. **Beyond.** |
| `br08_order_line_immutable` | trigger fn `br08_guard_order_line()`, `BEFORE INSERT OR UPDATE OR DELETE` on `order_line`; replaces main's `br08_block_unit_price_change()` / `br08_unit_price_immutable` trigger | BR08 (widened) | INSERT only while the parent order is `placed` (parent row locked, so it can't race `placed → paid`); a `unit_price` change still raises `br08_unit_price_immutable` first; any other change and any DELETE raise `br08_order_line_immutable`. |
| `br09_order_header_immutable` | trigger fn `br09_block_order_header_change()`, `BEFORE UPDATE` on `customer_order` | BR09 | `order_id, customer_id, idempotency_key, fulfilment_method, fulfilling_store_id, delivery_address_no, placed_at` never change (`IS DISTINCT FROM`); only `status` does. |
| `br14_payment_append_only`, `br09_history_append_only` | one shared fn `block_append_only_change()` (constraint name from `TG_ARGV[0]`); `BEFORE UPDATE OR DELETE FOR EACH ROW` on `payment` and `order_status_history` | BR14, BR09 | Ledger and audit trail are never changed or deleted. |
| `…_truncate` statement triggers | the same fn, `BEFORE TRUNCATE FOR EACH STATEMENT` on `payment`, `order_status_history`, `stock_adjustment` and `order_line` | BR14, BR09, BR18, BR08 | Row triggers don't fire on `TRUNCATE`; these do, raising `br14_payment_append_only`, `br09_history_append_only`, `br18_adjustment_append_only` and `br08_order_line_immutable` (the last also closes `TRUNCATE order_line CASCADE`). The project's first statement-level triggers. |
| `br07_product_on_sale` | trigger fn `br07_check_product_on_sale()`, `BEFORE INSERT` on `order_line` | BR07 (widened) | A retired product (`is_active = FALSE`) can't be ordered; a missing product is left to `order_line_product_fk`. Replaces Yuhang's Python check. |
| `br07_order_has_lines` | `CREATE CONSTRAINT TRIGGER … AFTER INSERT ON customer_order DEFERRABLE INITIALLY DEFERRED` | BR07 | Every order has ≥ 1 line, checked at COMMIT (lines are inserted after their order). **Beyond.** Tested with `SET CONSTRAINTS br07_order_has_lines IMMEDIATE` (by name, never `ALL`). |
| `br17_order_address_active` | trigger fn `br17_check_address_active()`, `BEFORE INSERT` on `customer_order` | BR17 (widened) | A delivery order can't use a retired address; a missing or foreign one is still reported by the FK `br17_order_address_is_customers`. |
| `br09_history_first_row_is_creation`, `br09_history_status_changes` | two named `CHECK`s on `order_status_history` | BR09 | `(seq = 1) = (from_status IS NULL)`; `from_status IS DISTINCT FROM to_status`. |
| `br09_history_written_by_trigger` | trigger fn `br09_check_history_writer()`, `BEFORE INSERT` on `order_status_history` | BR09 / R11 | Refuses an insert when `pg_trigger_depth() < 2`, so only the BR09 log trigger writes history. **Beyond.** |
| `br06_collect_at_retail_store` (order side, changed) | main's existing trigger | BR06 | Now reads the store row `FOR SHARE`, so a concurrent store-type change waits (the taught shared lock). |
| `br06_store_stays_retail` | trigger fn `br06_check_store_type()`, `BEFORE UPDATE OF store_type` on `store`, raising `br06_collect_at_retail_store` | BR06 | A store with any Click & Collect order can't stop being `retail` — a rule over two tables gets a guard on each side, as BR15 does. |

Consequences to state in report §3: orders with lines or history can no longer be deleted, so the `ON DELETE
CASCADE`s on `order_line` and `order_status_history` can't fire.

### 2.2 Views (computed, never stored — T-2)

| View | Columns | Notes |
|---|---|---|
| `v_order_summary` | `order_id, customer_id, placed_at, status, fulfilment_method, fulfilling_store_id, fulfilling_store_name, total, line_count, last_updated_at` | `customer_order JOIN store JOIN v_order_total`; `last_updated_at` from a correlated `max(changed_at)` subquery. |
| `v_order_payment` | `order_id, charged, refunded, balance` | One row per order (`LEFT JOIN` from orders); charges and refunds aggregated with `SUM(CASE …)` **before** joining, so lines never multiply payments; `balance = charged − refunded` (what the shop holds). Every column cast to `numeric(10,2)` so zero is `0.00`. No `FILTER`, no `LATERAL`. |
| `v_order_timeline` | `order_id, seq, from_status, to_status, changed_at, changed_by_staff_id, changed_by_name` | `order_status_history LEFT JOIN staff` — an inner join would drop the customer's and system's rows. Readers `ORDER BY seq` (T1's `placed` and `paid` share one `now()`). |

A test asserts status/history consistency with `NOT EXISTS` and `max(seq)` (no window functions): every order's
status is its newest history row's `to_status`; each row's `from_status` is the previous row's `to_status`; row 1
is `NULL → placed`.

## 3. T1 checkout (`app/services/orders.py`)

One service call, one transaction, `READ COMMITTED` (main's default). Steps:
**lookup → claim → lines → price check → stock → charge → paid**.

0. `require_customer(actor)` before any SQL.
1. **Lookup:** `SELECT order_id FROM customer_order WHERE customer_id = %s AND idempotency_key = %s`. Found →
   return that order with **200**, touching nothing (a retry replays even if the address was retired since).
2. **Claim:** `INSERT INTO customer_order (…) VALUES (…) ON CONFLICT ON CONSTRAINT br10_order_idempotency_unique
   DO NOTHING RETURNING order_id`. No row → a concurrent request with the same key committed first: re-read and
   return it with 200. (ON CONFLICT waits for the other transaction; at most one order — BR10.)
3. **Lines**, items sorted by `product_id`, `line_no` 1..n: `INSERT INTO order_line (…) SELECT %s, %s, product_id,
   %s, current_price FROM v_product_current_price WHERE product_id = %s RETURNING …`. Zero rows → 404 unknown
   product. The client never sends a price (BR08).
4. **Price check:** `SELECT total FROM v_order_total WHERE order_id = %s`; differs from the body's
   `expected_total` → **409 `price_changed`** `{total, lines}` (money as strings) and everything rolls back.
5. **Stock**, in `product_id` order: `UPDATE inventory SET quantity = quantity - %s WHERE store_id = %s AND
   product_id = %s AND quantity >= %s RETURNING quantity`. Zero rows → **409 `out_of_stock`**
   `{store_id, product_id, sku, requested, available}`. No product row lock: the inventory row lock decides the
   last-unit race (plan §5's story; fixes the review finding).
6. **Charge** (`_charge`, its own function so a test can make it fail): `INSERT INTO payment (order_id, kind,
   amount) SELECT order_id, 'charge', total FROM v_order_total WHERE order_id = %s AND total > 0`.
7. **Paid:** `SELECT set_config('app.staff_id', '', true)` (the customer's own move), then `UPDATE customer_order
   SET status = 'paid' WHERE order_id = %s` — BR09 validates and logs, BR20 checks.
8. COMMIT; the deferred `br07_order_has_lines` runs here. Any exception rolls everything back.

**Locks** (for the module docstring and report §4): no explicit row locks; the FK checks take `FOR KEY SHARE` on
the customer, store, address and products; the BR06 trigger takes `FOR SHARE` on a Click & Collect store; inventory
rows get `FOR NO KEY UPDATE` in ascending `product_id`; the BR08 and charge triggers lock the order row
`FOR UPDATE`. Rule for later sub-projects: take `FOR UPDATE` on an order first and call `get_order` last (its
`FOR SHARE` would otherwise upgrade and could deadlock).

## 4. Reads, addresses, products

- **Order detail** `get_order(cur, actor, order_id)`: starts with `SELECT … FROM customer_order WHERE order_id = %s
  FOR SHARE` (the taught S lock: status writers wait, so header, lines, payments and timeline agree), then
  `require_order_reader`, then lines, delivery address, `v_order_payment`, `v_order_timeline ORDER BY seq`, and
  `allowed_next_statuses` straight from `order_status_transition` (same for every reader; shown as text).
- **My orders** `list_customer_orders`: `v_order_summary`, newest first; that customer or support.
- **Addresses** (owner only): `add_address` locks the parent (`SELECT 1 FROM customer WHERE customer_id = %s FOR
  UPDATE`) then `INSERT … SELECT COALESCE(max(address_no), 0) + 1 … RETURNING`; `retire_address` runs `UPDATE …
  SET is_active = FALSE WHERE … AND is_active RETURNING` and re-reads if it was already retired. Yuhang's
  f-string column lists are not ported.
- **Products** `GET /products`: `min_price`, `max_price` (inclusive, on `current_price`; `min > max` → 422
  `invalid_price_range`) and `store_id` (adds `store_quantity`, `COALESCE(…, 0)`; `null` without `store_id`).
  Categories stay two levels.

## 5. API contract (under `/api/v1`; money is a 2-decimal string)

| Endpoint | Caller | Success | Errors |
|---|---|---|---|
| `POST /orders` (header `Idempotency-Key: <uuid>`; body `fulfilment_method`, `fulfilling_store_id`, `delivery_address_no` (delivery only), `items[{product_id, quantity}]` (≥ 1), `expected_total`) | a customer | 201 `OrderDetail` (`paid`); 200 the same key's order | 401 `not_signed_in`; 403 `customer_only`; 404 `not_found` (product); 409 `price_changed`, `out_of_stock`, `br06_collect_at_retail_store`, `br06_order_address_matches_method`, `br17_order_address_active`, `br17_order_address_is_customers`, `customer_order_store_fk`, `br07_product_on_sale`, `br07_order_line_product_once`, `br07_order_line_qty_positive`; 422 `validation_error` |
| `GET /orders/{id}` | the order's customer, its store's staff, support | `OrderDetail` | 401; 403 `not_your_order` / `other_store` (also for ids that don't exist); 404 (support only) |
| `GET /customers/{id}/orders` | that customer, support | `OrderSummary[]` newest first | 401; 403 `not_your_account` / `support_only` |
| `POST /customers/{id}/addresses` (`line1, suburb, state, postcode`) | that customer | 201 `Address` | 401; 403 `customer_only` / `not_your_account`; 409 `au_state_valid` / `au_postcode_format`; 422 |
| `PATCH /customers/{id}/addresses/{no}` (`{is_active: false}` only) | that customer | 200 `Address` (idempotent) | 401; 403; 404; 422 |
| `GET /products` (`q, category_id, brand_id, include_inactive, min_price, max_price, store_id`) | everyone | `ProductSummary[]` incl. `store_quantity` | 404 (store); 422 `validation_error` / `invalid_price_range` |

`OrderSummary` = the `v_order_summary` columns. `OrderDetail` = `OrderSummary` + `lines[{line_no, product_id, sku,
name, quantity, unit_price, line_total}]`, `delivery_address` (or null), `payment{charged, refunded, balance}`,
`history[{seq, from_status, to_status, changed_at, changed_by_staff_id, changed_by_name}]`,
`allowed_next_statuses[]`. Quantity ≤ 0, duplicate products and unknown stores are answered by the database
(409 with the constraint name), per "Pydantic checks shape only"; an empty basket is a 422 (a length check).

**Auth helpers added to `app/auth.py`:** `require_customer` (403 `customer_only`); `require_own_account(actor,
customer_id)` (customer and owner, else 403 `customer_only` / `not_your_account`); `require_order_reader(actor,
order)` (support: any, 404 if missing; customer: own, else 403 `not_your_order`; store staff: own store, else 403
`other_store`). No `RequiredActor` alias — routers pass `actor: CurrentActor` to the services.

## 6. Frontend (`web/`)

Pages ported from the branch and adapted: `/products`, `/products/[id]`, `/stores`, `/cart`, `/checkout`,
`/orders`, `/orders/[id]`, `/account`; the home page's reserved "My orders" card shows the 3 newest orders.

- Identity comes from main's `useMe` / `ShopProvider`; the branch's demo session (`session.ts`, `ensureSession`,
  admin `session.tsx`) is not ported. All calls go through main's API client (Bearer token).
- Checkout sends `Idempotency-Key` (kept across retries of the same reviewed basket — `checkout-attempt.ts`) and
  `expected_total`; the cart works in integer cents. Delivery pre-selects the warehouse; the customer may switch
  to any store with stock, held in checkout page state (not the global "My store").
- `price_changed` and `out_of_stock` are business conflicts, excluded from `ApiError.isRule` (an `APP_CONFLICTS`
  set in `client.ts`), so they aren't headed "rejected by the database".
- Signed-out visitors on `/checkout`, `/orders`, `/orders/[id]`, `/account` see a Clerk sign-in button; the cart is
  kept. Staff opening a storefront order page see whatever the API allows. `allowed_next_statuses` is shown as
  text. "Add to cart" stays enabled when "My store" has none (delivery can ship elsewhere); stock is information.
- Left out until later: cancel buttons (SP2), return forms and return status (SP3). The branch's focus-trapping
  Modal is not ported now.
- **Vitest** (the branch's verified `vitest ^3.2.7`, `jsdom ^26`, `@vitejs/plugin-react`, testing-library) with a
  `vitest.config.mts` (avoids the branch CI's `ERR_REQUIRE_ESM` on Node 20.9); unit tests only for the cart
  (cents) and the checkout attempt (key kept across retries). `npm run test:unit` script.

## 7. Testing

Backend (pytest, `jbhifi_test`): branch tests are ported or adapted to `as_customer` / `as_staff`, with fingerprint,
`flush_deferred` and 503 expectations removed and renamed codes (`product_unavailable` → `br07_product_on_sale`,
`address_inactive` → `br17_order_address_active`). The branch's file layout is kept: `test_checkout.py`,
`test_checkout_transactions.py`, `test_order_reads.py`, `test_addresses.py`, `test_catalogue.py`; plan §8 is updated.

New tests (names are binding):

- `tests/test_business_rules.py`: `test_br20_an_order_is_paid_only_when_its_charge_equals_the_total`,
  `test_br20_an_order_without_lines_cannot_be_paid`, `test_br20_a_zero_total_order_is_paid_without_a_charge`,
  `test_br20_a_charge_is_taken_only_while_the_order_is_placed`, `test_br20_at_most_one_charge_per_order`,
  `test_br08_lines_are_added_only_while_the_order_is_placed` (also UPDATE, DELETE and `TRUNCATE order_line CASCADE`),
  `test_br09_the_order_header_never_changes`, `test_br09_only_the_status_log_writes_history`,
  `test_br09_history_rows_are_well_formed`, `test_br07_a_retired_product_cannot_be_ordered`,
  `test_br07_an_order_without_lines_fails_at_commit`, `test_br17_a_retired_address_cannot_be_ordered_to`,
  `test_br06_a_store_with_collect_orders_stays_retail` (allowed case on a store created inside the test),
  `test_br14_payments_are_append_only` (UPDATE, DELETE, TRUNCATE), `test_order_summary_has_the_total_store_and_last_update`,
  `test_order_payment_balances_charges_and_refunds_without_fan_out` (asserts `'0.00'` strings),
  `test_order_timeline_names_the_staff_in_seq_order`, `test_every_orders_status_is_its_latest_history_entry`;
  and the existing BR18 test gains its `TRUNCATE` case.
- `tests/test_checkout.py`: happy paths (delivery and Click & Collect: order, lines, stock, one charge, history),
  replay of the same key, `test_a_retry_after_the_address_was_retired_replays_the_order`,
  `test_another_customers_key_never_replays_their_order`, `test_a_refused_checkout_does_not_use_up_its_key`,
  `test_a_promotion_starting_after_review_is_a_price_change`, unknown product 404, retired product, retired address,
  `test_a_zero_total_order_gets_no_charge_row`, `test_lines_are_numbered_in_product_id_order`,
  `test_staff_cannot_check_out`, `test_out_of_stock_saves_nothing` (asserts `sku` in the detail), and
  **`test_a_failed_charge_rolls_back_everything`** (monkeypatch `_charge` to raise: no order, lines, payment or
  history; stock unchanged; key free) — plan §5's simulated payment failure.
- `tests/test_checkout_transactions.py`: concurrent same key → one order returned to both; last unit → one buyer,
  the other `out_of_stock`; `test_stock_is_locked_per_store_not_per_product` (a checkout of P at store A commits
  while another of P at store B is still open); `test_baskets_in_opposite_product_order_do_not_deadlock`;
  `test_br06_a_store_type_change_and_a_collect_order_race_has_one_winner`.
- `tests/test_order_reads.py`: own / other customer / store staff / support (403 before 404),
  `test_support_lists_any_customers_orders_but_store_staff_cannot`,
  `test_reading_an_order_holds_off_a_status_change_until_the_read_ends`,
  `test_the_detail_lists_the_next_statuses_the_transition_table_allows`.
- `tests/test_addresses.py`: add, retire (idempotent), concurrent adds get distinct numbers, owner only,
  `test_a_missing_address_is_404_for_its_owner_and_403_for_anyone_else`.
- `tests/test_catalogue.py`: price filter on the current price (a promotion inside the range whose base price is
  outside it), `store_quantity`, `invalid_price_range`, `test_a_top_level_category_includes_its_subcategories`.
- `tests/test_permissions.py`: matrix rows for the new endpoints.
- Existing tests that BR20 breaks (the `collected_order` fixture, `test_br09_status_moves_only_along_allowed_transitions`,
  `test_br11_only_completed_orders_can_be_returned`, `test_br14_refunds`) get a `pay(cur, order_id)` helper (charge
  from `v_order_total`, then `paid`) **in the same commit as the SQL change**.

Frontend: `npm run typecheck`, `npm run lint`, `npm run test:unit`, and a browser walk-through (sign in as a
persona, browse with filters, check out both ways, see the order and its timeline, add and retire an address).

## 8. Build order

1. SQL rules, views and the existing-test fixes (one commit), with the new rule tests.
2. Auth helpers, products filter, addresses.
3. T1 checkout and order reads, with their tests and the permission rows.
4. Web: shared libs (cart, checkout attempt, Vitest), then pages; `npm run gen:api`.
5. Dev database: the new SQL can't be re-run on the existing volume, so rebuild it
   (`docker compose down -v && docker compose up -d`, **asked before running**), then re-run
   `scripts/clerk_personas.py` to re-link the personas; then the browser walk-through.
6. Docs: plan.md (§3 BR06/07/08/09/14/17/18/20, §4 entities, derived data, T-8, §5 T1 steps/concurrency/demonstrate/
   reads, §8 test files), README if setup changes, and a `doc/progress.md` entry.

## 9. Risks and notes

- The Week 9 transactions lecture (5–11 Oct) comes after this work; re-check §3's wording against it.
- Scope labels for features the outline never names (CTEs, window functions, savepoints, `GRANT`, the `FOR UPDATE`
  syntax) rest partly on an unofficial 2025 S1 copy; confirm on Canvas or at the Week 9 tutor milestone. Nothing
  from those materials goes into the submission.
- The API still connects as the database owner (superuser); SP4's optional least-privilege role answers that
  Q&A question if wanted.
- `GET /orders/{id}` takes `FOR SHARE`; later services must lock `FOR UPDATE` first and read with `get_order` last.

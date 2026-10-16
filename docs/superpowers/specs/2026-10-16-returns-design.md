# Sub-project 3: Returns (T2) — design

Status: approved on 2026-10-16. Branch `gogy717/fusilier-returns-t2`, from `main` at `d8a836f`. Covers R6
(customers request returns) and R8 (staff receive returns, restock and refund). Cancellation is SP2's; the
return-rate report and the support lookup are SP4's.

| Decision | Choice |
|---|---|
| Retries of a return request | `Idempotency-Key`, as BR10: look the key up, then claim it; a replay returns the first return, unchanged |
| Refund amount | the purchase price of what came back: Σ `order_line.unit_price` × returned quantity, enforced by the database; partial returns (some lines, some units) allowed; a zero-value return gets no refund row |
| Where a return is received | any retail store, by that store's own staff; the stock goes back to that store |
| Rejection | only after receipt, by the receiving store, with a reason; enforced in the database |
| Who did what | `processed_by_staff_id` stays the receiver; new `received_at`, `resolved_by_staff_id`, `resolved_at` |
| A second click on a return that has moved on | 409 `return_status_transition` with the current status |

## 1. Database (`sql/`, SP3 sections at the end of each file unless noted)

**`return_request` gains** `idempotency_key UUID NOT NULL`, `rejection_reason TEXT`, `received_at TIMESTAMPTZ`,
`resolved_by_staff_id INT`, `resolved_at TIMESTAMPTZ` (edited in its `CREATE TABLE`).

| Name | Kind | Rule |
|---|---|---|
| `br10_return_idempotency_unique` | `UNIQUE (order_id, idempotency_key)` | BR10 widened: a return request retried with the same key creates at most one return |
| `return_request_receipt_recorded` (changed) | `CHECK` | `received`, `refunded` **and now `rejected`** returns have a receiving store and receiver |
| `return_request_received_at_recorded` | `CHECK` | `(received_store_id IS NULL) = (received_at IS NULL)` |
| `return_request_resolution_recorded` | `CHECK` | only `refunded`/`rejected` have a resolver, and a resolver comes with `resolved_at` |
| `return_request_rejection_has_reason` | `CHECK` | only a `rejected` return has a reason, and it isn't blank |
| `return_request_resolver_at_store` | composite FK `(received_store_id, resolved_by_staff_id) → staff (store_id, staff_id)` | the resolver works at the receiving store. Because every resolved return now has a receiving store, the FK is always checked (`MATCH SIMPLE` skips a row whose store is `NULL`) |
| `return_status_transition` (changed) | main's trigger | `requested → rejected` removed: `requested → received → refunded / rejected` (plan §4) |
| `br14_refund_matches_return` | trigger fn `br14_check_refund_matches_return()`, `BEFORE INSERT` on `payment` | BR14 widened: a refund **for a return** (`return_id IS NOT NULL`) equals that return's value. Refunds without a return are SP2's cancellation refunds and are left alone; a missing return is left to the FK |
| `br22_return_received_at_retail_store` | trigger fn `br22_check_receiving_store()`, `BEFORE INSERT OR UPDATE OF received_store_id` on `return_request` | BR22 (new): when a return is received, the store is retail. It reads the store `FOR SHARE`, so a concurrent store-type change waits |

BR22 has no store-side guard, unlike BR06. BR06 is a standing state: while a store has Click & Collect orders it
must stay retail. BR22 is a fact about one moment: the store was retail when the item came in, and a later
change of store type doesn't undo a past receipt.

**View `v_return_value (return_id, order_id, quantity, value)`**: `return_request r LEFT JOIN (return_line rl
JOIN order_line ol ON …) ON …` — the parenthesised join, because a plain `LEFT JOIN … JOIN` groups left to right
and its inner join would drop a return that has no lines yet. One row per return; `quantity` and `value`
(`Σ quantity × unit_price`, cast to `NUMERIC(10,2)`) are `COALESCE`d to 0 and 0.00, so the BR14 trigger never
compares an amount with `NULL`. The BR14 trigger, T2 and the reads all use it, so the refund is computed in one
place (derived data is not stored, T-2).

**A return has at least one line** is enforced by the service and the request's shape (`lines` ≥ 1), not by
the database: the database way would be a deferred constraint trigger, as BR07's, which is beyond Week 10. It is
acceptable because a return inserted by SQL without lines is worth 0.00, so refunding it inserts no payment row:
nothing can go wrong with the money.

## 2. Transactions (`app/services/returns.py`; one call = one transaction, `READ COMMITTED`)

**Request** — `POST /orders/{order_id}/returns`, header `Idempotency-Key`, body `reason`, `lines[{line_no,
quantity}]` (≥ 1). Same shape as T1:

1. `require_customer`; read the order's `customer_id` — someone else's order, or none, is 403 `not_your_order`.
2. **Lookup** `(order_id, idempotency_key)` → found: return it with 200, touching nothing. It comes before the
   claim, so a retry that arrives late (after the 30-day window closed, or when BR12's total is full) still
   replays its return instead of being refused by BR11 or BR12.
3. **Claim** `INSERT … ON CONFLICT ON CONSTRAINT br10_return_idempotency_unique DO NOTHING RETURNING return_id`
   (BR11 runs here). No row → a concurrent request with the key committed first: re-read it, 200.
4. **Lines** in `line_no` order (BR12 locks each `order_line` `FOR UPDATE`, so two requests lock lines in the same
   order). Unknown line, duplicate line and quantity ≤ 0 are answered by `return_line_order_line_fk`,
   `return_line_pk` and `return_line_qty_positive` (409 with the name). 201.

The request takes no explicit lock; it doesn't change the order. Its FK checks hold `FOR KEY SHARE` on the order.

**Staff actions** — `POST /returns/{id}/receive`, `/refund` (T2), `/reject` (`{reason}`). Each locks, in this
order: **the order `FOR UPDATE` → the return `FOR UPDATE` → inventory rows in ascending `product_id` → the refund
insert** (whose BR14 triggers lock the order again, already held). The `order_id` comes from one unlocked read
first; it can't change, because the return's lines hold it through their composite FK. Under the locks:

- **receive**: store staff (not support); status must be `requested`. Sets `received`, `received_store_id` =
  the actor's store (BR22 checks it is retail), `processed_by_staff_id`, `received_at`. No stock moves yet.
- **refund (T2)**: staff of the receiving store; status must be `received`. For each line in `product_id` order:
  `INSERT INTO inventory … 0 ON CONFLICT DO NOTHING` (the store may never have stocked it), then `UPDATE …
  SET quantity = quantity + n`. Then `_refund` (its own function, so a test can make it fail) inserts
  `payment(kind 'refund', amount = v_return_value.value, return_id)` — none for a zero value. Then `refunded`,
  `resolved_by_staff_id`, `resolved_at`. No `stock_adjustment` row: BR18 logs manual changes, and the return
  lines are this change's record. Any failure rolls back the stock, the refund and the status together.
- **reject**: staff of the receiving store; status must be `received`. Sets `rejected`, `rejection_reason`,
  `resolved_*`. Nothing is restocked; the item goes back to the customer.

A status that isn't the one the action needs → 409 `return_status_transition`, detail `{status}` (the database
trigger of the same name is the backstop). The request carries no `expected_status`: each action has exactly one
valid starting status, and each status has at most one way in, so the action itself is the check — two staff
refunding the same return: one 200, the other 409 `refunded`, and one refund row. (SP2's cancel needs a
`from_status` because it starts from either `paid` or `ready`.) `UNIQUE (return_id)` on payment (BR14) is the
backstop if the status check were skipped.

**Why it can't deadlock.** SP2's cancel locks order O′ then inventory; T2 locks order O then inventory.
A cancellable order is never completed, so O′ ≠ O, and both take inventory in ascending `product_id`, so neither
waits for a lock the other will need next. T1 takes inventory then its new order; T3 one inventory row. Two
actions on returns of one order queue on the order lock. `get_order` takes the order `FOR SHARE` and nothing
after it. A return request holds `FOR KEY SHARE` on the order (FK) and its `order_line` locks; T2's `FOR UPDATE` on
the order waits for it, or the request's FK check waits for T2 — waiting, never a cycle, since T2 never touches
`order_line` locks.

## 3. Reads and permissions (under `/api/v1`; money as 2-decimal strings)

| Endpoint | Caller | Returns |
|---|---|---|
| `GET /returns/{id}` | its customer; retail staff (any `requested` return, since any retail store may receive it; otherwise only returns received at their store); support | `ReturnDetail`. Customers get 403 `not_your_return`, staff 403 `other_store`, for missing ids too; support 404 |
| `GET /customers/{id}/returns` | that customer, support (as `/customers/{id}/orders`) — the contract SP4 uses | `ReturnSummary[]` newest first |
| `GET /stores/{id}/returns` | that store's staff, support | `requested` returns of orders this store fulfilled, and every return received here |

`ReturnSummary`: `return_id, order_id, status, reason, requested_at, quantity, value, refunded` (the refund
amount or null), `received_store_id, received_store_name, received_at, resolved_at, rejection_reason`.
`ReturnDetail` adds `customer_id, fulfilling_store_id, lines[{line_no, product_id, sku, name, quantity,
unit_price, line_total}], processed_by_name, resolved_by_name`. `get_return` reads the header, the value and the
refund in one statement (one snapshot); lines don't change after the request, so it takes no row locks.
Staff actions return `ReturnDetail`. Support reads but never acts (403 `store_staff_only`).

## 4. Frontend (`web/`)

- `/returns` replaces the `ReservedPage`: my returns with status, value, refund and rejection reason;
  `shop-pages.ts` marks it live.
- Order detail gets one line, `<ReturnRequestForm order={order} />`, shown for delivered or collected orders:
  a quantity per line (capped at bought − already returned, from my returns), a reason. One reviewed request
  keeps its `Idempotency-Key` across retries and gets a new one after success or an edit (`return-attempt.ts`,
  unit-tested).
- `/admin/returns` (the store's desk, plus "find return #") and `/admin/returns/[id]` (receive, refund, reject
  with a reason); one line in `components/sidebar.tsx`.

## 5. Testing

- `tests/test_business_rules.py` (SP3 section): `br10_return_idempotency_unique`, `br14_refund_matches_return`,
  `br22_return_received_at_retail_store`, `return_status_transition` refusing `requested → rejected`, and the four
  `return_request_*` checks. Existing tests changed: the BR12 rejection tests receive first; `test_br14_refunds`
  expects `br14_refund_matches_return` for a wrong amount, tests `br14_refunds_within_charged` with
  `br14_refund_matches_return` disabled inside the test transaction (the second line of defence), and repeats a
  correct amount for `br14_refund_once_per_return`; `request_return` sends a key.
- `tests/test_returns.py`: request (201, lines, value), replay (also after the window closed), BR11 / BR12 / FK
  409s, another customer's order, staff can't request; receive (retail only), refund end to end (status, refund
  = value, stock +n at the receiving store including a product it never stocked, `v_order_payment`), zero value,
  reject, and the 403s; customer, store and support reads.
- `tests/test_return_transactions.py`: two staff refund at once → one 200, one 409, one refund row, stock added
  once; BR14 backstop — two raw transactions insert a refund for the same return, the second fails on
  `br14_refund_once_per_return` (the return is worth less than half the order: otherwise the waiting insert
  resumes in `br14_refunds_within_charged`, which runs before the unique check, and fails there); `_refund` made to
  fail rolls back status, stock and payment; the same key at once → one return.
- `tests/test_permissions.py`: rows for the new endpoints.
- Web: `typecheck`, `lint`, `build`, `test:unit`. The browser walk-through needs the user's Clerk sign-in and
  SP2's fulfilment, so it is done after merge.

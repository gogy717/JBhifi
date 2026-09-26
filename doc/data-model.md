# Data model

The database is the authority for integrity, history and transaction safety. This document describes the
structure that `sql/00_domains.sql`, `sql/01_tables.sql`, `sql/02_rules.sql` and `sql/03_views.sql` build,
the keys that make it work, and the small amount of deliberate redundancy that lets a composite foreign
key enforce a rule the schema could not otherwise express.

The reference data (`sql/10_seed_reference.sql`) fills 12 retail stores, one warehouse, 42 staff,
15 categories, 16 brands, 48 products, their specs, opening stock, 9 promotions and four demo customers.

## 1. Entity overview

```
customer ──< customer_address
    │
    └──< customer_order ──< order_line ──> product
              │  │  │                          │
              │  │  └──< order_status_history │
              │  └────< payment ──> order_cancellation
              │                 └─> return_request ──< return_line
              │                              │
              │                              └──< return_status_history
              └────> store ──< inventory ──> product
                        │
                        └──< staff

category ──< category            (recursive, arbitrary depth)
brand ──< product ──< product_spec
                 └──< promotion
store ──< stock_adjustment
```

`store` and `staff` reference each other (a store names its manager; a staff member belongs to a store),
so that pair is created last, with a deferred foreign key.

## 2. Tables, keys and what the key means

| Table | Primary key | Foreign keys | Notes |
|---|---|---|---|
| `customer` | `customer_id` | — | `email` is an `email_address` domain (lower-case, well-formed, unique) |
| `customer_address` | `(customer_id, address_no)` | `customer_id → customer` | weak entity: `address_no` is only unique inside its customer |
| `store` | `store_id` | `(store_id, manager_id) → staff` (deferred) | `store_type` is `retail` or `warehouse` |
| `staff` | `staff_id` | `store_id → store` | discriminator `staff_type` (`store`/`support`); `(store_id, staff_id)` is unique so it can be a composite FK target |
| `category` | `category_id` | `parent_id → category` | recursive relationship; cycle guard in `02_rules.sql` |
| `brand` | `brand_id` | — | |
| `product` | `product_id` | `brand_id`, `category_id` | `sku` unique and format-checked; `is_active` retires, never deletes |
| `product_spec` | `(product_id, spec_name)` | `product_id → product` | weak entity: key–value specs, one value per name |
| `promotion` | `promotion_id` | `product_id → product` | half-open period `[starts_at, ends_at)` |
| `inventory` | `(store_id, product_id)` | `store_id → store`, `product_id → product` | M:N relationship with the attribute `quantity`; `quantity >= 0` |
| `stock_adjustment` | `adjustment_id` | `(store_id, product_id) → inventory`, `(store_id, staff_id) → staff` | the BR18 audit log; composite FKs give it "staff of that store" |
| `order_status_transition` | `(fulfilment_method, from_status, to_status)` | — | allowed moves as data (BR09) |
| `customer_order` | `order_id` | `customer_id`, `fulfilling_store_id`, `(customer_id, delivery_address_no)` | the composite address FK is BR17 |
| `order_line` | `(order_id, line_no)` | `order_id → customer_order`, `product_id → product` | weak entity; `unit_price` is the purchase-time snapshot (BR08) |
| `order_status_history` | `(order_id, seq)` | `order_id`, `changed_by_staff_id` | written only by the BR09 trigger; append-only |
| `order_cancellation` | `cancellation_id`; unique `order_id` | `order_id`, `cancelled_by_staff_id` | a cancellation is not a merchandise return; second refund source |
| `return_request` | `return_id`; unique `(order_id, idempotency_key)` | `order_id`, `received_store_id`, `(received_store_id, processed_by_staff_id)` | retry key scoped to the order |
| `return_line` | `(return_id, line_no)` | `(return_id, order_id) → return_request`, `(order_id, line_no) → order_line` | weak entity; the copied `order_id` is the controlled redundancy described below |
| `return_status_history` | `(return_id, seq)` | `return_id`, `changed_by_staff_id` | written only by the return-history trigger; append-only |
| `payment` | `payment_id` | `order_id`, `(return_id, order_id)`, `(cancellation_id, order_id)` | charges and refunds; each refund has exactly one source |

## 3. Weak entities

Four tables have no meaning without their parent, and their key reflects that:

- `customer_address(customer_id, address_no)` — address 1 of customer A and address 1 of customer B are
  different rows. `address_no` is therefore allocated per customer.
- `product_spec(product_id, spec_name)` — at most one value per spec name per product.
- `order_line(order_id, line_no)` — line numbers restart for every order; BR07 also makes
  `(order_id, product_id)` unique, so one product appears once per order.
- `return_line(return_id, line_no)` — the returned quantities for one return, keyed by the order line they
  come from.

The two history tables follow the same pattern: `sequence` numbers are per order or per return.

## 4. The staff ISA hierarchy

`staff` is one table with a discriminator, `staff_type`:

- `store` staff have a `store_id` and work at that store;
- `support` staff have `store_id IS NULL` and work across stores.

A single CHECK, `br05_staff_store_matches_type`, expresses "support staff do not have a store; store staff
do". A store manager is a `store` staff member who is named by their store's `manager_id`.

Two composite foreign keys then give other tables a "staff member *of store S*" target:

- `store (store_id, manager_id) → staff (store_id, staff_id)` — BR04: a store's manager works there;
- `stock_adjustment (store_id, staff_id) → staff (store_id, staff_id)` — BR18: only that store's staff can
  adjust its stock.

`staff_store_staff_unique (store_id, staff_id)` exists only to be a target for those two keys (the
`staff_id` primary key already guarantees uniqueness on its own).

## 5. The recursive category tree

`category.parent_id` points at another category, `NULL` for a top-level category. The tree is walked to
arbitrary depth by the catalogue. Two protections keep that safe:

- `category_not_own_parent` stops the trivial one-row cycle;
- `category_no_cycle` walks the prospective ancestor chain with a `UNION` recursive CTE and refuses a
  move that would put a category inside its own subtree.

The catalogue's descendant filter uses the same `UNION` shape, so even a legacy malformed cycle would
terminate rather than loop.

## 6. The circular store ↔ manager reference

`store.manager_id` is `NOT NULL` and `staff.store_id` is nullable, so the two tables reference each other.
The database cannot insert both rows at once, so:

1. `sql/10_seed_reference.sql` pins `store_id` and `staff_id` values (`GENERATED BY DEFAULT`) and inserts
   stores before staff, then staff, then runs `setval` so the identity sequences continue past the pins.
2. `br04_store_manager_works_here` is `DEFERRABLE INITIALLY DEFERRED`: it is checked when the seeding
   transaction commits, after both inserts exist. `test_br04_a_new_store_and_its_manager_in_one_transaction`
   covers the same path.

## 7. Deliberate redundancy

Each row below duplicates a value that could be joined, in order to make one database rule declarative.
The duplicate is written by the same service that writes the row and is never edited afterwards.

| Column | Duplicates | Why it is kept |
|---|---|---|
| `order_line.unit_price` | the current price at purchase time | BR08: the purchase record must keep the price it was sold at, even after the base price or promotion changes |
| `return_line.order_id` | `return_request.order_id` | lets the composite FK `(return_id, order_id)` require that a return line belongs to the returned order (BR13) |
| `stock_adjustment.quantity_after` | `inventory.quantity` at that moment | an audit snapshot: the log says how much was left, not what is left now |
| `customer_order.fulfilling_store_id` | the store chosen at checkout | one order has one fulfilment location; delivery and collection both read it |
| `payment.return_id` / `payment.cancellation_id` | the refund's source | BR14: a refund has exactly one source, and the source can be refunded once |
| `order_status_history.changed_by_staff_id` | the actor | the audit trail says who moved the status, without joining back through the API's session |

## 8. Views: derived data is never stored

`sql/03_views.sql` defines two views so that calculated values cannot disagree with their sources:

- `v_product_current_price` — one row per product with `current_price`: the running promotion's
  `sale_price`, else `base_price`. The join uses `starts_at <= now() AND now() < ends_at`, so a promotion
  stops applying at its end instant. BR15 permits at most one active promotion per product, so the LEFT
  JOIN cannot multiply rows.
- `v_order_total` — one row per order with `line_count` and `total = sum(quantity * unit_price)`. Order
  lists and detail reads take the total from here; checkout compares its own computed total against the
  customer's `expected_total` before writing anything.

## 9. Money, domains and status types

- `money_aud` is `NUMERIC(10,2)` with `VALUE >= 0` (BR02). Prices and totals therefore have exactly two
  decimals and are never floats. Python code carries them as `Decimal`, and the API serialises them as
  decimal strings.
- `email_address` is lower-case and pattern-checked (BR01).
- `au_state` and `au_postcode` carry the Australian address formats.
- `fulfilment` is `delivery` or `click_collect`; `order_status` is
  `placed`, `paid`, `picking`, `shipped`, `ready`, `delivered`, `collected`, `cancelled`.
- `return_request.status` is `requested`, `received`, `refunded` or `rejected`, guarded by a CHECK and by
  the `return_status_transition` trigger.

## 10. Transaction and lock order

Every API call is one database transaction: `app/db.py` commits when the route returns and rolls back when
it raises. Workflows that touch the same tables take locks in the same order so two of them cannot
deadlock:

1. the customer row (`SELECT … FOR UPDATE`), which also serialises two retries of the same checkout key;
2. the delivery address, if any;
3. the affected `product` rows in ascending `product_id`;
4. `inventory` rows in ascending `(store_id, product_id)`;
5. the `customer_order`, then its `order_line` rows in line order;
6. for returns, the parent order, then the `return_request`, then its lines;
7. `payment` last (writing it locks the order through the BR14 trigger).

Stock is only ever changed with a relative statement
(`UPDATE inventory SET quantity = quantity - %s WHERE … AND quantity >= %s`, or `+ %s` when restocking).
The CHECK on `quantity` is a backstop; the conditional update is what prevents two buyers from taking the
same last unit.

## 11. Which service writes what

| Service | Tables it writes |
|---|---|
| `app/services/products.py`, `promotions.py` | `product`, `product_spec`, `promotion` |
| `app/services/inventory.py` | `inventory`, `stock_adjustment` (one transaction) |
| `app/services/customers.py` | `customer_address` (insert a new one, or set `is_active = false`) |
| `app/services/orders.py` | `customer_order`, `order_line`, `inventory` (decrement) |
| `app/services/cancellations.py` | `order_cancellation`, `customer_order.status`, `inventory` (restore) |
| `app/services/returns.py` | `return_request`, `return_line`, `inventory` (restore), `customer_order` status |
| `app/services/payments.py` | `payment` (called by checkout, cancellation and return processing) |

The two status-history tables are never written directly: the BR09 and return-history triggers write them,
taking the actor from the transaction-local `app.staff_id` setting that the service sets before its
`UPDATE`.

## 12. Transactions, retries, rollback and money

**One request, one transaction.** `app/db.py` yields a cursor inside `with conn:`, so the route's work
commits when it returns and rolls back if it raises. A service never commits on its own, which is what lets
checkout write an order, its lines, stock, the charge and two history rows as one unit — and what lets
cancellation and return processing combine a status change, a restock and a refund.

**Commit-time rules fail inside the request.** The BR14 completeness checks are `DEFERRABLE INITIALLY
DEFERRED`, so a service may write the payment and move the status in whichever order reads best. Each
transactional service ends with `SET CONSTRAINTS ALL IMMEDIATE`, which runs those checks before the
response is sent, so a half-finished financial state becomes the API's `409` instead of a 500 at COMMIT.

**A retry is not a new request.** `Idempotency-Key` is a UUID: an order's key is unique per customer
(BR10) and a return's key is unique per order (`return_idempotency_unique`). Each stored row keeps a
`request_fingerprint`, a SHA-256 of the validated request in canonical form — keys sorted, lines sorted,
money as exact two-decimal strings. The service resolves the key before re-reading any mutable state, so a
committed request replays (200, same resource, no second side effect) even after prices, stock, address
activity or the return window have changed. The same key with a different fingerprint is
`409 idempotency_conflict`. Checkout takes the customer row lock before looking the key up, so two
simultaneous retries queue instead of racing. Staff actions do not need a key: they are retried through a
locked status check, and a repeat that sets the same status appends no history row.

**Failure writes nothing.** Checkout compares its computed total with the customer's `expected_total`
before the first INSERT: a mismatch is `409 price_changed` with the reviewed lines and leaves the database
untouched. A shortage on the second line of a two-line order raises `409 out_of_stock` and rolls the first
line's stock deduction back with it. Return processing that fails while recording the refund leaves the
item unrestocked and the return unreceived, because the restock and the refund are in the same transaction.

**Cancellation money.** An uncompleted order is not a merchandise return, so it writes an
`order_cancellation` row and a refund whose `payment.cancellation_id` points at it. The refund is the
balance still captured on the order (charges less any earlier refund), the stock goes back to the
fulfilling store only when the order had actually taken stock (anything past `placed`), and the deferred
check at COMMIT refuses a cancelled order with no cancellation record or with the wrong number of refunds.

**Return money.** A processed return refunds `sum(return_line.quantity × order_line.unit_price)` — the
purchase-time prices, never today's — and adds the same quantities back at the receiving store. A
zero-value return (for example a replacement item sold at $0) moves its status and stock with no payment
row, because `payment.amount` must be positive.

The concurrency experiment in `doc/progress.md` (two buyers and the last unit) is why every stock change is
relative and conditional rather than computed in Python; `tests/test_checkout_transactions.py`,
`tests/test_cancellation_transactions.py`, `tests/test_return_processing_transactions.py` and
`tests/test_rule_concurrency.py` pin the same races.

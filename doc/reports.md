# Reports

Three reports, all read-only, all scoped to the store the signed-in staff member works at (support staff
may look at any store, or at all of them for sales and returns). They are the *retained* reporting scope
recorded in `doc/requirements.md` §6: the repository names a reporting slice but supplies no
specification, so these definitions — not a new requirement — are what the delivery is judged against.

The SQL lives in `app/services/reports.py` and, with explanations and expected shapes, in
`queries/reports.sql`. That file is deliberately **not** in `sql/`: every file in `sql/` runs while the
container builds the database, and these are parameterised queries to be driven from Python.

## Time and boundaries

* `from_date` and `to_date` are **Sydney calendar dates**. `from_date` is inclusive, `to_date` exclusive.
* The dates become instants in the database (`<date>::timestamp AT TIME ZONE 'Australia/Sydney'`), not in
  Python: PostgreSQL always has the zone database, whereas a bare Windows Python often has none. Each
  report returns the window it used (`window.from_at`, `window.to_at`) so a figure can be checked by hand.
* With no dates, the window is the last 30 Sydney days including today (`today - 29` to `tomorrow`).
* `to_date <= from_date` is `422 invalid_date_range`, before any query runs.

## Sales

`GET /api/v1/reports/sales?store_id=&from_date=&to_date=` → one row per store that traded in the period.

| Field | Meaning |
|---|---|
| `captured_amount` | Charges whose **own** `created_at` falls in the window |
| `refunded_amount` | Refunds whose **own** `created_at` falls in the window |
| `net_receipts` | `captured_amount - refunded_amount` |
| `order_count` | Orders **placed** in the window |
| `charged_orders` | Distinct orders with a charge booked in the window |
| `refund_count` | Number of refund rows booked in the window |

**Why the aggregates are computed separately.** A charge belongs to an order, and an order has many lines.
Joining `payment` to `order_line` before aggregating would multiply one 300.00 charge by three lines and
report 900.00. Each aggregate is therefore built in its own CTE and only then joined to `store`
(`test_sales_does_not_multiply_payments` pins exactly this).

**Events, not cohorts.** Money is counted when it moved, so an order placed in August and charged in
September appears in September's receipts and in August's order count. `test_refunds_use_their_own_event_date_and_net_off`
covers a charge and a later refund falling in different months, and the boundary test covers the Sydney
midnight either side of a month.

**Attribution.** The fulfilling store (`customer_order.fulfilling_store_id`) — the store that shipped the
order or handed it over.

## Low stock

`GET /api/v1/reports/low-stock?store_id=&threshold=3` → the active products whose quantity at that store is
at or below `threshold`, including products with **no inventory row** there.

| Field | Meaning |
|---|---|
| `quantity` | The store's quantity, `0` when there is no inventory row |
| `has_inventory_row` | `false` = never stocked here, which is not the same as "sold out" |
| `current_price` | The price right now, from `v_product_current_price` |

Retired products are excluded: they cannot be bought, so they are not work to do.
`test_low_stock_includes_products_with_no_inventory_row` covers the missing-row case, and
`test_low_stock_is_for_one_store_only` covers the per-store scoping.

## Returns

`GET /api/v1/reports/returns?store_id=&from_date=&to_date=` → one row per store, for the **cohort** of
return requests created in the window.

| Field | Meaning |
|---|---|
| `requested_count` | Requests created in the window (the cohort size) |
| `received_count`, `refunded_count`, `rejected_count` | Those requests' **current** status |
| `refunded_amount` | Refunds **linked to those requests**, whenever they were paid |
| `receiving_stores` | Where the items were actually taken in, e.g. `Bondi Junction (1)` |

The cohort definition matters in two directions, and both are tested
(`test_return_report_cohort_is_the_request_date_not_the_refund_date`): a request made in August and
refunded in September still belongs to August with its refund attached, and a refund paid in September
does not create a September row on its own. The report is attributed to the store that fulfilled the
order, with the receiving store shown separately, because a customer may hand an item back anywhere.

## Permissions

| Who | Sales / Returns | Low stock |
|---|---|---|
| Guest | `401 not_signed_in` | `401 not_signed_in` |
| Store staff | own store only; another store is `403 other_store`; all stores is `403 support_only` | own store |
| Support staff | any store, or all of them | any store |

`test_reports_are_scoped_to_the_signed_in_store` pins every one of those cases.

## Indexes

The reports read `payment`, `customer_order` and `return_request` by store and by time. `sql/04_indexes.sql`
is added only where a plan inspection shows it pays for itself; with the seeded volume (about 50 products,
13 stores and a handful of orders) an index does not change the plan, so none was added and none is
claimed. A real deployment would start with `payment (order_id)`, `customer_order (fulfilling_store_id,
placed_at)` and `return_request (order_id)` — `EXPLAIN (ANALYZE, BUFFERS)` on production-like data should
decide it, not this prototype.

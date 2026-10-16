# Sub-project 4: Reports and support lookup — design

Status: approved on 2026-10-16 (decisions below). Branch: `gogy717/sp4-reports-support-queries`, from `main` at
`d8a836f`. Covers R9 (manager reports) and R10 (support lookup), and plan §6 #4–#6. Yuhang's report code (`4a69838`)
is **not** ported: it doesn't follow §6 (sales per store by payment date, returns counted by status with no rate,
no `HAVING`, no division), and its `receiving_stores` subquery isn't correlated with its group. Every query below is
derived again.

## 1. Decisions

| Decision | Choice |
|---|---|
| What counts as a sale | an order line whose order is paid and not cancelled (`status NOT IN ('placed', 'cancelled')`), dated by `placed_at`, credited to the order's `fulfilling_store_id`, worth `quantity × unit_price` (the purchase-time price, T-1). Matches stock: checkout takes stock from that store, and cancellation (SP2) puts it back there |
| Where the definition lives | one view, `v_sale_line`; the parameterised `GROUP BY` / `HAVING` / `NULLIF` queries live in `app/services/reports.py` |
| Report window | `days` (1–365, default 30), rolling back from the transaction's `now()`; the page offers 7 / 30 / 90 |
| Low stock | products the store stocks (it has an `inventory` row) and still sells, with quantity ≤ 3 **or** fewer than 14 days of cover at the last 30 days' rate. The 30 days are fixed: reordering doesn't follow the report window |
| Return rate | of the units sold in the window, how many came back: non-rejected returned units (BR12's count) ÷ units sold, on the same order lines, credited to the order's store (not the store that received the return). Only existing columns, so it doesn't depend on SP3 |
| Who reads a store's report | its manager (`store.manager_id`), and support for any store |
| Consistency | the whole store report is one response, read in one `REPEATABLE READ READ ONLY` transaction (§3) |
| Relational division (§6 #5) | an endpoint plus a panel on the reports page |
| Support lookup | search on `GET /customers`; a merged history endpoint; returns come from SP3's `GET /customers/{id}/returns` |
| Indexes and `EXPLAIN` | not in SP4: on test-sized tables every plan is a sequential scan. A separate PR after the seed (T-8) |

## 2. Database (`sql/03_views.sql`, appended under `-- ===== SP4: reports =====`)

`v_sale_line(order_id, line_no, store_id, placed_at, product_id, category_id, quantity, unit_price, line_total)`:
`customer_order JOIN order_line JOIN product`, `WHERE o.status NOT IN ('placed', 'cancelled')`. "What is a sale" is
defined once, in the database, for every report and test (as T-2 does for totals). No new tables, rules or BR numbers.

## 3. Store report — `app/services/reports.py`

All queries use `%s` parameters. The window is `s.placed_at >= now() - make_interval(days => %s)`.

1. **Low stock (§6 #4: join + `GROUP BY` + `HAVING`).** `inventory i JOIN product p` (active products, this store)
   `LEFT JOIN v_sale_line s` on the product, this store and the last 30 days; `GROUP BY` the product and `i.quantity`;
   `HAVING i.quantity <= 3 OR i.quantity * 30 < COALESCE(sum(s.quantity), 0) * 14` (integer comparison, no division).
   Columns: product, sku, name, category, quantity, `sold_30d`, `days_of_cover = round(quantity * 30.0 / NULLIF(sold_30d, 0), 1)`
   (null when nothing sold). Ordered by quantity, then sku.
2. **Sales by category.** Every category that has products, `LEFT JOIN category parent` (the recursive relationship)
   and `LEFT JOIN v_sale_line` (this store, window): `count(DISTINCT order_id)`, `sum(quantity)`, `sum(line_total)`.
   Categories with no sales show `0` / `0.00`. Plus one totals row over `v_sale_line`. An order with lines in two
   categories counts once in each, so the category order counts don't add up to the total.
3. **Return rate (§6 #6: outer join + aggregates + `NULLIF`)**, by category (every category with products) and by
   product (products sold in the window). The sold lines `LEFT JOIN` a derived table of returned units **per order
   line**: `SELECT order_id, line_no, sum(quantity) FROM return_line JOIN return_request … WHERE status <> 'rejected'
   GROUP BY order_id, line_no`. `rate = round(COALESCE(sum(returned), 0) / NULLIF(sum(sold), 0), 4)`: `0.0000` when
   nothing came back, null when nothing was sold. Two mistakes this layout avoids, for the report:
   - **Fan-out.** Joining `return_line` before aggregating repeats a sale line once per return line, so a line with
     two partial returns counts its sold units twice. Each sale line meets at most one aggregated row here.
   - **`WHERE` turning the outer join into an inner join.** `WHERE rr.status <> 'rejected'` on the outer query drops
     every sale line with no return, so only returned lines are left and the rate rises towards 1. The filter goes in
     the derived table.
   Caveat: units sold in the last 30 days can still come back (BR11), so a recent window understates the rate.

**One snapshot.** One statement already sees one snapshot. The report runs several (low stock, two category
queries, a total, the product rates), and under `READ COMMITTED` each statement sees the latest commits, so a sale
committed between two of them could appear in the totals but not in the category rows. `store_report` therefore:
(1) checks permission (no SQL); (2) `cur.connection.commit()`; (3) runs
`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY` as the first statement of the next transaction; (4) runs
every query; `get_cursor` commits at the end. Three points for the report:

- This keeps "one service call = one transaction". The commit ends the request's sign-in step (`current_actor`),
  which isn't part of this service. All of the service's own work is in one transaction.
- The only write that commit can include is the `user_account` row `link_account` makes on a first sign-in, which
  would be committed anyway.
- `app/db.py` and `app/auth.py` are unchanged, so no other endpoint behaves differently. `now()` is the transaction's
  start time, so every section uses the same window.

Permission helper (in `reports.py`, not `auth.py`): `require_staff`; support passes; store staff who don't manage
their store get 403 `manager_only`; a manager of another store gets 403 `other_store` (also for a store that doesn't
exist). Only support is told 404.

## 4. Division and support lookup

- **Stocked in every store of a state (§6 #5, double `NOT EXISTS`):** active products for which there is no retail
  store in that state that doesn't have the product in stock (`quantity > 0`). The warehouse isn't a store a customer
  shops at, so it's excluded. The state is cast to `au_state`, so a typo is a 409 `au_state_valid` from the domain,
  not an empty divisor. A valid state with no retail stores returns **every** active product (vacuous truth). The
  response lists the divisor stores, so the page can say so. Any staff member may call it.
- **Search:** `GET /customers?q=` (support only, as now): `full_name ILIKE … OR email ILIKE …` with
  `filters.contains_pattern`.
- **History:** `GET /customers/{id}/history`, the same permission as `/customers/{id}/orders` (that customer, or
  support; 404 only for support). One `UNION ALL` of three branches for this customer's orders: status changes
  (`v_order_timeline`, so the staff name comes from its `LEFT JOIN`), payments (`charge` / `refund`, each at its own
  `created_at`, as ledger events), and return requests (`requested_at`). Columns: `at, kind, order_id, return_id,
  from_status, to_status, amount, staff_name`. Newest first, then by order id, status `seq`, payment id (checkout
  writes `placed`, its charge and `paid` with one `now()`). After rebasing on SP3: add received / resolved events
  from its new columns.
- **Returns list:** the page calls SP3's `GET /customers/{id}/returns`. A return is SP3's entity, so its shape and
  value (`v_return_value`) are defined once. Until SP3 is merged, the section is not rendered.

## 5. API (under `/api/v1`; money and rates are decimal strings)

| Endpoint | Caller | Success | Errors |
|---|---|---|---|
| `GET /stores/{id}/report?days=` | that store's manager, support | `StoreReport{store_id, store_name, days, generated_at, low_stock[], sales_by_category[], sales_total, return_rate_by_category[], return_rate_by_product[]}` | 401; 403 `staff_only` / `manager_only` / `other_store`; 404 (support); 422 `validation_error` (days) |
| `GET /reports/stocked-in-every-store?state=` | any staff | `{state, stores[{store_id, name}], products[{product_id, sku, name}]}` | 401; 403 `staff_only`; 409 `au_state_valid` |
| `GET /customers?q=` | support | `CustomerSummary[]` | 401; 403 |
| `GET /customers/{id}/history` | that customer, support | `HistoryEvent[]` | 401; 403 `not_your_account` / `support_only`; 404 |

New code goes in new files: `app/{services,routers,schemas}/reports.py`, `app/{services,routers,schemas}/support.py`
(the history route lives here, not in `customers.py`, which SP3 also edits). `customers.py` gains only `q`.

## 6. Frontend

- `/admin/reports`: the store (fixed for a manager, any store for support), the 7 / 30 / 90 choice, then low stock,
  sales by category with the total, return rate by category and by product, and the "in stock at every store in
  [state]" panel (NSW by default). A 403 shows the API's message.
- `/admin/support`: search, then a customer: profile and addresses, orders (linking to `/orders/{id}`), history, and
  (after SP3) returns.
- Two lines in `web/src/components/sidebar.tsx`; the client is regenerated on port 8004.

## 7. Testing

Data is built in SQL in `tests/reports_support.py`, committed: a fresh leaf category and products per test, so a
test's figures don't depend on what other tests committed at the same store. Orders are inserted with an explicit
`placed_at` for "n days ago", because BR09 forbids updating it later. Returns are built as `requested` or
`rejected` only.

- `tests/test_reports.py`: `test_a_sale_is_a_paid_order_that_is_not_cancelled` (the view);
  low stock by the threshold, by days of cover, the 30 days not following `days`, stores not stocking it, retired
  products; sales by category with exact `revenue` / `units` / `orders`, the window edge, other stores excluded,
  `0.00` rows; `test_return_rate_counts_a_line_with_two_partial_returns_once`,
  `test_return_rate_ignores_rejected_returns_without_dropping_unreturned_sales`, a null rate with no sales, credit to
  the order's store when another store received the return; division: a product missing from one store, quantity 0,
  the warehouse ignored, `test_a_state_with_no_retail_stores_divides_to_every_product`, `au_state_valid`;
  permissions (manager, other manager, store staff, support, missing store).
- **Concurrency evidence (report §4):** `test_repeatable_read_keeps_a_sale_committed_mid_report_out_of_every_section`
  and `test_read_committed_would_let_a_sale_committed_mid_report_into_later_sections` (another connection commits a
  sale between the first and second query; the second test runs the same sections without `SET TRANSACTION`).
- `tests/test_support.py`: search by name and email, support only; history merges status changes, payments and
  return requests newest first with the staff name, and no other customer's events.
- `tests/test_permissions.py`: rows for the three new endpoints.
- Web: `typecheck`, `lint`, `build`, `test:unit`. The browser walk-through needs Clerk passwords, so it isn't done
  here; the PR says so.

## 8. Build order and risks

1. View + store report + its tests; 2. division; 3. search + history; 4. permission rows; 5. pages; 6. progress
entry, PR (with a "Plan changes" section: §6 #4–#6 done, `v_sale_line`, R9 manager + support, R10 history, §5 Reads'
`REPEATABLE READ`, T-8 indexes after the seed). After SP2 and SP3 are merged: rebase, add the returns section and
the return events to the history, rerun everything.

Risk: SP2's cancellation and SP3's return rules may change what SQL-built test orders and returns must look like.
The builders live in one file, so a rebase fixes them in one place.

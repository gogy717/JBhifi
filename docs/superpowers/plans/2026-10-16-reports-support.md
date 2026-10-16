# Sub-project 4: Reports and support lookup — implementation plan

**Goal:** R9's store report (low stock, sales by category, return rate), §6 #5's division, and R10's support
lookup (search, merged history), each with its page.

**Spec:** `docs/superpowers/specs/2026-10-16-reports-support-design.md`. The SQL, columns, permissions and test
names there are binding; this plan only orders the work.

**Commands** (from `.claude/parallel.md` §2): tests `/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/pytest`
(test database `jbhifi_test_sp4`); API on port 8004; web on port 3004; types regenerated from
`http://127.0.0.1:8004/openapi.json`.

## Global constraints

- `%s` parameters only; route handlers are `def`; `DbCursor` keeps `scope="function"`.
- No changes to `app/db.py` or `app/auth.py`. New code goes in new files; `customers.py`, `main.py`, `sidebar.tsx`
  and `test_permissions.py` get small additions only.
- Nothing committed by figure tests (`test_api` counts the seeded stores and categories).
- English in code and docs; no AI attribution in commits.

## Review focus

1. A product with two partial returns on one line, or a rejected return: units must not double or disappear.
2. Integer division in rates: 4 sold, 1 back must be `0.2500`.
3. A typo'd state must not divide to "every product": 409 `au_state_valid`.
4. A store-staff member who isn't the manager, a manager of another store, a missing store: 403 / 403 / 404 (support).
5. Same-instant checkout events must read placed → charge → paid.

## Task 1 — `v_sale_line` and the test builders

- `sql/03_views.sql`: append `-- ===== SP4: reports =====` and the view (spec §2).
- `tests/reports_support.py` (cursor-based, nothing committed by itself): `a_store(cur, state="ACT") -> (store_id,
  manager_id)` (inserts store and manager in one transaction; BR04 is deferred), `a_category(cur) -> category_id`
  (a leaf under `Audio`), `a_product(cur, category_id, price, stock=None, store_id=None, active=True) -> product_id`,
  `a_sale(cur, store_id, items, days_ago=0, method="click_collect") -> order_id` (explicit `placed_at`, lines at
  the current price, one charge, `paid`), `collect(cur, order_id)` (paid → picking → ready → collected),
  `cancel(cur, order_id)`, `a_return(cur, order_id, [(line_no, qty)], status="requested", store_id=None,
  staff_id=None) -> return_id`.
- Test: `test_a_sale_is_a_paid_order_that_is_not_cancelled`. Commit.

## Task 2 — the store report: sections, permission, snapshot

- `app/schemas/reports.py`: `LowStockRow`, `CategorySales`, `SalesTotal`, `CategoryReturnRate`, `ProductReturnRate`,
  `StoreReport`.
- `app/services/reports.py`: `_low_stock`, `_sales_by_category`, `_sales_total`, `_return_rate_by_category`,
  `_return_rate_by_product` (each `(cur, store_id, days) -> list|dict`), `build_store_report(cur, store_id, days)
  -> dict` (store lookup, then the sections in that order), `_require_report_reader(actor, store_id)`,
  `store_report(cur, actor, store_id, days)` (permission → commit → `SET TRANSACTION …` → build).
- `app/routers/reports.py`: `GET /stores/{store_id}/report` with `days: int = Query(30, ge=1, le=365)`;
  `app/main.py` includes it.
- Tests (`tests/test_reports.py`, test-first, section by section): the low-stock, sales, and return-rate tests
  named in spec §7; permissions through the API (Olivia own store, Olivia store 2 → `other_store`, Aiden →
  `manager_only`, a customer → `staff_only`, Nora any store, Nora store 999999 → 404, `days=0` → 422); then the two
  concurrency tests (monkeypatch `_sales_by_category` to commit a sale on another connection after it runs).
  Commit per section.

## Task 3 — stocked in every store of a state

- `stocked_in_every_store(cur, actor, state)` in `reports.py`; `GET /reports/stocked-in-every-store?state=`.
- Tests: all four NSW stores stocked → listed; one store missing it or at 0 → not listed; stocked everywhere but
  the warehouse → listed; `test_a_state_with_no_retail_stores_divides_to_every_product` (`NT`); `XX` → 409
  `au_state_valid`; a customer → 403. Commit.

## Task 4 — support lookup

- `customers.list_customers(cur, actor, q=None)` and the router's `q`; `app/{services,routers,schemas}/support.py`
  with `customer_history(cur, actor, customer_id)` and `GET /customers/{customer_id}/history`.
- Tests (`tests/test_support.py`): search by part of a name and of an email, `%` matched literally, support only;
  history (status rows with the staff name, charge, return request, newest first, no other customer's events,
  `test_checkout_events_at_one_instant_read_placed_charge_paid`, a cancellation reads refund → cancelled once SP2
  is in); 404 for support, 403 for another customer. Commit.

## Task 5 — permission matrix

- Rows in `tests/test_permissions.py` for the three new endpoints and `GET /customers?q=`. Full pytest. Commit.

## Task 6 — pages

- Start the API on 8004, regenerate `schema.d.ts`. `web/src/app/admin/reports/page.tsx`,
  `web/src/app/admin/support/page.tsx` (components in their own files if they grow), two `LINKS` lines in
  `sidebar.tsx`. Run `typecheck`, `lint`, `build`, `test:unit`. Commit.

## Task 7 — wrap-up

- `doc/progress.md` entry at the top; full pytest; push; PR to `main` with "Plan changes" (spec §8) and the shared
  files touched; send the coordinator the link and test counts. After SP2/SP3 merge: rebase, update the builders,
  add the returns section and the return events, rerun everything.

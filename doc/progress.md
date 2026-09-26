# Progress log

Newest entries first. IDs such as R#, BR# and T1 refer to `.claude/plan.md`.

---

## 2026-09-26 — T18: browser journeys, delivery checks, and one bug they found

**Eighteen browser journeys** (`web/e2e/`, `npm run test:e2e`, Playwright against Chromium). The config
gives the suite its own stack: `scripts/seed_demo.py --database jbhifi_e2e_demo --create --seed 9120`
rebuilds a disposable database from `sql/*.sql` plus the documented scenarios, `uvicorn` serves it on
`:8100`, and `next dev` on `:3100` proxies to *that* API (`NEXT_DIST_DIR=.next/e2e` gives it its own build
directory, because `next dev` allows one server per directory and a developer's storefront is usually
running). No journey can read or write `jbhifi`. What the specs cover: catalogue search, a product page,
the cart; delivery checkout and Click & Collect; a lost reply retried under the same `Idempotency-Key`
(one order, not two); staff fulfilment to `delivered` with the customer's timeline; staff cancellation with
the stock back and a refund recorded; the returns desk (receive → process → refunded) and a final rejection;
the seeded empty store (`409 out_of_stock`), a product retired while it sits in the cart, and an address
retired between the cart and the checkout; a guest, a customer switch, another customer's order by URL
(`not_found`), a staff session on the storefront; and every customer route at phone width with no
`ReservedPage` copy left. Journeys assert in the browser *and* against the API, and prepare awkward state
through an isolated `request` context as the person entitled to create it.

**The browser suite found a real defect, and it is fixed.** Both providers declare who their surface acts
as (`ensureSession`), while the chosen identity lives in `localStorage` — unreadable until hydration.
During hydration the choice was still `undefined`, so the provider asked the API to *sign out*, racing the
load that was about to read the choice: a refresh, a pasted URL or a deep link cancelled a signed-in
session, and the next write came back `401 not_signed_in`. The Playwright trace shows it plainly — a
`DELETE /api/v1/session` between the reads and the writes. `context.tsx` and `admin/session.tsx` now hold
the session load until hydration has said who the browser chose.

**The error contract is now tested, and what a failure may say is part of it.** `tests/test_api_errors.py`
(13) pins the envelope, the status and the code for 401/403/404/409/422, the smoke endpoints, the rule names
(`br03_…`, `br18_…`, `product_sku_unique`, `br06_collect_at_retail_store`), malformed requests, unknown
routes and methods, a foreign order reading exactly like a missing one, and a commit-time deferred failure
returned as the ordinary 409 rather than a 500. It also pins what a failure may *not* say: the API answers a
database outage with a `503 database_unavailable` whose message is a sentence and whose driver text goes to
the log, and an unexpected traceback becomes `internal_error` plus one sentence, logged server-side.

**CI.** `.github/workflows/ci.yml` runs the backend suite, the web checks (`typecheck`, `lint`, `test:unit`,
`build`), an OpenAPI regeneration that fails if `web/src/lib/api/schema.d.ts` is stale, and these journeys —
all against a PostgreSQL 18 service, with no `.env` and no reliance on a developer's machine.

**Also.** A new address is normalised in the schema (trimmed, state upper-cased) before its length checks,
so a pasted ` nsw ` is accepted as `NSW`; `requirements.txt` had `httpx2` where the TestClient needs `httpx`.

**Verification (actually run, 2026-09-26).** `pytest -q` → **208 passed**; `npm run typecheck` → clean;
`npm run lint` → clean; `npm run test:unit` → **30 passed**; `npm run build` → succeeded; `npm run test:e2e`
→ **18 passed** (46.9 s once the database and caches exist). CI was written but not executed here — it needs
a GitHub runner.

**AI use.** T18 implemented with Codex (GPT-5) on 2026-09-26. Every command quoted above was run.

---

## 2026-09-26 — T17: reproducible demo data and project evidence

**One command builds the demo.** `scripts/seed_demo.py --database jbhifi_demo --create --seed 9120` drops
and rebuilds a disposable database from `sql/*.sql`, then adds ten scenarios on top of the reference seed:
both fulfilment paths in flight (`paid`, `picking`, `ready`), completed orders that are still returnable
and one that is 45 days old, a partial refund on a multi-line collection, a received return, a rejected
return, a return still waiting at the desk, a paid delivery cancellation, and `LG-43UT8050` emptied at
Sydney CBD as an out-of-stock example. The seeder refuses any database that is the API's own (`jbhifi`) or
whose name does not end in `_demo`/`_test`; a repeat run stops with "already contains the demo scenarios"
because each scenario has a deterministic `uuid5` idempotency key, so BR10 itself detects it and no marker
table was needed.

**How the scenarios are built.** Every row goes through the statements the application uses — real
`customer_order`/`order_line` inserts, the price from `v_product_current_price`, a conditional
`UPDATE … WHERE quantity >= n`, and real status `UPDATE`s so BR03, BR06–BR14 and BR18 run. Only the
*recorded times* are then aged, inside one maintenance transaction, by disabling exactly the timestamp and
immutability guards involved (`order_immutable`, the three append-only guards, `br18_adjustment_append_only`
and `br11_return_window`) and restoring them in a `finally`. `SET CONSTRAINTS ALL IMMEDIATE` runs the
deferred BR14 checks afterwards, and `reconcile()` recomputes every touched inventory row from opening
stock + logged adjustments − purchases + cancellations + processed returns, re-checks each order's charges
against its lines and its refunds against the charge, and re-checks BR12. A disagreement fails the run, so
a half-seeded database cannot pass silently.

**Documentation.** `doc/data-model.md` describes the keys, the four weak entities, the staff discriminator,
the recursive category tree, the deferred store ↔ manager key, the controlled redundancy, the two views and
the lock order. `doc/business-rules.md` maps BR01–BR18 to the exact constraint or trigger name, the
service responsible and the tests, and lists the record guards no numbered rule covers. `doc/demo.md` is
the walkthrough, and `scripts/demo_walkthrough.py` runs the customer → staff → customer journey over HTTP
with the same bodies the browser posts.

**Verification (actually run).** `pytest tests/test_demo_seed.py -q` → **9 passed**. The full suite with
`POSTGRES_TEST_DB=jbhifi_seed2_test` → **184 passed** (the count includes T04's catalogue tests and the
T11/T13/T14 lifecycle tests landed alongside this task). `seed_demo.py --database jbhifi_demo --create
--seed 9120` → 10 orders, 5 returns, 1 cancellation, reconciliation "13 stock rows, 10 orders, no
problems"; a second run exited 1 with the already-seeded message and `--database jbhifi` exited 2. With the
API running against `jbhifi_demo` (a second uvicorn on :8001, stopped afterwards),
`scripts/demo_walkthrough.py --api http://127.0.0.1:8001` → **25/25 steps passed**: both checkout modes,
two safe retries, staff fulfilment to `collected`, a cross-store `403`, a return requested-received-processed
with the refund equal to the purchase-time preview, and an `out_of_stock` refusal. The demo database
`jbhifi_demo` was left seeded for the browser walkthrough; the shared `jbhifi` database was never touched.

**AI use.** T17 implemented with Codex (GPT-5) on 2026-09-26. Every command and count above was run.

---

## 2026-09-26 — T09: atomic checkout, idempotent retries and protected order reads

**Checkout (transaction T1).** `app/services/orders.py` places one order per POST, in one transaction: lock
the customer, resolve the retry key, validate the reviewed request against current data, write
`customer_order` and `order_line` at the *server's* prices from `v_product_current_price`, take stock with a
conditional `UPDATE … WHERE quantity >= n` (BR03: the last unit has exactly one buyer), record the charge
through `app/services/payments.py` — nothing at all for a zero total — and move the status to `paid` with a
NULL staff actor. Locks are taken in a fixed order (customer, address, products by ascending id, then
inventory by store and product), so concurrent checkouts queue instead of deadlocking. `SET CONSTRAINTS ALL
IMMEDIATE` flushes the deferred rules inside the request, so a commit-time failure is the API's 409 rather
than a 500 at close. The client cannot supply a price, a customer or a line total: they are not in the body,
and the submitted `expected_total` is only compared — a mismatch is `409 price_changed` with the reviewed
lines, raised before anything is written.

**Retries.** `Idempotency-Key` is a required UUID header. `app/services/idempotency.py` fingerprints the
validated request canonically (sorted keys and lines, money as exact two-decimal strings), so the same key
with the same meaning replays the committed order — 200, no second side effect, even after a price change —
while the same key with a different body is `409 idempotency_conflict`.

**Reads.** `GET /api/v1/orders/{order_id}` and `GET /api/v1/customers/{customer_id}/orders` (newest first)
serve the customer's own orders, support staff any of them and store staff only their own store's; anything
else is a 404 — the same answer as an order that does not exist, so ids cannot be probed. The detail keeps
the sold prices, the address the order was placed with, the whole status timeline, and the moves the caller
may legally make next. `app/auth.py` gains `require_customer`, so a staff session cannot shop.

**Tests.** `tests/shop.py` is the shared harness (create a customer and a stocked product, place an order
through the API). `tests/test_checkout.py` (18) covers Click & Collect and delivery, a running promotion's
price, a zero-total order with no payment row, the warehouse refusal for collection, delivery needing the
customer's own active address, a malformed or duplicate basket, a retired or unknown product, the
reviewed-total check with nothing committed, out of stock, a later line failing and rolling back the earlier
ones, replay, key reuse with a different body, replay after a price change, and a guest being refused.
`tests/test_checkout_transactions.py` (4) races checkouts on their own connections: two buyers for the last
unit, the same key from two threads, overlapping baskets, and a checkout racing a retirement.
`tests/test_order_reads.py` (7) covers the read permissions, the timeline and the price snapshots.

**Verification (actually run).** `pytest -q` → **114 passed** (was 85) on the tree this landed in. The task
changes no frontend; the web checks were run against the same tree and are clean (`npm run test:unit` → 11
passed, `npm run typecheck`, `npm run lint`, `npm run build`).

**AI use.** T09 implemented with Codex (GPT-5) on 2026-09-26. Every command quoted above was run.

---

## 2026-09-26 — T05: shared web state you cannot act on by accident

**The loader names the resource, not just the request.** `web/src/lib/use-load.ts` keeps the logical key
next to the in-flight request id, so `data` is only ever *this* store's (or product's, or filter's) rows; a
same-key refresh keeps them on screen, and `isCurrent` says whether what is displayed came from the key
being asked for now. `setData(expectedKey, update)` applies only while the data still belongs to that key,
so a response that lands after the viewer moved on cannot be written into another record's screen. The
product page's one local update ("saved") is keyed the same way.

**Screens.** Stock: actions need `canAdjust && isCurrent`; changing store closes an open adjust dialog; and
a change made while "low stock only" is on re-reads the filtered list instead of editing it locally, since
a local edit cannot know whether a row still belongs in a ≤3 list. Product detail: while the route's
product is not current, Save and the brand picker are disabled, and the spec rows carry explicit labels.
Reference data a screen cannot work without — stores, categories, brands, the product list behind "New
promotion", the staff directory — now shows a retryable error (`ErrorBox` gained the optional `Retry`)
instead of an empty picker that still looks choosable.

**Dialogs.** The shared `Modal` has an accessible name (`aria-labelledby` on the title), moves focus inside
on open (deferring to a control's own `autoFocus`), keeps Tab cycling inside, closes on Escape, restores
focus to whatever opened it, and locks page scrolling while it is open.

**Tests.** `npm run test:unit` (new: Vitest + React Testing Library in jsdom, 11 tests in 5 files). The
network is mocked at the API-client boundary and resolved by hand, so every race is real: an answer for
store A arriving after the viewer switched to store B — asserted against store B's rows *and* its history —
a save started on one product while the route moves to another, out-of-order and same-key reloads and a
rejected load, the demo-customer switch never showing the previous customer's record and a failed record
surfacing with a retry, and the dialog's keyboard behaviour plus named controls.

**Verification (actually run).** `web/`: `npm run test:unit` → **11 passed**; `npm run typecheck`,
`npm run lint` and `npm run build` (15 routes) clean. This task changes no Python; the suite it shares the
tree with — T09's checkout and order reads — is green, `pytest -q` → **114 passed**.

**AI use.** T05 implemented with Codex (GPT-5) on 2026-09-26. Every command quoted above was run.

---

## 2026-09-26 — T16: the agreed reporting slice

The repository names a reporting slice but supplies no specification, so `doc/requirements.md` §6 records
these three reports as the retained scope and `doc/reports.md` defines each one's grain and filter.

**Definitions.** *Sales* counts money by each payment's **own** event time and orders by when they were
placed, with the three aggregates built in separate CTEs and only then joined to `store` — joining
`payment` to `order_line` first would multiply a 300.00 charge by the number of lines on its order.
*Low stock* lists active products at or below a threshold at one store, including products with **no
inventory row** there (a quantity of zero, not a missing row). *Returns* is the **cohort** of requests
created in the window, attributed to the store that fulfilled the order, with the refund joined on the
request rather than on the refund's date and the receiving store shown separately.

**Boundaries and access.** `from_date` is inclusive and `to_date` exclusive, both Sydney calendar dates;
the conversion to instants happens in SQL (`AT TIME ZONE 'Australia/Sydney'`), because a bare Windows
Python has no zone database while PostgreSQL always does, and each report returns the instants it used so
a figure can be checked by hand. Store staff see their own store; support may see any store, or all of
them for sales and returns; a guest gets 401.

**Artefacts.** `queries/reports.sql` holds the three queries with their explanations and expected shapes,
plus the read-only `NOT EXISTS` division example the plan asks for — deliberately outside `sql/`, whose
files all run during database creation. `app/services/reports.py` keeps the service copies, `doc/reports.md`
is the definition of record, and `/admin/reports` shows all three with a store picker and a date range.
No index was added: with this volume an index does not change the plan, and `doc/reports.md` records which
ones a real deployment should measure rather than claiming an unmeasured improvement.

**Tests.** `tests/test_reports.py` — 11 tests, each building committed rows in a month no other suite
touches (2025, because everything else commits "now") and checking a hand-calculated answer:
`test_sales_does_not_multiply_payments`, `test_only_that_stores_trade_is_reported`,
`test_refunds_use_their_own_event_date_and_net_off`, `test_an_impossible_period_is_refused`,
`test_low_stock_includes_products_with_no_inventory_row`, `test_low_stock_is_for_one_store_only`,
`test_return_report_cohort_is_the_request_date_not_the_refund_date`,
`test_return_report_counts_every_status`, `test_the_window_is_sydney_midnight_inclusive_to_exclusive`,
`test_reports_are_scoped_to_the_signed_in_store` and `test_the_default_window_is_the_last_thirty_days`.
The return fixtures use the same maintenance path as `scripts/seed_demo.py` for the two timestamps the API
generates for itself, and flush deferred constraints (`SET CONSTRAINTS ALL IMMEDIATE`) before the
`ALTER TABLE … DISABLE TRIGGER` that ages `requested_at`.

**Verification (actually run).** `pytest -q` → **208 passed**. In `web/`: `npm run test:unit` → 30 passed,
`typecheck`, `lint` and `build` clean with 21 routes (`/admin/reports` among them), and
`web/src/lib/api/schema.d.ts` regenerated from the app's own OpenAPI (the running server on :8000 predated
this router, so the document was taken from `app.openapi()` directly).

**AI use.** T16 implemented with Codex (GPT-5) on 2026-09-26. All commands and counts above were run.

---

## 2026-09-26 — T06–T15: the customer and staff screens

The storefront and the store admin are now real applications on top of the frozen API. Every screen talks
to the API through the same-origin proxy, and no customer route renders a placeholder any more.

**Storefront.** `/products` is a URL-backed catalogue (search, category at any depth, brand, inclusive
price range, store-aware stock, one request per view); `/products/[id]` shows specs, promotions and stock
at every store with mine first; `/stores` groups the 13 locations by state and answers "who has it?" for a
searched product; `/cart` keeps product ids and quantities in the browser and shows the current prices and
that store's stock, with all arithmetic in integer cents; `/checkout` offers delivery or Click & Collect
and sends one request keyed by an Idempotency-Key that is reused only while the reviewed body is identical;
`/orders` and `/orders/[id]` show the purchase-time lines, the recorded address, the payments and the full
timeline, with the return form driven by the server's `return_eligibility`; `/returns` lists requests and
their outcome; `/account` adds and retires addresses (a dialog for each, with the API allocating numbers
and the customer re-read afterwards). The home page's placeholder cards became real "My orders" and
"Returns" panels, and the category counts now use the same recursive walk as the catalogue.

**Store admin.** `/admin/orders` is the store-scoped queue with a status filter; `/admin/orders/[id]` shows
the pick list, address, payments and timeline, and offers exactly the moves the server reports in
`allowed_actions` — with cancellation as its own dialog that spells out the refund and the restock before
it happens. `/admin/returns` is the returns desk (requests to take in, and what it has already taken in)
with receipt, rejection and processing as separate confirmed actions showing the refund preview. Both
screens keep the *displayed* `expected_status`, so a colleague's move is reported as `stale_status` rather
than silently applied, and every mutation is keyed to the record the screen is showing.

**Verification (actually run).** `pytest -q` → **197 passed**. In `web/`: `npm run test:unit` → 30 passed,
and `typecheck`, `lint` and `build` (17 routes) are clean. A scripted journey against the running demo
stack (Alice signs in → 2 × Xbox consoles collected at Sydney CBD → the same request replayed → staff move
placed → paid → picking → ready → collected → customer requests 1 back → staff receive → process) left
exactly one order, one charge of 1598.00, one refund of 799.00, stock 8 → 6 → 7, and the customer's
returns list showing `refunded`. `rg 'ReservedPage' 'web/src/app/(shop)'` finds nothing; the obsolete
placeholder component was deleted and `shop-pages.ts` is kept as the route/requirement catalogue.

**AI use.** The screens were built with Codex (GPT-5) on 2026-09-26, in several agent sessions working on
different routes at once. All commands and counts above were actually run.

---

## 2026-09-26 — T01: demo sessions and enforced actor permissions

**Identity.** `app/auth.py` issues one signed, HTTP-only cookie (`jbhifi_session`: base64url JSON plus an
HMAC-SHA256 tag) and re-reads the identity from the database on every request, so a deleted customer or
staff row ends the session instead of being trusted from the cookie. The cookie carries only
`{kind, id}`; the store, the staff type and the manager flag come from the row, so a privilege change
takes effect on the next request. `app/routers/auth.py` exposes the session as
`GET/POST/DELETE /api/v1/session` — the plan named `POST /auth/demo-login`; one session resource for
"who am I", set and cleared, is the smaller surface — and `DEMO_MODE=0` refuses to sign anyone in.

**Role matrix (plan §3 decisions).** Public reads stay public: products, categories, brands, stores and
per-store stock, plus the demo customer directory the storefront picker reads. That last one is a
deliberate, recorded deviation from the strictest reading of the plan: `GET /customers` still lists
id/name/email so the picker works before anyone signs in, while `GET /customers/{id}` serves a customer
only their own record and support staff anyone's — another customer's id is `403 not_your_account`
without revealing whether it exists. Catalogue and promotion writes need a store manager or support
staff; stock adjustments and the adjustment log need that store's staff, or support; an absent session
is `401 not_signed_in` and a wrong one `403` with a distinct code per case. 401 and 403 joined
`ERROR_RESPONSES`, so the generated client knows them.

**The actor is never in the body.** `staff_id` is gone from `AdjustmentCreate` (which now forbids extra
fields) and from the admin payload: the API derives the logged staff member from the session, and the
database still enforces BR18, so a forged body cannot attribute a stock change to someone else. The web
side replaces the customer-in-localStorage identity with `web/src/lib/session.ts` (a thin `fetch`
wrapper, deliberately outside the generated types so a sign-in cannot be broken by an API change) and
per-surface session providers — `AdminSessionProvider` for `/admin`, the shop context for the
storefront — which declare who that surface acts as, treat the browser's picker as a hint only, and drop
it on switch.

**Shared web prerequisite (T05's interface, landed here to keep the tree green).**
`web/src/lib/use-load.ts` now exposes `isCurrent` and applies `setData(expectedKey, update)` only while
the data on screen still belongs to `expectedKey`, so a late result cannot be written into another
store's or product's rows.

**Tests.** `tests/test_auth.py` adds 14: guest browsing, the signed HTTP-only cookie, sign-out, a
tampered cookie, an unknown identity, demo sign-in switched off, a customer reading only their own
record, support reading any customer, store staff refused customer records, a body that tries to choose
the staff member, another store's stock, store-scoped history, and catalogue/promotion writes refused
to customers and ordinary store staff. `tests/test_api.py` still covers every endpoint and rule, but now
uses a per-test client with an explicit `sign_in(...)`, so one test's session never leaks into the next,
and its stock cases prove the store-scope refusal (`403 other_store`) alongside the unchanged BR03 and
BR18 `409`s.

**Verification (actually run).** `pytest -q` → **85 passed** (was 71). `web/`: `npm run typecheck`,
`npm run lint` and `npm run build` (15 routes) clean. `web/src/lib/api/schema.d.ts` was regenerated from
the app's own OpenAPI (`app.openapi()`), which is where `SessionIn`/`SessionOut` and the
`staff_id`-free `AdjustmentCreate` come from. Operational note for the demo: the API process that was
already running on :8000 was started before this change, so restart it
(`.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`) to serve
`/api/v1/session`.

**AI use.** T01 implemented with Codex (GPT-5) on 2026-09-26. Every command quoted above was run.

---

## 2026-09-26 — T03: retry keys, cancellation refunds and the return audit trail

**Schema.** `customer_order.request_fingerprint` and `return_request.idempotency_key` /
`request_fingerprint` make a retry distinguishable from changed content; a return request is unique per
`(order_id, idempotency_key)` (`return_idempotency_unique`), so the same key on another order is a
different request. `order_cancellation` records a cancellation separately from a merchandise return (one
per order, composite key as an FK target, append-only), and `payment.cancellation_id` gives a refund a
second legal source. `br14_refund_has_return` is replaced by `br14_refund_has_source`: a charge has no
source and a refund has exactly one, with `br14_refund_once_per_return` and
`br14_refund_once_per_cancellation` keeping each source refundable once.

**Rules.** `return_status_history` mirrors the order timeline and is written only by a `SECURITY DEFINER`
trigger (`log_return_status_change`), including the actor from the transaction's `app.staff_id`; a retry
that sets the same status appends nothing. BR14 now has two layers: a BEFORE trigger keeps the ceiling
(`br14_refunds_within_charged`), an AFTER trigger requires the amount to equal what the source entitles
(`br14_refund_matches_source` — the returned lines at purchase prices, or the balance left captured on a
cancelled order), and three deferred constraint triggers (`br14_source_complete`) run at COMMIT so a
service may write the payment and move the status in either order, while a half-finished financial state
cannot commit. The AFTER placement is deliberate: a declarative constraint that also applies (say the
once-per-return UNIQUE) is then the one reported, which keeps the rule names informative.

**Tests.** `tests/test_lifecycle_schema.py` covers the key uniqueness, exactly-one-source,
amount-matches-source, once-per-cancellation, append-only history and actor attribution, plus six
commit-time completeness cases run on their own connection (so a COMMIT-time failure is observed exactly
as the API sees it). Existing fixtures now supply the new NOT NULL columns, and `br14_refund_has_return`
assertions moved to `br14_refund_has_source` deliberately.

**Verification (actually run).** `pytest -q` → **71 passed** (was 57). A full database rebuild from an
empty volume re-runs `sql/*.sql` in order, loads the seed (48 products) and creates the new tables; the
running API still answers `/health` with `{"status":"ok","db":"jbhifi"}`.

**AI use.** T03 implemented with Codex (GPT-5) on 2026-09-26. All tests and commands above were run.

---

## 2026-09-26 — T02: close the lifecycle and audit bypasses

The purchase record, the audit trail and the payment ledger are now immutable, the return window is
exact, the category tree cannot cycle, and the API runs as a least-privilege role.

**Schema and triggers (`sql/01_tables.sql`, `sql/02_rules.sql`, `sql/05_permissions.sql`).**

- **Order lines** (BR08) are guarded by one function that raises both codes: a unit-price change is still
  `br08_unit_price_immutable` (the existing test still asserts that name), while any other change to
  `order_id`, `line_no`, `product_id`, `quantity`, or inserting into / deleting from a committed order is
  `br08_order_line_immutable`. Lines can only be assembled while the order is `placed`.
- **Order headers** are frozen after placement (customer, idempotency key, fulfilment method, store,
  address, placement time): only `status` may move, so `order_immutable` stops an UPDATE re-pointing an
  order at another customer, store or address.
- **Payments and both status histories are append-only** (`payment_append_only`,
  `order_status_history_append_only`). A charge can no longer be reduced or deleted after a refund was
  accepted against it, so BR14's ceiling stays meaningful.
- **BR12** now fires on INSERT, UPDATE *and* DELETE, refuses to let a return line change its request,
  order or line (`br12_return_line_ownership`), and refuses any edit once the request is no longer
  `requested` (`br12_return_line_editable`) — closing the "move a rejected line onto a live request"
  hole.
- **BR11** generates `requested_at` on the server (a supplied value is overwritten) and makes it
  immutable. The window is the extracted predicate
  `return_request_is_in_window(completed_at, requested_at)`, so the exact boundary is testable: 30 days
  is inside, 30 days + 1 µs is not.
- **Category cycles** are refused by `category_no_cycle`, which walks the subtree with a recursive CTE.
  This is the precondition for T04's arbitrary-depth traversal.
- **`jbhifi_app`** is a login role with the table/sequence privileges the application needs: it can
  append to `stock_adjustment` but not edit it, read but never write `order_status_history`,
  `return_status_history` and `payment` (beyond INSERT), and cannot change the schema. The two history
  triggers are `SECURITY DEFINER` with a fixed `search_path`, so the audit row can still be written
  without giving the role INSERT on the history tables. `app/db.py` connects as this role when
  `POSTGRES_APP_USER` is set, and the bootstrap/test owner connection is unchanged.

**Tests.** `tests/lifecycle.py` builds histories through real statements and exposes `backdate_history`
(a maintenance-only path that briefly suspends the history guard) for the expiry case.
`tests/test_lifecycle_rules.py` adds the charge/history/line/return-line immutability tests, the exact
window predicate, the three-level category cycle and the two role-permission tests;
`tests/test_rule_concurrency.py` adds BR12, BR14 and BR15 races driven by `tests/concurrency.py`
(bounded barrier and bounded join, so a stuck lock fails loudly instead of hanging).

**Verification (actually run).** `pytest -q` → **57 passed** (was 42). Full database rebuild from an
empty volume re-runs `sql/*.sql` in order and loads the seed (48 products) with the role created. The API
was started and confirmed to connect as `jbhifi_app` (`select current_user` → `jbhifi_app`), serving
`/health`, `/api/v1/products` and a stock adjustment.

**AI use.** T02 implemented with Codex (GPT-5) on 2026-09-26. All tests and commands above were run.

---

## 2026-09-26 — T00: canonical project and runnable baseline

Established the root checkout as the single working tree and recorded a verified starting point before
implementation began.

- **Working tree.** All work targets the repository root. The nested `JBhifi/` gitlink is documented as a
  duplicate and left untouched (keep/remove is still a team decision). See `doc/requirements.md` §1.
- **Requirements.** Wrote `doc/requirements.md` from the repository's own R#/BR# wording and the proposed
  decisions, marking R7–R10 and R12 and the original T3+ tasks as **unknown** rather than inventing them.
- **Test isolation.** `POSTGRES_TEST_DB` (default `jbhifi_test`) selects the disposable test database, and
  `assert_is_test_database` refuses to let any fixture drop/rebuild the demo database or a name that is not
  test-shaped. `docker-compose.yml` is untouched: the demo database and data survive a test run.
- **Baseline checks (actually run on 2026-09-26, on this machine).**
  - `docker compose up -d` → PostgreSQL 18.6 on `localhost:5433`, seed loaded (48 products, 4 customers).
  - `pytest -q` → **42 passed** (31 business-rule + 4 stock-transaction + 7 API tests) in ~3 s.
  - `web/`: `npm ci` (382 packages, 0 vulnerabilities) → `npm run typecheck`, `npm run lint`,
    `npm run build` all clean. Node 24.19.0, npm 11.17.0, Python 3.12, `postgres:18`.
  - Tool versions installed: fastapi 0.141.1, pydantic 2.13.5, psycopg2-binary 2.9.13, pytest 9.1.1,
    next 16.3.6, react 19.2.8, typescript 5.
- **AI use.** T00 executed with Codex (GPT-5) on 2026-09-26: environment provisioning, the test-isolation
  guard and this record. All commands above were actually run and their real output recorded.

---

## 2026-09-26 — Implementation audit and detailed todo plan

Reviewed the root project, with separate read-only backend, database and frontend audits, and wrote
[`todo.md`](../todo.md). The user selected the current repository requirements as the source because the
referenced `.claude/plan.md` is absent. The plan distinguishes existing code, missing workflows, confirmed
requirements and proposed decisions, including retry support, cancellation refunds and reporting scope.

**Verification during planning.** Compared all 82 regular tracked root files with the nested `JBhifi/`
checkout: identical. Parsed 23 app and 6 test Python files successfully and counted 42 test functions.
These are static checks only. Application tests, frontend checks and browser journeys were not rerun:
this checkout lacks installed frontend dependencies, `.env` and the required runnable test/API setup.
No application code or database content was changed.

**AI use.** Repository audit and planning performed with Codex, including three read-only subsystem
agents. Implementation tasks in `todo.md` remain unchecked.

---

## 2026-09-26 — Branch `storefront`: customer home page, reserved customer pages

**What's on the branch.**

- The web app now has two parts: the **storefront at `/`** and the **store admin at `/admin`** (moved from
  `/inventory`, `/products`, `/promotions` — those old URLs are gone). Route group `web/src/app/(shop)`.
- **Home page, live:** current deals sorted by discount, each with its stock at "my store" (R2, R3); "starting
  soon" promotions; shop by category (the recursive category tree); stores near you, retail only (BR06).
- **Reserved pages:** catalogue, product, cart, checkout, my orders, order, my returns, stores, account. Each
  shows what it will do, which R#/BR#/T# it covers, the API it needs (existing or to build) and the owner
  slice. The content is one list, `web/src/lib/shop-pages.ts`; building a page = replacing its `<ReservedPage>`.
- **Demo customers:** 4 customers with addresses in `10_seed_reference.sql` (one has a retired address, BR16),
  and `GET /api/v1/customers`, `/customers/{id}`. **Reset the database** to get them.

**Decisions — proposed.**

1. **Demo sign-in is a "Signed in as" picker kept in the browser (localStorage)**, not the plan's signed-cookie
   demo login. It is a UI convenience, not an actor/authorisation layer: the API doesn't know who is asking yet.
   The `get_current_actor` dependency (plan §7) is still to build, before checkout.
2. **"My store"** is the chosen store, else the first retail store in the customer's state, else the first one.
3. **Promotions report `product_active`**, so the storefront never advertises a retired product.
4. **Added three pages to plan §7's list** (my returns, stores, account) — see the plan for why.

**Verification.** `pytest`: 42 passed. Typecheck, lint and build clean. A scripted browser run checked guest vs
signed-in home, store choice and its persistence, search and category links, every reserved page, and the
moved admin. A four-lens review (Next.js/React, data/API, UX/accessibility, spec/docs) with adversarial
verification confirmed 18 distinct issues; all were fixed (e.g. page titles, API-down state, last day of a sale,
phone navigation).

**AI use.** Built and reviewed with Claude Code (including a multi-agent review workflow) on 2026-09-26.
Include in the AI-use acknowledgement.

---

## 2026-09-26 — Branch `admin`: schema v1, catalogue and stock API, stock admin UI

**What's on the branch.**

- `sql/` implements the whole data model of plan §4: domains (`00_domains`), tables and declarative
  constraints (`01_tables`), trigger rules (`02_rules`), views (`03_views`) and reference data
  (`10_seed_reference`: 12 stores + 1 warehouse, 42 staff, 48 products with specs, 9 promotions, opening stock).
- API under `/api/v1`: stores, staff, categories, brands, products (+ specs), per-store inventory and stock
  adjustments, promotions. One error shape; a database rule violation is a 409 whose `code` is the constraint
  name (`app/errors.py`).
- `web/` (Next.js 16): admin console — inventory (±1 buttons, adjust dialog, recent adjustments), products
  (list, create, edit, specs), promotions (list, create, delete).
- `tests/`: every rule BR01–BR18 broken and identified by constraint name; the stock-adjustment transaction
  under concurrency; an API smoke test per endpoint. Runs against a separate `jbhifi_test` database.

**Decisions — proposed, need team agreement.**

1. **R13 / BR18 / T-7: manual stock adjustments are logged** in `stock_adjustment`: who (a staff member of
   that store — a composite FK, the same pattern as BR04), why (the reason must fit the sign), how much, and
   the quantity left. Append-only.
2. **The API checks the shape of a request; only the database checks the rules.** Each rule lives in one
   place, and the UI shows the database's own refusal (the constraint name), which is what the demo should
   show. So Pydantic has no `ge=0` on prices: a negative price reaches the database and fails BR02.
3. **Stock changes are relative** (`quantity = quantity + delta`), never read → compute in Python → write
   back (the lost update in the experiment below).
4. **Triggers that read other rows lock a parent row first** (`SELECT … FOR UPDATE`): BR12 locks the order
   line, BR14 the order, BR15 the product. Without that, two concurrent transactions could both pass the check
   and together break the rule (write skew).
5. **Surrogate keys are `GENERATED BY DEFAULT AS IDENTITY`**, so the seed can pin store and staff ids (the
   circular store ↔ manager FK needs them); the seed then moves the sequences past them with `setval`.
6. **Seeded promotions are computed in Sydney time** (`SET LOCAL timezone` in the seed transaction), so they
   start at local midnight even across the daylight-saving change.

**Gotchas found.**

- `INSERT … ON CONFLICT DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity` can't apply a negative
  delta: PostgreSQL checks the `CHECK` against the proposed insert row first (verified: with 5 in stock,
  inserting −3 fails with `Failing row contains (1, -3)`). Hence "insert 0 if missing, then a relative UPDATE".
- The Next.js 16 dev server only trusts `localhost`. Opening `http://127.0.0.1:3000` blocked its dev scripts and
  the pages never loaded data, so `127.0.0.1` is in `allowedDevOrigins`.
- Starlette 1.x wants `httpx2` for `TestClient` (plain `httpx` still works, with a deprecation warning).

**Verification.** `pytest`: 41 passed. `npm run typecheck`, `lint` and `build` are clean. A scripted browser
run (Playwright driving local Chrome; the script is not committed) clicked through ±1, the adjust dialog, the
BR03 / BR18 / BR15 / SKU-format refusals and creating and deleting a promotion: 17/17 checks, and no console
errors apart from the deliberate 409 responses.

**AI use.** Built with Claude Code on 2026-09-25/26 from `.claude/plan.md`: schema, triggers, API, tests and
UI. The tests and checks above were actually run. Include this in the AI-use acknowledgement. Every member
should read `sql/` and `tests/test_business_rules.py` before the Week 9 tutor meeting.

---

## 2026-09-25 — Decision: hand-written SQL (psycopg2), no ORM in Phase 1

**Question.** Should Phase 1 use an ORM (e.g. SQLAlchemy), or keep hand-written SQL through psycopg2?

**Decision.** Phase 1 uses hand-written SQL via psycopg2 — no ORM. The Phase 2 spec may revisit this, but only
for new CRUD-heavy modules (admin screens, support tickets, agent logs). Checkout, returns and the other core
transactions keep explicit SQL with explicit locking, and the database constraints and triggers stay either way.

**Why.**

1. **The SQL itself is assessed.** Criterion 4 (20%) is marked on the submitted implementation, and its HD
   descriptor asks for SQL that is "precise and expressive". ORM-generated SQL isn't ours to present, and it
   can't show the unit's techniques (joins, nested queries, `NOT EXISTS` division).
2. **We couldn't use what an ORM is best at.** Domains, named constraints, `DEFERRABLE` circular FKs, triggers
   and views all need raw SQL anyway, so an ORM would mean maintaining two layers.
3. **An ORM hides what criterion 4 asks us to reason about** — transaction boundaries, locking, concurrency.
   The experiment below shows the idiomatic ORM pattern overselling stock.
4. **Every member must be able to explain the submission.** An ORM adds sessions, autoflush and lazy loading on
   top of SQL, which makes "which statements run, and where does the transaction start and end?" harder to answer.

**Costs we accept, and how we handle them.**

| Cost | Mitigation |
|---|---|
| Mapping rows to objects | `RealDictCursor` + Pydantic models |
| Optional search filters need a dynamic `WHERE` | compose it with the `psycopg2.sql` module; values still go through `%s` parameters — never f-strings |
| Schema migrations | Phase 1 data is generated, so edit `sql/` and rebuild with `docker compose down -v` — no Alembic |
| Repeated queries | SQL lives in `app/services/`; each query is written once |

### Experiment: two customers buy the last unit

**Goal.** Find out whether the idiomatic ORM update is safe under concurrency, compared with a hand-written
conditional `UPDATE`, and whether the BR03 constraint `CHECK (quantity >= 0)` catches overselling.

**Setup.**

- Throwaway PostgreSQL 18.6 container on port 5434 — the project database on 5433 was not touched.
  Default isolation level (`READ COMMITTED`).
- Python 3.14.7, SQLAlchemy 2.1.0, psycopg2-binary 2.9.13.
- One table, one product, one unit in stock:

  ```sql
  CREATE TABLE inventory (
      product  text PRIMARY KEY,
      quantity int  NOT NULL CONSTRAINT br03_inventory_qty_nonneg CHECK (quantity >= 0)
  );
  INSERT INTO inventory VALUES ('PS5', 1);
  ```

**Scenarios.**

1. **ORM idiom.** Each customer loads the row as an object, decrements `quantity` in Python and commits. The two
   sessions are interleaved deterministically: both read before either writes.
2. **Hand-written conditional UPDATE.**
   `UPDATE inventory SET quantity = quantity - 1 WHERE product = %s AND quantity >= 1`, run by two concurrent
   transactions. A holds its row lock for 1 s before committing; B starts 0.2 s after A.
3. **ORM with a row lock.** Same as 1, but the row is loaded with `with_for_update=True`
   (`SELECT … FOR UPDATE`); same timing as 2.

**Output** (this run was on 2026-09-25; an earlier run the same day gave the same results, with B waiting 0.78 s
in scenario 2):

```text
PostgreSQL 18.6 | isolation: read committed | SQLAlchemy 2.1.0 | psycopg2 2.9.13

[1] ORM idiom: load the row as an object, decrement in Python, commit
    SQL emitted by the ORM: UPDATE inventory SET quantity=%(quantity)s WHERE inventory.product = %(inventory_product)s  params={'quantity': 0, 'inventory_product': 'PS5'}
  customer A: order placed
    SQL emitted by the ORM: UPDATE inventory SET quantity=%(quantity)s WHERE inventory.product = %(inventory_product)s  params={'quantity': 0, 'inventory_product': 'PS5'}
  customer B: order placed
  RESULT: sold 2, stock left 0  <- 1 unit sold twice; the CHECK never fired

[2] Hand-written SQL: UPDATE ... SET quantity = quantity - 1 WHERE ... AND quantity >= 1
  customer A: 1 row(s) updated after waiting 0.00s -> order placed
  customer B: 0 row(s) updated after waiting 0.79s -> refused: out of stock
  RESULT: sold 1, stock left 0

[3] ORM with SELECT ... FOR UPDATE (with_for_update=True)
    SQL emitted by the ORM: UPDATE inventory SET quantity=%(quantity)s WHERE inventory.product = %(inventory_product)s  params={'quantity': 0, 'inventory_product': 'PS5'}
  customer A: order placed (waited 0.01s for the lock)
  customer B: refused: out of stock (waited 0.82s for the lock)
  RESULT: stock left 0
```

**What happened.**

- **[1] Lost update → oversold.** Both sessions read `quantity = 1`. The ORM computed `1 - 1` in Python and wrote
  the result as an absolute value — `UPDATE inventory SET quantity = 0`, twice. One unit, two orders.
  The CHECK constraint never fired because no statement ever wrote a negative value, so **BR03 alone cannot
  prevent this**. This is the classic read–modify–write lost update. Hand-written SQL that runs a `SELECT` and
  then `UPDATE … SET quantity = <value computed in Python>` has exactly the same bug; the ORM just makes that
  pattern the default.
- **[2] Correct.** B's `UPDATE` blocked on A's row lock for about 0.8 s. After A committed, PostgreSQL
  re-evaluated B's `WHERE quantity >= 1` against the newest version of the row, found 0, and updated 0 rows —
  so B was refused. The decrement happens inside the database, atomically with the check.
- **[3] Also correct — but only because we knew to lock.** B's `SELECT … FOR UPDATE` waited about 0.8 s for A,
  then read 0 and refused.

**Takeaways.**

- Checkout (T1, plan §5) uses the conditional `UPDATE` from scenario 2 and treats "0 rows updated" as
  out of stock.
- BR03's `CHECK` is a backstop, not the mechanism: it only catches writes that go negative.
- Report §4 material: how the lost update happens, why a CHECK constraint can't catch it, and why the
  conditional `UPDATE` is correct under `READ COMMITTED`. Scenario 2 is also the basis of the
  "last console on launch day" video idea (plan §10).

<details>
<summary><b>Reproduce</b> — commands and full script</summary>

```bash
docker run --rm -d --name orm-demo-db -p 5434:5432 \
  -e POSTGRES_USER=jbhifi -e POSTGRES_PASSWORD=devpassword -e POSTGRES_DB=jbhifi postgres:18
python3 -m venv /tmp/orm-demo && /tmp/orm-demo/bin/pip install sqlalchemy psycopg2-binary
/tmp/orm-demo/bin/python orm_vs_sql.py
docker stop orm-demo-db        # --rm removes the container and its data
```

`orm_vs_sql.py`:

```python
"""Two customers race for the last unit: ORM idiom vs conditional UPDATE vs ORM with a row lock."""
import threading
import time

import psycopg2
import sqlalchemy
from sqlalchemy import Integer, String, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DSN = dict(host="localhost", port=5434, dbname="jbhifi", user="jbhifi", password="devpassword")
engine = create_engine("postgresql+psycopg2://jbhifi:devpassword@localhost:5434/jbhifi")


class Base(DeclarativeBase):
    pass


class Inventory(Base):
    __tablename__ = "inventory"
    product: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)


@event.listens_for(engine, "before_cursor_execute")
def show_update(conn, cursor, statement, params, context, executemany):
    if statement.lstrip().startswith("UPDATE"):
        print(f"    SQL emitted by the ORM: {' '.join(statement.split())}  params={params}")


def reset():
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS inventory"))
        c.execute(text("CREATE TABLE inventory (product text PRIMARY KEY, quantity int NOT NULL "
                       "CONSTRAINT br03_inventory_qty_nonneg CHECK (quantity >= 0))"))
        c.execute(text("INSERT INTO inventory VALUES ('PS5', 1)"))


def stock_left():
    with engine.connect() as c:
        return c.execute(text("SELECT quantity FROM inventory")).scalar()


with engine.connect() as c:
    print("PostgreSQL", c.execute(text("SHOW server_version")).scalar().split()[0],
          "| isolation:", c.execute(text("SHOW transaction_isolation")).scalar(),
          "| SQLAlchemy", sqlalchemy.__version__, "| psycopg2", psycopg2.__version__.split()[0])
print()

# 1. ORM idiom: load the row as an object, decrement in Python, commit
print("[1] ORM idiom: load the row as an object, decrement in Python, commit")
reset()
sold = 0
a, b = Session(engine), Session(engine)
inv_a = a.get(Inventory, "PS5")   # A reads quantity = 1
inv_b = b.get(Inventory, "PS5")   # B reads quantity = 1 (A has not written yet)
for name, s, inv in (("A", a, inv_a), ("B", b, inv_b)):
    if inv.quantity >= 1:
        inv.quantity -= 1
        s.commit()
        sold += 1
        print(f"  customer {name}: order placed")
print(f"  RESULT: sold {sold}, stock left {stock_left()}  <- 1 unit sold twice; the CHECK never fired\n")

# 2. Hand-written conditional UPDATE, two concurrent transactions
print("[2] Hand-written SQL: UPDATE ... SET quantity = quantity - 1 WHERE ... AND quantity >= 1")
reset()
results = {}


def raw_buyer(name, hold_seconds):
    conn = psycopg2.connect(**DSN)
    t0 = time.perf_counter()
    with conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE inventory SET quantity = quantity - 1 "
                        "WHERE product = %s AND quantity >= 1", ("PS5",))
            results[name] = (cur.rowcount, time.perf_counter() - t0)
            time.sleep(hold_seconds)      # A holds its row lock for 1 s before committing
    conn.close()


ta = threading.Thread(target=raw_buyer, args=("A", 1.0)); ta.start(); time.sleep(0.2)
tb = threading.Thread(target=raw_buyer, args=("B", 0)); tb.start()
ta.join(); tb.join()
for name in ("A", "B"):
    rows, waited = results[name]
    print(f"  customer {name}: {rows} row(s) updated after waiting {waited:.2f}s -> "
          f"{'order placed' if rows else 'refused: out of stock'}")
print(f"  RESULT: sold {sum(r for r, _ in results.values())}, stock left {stock_left()}\n")

# 3. ORM with an explicit row lock
print("[3] ORM with SELECT ... FOR UPDATE (with_for_update=True)")
reset()
outcome = {}


def orm_locked_buyer(name, hold_seconds):
    with Session(engine) as s:
        t0 = time.perf_counter()
        inv = s.get(Inventory, "PS5", with_for_update=True)   # waits while another tx holds the lock
        waited = time.perf_counter() - t0
        if inv.quantity >= 1:
            inv.quantity -= 1
            time.sleep(hold_seconds)
            s.commit()
            outcome[name] = f"order placed (waited {waited:.2f}s for the lock)"
        else:
            s.rollback()
            outcome[name] = f"refused: out of stock (waited {waited:.2f}s for the lock)"


ta = threading.Thread(target=orm_locked_buyer, args=("A", 1.0)); ta.start(); time.sleep(0.2)
tb = threading.Thread(target=orm_locked_buyer, args=("B", 0)); tb.start()
ta.join(); tb.join()
for name in ("A", "B"):
    print(f"  customer {name}: {outcome[name]}")
print(f"  RESULT: stock left {stock_left()}")
```

</details>

**AI use.** This experiment was designed and run with Claude Code; the output above is from an actual run.
Include it in the submission's AI-use acknowledgement.

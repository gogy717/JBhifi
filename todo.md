# JB Hi-Fi Full Implementation Plan

## Status and ownership (keep this section current)

Updated 2026-09-26. The checkbox list below is the original plan; this table is the live status, plus who
is working where — read it before starting anything, so two workers do not touch the same file.

| Task | Status | Commit / notes |
|---|---|---|
| T00 | done | `32e0b4e` requirements, test isolation, baseline recorded |
| T01 | done | `6c5266d` signed demo session, actor permissions, role matrix |
| T02 | done | `fcb1e49` purchase records frozen, history/payments append-only, `jbhifi_app` role |
| T03 | done | `ad05e0b` retry fingerprints, cancellation source, return audit trail |
| T04 | done | `4d48349` price filters, arbitrary-depth categories, `store_quantity` |
| T05 | done | `12ea4eb` `useLoad.isCurrent` + keyed `setData`, a11y modal, Vitest runner |
| T09 | done | `d4d2e0c`/`14773d7`/`52bc14c` atomic checkout, idempotent retries, order reads |
| T11 | done | `ea97295` staff fulfilment moves, atomic cancellation |
| T13, T14 | done | `16af842` return requests, receipt, rejection, atomic refund/restock |
| T06, T07, T08, T10, T12, T15 | done | the customer and admin screens: catalogue, product, stores, cart, checkout, orders, returns, account, the staff order queue and the returns desk (see `doc/progress.md`) |
| T16 (reports) | done | `e2e878c`: `queries/reports.sql`, `app/{schemas,services,routers}/reports.py`, `tests/test_reports.py` (11 tests), `doc/reports.md`, `/admin/reports` and its sidebar link. Definitions in `doc/reports.md`. |
| T17 (demo data + evidence) | done | `f4471e3`/`fa235e8`/`d3581f1`: `scripts/seed_demo.py`, `scripts/demo_walkthrough.py`, `tests/test_demo_seed.py`, `doc/demo.md`, `doc/data-model.md`, `doc/business-rules.md`. The last two items — cleaning the planning copy out of `web/src/lib/shop-pages.ts`, `web/README.md` and the home page — are the root agent's and are done too. |
| T18 (e2e + CI) | done | `afa8cf3` one sanitised error envelope + `tests/test_api_errors.py` (13), `0b15dc0` `web/playwright.config.ts`, `web/e2e/**` (18 journeys), `web/package.json` (`test:e2e`), `web/e2e/README.md`, `.github/workflows/ci.yml`, `web/next.config.ts` (`NEXT_DIST_DIR`); `886c69f` address normalisation. The journeys found and `c2f62f0` fixed a session-sign-out race during hydration in `web/src/components/{shop/context,admin/session}.tsx` — the only two screen files T18 touched. |

**Every task in this plan is implemented.** The delivery verification is at the top of `doc/progress.md`:
208 backend tests, 30 web unit tests, 21 built routes, 18 browser journeys and generated types in sync with
the API. The limitations that remain are listed there too.

**Frozen contracts.** The API covers catalogue (`/products`, with `store_quantity`), orders (`/orders`,
`/customers/{id}/orders`, `/stores/{id}/orders`, status + cancel), returns (`/orders/{id}/returns`,
`/customers/{id}/returns`, `/stores/{id}/returns`, receive/reject/process), addresses and reports
(`/reports/{sales,low-stock,returns}`). If you change the API, run `npm run gen:api` and commit the result:
CI fails on a drift between `web/src/lib/api/schema.d.ts` and the running API.

**Rules for every worker.** `pytest -q` must stay green; never run `docker compose down -v`; `git add` only
the files you own, never `git add -A`; and if two people run `pytest` at once, give each its own
`POSTGRES_TEST_DB` ending in `_test`, or they will drop each other's database.

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task by task. Track work with the checkboxes below. This document is a plan; unchecked items have not been implemented.

**Goal:** Complete the existing COMP9120 retailer prototype so customers can browse, buy, track orders and request returns, while staff can fulfil orders, process refunds and manage the existing catalogue and stock.

**Architecture:** Keep PostgreSQL as the authority for integrity, historical records and transaction safety. Extend the existing FastAPI router → service → parameterised SQL pattern, using one database transaction per operation. Complete the existing Next.js storefront and `/admin` application through the same-origin API proxy and generated OpenAPI types.

**Tech stack:** PostgreSQL 18, Python/FastAPI/Pydantic/psycopg2, Next.js 16.3.6, React 19.2.8, TypeScript, Tailwind CSS 4, openapi-fetch, pytest.

**Spec:** Recovered repository requirements in `README.md`, `web/README.md`, `web/src/lib/shop-pages.ts`, `doc/progress.md` and `sql/`. The referenced `.claude/plan.md` is absent from both checkouts. The user explicitly selected the current repository requirements as the planning source. Proposed decisions below fill implementation gaps; they are not quotations from the missing brief.

**Audit date / baseline:** 2026-09-26; workspace root `/Users/yuhang/Desktop/A1_9120`; root HEAD `5c749fc`.

## Global constraints

- Preserve the existing PostgreSQL-first approach: business rules stay in named database constraints/triggers, with `brNN_<what>` identifiers and tests that assert the constraint name.
- Preserve hand-written SQL with psycopg2; use `%s` parameters for values and `psycopg2.sql` for identifiers/composition. No ORM is needed for this scope.
- README runtime floors: **Python 3.12 or newer** and **Node.js 20.9 or newer**. Compose currently uses `postgres:18` on host port **5433**.
- Keep monetary calculations in PostgreSQL NUMERIC/Python Decimal. API amounts remain decimal strings; frontend arithmetic uses integer cents.
- Preserve the storefront at `/`, admin at `/admin`, backend prefix `/api/v1`, and the Next.js `/api/*` proxy.
- Preserve simulated payments and demo identity selection. Real payment processing and production identity verification are outside the recovered scope.
- Keep the existing seed data and existing admin features working as modules are completed.
- SQL bootstrap files run in filename order on an empty volume. Never use a development-volume reset as an automatic test step against data that needs preserving.
- Read `web/AGENTS.md` and the installed Next.js guides before implementation. Regenerate `web/src/lib/api/schema.d.ts` whenever API contracts change.
- Record implementation decisions, actual verification and GenAI use in `doc/progress.md`.

## Review focus

These five risks need explicit coverage; the owning tasks below name their tests.

1. Concurrent purchases, cancellation and stock adjustments must not oversell, lose updates or deadlock indefinitely — T09, T11, T18.
2. Retries after a timeout must not duplicate an order, return, charge, refund or restock; reusing a key for different content must fail clearly — T03, T09, T13–T14.
3. Switching customer, store or route during an in-flight request must not expose another customer's details or apply a mutation result to another store/product — T01, T05, T10.
4. Promotions ending, addresses retiring and products becoming inactive between cart review and checkout must produce an authoritative, all-or-nothing result — T04, T06, T09.
5. Return quantities, the inclusive 30-day boundary, paid cancellation and historical money must remain correct after later edits and concurrent requests — T02–T03, T11, T13–T14.

---

## 1. What is already constructed

Checked items here mean **present in source**, not freshly proven at runtime.

| Status | Area | Evidence and current capability | What remains |
|---|---|---|---|
| [x] | Database foundation | `sql/00_domains.sql`, `01_tables.sql`: 6 domains and 18 tables covering customers/addresses, stores/staff, catalogue/specs/promotions, stock/audit, orders/history, returns and payments | Harden lifecycle invariants; add retry/cancellation support |
| [x] | Database business rules | `sql/01_tables.sql`, `02_rules.sql`: mechanisms for BR01–BR18, allowed order/return status transitions and locks in aggregate checks | Existing rule tests do not establish that every UPDATE/DELETE or concurrent path is safe |
| [x] | Derived views | `sql/03_views.sql`: `v_product_current_price`, `v_order_total` | Use them in checkout, order reads and reports |
| [x] | Reference/demo seed | `sql/10_seed_reference.sql`: 12 retail stores, 1 warehouse, 42 staff, 15 categories, 16 brands, 48 products, specs, opening inventory, 9 promotions, 4 customers and addresses | No committed end-to-end order/return demo scenarios |
| [x] | Backend infrastructure | `app/db.py`, `app/errors.py`, `app/main.py`: request transaction, unified errors and database health check | Verified commit-time failure handling, session actor and permissions |
| [x] | Catalogue/reference API | Stores, staff, categories, brands, customer reads; product list/detail/create/update/spec replacement; promotion list/create/delete | Price filters, deeper category traversal, actor restrictions and missing business workflows |
| [x] | Stock API | Store inventory, relative stock adjustment plus audit row, recent adjustment list | Derive staff identity from the session; retain atomicity/concurrency coverage |
| [x] | Admin UI | `/admin` redirects to inventory; inventory adjustments/history, product creation/editing/specs, promotion creation/deletion | Auth, stale-data fixes, fulfilment and return-processing screens |
| [x] | Storefront home | `web/src/app/(shop)/page.tsx`: deals, upcoming promotions, categories, nearby retail stores | Wire completed routes into the home page and remove implementation-status copy |
| [x] | Shared web foundation | Generated client/types, money/date formatters, `useLoad`, UI components, customer/store browser preferences | Real demo session, cart state, focused web tests and UI hardening |
| [ ] | Nine customer routes | `/products`, `/products/[id]`, `/cart`, `/checkout`, `/orders`, `/orders/[id]`, `/returns`, `/stores`, `/account` all contain `ReservedPage` | Implement actual customer flows |
| [ ] | Checkout / order workflows | Tables and status rules exist | No order router, schema or service; no charge/stock checkout transaction or customer order reads |
| [ ] | Return workflows | Tables and quantity/refund rules exist | No return API, request idempotency, processing transaction or operational UI |
| [ ] | Staff/reporting slice | Named in `shop-pages.ts`; staff reference data exists | Operational fulfilment/returns are required; exact reporting and staff CRUD requirements are not recoverable |
| [x] | Existing test sources | 31 business-rule test functions, 4 stock transaction tests, 7 API tests: **42 test functions** | Auth, checkout, returns, cancellation, web tests and automated browser journeys |

### Current API inventory

There are 17 versioned API operations plus `/health`. Preserve compatible response shapes while extending them.

| Module | Existing operations |
|---|---|
| `app/routers/reference.py` | `GET /stores`, `/staff`, `/categories`, `/brands` |
| `app/routers/customers.py` | `GET /customers`, `/customers/{customer_id}` |
| `app/routers/products.py` | `GET/POST /products`; `GET/PATCH /products/{product_id}`; `PUT /products/{product_id}/specs` |
| `app/routers/inventory.py` | `GET /stores/{store_id}/inventory`; `POST /stores/{store_id}/inventory/{product_id}/adjustments`; `GET /stores/{store_id}/adjustments` |
| `app/routers/promotions.py` | `GET/POST /promotions`; `DELETE /promotions/{promotion_id}` |

### Audit and verification limits

- The source audit parsed all **23 app Python files and 6 test Python files** successfully; this is syntax checking only.
- `doc/progress.md` records an earlier **42 passed** result and clean frontend checks. Those are historical claims, not checks repeated for this plan.
- This checkout has no `.env`, `.venv` or `web/node_modules`. `pytest` and `fastapi` are unavailable in the inspected Python environment; `docker` and `psql` are not on PATH. No application tests or browser/build checks were run during this audit.
- The pytest session fixture forcibly recreates **`jbhifi_test`**. It is not a read-only test command; use an isolated test instance and explicit test database configuration during implementation.
- The nested `JBhifi/` is a separate checkout recorded as a Git gitlink at `84dbbb1`, without a tracked `.gitmodules` file. All **82 regular tracked root files** have identical nested copies. This plan targets the **root**, not `JBhifi/`; do not implement each change twice.

## 2. Requirement coverage and known gaps

| Recovered requirement | Current state | Completion tasks |
|---|---|---|
| R1 — browse/search/category/brand/price filters | API partial; customer list placeholder | T04, T07 |
| R2 — current promotional price | View/API/home exist | T04, T07–T10 |
| R3 — product stock by store | API/admin/home exist | T07–T09 |
| R4 — delivery or Click & Collect order | Schema only | T01–T03, T06, T08–T12 |
| R5 — order list and status timeline | Tables/triggers only | T09–T12 |
| R6 — request and track returns | Tables/triggers only | T02–T03, T13–T15 |
| R11 — auditable status changes | Order history trigger exists; history writable; no return history | T01–T02, T11–T15 |
| R13 — logged manual stock adjustments | Implemented API/DB/UI | T01, T05, T18 regression coverage |
| Additional reserved pages — stores and account | Placeholders; read APIs mostly exist | T06–T07 |
| Slice C — staff and reporting | Staff reads only; exact report definitions absent | T12, T15; proposed reporting extension T16 |
| R7–R10, R12; original T3+ definitions | Full wording absent | Do not invent numbered requirements; T00 records the recovered scope |

### Concrete gaps discovered in existing code

| Priority | Finding | Evidence | Owner |
|---|---|---|---|
| P0 | Browser-selected customer/staff IDs are not authenticated actors; APIs accept unauthenticated reads/mutations | `shop/context.tsx`, `app/schemas/inventory.py`, registered routers; progress log explicitly acknowledges this | T01 |
| P0 | A checkout uniqueness constraint does not implement safe replay or payload conflict detection; returns have no idempotency columns at all | `customer_order`, `return_request`; `shop-pages.ts` promises both retryable POSTs | T03, T09, T13 |
| P0 | Paid/ready cancellation is allowed, but all refunds require a return, and returns require completed orders | Order transition seed + BR11 + `br14_refund_has_return` | T03, T11 |
| P0 | Historical order line quantity/product and order ownership/fulfilment fields can change; only unit price is protected | BR08 trigger and table definitions | T02 |
| P0 | Charge UPDATE/DELETE can invalidate the refund ceiling; order history UPDATE/DELETE is not blocked | BR14 only checks `NEW.kind = 'refund'`; no history immutability guard | T02 |
| P0 | BR12 does not run on a return-line `return_id`-only update; moving a rejected line to a live request can evade the aggregate check | Trigger `UPDATE OF quantity, order_id, line_no`; `return_id` omitted | T02 |
| P1 | BR11 trusts a supplied `requested_at` and only checks its upper bound | `br11_check_return_window` | T02, T13 |
| P1 | Store/route changes can leave stale records actionable; late mutation responses use unguarded `setData` | `use-load.ts`, admin inventory and product detail | T05 |
| P1 | Customer detail failures are omitted from shared error/retry handling | `ShopProvider` exposes only list errors and retries | T01, T05 |
| P1 | Category filtering and rendering assume two levels despite a recursive data model | `app/services/filters.py`, `category-select.tsx`, home category rendering | T04, T07 |
| P1 | Modal accessibility and product-spec input labels need completion | `web/src/components/ui.tsx`, admin product detail | T05 |
| P1 | Browser verification is described in the progress log, but scripts are not committed; no web test command exists | `web/package.json`, progress log | T05, T18 |

## 3. Proposed implementation decisions

These defaults make the recovered scope implementable. Record them in `doc/requirements.md` in T00; revise if the team later supplies a conflicting brief.

1. **Identity and permissions:** a signed, HTTP-only demo session carries either a customer or staff identity. Guest browsing remains available. Customers access their own account/orders/returns. Store staff adjust stock and fulfil orders for their own store, and receive returns at their own retail store. Managers and support staff maintain catalogue/promotions; support can read across stores. Identity pickers remain explicitly labelled as a demo, with the login endpoints disabled when demo mode is off.
2. **One order, one fulfilment store:** preserve `customer_order.fulfilling_store_id`; do not introduce split shipments. Click & Collect offers retail stores only. Delivery offers a single fulfilment location, defaulting to the warehouse, while allowing another store with sufficient stock. The database currently permits either store type for delivery.
3. **Prices and payment:** prices are calculated from `v_product_current_price` inside checkout, not accepted from the cart. The submitted expected total is a comparison value only; a changed total returns `409 price_changed` before any writes commit. Simulate charge/refund records; add no card fields. Product totals include no newly invented shipping fee/tax calculation.
4. **Zero-value purchases:** because `money_aud` permits zero but `payment.amount` must be positive, allow zero-total orders and zero-value returns with no zero-valued payment row. Order/return status and stock still advance correctly.
5. **Idempotency:** `Idempotency-Key` is a UUID. Orders scope it to customer; return requests scope it to order. A normalised request fingerprint distinguishes a replay from changed content. A replay returns the same resource, without repeating side effects. Staff receive/process/cancel operations are also safe to retry through locked status checks and unique source records.
6. **Cancellation:** preserve existing legal cancellation transitions. Add a separate cancellation record and a cancellation refund reference on `payment`; do not fabricate a merchandise return for an uncompleted order. Restock and refund once in the cancellation transaction. Initially expose cancellation to authorised staff; customer cancellation is not promised by the recovered pages.
7. **Returns:** request against completed orders within the inclusive 30-day window; rejected requests release reserved return quantities. Receiving records location/staff but does not restock yet. Processing a received return atomically restocks accepted quantities, records the refund and marks it refunded. Rejected/refunded states remain final. Returned items are assumed resaleable in this prototype; damaged-item disposition is outside current scope.
8. **Audit and history:** append-only order and return status trails, immutable committed financial records and purchased line snapshots. Set actor context with transaction-local `set_config`, using the verified session, never an arbitrary submitted staff ID.
9. **Cart and navigation:** persist a browser cart of product IDs/quantities only; it reserves no stock. Keep it across demo customer changes but clear identity-specific data and any pending checkout key. Preserve `q` and `category` URLs already emitted by the home/header.
10. **Reporting/assessment:** complete operational order/return screens first. T16 provides a small proposed reporting set because the repository names that slice; no report count, grading weight or missing requirement is assumed. Real deployment, support agents/tickets, an ORM, product images, external search and real payment gateways are future scope.

## 4. Delivery order and ownership

Priorities: **P0** = required before transaction flows; **P1** = required to complete the recovered user experience; **P2** = proposed/reporting and delivery improvements.

| Milestone | Tasks | Independently reviewable outcome |
|---|---|---|
| M0 — reliable foundation | T00–T03, T05 | Repeatable setup, session actor, corrected lifecycle schema, safe shared UI |
| M1 — customer browsing | T04, T06–T08 | Real catalogue/product/stores/account/cart pages |
| M2 — purchase to fulfilment | T09–T12 | Delivery and collection orders, timelines, staff progression and cancellation |
| M3 — returns to refund | T13–T15 | Customer requests/tracking and staff receipt/refund |
| M4 — delivery evidence | T16–T18 | Agreed reports, demonstration data, documentation and repeatable verification |

Parallel work: catalogue T04 and shared web T05 can proceed while database T02–T03 is completed. After T01, the account T06 slice can run alongside catalogue UI. After contract/schema tasks, an API implementer and a UI implementer can work independently using generated types/fixtures. Coordinate edits to `app/main.py`, `sql/02_rules.sql`, shared contexts and generated API types; avoid concurrent edits to these shared files.

## 5. Detailed implementation checklist

For each behavioral task: add the named regression tests first, run the focused command and observe the relevant failure, implement the smallest change, then rerun for passing assertions. Review and commit each completed task separately. Setup/documentation tasks use inspection instead of artificial unit tests. Paths below are relative to the workspace root.

### T00 — Establish the canonical project and runnable baseline [P0]

**Depends on:** none. **Owner:** integration.

**Files:** create `doc/requirements.md`; update `README.md`, `doc/progress.md`, `.env.example`, `requirements.txt` and `tests/support.py` only as required for repeatable setup.

**Produces:** one documented source tree, recovered requirements/decisions, runtime instructions and an isolated test configuration used by later tasks.

- [ ] Document root `/Users/yuhang/Desktop/A1_9120` as the working tree; flag the duplicate gitlink and record the team's eventual keep/remove decision. Do not delete the nested checkout as an incidental cleanup.
- [ ] Write `doc/requirements.md` from sections 2–3, preserving known R#/BR# IDs and explicitly identifying missing original wording.
- [ ] Create a local `.env` from `.env.example`; provision the documented Python/Node dependencies and PostgreSQL runtime. Use `npm ci` with the existing tracked lockfile.
- [ ] Add a clearly separate test connection configuration and assert the target database is `jbhifi_test` before any fixture drops/rebuilds it. Keep fixture resets away from the normal demo database.
- [ ] Run `pytest`, then in `web/` run `npm run typecheck`, `npm run lint`, `npm run build`. Record actual counts/failures and tool versions. Fix environment problems before treating results as application failures.
- [ ] Keep Python requirements hand-maintained and cross-platform; record tested version constraints rather than dumping `pip freeze` output.
- [ ] Record baseline results and commit the setup/documentation changes.

**Acceptance:** a fresh clone can follow README instructions; the initial 42 test functions are collected and results are recorded; demo data survives a test run. Root and nested source files are not both being modified.

### T01 — Add demo sessions and enforce actor permissions [P0]

**Depends on:** T00. **Owner:** backend + shared web.

**Files:** create `app/auth.py`, `app/schemas/auth.py`, `app/routers/auth.py`, `tests/test_auth.py`, `web/src/components/session-provider.tsx`; modify `app/main.py`, existing routers, `app/schemas/inventory.py`, `app/errors.py`, `.env.example`, `requirements.txt`, shop context/header, admin layout/sidebar and generated API types.

**Interfaces:** `Actor(kind: Literal['customer','staff'], actor_id: int, store_id: int | None, is_manager: bool, staff_type: str | None)`; `get_current_actor(request, cur) -> Actor` rejects an absent/invalid session; an optional-actor variant serves public reads. `GET /api/v1/auth/session -> {actor: Actor | null}`; `POST /api/v1/auth/demo-login` accepts `{kind, actor_id}`; `POST /api/v1/auth/logout` clears the cookie.

- [ ] Add `test_guest_cannot_mutate`, `test_customer_cannot_read_another_customer`, `test_staff_store_scope`, `test_forged_actor_is_ignored`, and `test_demo_login_disabled`: assert 401/403/404 as applicable and no changed database rows.
- [ ] Validate selected demo identities against the database; sign the cookie using an environment secret; use HttpOnly and SameSite, secure cookies for HTTPS, and same-origin checks for cookie-authenticated mutations. Never put a trusted actor in localStorage.
- [ ] Apply the section 3 role matrix to all existing and new APIs; keep public product/category/brand/store/stock reads. Expose only minimal demo identity choices when demo mode is enabled; restrict customer address details, staff operational data and audit logs.
- [ ] Derive `staff_id` for stock changes from the actor; remove it from `AdjustmentCreate` and the admin mutation payload. Keep BR18 database tests that directly exercise invalid store/staff pairs.
- [ ] Set `app.staff_id` transaction-locally for staff status changes. Add documented 401/403 responses to the existing error envelope; return safe client messages without raw row details containing personal data.
- [ ] Replace customer localStorage identity with session state. Add the staff demo selector, clear identity-specific state on logout/switch, preserve the independent store preference and surface/retry customer detail failures.
- [ ] Run `pytest tests/test_auth.py tests/test_api.py tests/test_transactions.py -q`; verify cookie persistence/expiry, tamper rejection, logout and existing authorised admin actions. Regenerate API types and run frontend checks.
- [ ] Review and commit this task.

**Acceptance:** changing a request body, URL customer ID or browser storage cannot authorise a different actor. The picker is functional demo identity selection, not a claim of production account verification.

### T02 — Close database lifecycle and audit bypasses [P0]

**Depends on:** T00. **Owner:** database.

**Files:** modify `sql/01_tables.sql`, `sql/02_rules.sql`, `tests/test_business_rules.py`, `tests/support.py`, `.env.example`, `README.md`; create `sql/05_permissions.sql`, `tests/test_lifecycle_rules.py`, `tests/test_rule_concurrency.py`.

**Produces:** immutable purchase history and financial records, comprehensive BR12 guards, authoritative return request time and append-only order history. Existing constraint names stay stable unless T03 explicitly extends their meaning.

- [ ] Add failing `test_charge_cannot_be_reduced_or_deleted_after_refund`, `test_order_history_cannot_be_edited`, `test_purchased_line_cannot_change`, and `test_return_line_cannot_move_between_requests`; assert named integrity errors and unchanged historical totals.
- [ ] Freeze order customer/fulfilment/address/idempotency/placement metadata after creation. Allow line assembly only while `placed`; block line insert/update/delete once the purchase is committed, including quantity/product/order/key changes. Preserve BR08's unit-price guard.
- [ ] Make payment rows append-only and order history updates/deletes invalid. Add an application database role with the required table/sequence access but no schema-owner rights or direct history writes; retain a separate bootstrap/test-owner connection. Give only the history-writing trigger function the narrow authority needed to insert audit rows, with a fixed safe search path. Test permissions using the application role as well as testing trigger guards through the owner connection.
- [ ] Make return-line ownership immutable, including `return_id`, `order_id` and `line_no`. Enforce BR12 for every supported quantity path and reject edits once receipt/processing starts.
- [ ] Use server-generated immutable `requested_at` for return requests. Extract `return_request_is_in_window(completed_at, requested_at) -> boolean` in SQL for exact boundary tests; the trigger supplies authoritative timestamps and rejects pre-completion requests. Cover exactly 30 days versus 30 days plus one microsecond.
- [ ] Add concurrent tests for excessive return quantities, excessive refunds and overlapping promotions using separate connections and bounded barriers/timeouts. Expected result: exactly the valid subset commits, with the constraint name identified for refusals.
- [ ] Check category cycle integrity before adding arbitrary-depth traversal in T04; reject a parent change that introduces a cycle and test a three-level cycle.
- [ ] Run `pytest tests/test_business_rules.py tests/test_lifecycle_rules.py tests/test_rule_concurrency.py -q` on a rebuilt isolated database. Adapt fixtures to build valid histories through supported transitions; keep any historical fixture loading in test-only setup, not a production bypass flag.
- [ ] Review and commit this task.

**Acceptance:** changing or deleting supporting rows cannot invalidate an already accepted refund, purchased quantity or audit timeline; all current BR tests retain meaningful coverage after fixture updates.

### T03 — Add retry, cancellation and return-audit schema [P0]

**Depends on:** T02. **Owner:** database.

**Files:** modify `sql/01_tables.sql`, `sql/02_rules.sql`, `sql/05_permissions.sql`, `app/errors.py`, `tests/test_business_rules.py`; create `tests/test_lifecycle_schema.py`.

**Produces:** `customer_order.request_fingerprint`; `return_request.idempotency_key` and `request_fingerprint`; unique `(order_id, idempotency_key)`; `order_cancellation`; optional `payment.cancellation_id`; `return_status_history` with trigger-written actor/time/transition records.

- [ ] Add `test_return_request_key_is_unique_per_order`, `test_refund_requires_exactly_one_source`, `test_cancellation_refund_matches_order`, `test_refund_once_per_cancellation`, and `test_return_status_history_is_append_only`.
- [ ] Add non-null fingerprints to new checkout/return requests. Preserve `br10_order_idempotency_unique`; add `return_idempotency_unique`. Update all fixture inserts to supply fingerprints/keys.
- [ ] Create `order_cancellation(cancellation_id, order_id UNIQUE, reason, cancelled_by_staff_id, created_at)` with a composite unique key `(cancellation_id, order_id)` for payment ownership checks.
- [ ] Add nullable `payment.cancellation_id`, its composite FK to the cancellation/order and a unique constraint for one refund per cancellation. A charge has neither refund source; a refund has exactly one of `return_id`/`cancellation_id`.
- [ ] Replace `br14_refund_has_return` with the documented extension `br14_refund_has_source`; update tests/error references deliberately. Preserve BR14's aggregate refund ceiling and once-per-return constraint.
- [ ] Add append-only `return_status_history(return_id, seq, from_status, to_status, changed_at, changed_by_staff_id)` and log creation, receipt, rejection and refund. Match the existing order-history convention for customer/system actor attribution.
- [ ] On refund insertion, require a received return and an amount equal to its original-price returned lines, or a recorded legal cancellation and its captured balance. Add deferred completion checks so, at commit, a positive-value refunded return has its matching payment, a zero-value refunded return has none, and a cancellation record belongs to a cancelled order with the correct refund. The service may insert a payment then change status within the transaction; partially completed financial states must not commit. Test both valid operation order and incomplete commit failure.
- [ ] Extend the application-role grants for cancellation/return operations and give the return-history trigger the same protected write path as order history. Verify terminal-state retries do not append extra history.
- [ ] Run `pytest tests/test_business_rules.py tests/test_lifecycle_rules.py tests/test_lifecycle_schema.py -q`; rebuild the isolated database from filenames in order to validate bootstrap dependencies.
- [ ] Review and commit this task.

**Acceptance:** cancellation refunds are expressible without violating BR11, return requests have database-backed retry uniqueness, and both lifecycle types have protected audit trails.

### T04 — Complete catalogue filtering and store-aware results [P1]

**Depends on:** T00; category cycle guard from T02 for arbitrary-depth data. **Owner:** catalogue.

**Files:** modify `app/routers/products.py`, `app/schemas/products.py`, `app/services/products.py`, `app/services/filters.py`, `app/services/reference.py`; create `tests/test_catalogue.py`; regenerate API types.

**Interfaces:** extend `list_products(cur, q=None, category_id=None, brand_id=None, include_inactive=False, min_price: Decimal | None=None, max_price: Decimal | None=None, store_id: int | None=None) -> list[ProductSummary]`; add nullable `store_quantity` when no store is requested. Keep the existing list response and existing `total_stock` semantics.

- [ ] Add `test_price_filter_uses_sale_price` (`base=100`, `sale=80`, range `75..85` includes the product), `test_category_includes_grandchildren`, `test_missing_inventory_is_zero`, and `test_filters_treat_wildcards_as_text`.
- [ ] Filter inclusively on `cp.current_price`; reject negative/malformed bounds and `min_price > max_price` with 422. Preserve parameterised search and the existing default exclusion of inactive products.
- [ ] Replace direct-child category logic with cycle-safe recursive descendants shared by catalogue/inventory queries; preserve brand and text filters when combined.
- [ ] Add optional selected-store quantity via a left join; return 404 for an unknown requested store and zero for a product without an inventory row there. Avoid a per-product HTTP inventory request.
- [ ] Keep product detail's existing specs, store stock and promotions; allow retired detail to render unavailable while checkout rejects purchase. Verify promotion activity uses `[starts_at, ends_at)` and test the end boundary.
- [ ] Run `pytest tests/test_catalogue.py tests/test_api.py -q`; regenerate types and verify existing admin callers still compile.
- [ ] Review and commit this task.

**Acceptance:** customer filters satisfy R1–R3 using the authoritative current price and arbitrary category depth, while existing admin list contracts remain usable.

### T05 — Make shared UI state safe and add focused web tests [P0/P1]

**Depends on:** T00. **Owner:** shared web.

**Files:** modify `web/src/lib/use-load.ts`, `web/src/components/ui.tsx`, shop context, admin inventory/product detail, `web/package.json` and lockfile; create `web/vitest.config.ts`, `web/src/test/setup.ts`, `web/src/lib/use-load.test.tsx`, `web/src/components/ui.test.tsx`, `web/src/app/admin/inventory/inventory.test.tsx`.

**Interfaces:** retain `useLoad(key, load)` but expose `isCurrent`; `setData(expectedKey, update)` applies an update only to that resource key. Same-key refresh can retain display data; changed-key data cannot authorise mutations.

- [ ] Add a web test runner with React Testing Library; define `npm run test:unit` as a non-watch run. Mock deferred network responses, not the race being tested.
- [ ] Add `late_store_a_response_cannot_change_store_b`: start adjustment at A, switch/load B, resolve A, assert B's rows/history remain unchanged. Add the equivalent product route-change test.
- [ ] Guard both request freshness and mutation targets. Disable stock/edit actions for stale/loading records; close or invalidate an adjust dialog when its store/product changes. Do not rely only on a spinner.
- [ ] Reapply the low-stock filter after adjustments, disable duplicate promotion deletion while pending, and show retryable failures for required brands/categories/staff/store data instead of leaving empty selectors actionable.
- [ ] Surface customer-detail failures and make Retry repeat the failed detail request; assert a failure cannot silently display the prior customer's record.
- [ ] Give modals an accessible name, initial focus, contained Tab navigation, Escape close and focus restoration. Prevent background interaction while open and label spec inputs explicitly.
- [ ] Add tests for out-of-order loads, same-key reloads, rejected requests, dialog keyboard use and named controls; preserve useful loading/empty/error states.
- [ ] Run `npm run test:unit`, `npm run typecheck`, `npm run lint` from `web/`.
- [ ] Review and commit this task.

**Acceptance:** stale data is never actionable under a different resource identity, late writes cannot corrupt the current screen, and shared dialogs work with a keyboard.

### T06 — Complete account and immutable-address management [P1]

**Depends on:** T01, T02, T05. **Owner:** customer account.

**Files:** modify customer router/service/schema, `web/src/app/(shop)/account/page.tsx`, shop context and generated API types; create `tests/test_addresses.py`, `web/src/components/shop/address-form.tsx`.

**Interfaces:** `AddressCreate(line1, suburb, state, postcode)`; `AddressRetire(is_active: Literal[False])`, both reject extra fields. `add_address(cur, customer_id: int, body: AddressCreate) -> Address`; `retire_address(cur, customer_id: int, address_no: int) -> Address`. Expose the POST/PATCH customer address paths already listed in `shop-pages.ts`.

- [ ] Add `test_add_address_allocates_next_number`, `test_concurrent_address_adds_are_distinct`, `test_retire_is_idempotent`, `test_address_text_cannot_be_patched`, and `test_customer_cannot_change_another_address`.
- [ ] Lock the customer row before allocating `max(address_no)+1`; insert the new address in the same transaction. Require nonblank address text and let the existing state/postcode domains enforce their values.
- [ ] Retire only through `is_active=false`; no text editing, deleting or reactivation API. Return 404 for unknown addresses and the unchanged retired address on repeat retirement.
- [ ] Replace the account placeholder with customer details, active/past address lists and an add form. Provide a replace flow that adds a new address then lets the customer retire the old one; explain any partial outcome if these are separate requests.
- [ ] Refresh session-owned customer detail after successful changes, including the context used by checkout and store defaults. Retain entered values after a rejected request.
- [ ] Run `pytest tests/test_addresses.py -q` and frontend checks. Verify an order referencing address 1 still shows address 1 after address 2 is added and address 1 retired.
- [ ] Review and commit this task.

**Acceptance:** a signed-in customer can prepare delivery addresses without rewriting the addresses held by old orders.

### T07 — Replace catalogue, product and store placeholders [P1]

**Depends on:** T04, T05; add-to-cart interaction finishes with T08. **Owner:** storefront catalogue.

**Files:** modify `web/src/app/(shop)/products/page.tsx`, `products/[id]/page.tsx`, `stores/page.tsx`, home page and `web/src/components/category-select.tsx`; create `web/src/components/shop/product-card.tsx`, `web/src/components/shop/store-stock.tsx`, `web/src/lib/categories.ts`, `web/src/lib/categories.test.ts`.

**Interfaces:** `descendantIds(categories: Category[], rootId: number): number[]` and `categoryOptions(categories: Category[], leavesOnly: boolean): {id: number; label: string; depth: number}[]`. Use T04's typed product/store quantities; preserve URL keys `q`, `category`, adding `brand`, `min_price`, `max_price`.

- [ ] Add category tests: root leaves remain selectable; a three-level tree includes grandchildren; malformed cycles terminate safely without duplicate options.
- [ ] Implement URL-backed catalogue search and combined filters, reset, count, loading, empty and error/retry states. Map public `category` to API `category_id`; back/forward navigation must restore filters.
- [ ] Render current/base prices, sale state and selected-store stock. Use a single store-aware list request; distinguish unknown/loading stock from a confirmed zero.
- [ ] Implement product detail using promised route params as required by the installed Next.js version; validate the ID and render not-found/error states, specs, selected-store-first stock and inactive-product unavailability.
- [ ] Implement stores grouped by state with product stock lookup and preferred-store selection. Label warehouse stock when shown; exclude warehouse from the retail preference/collection selector.
- [ ] Share recursive category handling with the existing home page and admin selectors, including counts. Surface failures in home stock/upcoming-promotion loads instead of substituting misleading empty results.
- [ ] Run `npm run test:unit`, `npm run typecheck`, `npm run lint`; manually follow existing header search and home category links into real results until T18's browser suite is available.
- [ ] Review and commit this task.

**Acceptance:** R1–R3 are usable from the customer interface; there are no `ReservedPage` components in these three routes.

### T08 — Implement a persistent, price-aware cart [P1]

**Depends on:** T05, T07. **Owner:** storefront cart.

**Files:** create `web/src/lib/cart.ts`, `web/src/lib/cart.test.ts`, `web/src/components/shop/cart-context.tsx`; modify shop layout/header, product detail and `web/src/app/(shop)/cart/page.tsx`.

**Interfaces:** `CartItem = {product_id: number; quantity: number}`; `CartState = {version: 1; items: CartItem[]}`; `readCart(raw: string | null): CartState`; `addItem(items, product_id, quantity): CartItem[]`; `setQuantity(items, product_id, quantity): CartItem[]`; `toCents(decimal: string): number`; provider exposes `items`, `addItem`, `setQuantity`, `removeItem`, `removeSubmittedItems`.

- [ ] Add `cart_merges_duplicate_products`, `cart_rejects_invalid_quantities`, `cart_recovers_from_corrupt_storage`, `cart_works_when_storage_is_blocked`, and `cart_totals_use_cents`. Pin `toCents('19.95') * 3 === 5985` and `toCents('0.10') + toCents('0.20') === 30`.
- [ ] Store only validated positive integer IDs/quantities in versioned browser storage; keep an in-memory fallback and hydration-safe initial state. Preserve the section 3 customer-switch cart policy.
- [ ] Wire add-to-cart and header count; adding an existing product merges quantities. Provide remove, quantity update, empty state and continue-shopping links.
- [ ] Refresh catalogue prices and selected-store stock for cart items; display retired/missing products and shortages without silently deleting items. Do not reserve inventory or treat the displayed stock as a guarantee.
- [ ] Display exact line/subtotal values; disable checkout for an empty/invalid/unresolved cart. Let customers resolve unavailable items and refresh after a price change.
- [ ] Run `npm run test:unit`, `npm run typecheck`, `npm run lint`; verify reload and customer/store switching preserve the intended cart and refresh data.
- [ ] Review and commit this task.

**Acceptance:** a guest or customer can build and review a cart; the browser never supplies authoritative unit prices or creates database orders merely by editing the cart.

### T09 — Implement atomic checkout and protected order reads [P0]

**Depends on:** T01–T04, T06. **Owner:** orders backend.

**Files:** create `app/schemas/orders.py`, `app/services/orders.py`, `app/services/payments.py`, `app/services/idempotency.py`, `app/routers/orders.py`, `tests/test_checkout.py`, `tests/test_checkout_transactions.py`, `tests/test_order_reads.py`; modify `app/main.py`, customer router, error mappings and generated API types.

**Interfaces:**

- `OrderItemIn(product_id: int, quantity: int)`; `OrderCreate(fulfilment_method, fulfilling_store_id: int, delivery_address_no: int | None, items: list[OrderItemIn], expected_total: Decimal)`; nonempty items and no extra fields.
- `fingerprint_request(normalised_payload: dict) -> str`: canonical JSON/SHA-256 of validated input. The order caller sorts items by product ID and formats Decimal fields as two-decimal strings; the return caller sorts lines by line number. Preserve the expected total in order input. Reject duplicate rows rather than ambiguously combining them.
- `record_charge(cur, order_id: int, amount: Decimal) -> int | None`; `record_refund(cur, order_id: int, amount: Decimal, *, return_id: int | None=None, cancellation_id: int | None=None) -> int | None`. These shared payment helpers return a payment ID, or None for zero value, and never commit independently.
- `checkout(cur, actor: Actor, key: UUID, body: OrderCreate) -> tuple[OrderDetail, bool]`, where the boolean means a replay; `get_order(cur, actor: Actor, order_id: int) -> OrderDetail`; `list_customer_orders(cur, actor: Actor, customer_id: int) -> list[OrderSummary]`.
- `OrderSummary`: `order_id`, `placed_at`, `status`, `fulfilment_method`, `fulfilling_store_id`, `total`. `OrderDetail` adds purchased `lines`, `delivery_address`, `payments`, `history` and actor-specific `allowed_actions`.
- `POST /api/v1/orders` returns 201 for creation, 200 for replay; `GET /api/v1/orders/{order_id}` and `GET /api/v1/customers/{customer_id}/orders` return only authorised resources.

- [ ] Add checkout tests for delivery, retail collection, active owned address, empty/duplicate/nonpositive lines, inactive products, zero total and server price snapshots. A client-supplied unit price or customer ID must be rejected as an extra field.
- [ ] Resolve idempotency before validating mutable current state: an already committed identical request must replay even if prices/stock/address activity have subsequently changed. Reused key with another fingerprint returns `409 idempotency_conflict`.
- [ ] Lock the customer before inserting an order, then recheck the key under that lock. This prevents two same-customer transactions from deadlocking while upgrading the foreign-key locks acquired by order insertion. For a genuinely new request, validate it before claiming its key with `INSERT ... ON CONFLICT DO NOTHING RETURNING ...` and a safe fallback replay lookup. Do not continue an aborted transaction after a uniqueness exception.
- [ ] For a new request, lock/validate the customer and address, then products in ascending ID order; read all current prices at one documented transaction timestamp. Reject retired products and inactive/foreign addresses. Coordinate address/product retirement locks with the corresponding write services.
- [ ] Compare computed Decimal total with `expected_total`; return `409 price_changed` with the refreshed review data if different. No part of the checkout may commit on this path.
- [ ] Insert the placed order and lines at the server prices; decrement inventory with `quantity = quantity - requested WHERE quantity >= requested`, in ascending `(store_id, product_id)` order. Missing/insufficient rows raise `409 out_of_stock` with product/store/available/requested detail.
- [ ] Record the simulated charge only when total is positive; then update status to `paid`, allowing the existing trigger to generate history. Keep order, lines, stock, payment and both history events in the same transaction.
- [ ] Implement lists ordered by `placed_at DESC, order_id DESC`; read totals from `v_order_total`. Detail must retain sold prices, retained delivery address, chronological history and payment totals. Return a uniform 404 for a nonexistent or another customer's order.
- [ ] Add `test_second_line_failure_rolls_back_everything`, `test_last_unit_has_one_buyer`, `test_concurrent_same_key_creates_one_order`, `test_replay_after_price_change`, `test_changed_payload_key_conflicts`, `test_concurrent_overlapping_baskets_do_not_hang` and `test_checkout_races_with_retirement`.
- [ ] Pin transaction assertions: two buyers of one unit yield `successes == 1` and `stock == 0`; duplicate successful request yields `orders == 1`, `charges == 1` and one stock deduction; a later-line failure yields no new order/payment/history and unchanged stock for every line.
- [ ] Run `pytest tests/test_checkout.py tests/test_checkout_transactions.py tests/test_order_reads.py -q`; regenerate API types and run frontend typecheck.
- [ ] Review and commit this task.

**Acceptance:** checkout T1 is a real all-or-nothing transaction, safely replayable under concurrency, and the customer can retrieve the resulting immutable purchase.

### T10 — Complete checkout, order list and timeline UI [P1]

**Depends on:** T06, T08, T09. **Owner:** storefront orders.

**Files:** modify `web/src/app/(shop)/checkout/page.tsx`, `orders/page.tsx`, `orders/[id]/page.tsx`, home page and API aliases; create `web/src/lib/checkout-attempt.ts`, `web/src/lib/checkout-attempt.test.ts`, `web/src/components/shop/order-timeline.tsx`.

**Interfaces:** `CheckoutAttempt = {customer_id: number; key: string; fingerprint: string; body: OrderCreate}`; `getOrCreateAttempt(customerId, body): CheckoutAttempt`; `clearAttempt(): void`. Persist the exact unresolved attempt in session storage, using T09's normalisation convention; send its UUID as `Idempotency-Key`.

- [ ] Add `same_attempt_reuses_key`, `changed_payload_uses_new_key`, `unknown_outcome_preserves_body_and_key`, and `customer_switch_discards_pending_attempt` tests.
- [ ] Require a current customer session and reviewed cart. Provide delivery-address/location or retail collection selection, stock/pricing review, simulated-payment label and exact total; link to account when no active address exists.
- [ ] Generate one key per reviewed attempt. On an uncertain network outcome, retain and replay the exact submitted body/key to resolve it before allowing a replacement attempt; changing a known-failed attempt creates a new key.
- [ ] Disable duplicate submissions while pending; render `price_changed`, `out_of_stock`, session expiry and malformed-request errors with useful recovery. Keep the cart after failure or unknown outcome.
- [ ] On confirmed success, remove only submitted quantities so items added while the request ran survive; clear the attempt and navigate to the returned order ID.
- [ ] Implement newest-first order list, ready-to-collect emphasis and detail with purchased lines, total, fulfilment/address, payments and timestamp/actor timeline. Clear private data immediately on session changes.
- [ ] Replace the home order placeholder with recent orders; distinguish guest, empty, loading and retryable error states. Return-related actions can remain absent until T13, without displaying an unfinished feature panel.
- [ ] Run web unit/type/lint checks; exercise both fulfilment modes, a timeout replay and a customer switch. T18 automates these journeys.
- [ ] Review and commit this task.

**Acceptance:** all successful purchases lead to a real order and traceable timeline; repeated clicks or timeout recovery do not duplicate purchases.

### T11 — Implement staff fulfilment and atomic cancellation [P0]

**Depends on:** T01–T03, T09. **Owner:** orders backend.

**Files:** extend order schemas/router/service and `app/services/payments.py`; create `app/services/cancellations.py`, `tests/test_fulfilment.py`, `tests/test_cancellation_transactions.py`; update generated API types.

**Interfaces:** `StatusChange(to_status: str, expected_status: str)`; `transition_order(cur, actor, order_id, body) -> OrderDetail`; `CancellationCreate(expected_status: str, reason: str)`; `cancel_order(cur, actor, order_id, body) -> OrderDetail`. Expose `GET /api/v1/stores/{store_id}/orders?status=`, `PATCH /api/v1/orders/{order_id}/status`, and `POST /api/v1/orders/{order_id}/cancel`.

- [ ] Add tests for delivery `paid → picking → shipped → delivered` and collection `paid → picking → ready → collected`; assert exactly one history entry per transition with the authenticated staff ID.
- [ ] Lock the order before status checks, verify the actor's store and `expected_status`, and use the existing transition table as the authority. Return `409 stale_status` for a conflicting update and the existing BR09 code for an illegal transition.
- [ ] Keep cancellation out of the generic status route. Route it through the dedicated transaction so a status update cannot bypass refund/restock effects. An already applied identical target status may return current detail without another history event.
- [ ] For legal cancellation, lock the order, look up/create its unique cancellation record, then lock all affected products in ascending ID order before changing inventory. Restore each purchased quantity to the original fulfilling store with relative updates, refund the positive captured balance against that cancellation, and set `cancelled` in one transaction.
- [ ] Define allocation evidence explicitly: all purchases created by T09 deduct stock and commit as `paid`; unpaid `placed` rows created for fixtures have no allocation and must not gain stock when cancelled. If future persisted prepayment reservations are added, add an explicit allocation record before changing this policy.
- [ ] Replays of an existing cancellation return the current cancelled order without another restock/refund. Reject incompatible repeated cancellation details and terminal delivered/collected/shipped cancellation with a structured conflict.
- [ ] Add `test_paid_cancellation_restores_and_refunds_once`, `test_unpaid_cancellation_does_not_invent_stock`, `test_ready_collection_can_cancel`, `test_invalid_cancel_rolls_back`, `test_concurrent_cancel_and_fulfilment_has_one_winner`, and `test_refund_failure_rolls_back_cancellation`.
- [ ] Pin financial assertions: a charged `39.90` cancellation records one `39.90` refund; a repeated cancellation leaves payment count, inventory and history unchanged; forced failure leaves the original status, stock and captured balance intact.
- [ ] Run `pytest tests/test_fulfilment.py tests/test_cancellation_transactions.py tests/test_checkout_transactions.py -q`; regenerate types.
- [ ] Review and commit this task.

**Acceptance:** staff can complete both fulfilment paths or perform a valid cancellation with consistent stock, money and history. No generic API permits a financially incomplete cancellation.

### T12 — Add staff order queues and fulfilment screens [P1]

**Depends on:** T05, T10, T11. **Owner:** admin orders.

**Files:** create `web/src/app/admin/orders/page.tsx`, `web/src/app/admin/orders/[id]/page.tsx`, `web/src/components/admin/order-actions.tsx`; modify sidebar and API aliases.

**Consumes:** T09 order detail and T11 queue/status/cancellation contracts, including `allowed_actions` and `expected_status`.

- [ ] Add component tests for authorised queue scope, delivery versus collection action sets, stale-status conflict recovery and repeated cancellation controls.
- [ ] Show a store-scoped queue with status filter, customer/order summary, placed time and fulfilment mode. Expose only authorised stores; support can inspect other stores without gaining store-only mutation rights.
- [ ] Show immutable line/address/payment details and full status history. Derive buttons from server `allowed_actions` rather than maintaining a second transition table in the browser.
- [ ] Submit the displayed `expected_status`, disable actions while pending and refresh detail/queue after success or stale-state conflict. Never apply a delayed response to a different order.
- [ ] Provide a cancellation review dialog showing the order, proposed refund/restock consequence and required reason. Call the cancellation endpoint; do not PATCH status to cancelled.
- [ ] Run web unit/type/lint checks; use the UI to progress one delivery and one collection order to completion, then verify the customer's timeline.
- [ ] Review and commit this task.

**Acceptance:** a purchase can move from `paid` to `delivered`/`collected` entirely through the authorised interface, and supported cancellations explain and apply their effects once.

### T13 — Implement customer return requests, eligibility and tracking [P0/P1]

**Depends on:** T01–T03, T09–T10. **Owner:** returns backend + customer UI.

**Files:** create `app/schemas/returns.py`, `app/services/returns.py`, `app/routers/returns.py`, `tests/test_return_requests.py`, `tests/test_return_request_transactions.py`, `web/src/components/shop/return-request-form.tsx`; modify `app/main.py`, order detail schema/service, customer routes, customer order detail/returns/home pages and generated API types.

**Interfaces:**

- `ReturnLineIn(line_no: int, quantity: int)`; `ReturnCreate(reason: str, lines: list[ReturnLineIn])`, nonempty/unique/positive lines and no supplied customer/order/time/refund fields.
- `request_return(cur, actor, order_id: int, key: UUID, body: ReturnCreate) -> tuple[ReturnDetail, bool]`; `list_customer_returns(cur, actor, customer_id: int) -> list[ReturnSummary]`; `get_return(cur, actor, return_id: int) -> ReturnDetail`.
- `ReturnSummary`: `return_id`, `order_id`, `status`, `requested_at`, `reason`, `refund_amount` (null until refunded, then a decimal string). Detail adds lines, receiving store, status history, allowed actions and `refund_preview` (a decimal string computed from returned quantities and purchase-time prices).
- `POST /api/v1/orders/{order_id}/returns` (201/new, 200/replay); `GET /api/v1/customers/{customer_id}/returns`; `GET /api/v1/returns/{return_id}`.
- Add `return_eligibility` to order detail: `eligible`, `deadline`, `reason`, and per-line `remaining_quantity`. SQL remains authoritative when a request is submitted.

- [ ] Add `test_only_owner_can_request_return`, `test_returns_require_completed_order`, `test_cumulative_quantities_are_bounded`, `test_rejected_quantities_are_released`, `test_request_cannot_supply_time`, and missing/duplicate/nonpositive line tests.
- [ ] Implement eligibility using completion history and non-rejected return quantities. Use original line numbers/prices; compute the 30-day deadline on the server and return it to the UI.
- [ ] Before mutable eligibility checks, resolve an existing request key/fingerprint so a successful old request can replay after the window closes. Normalise lines by `line_no`; a changed payload with the same key returns `409 idempotency_conflict`.
- [ ] Lock the order and purchased lines in stable order; create the request and all lines in one transaction. Let BR11–BR13 reject invalid requests; a rejected later line must roll back the parent and earlier lines.
- [ ] Implement owner-scoped return list/detail ordered by `requested_at DESC, return_id DESC`. Keep rejected requests visible and distinguish a missing refund from a zero-value completed refund.
- [ ] Add the return form to order detail using backend eligibility, quantities remaining and a required reason. Retain the exact request/key through uncertain retries, reject duplicate submits and refresh order eligibility after confirmation.
- [ ] Replace `/returns` with actual status/line/refund/history data and replace the home return placeholder with recent/active returns. Do not hide rejected returns from the full list.
- [ ] Add `test_concurrent_return_requests_cannot_exceed_purchase`, `test_concurrent_same_return_key_has_one_effect`, `test_invalid_second_line_rolls_back_request`, and `test_return_replay_after_window_closes`. Pin purchased quantity 2: two simultaneous requests for 2 must total at most 2 accepted units.
- [ ] Run `pytest tests/test_return_requests.py tests/test_return_request_transactions.py -q`; regenerate types and run web unit/type/lint checks.
- [ ] Review and commit this task.

**Acceptance:** a customer can request and track legitimate returns with a reliable deadline, remaining quantities and safe retries; the browser cannot override order ownership or historical prices.

### T14 — Implement staff receipt, rejection and atomic refund/restock [P0]

**Depends on:** T01–T03, T13. **Owner:** returns backend.

**Files:** extend return schemas/router/service and `app/services/payments.py`; create `tests/test_return_processing.py`, `tests/test_return_processing_transactions.py`; update generated API types.

**Interfaces:** `ReturnAction(expected_status: str)`; `receive_return(cur, actor, return_id, body) -> ReturnDetail`; `reject_return(cur, actor, return_id, body) -> ReturnDetail`; `process_return(cur, actor, return_id, body) -> ReturnDetail`. Expose `POST /api/v1/returns/{return_id}/receive`, `/reject`, `/process`, and `GET /api/v1/stores/{store_id}/returns?status=`. The queue includes unreceived requests originating at that store and all returns already received there; other eligible returns can be looked up by ID for receipt.

- [ ] Add `test_receive_records_actor_and_store`, `test_receiving_does_not_restock`, `test_rejected_return_has_no_refund`, `test_partial_refund_uses_sold_price`, `test_wrong_store_cannot_process`, and `test_zero_value_return_has_no_payment_row`.
- [ ] For every action, load ownership metadata and lock the parent order before the return, then its lines in order. Recheck the current status and session permissions after locks are acquired.
- [ ] Receive a requested return only at the actor's retail store; record store/staff and `received` history without changing inventory. Allow staff at the original fulfilment store to reject an unreceived request; after receipt, only staff at the receiving store may reject/process it.
- [ ] Reject only from requested/received. Because stock is not added until processing, rejection needs no inventory reversal. Keep the request/history visible and terminal.
- [ ] Process only a received return at the actor's receiving store. Compute refund as `sum(return_line.quantity * order_line.unit_price)` with Decimal/NUMERIC, independent of current product prices or submitted amounts.
- [ ] In one transaction, lock all affected products in ascending ID order before inventory operations, create missing receiving-store inventory rows at zero, add returned quantities using relative updates in sorted order, insert the positive refund linked to the return, and move status to `refunded`. For zero amount, skip payment insertion but commit the stock/history/status effects. Keep this product-before-inventory order consistent with checkout/cancellation to avoid cross-workflow lock cycles.
- [ ] Enforce once-only effects through the locked return status and unique refund source. An already completed identical action returns its result; an incompatible terminal action returns a structured conflict. Do not label customer-return stock as a manual stock adjustment.
- [ ] Add `test_concurrent_process_refunds_and_restocks_once`, `test_refund_failure_rolls_back_inventory_and_status`, `test_reject_races_with_process`, and `test_two_returns_cannot_exceed_charge`. Pin one unit sold at `19.95`: processing twice adds exactly 1 unit and records exactly one `19.95` refund.
- [ ] Run `pytest tests/test_return_processing.py tests/test_return_processing_transactions.py tests/test_rule_concurrency.py -q`; regenerate types.
- [ ] Review and commit this task.

**Acceptance:** return processing T2 is all-or-nothing, actor-audited and safe under duplicate/concurrent requests. A failed refund cannot leave the item restocked or the return marked complete.

### T15 — Add staff return-processing screens [P1]

**Depends on:** T05, T13–T14. **Owner:** admin returns.

**Files:** create `web/src/app/admin/returns/page.tsx`, `web/src/app/admin/returns/[id]/page.tsx`, `web/src/components/admin/return-actions.tsx`; modify sidebar and API aliases.

**Consumes:** T13 return detail and T14 queue/action contracts. Use `allowed_actions`, server-computed refund preview and the displayed `expected_status`.

- [ ] Add component tests for requested/received/refunded/rejected action sets, actor/store restrictions, duplicate-click prevention and stale-status refresh.
- [ ] Build a status-filtered queue and return-ID lookup; show original order/customer/store, returned lines, reason, receiving location and full timeline.
- [ ] Show separate Receive, Reject and Process refund actions only when the server permits them. Before processing, display original-price refund amount and exact quantities/destination to be restocked.
- [ ] Submit the action, retain the screen on errors and refresh from the authoritative response. For a timeout, retry the same action or refetch status before offering a conflicting action.
- [ ] Link back to order details and show terminal outcome/history, including zero-value refunds. Verify the customer's `/returns` reflects staff changes after refresh.
- [ ] Run web unit/type/lint checks; complete a normal refund and a rejected return through the UI.
- [ ] Review and commit this task.

**Acceptance:** staff can receive/reject/process returns through the interface, and repeated actions cannot cause duplicate effects.

### T16 — Complete the agreed reporting/staff slice [P2; proposed scope]

**Depends on:** T11–T15. **Owner:** reporting.

**Files:** if retained in the team scope, create `queries/reports.sql`, `app/schemas/reports.py`, `app/services/reports.py`, `app/routers/reports.py`, `tests/test_reports.py`, `web/src/app/admin/reports/page.tsx`, `doc/reports.md`; update API registration/sidebar/types. Keep parameterised query examples outside bootstrap `sql/`, whose files are all executed during database creation.

**Scope distinction:** the repository names reporting/staff as a slice but provides no report specification or staff CRUD requirement. The following three reports are proposed defaults. Operational staff work is already supplied by T12/T15; do not add hiring, transfers, manager reassignment or support-ticket management without an actual requirement.

**Interfaces / definitions:**

- `GET /api/v1/reports/sales?store_id=&from_date=&to_date=` → store, captured amount, refunded amount, net receipts and order count. Count charges/refunds by their own event times; aggregate separately before joining to avoid multiplication by order lines.
- `GET /api/v1/reports/low-stock?store_id=&threshold=3` → active products with quantity at or below the threshold, including products with no inventory row. This can reuse the existing inventory query.
- `GET /api/v1/reports/returns?store_id=&from_date=&to_date=` → requested/received/refunded/rejected counts and refunded amount; state whether the filter selects request cohorts or event flows. Default here: requests created in the interval, with current status and refunds linked to those requests.
- Dates are Sydney calendar dates with inclusive `from_date` and exclusive `to_date`; convert local boundaries to aware timestamps. Managers see their own store, support may see all stores. Sales attributes to fulfilling store; return report attributes the request to the original fulfilling store and displays receiving store separately.

- [ ] Record whether these proposed reports are in scope in `doc/requirements.md`; if omitted, mark this task explicitly deferred instead of claiming it was implemented.
- [ ] Create hand-calculated fixtures and `test_sales_does_not_multiply_payments`, `test_refunds_use_event_date`, `test_low_stock_includes_missing_rows`, `test_return_report_cohort_definition`, `test_sydney_date_boundary`, and `test_report_store_permissions`.
- [ ] Implement documented parameterised queries, typed endpoints and a compact table/filter UI; show definitions, AUD amounts and empty/error states. Keep current inventory functionality reusable.
- [ ] Include at least one clear join/aggregate and nested-query example in `queries/reports.sql`; use a read-only demonstration of `NOT EXISTS` division only if the team needs that SQL technique, with a meaningful question and expected output. Do not invent an assessment-mandated query count.
- [ ] After representative data exists, inspect query plans and add `sql/04_indexes.sql` only for evidenced access needs, such as customer/order history, payment order IDs or return order/line lookups. Capture the before/after plan rather than claiming unmeasured improvements.
- [ ] Run `pytest tests/test_reports.py -q`, regenerate types and run web checks.
- [ ] Review and commit the retained scope.

**Acceptance:** each retained report has a precise grain, filter/time definition and hand-verifiable expected output. Unknown staff/reporting requirements remain labelled rather than fabricated.

### T17 — Add reproducible demonstration data and project evidence [P1]

**Depends on:** core lifecycle T09–T15; T16 if retained. **Owner:** integration/docs.

**Files:** create `scripts/seed_demo.py`, `doc/demo.md`, `doc/data-model.md`, `doc/business-rules.md`; update `README.md`, `web/README.md`, `doc/progress.md`, `web/src/lib/shop-pages.ts` and home copy. Add `tests/test_demo_seed.py` for generated lifecycle reconciliation.

**Interfaces:** `seed_demo(cur, reference_time: datetime, seed: int) -> SeedSummary`, with `SeedSummary = {scenario_order_ids: dict[str, int], scenario_return_ids: dict[str, int], created: bool}`; CLI `python scripts/seed_demo.py --database <name> --reference-time <ISO8601> --seed 9120` operates on an explicitly selected demo/test database. It must not be run against a database selected implicitly by a test fixture.

- [ ] Keep reference seed data intact; add stable scenario identifiers so a repeated demo seed is harmless or fails with a clear already-seeded message instead of duplicating orders.
- [ ] Include delivery/collection at multiple stages, an empty-stock checkout example, a paid cancellation, eligible and expired completed orders, partial/multiple returns, rejected/received/refunded outcomes, and a logged stock correction.
- [ ] Use the same transaction/service logic for normal scenarios. For historical fixtures, require a dedicated database whose name ends in `_demo` or `_test` and a maintenance-owner connection: create valid scenarios, then shift only their recorded timestamps relative to the chosen reference time inside one maintenance transaction. Temporarily suspend only the relevant timestamp/immutability guards, restore them before commit, and recheck temporal/financial invariants. Keep foreign keys and other business rules enabled; never expose this fixture-only operation through the API or allow it on the normal development database.
- [ ] Reconcile final stock against opening stock plus manual adjustments, minus fulfilled purchases, plus valid cancellations and processed returns. Reconcile charges/refunds to order/return/cancellation sources with exact decimal amounts.
- [ ] Write a runnable demo script: select customer/store → filter product → cart → both checkout modes → staff completion → customer return → staff receipt/refund → customer timeline; also demonstrate one rule refusal and safe retry.
- [ ] Document the actual ER structure, keys, weak entities, staff discriminator, recursive category, deferred manager FK, views and controlled redundancy. Add a BR01–BR18 table linking each rule to its constraint/trigger, service responsibility and tests.
- [ ] Describe transaction boundaries, lock order, failure rollback, retry fingerprints and cancellation accounting so a team member can explain the implementation. Link retained report queries and expected outputs.
- [ ] Remove obsolete reserved-route/API claims only when each route is implemented. Preserve the requirement catalogue if useful, but remove `ReservedPage` imports and developer-only planning banners from customer flows.
- [ ] Add dated GenAI acknowledgements and actual checks to the progress log. Treat any separate assignment report/rubric requirements as unavailable until supplied, not as automatically satisfied by these documents.
- [ ] Run `pytest tests/test_demo_seed.py -q`; follow the documented demo against a fresh isolated dataset and record outcomes.
- [ ] Review and commit this task.

**Acceptance:** a fresh setup can demonstrate every core lifecycle, and database/transaction decisions have inspectable project evidence.

### T18 — Automate end-to-end verification and delivery checks [P1]

**Depends on:** T01–T15, T17; T16 if retained. **Owner:** integration/review.

**Files:** create `web/playwright.config.ts`, `web/e2e/purchase.spec.ts`, `web/e2e/returns.spec.ts`, `web/e2e/session-isolation.spec.ts`, `web/e2e/recovery.spec.ts`, `.github/workflows/ci.yml`, `tests/test_api_errors.py`; modify test support/conftest/concurrency helpers, `web/package.json`, `app/errors.py` and docs as needed.

**Produces:** `npm run test:e2e`, a fresh-database verification pipeline and a recorded release checklist. Browser tests use their own prepared API/database configuration; they must not accidentally browse against the developer API.

- [ ] Commit browser journeys for catalogue → cart → delivery/collection checkout → order timeline → admin completion → return request → staff receive/process → customer refund status. Include a valid paid cancellation.
- [ ] Test guest/session expiry, foreign customer/order URLs, actor switches, stale store/product responses, quantity/price changes, inactive address/product, out-of-stock, timeout replay and duplicate processing.
- [ ] Test narrow mobile and desktop layouts, keyboard navigation, dialog focus, form labels and loading/empty/error/retry states. Check that no customer route renders `ReservedPage` or technical setup instructions as product copy.
- [ ] Add sanitized structured database-unavailable errors and server-side logging for unexpected failures. Preserve the error envelope without exposing SQL/credentials/row contents. Verify API `GET /promotions`, `/health`, 401/403/404/409/422 and database outage behavior explicitly.
- [ ] Update `ApiError.isRule`/`ErrorBox` so application conflicts such as `price_changed`, `stale_status` and `idempotency_conflict` are not falsely labelled database constraints. Keep actual BR codes inspectable.
- [ ] Add bounded barrier/join timeouts and thread diagnostics to concurrency helpers. Run the suite serially against its declared database or allocate a unique database per worker; never let concurrent suites force-drop each other's database.
- [ ] Verify errors during transaction commit are returned before a success response; preserve the existing function-scoped database dependency. Test a deferred constraint failure through an endpoint that creates related rows or a narrowly scoped test route.
- [ ] Configure CI with an isolated PostgreSQL 18 service, Python dependencies, locked frontend installation and explicit test environment values. Regenerate OpenAPI types from the built API/schema and fail on an unexpected committed-type diff.
- [ ] Run the full verification sequence below once after integration; rerun focused tests when later fixes warrant it. Record actual results and unresolved limitations, not expected results.
- [ ] Review the final diff, confirm no secrets/generated runtime folders or accidental nested-checkout changes are included, and commit the completed delivery work. Publishing/deployment is a separate task unless explicitly requested.

**Acceptance:** the entire retained scope is reproducibly checked from a clean setup, core journeys pass, and documentation matches the delivered behavior.

## 6. Final verification sequence

These are **future implementation checks**. They were not executed by the planning audit. New commands such as `test:unit` and `test:e2e` become available only after their owning tasks.

1. Configure an isolated test PostgreSQL instance/database with T00's settings; bootstrap the latest SQL in order.
2. From root, run `pytest -q`. Expected: all collected rule/API/lifecycle/concurrency tests pass, with no indefinite waits and no changes to demo data.
3. Start the API against the intended verification database; from `web/`, run `npm run gen:api`. Inspect `git diff -- web/src/lib/api/schema.d.ts` from root; generated types must match the implemented contracts.
4. From `web/`, run `npm run test:unit`, `npm run typecheck`, `npm run lint`, then `npm run build`. Expected: all exit successfully; no ignored framework/type errors.
5. Start the web/API verification stack with its own seeded dataset, then run `npm run test:e2e`. Expected: both purchase modes, cancellation, return/refund, session isolation and recovery journeys pass.
6. Run the demo reconciliation checks and the `doc/demo.md` walkthrough; compare visible totals/history with stored records.
7. Search customer source for unfinished components: `rg -n 'ReservedPage|ReservedCard|TODO|FIXME' 'web/src/app/(shop)'`. Review every match; no live customer feature may still be a placeholder.
8. Check `git status --short` and inspect the final diff. Confirm only intentional root-project changes and updated documentation are included.

## 7. Definition of full completion

- [ ] All nine originally reserved customer routes perform their documented functions.
- [ ] Catalogue/category/brand/current-price filtering and store availability work with existing home links.
- [ ] Customer identity, staff identity and resource/store permissions are enforced by the API.
- [ ] Delivery and retail collection checkout commit order/lines/stock/payment/history together and replay safely.
- [ ] Customers can inspect their orders, purchase-time amounts, retained addresses and full timelines.
- [ ] Staff can progress both fulfilment modes and cancel in the already allowed states with correct money/stock effects.
- [ ] Customers can add/retire addresses and request/track eligible returns, including rejected outcomes.
- [ ] Staff receipt/rejection/refund processing has correct actor/location history and exactly-once stock/payment effects.
- [ ] BR01–BR18, lifecycle mutation protections and relevant concurrency cases have passing, meaningful tests.
- [ ] Existing inventory/product/specification/promotion admin functionality still works under the new permissions.
- [ ] Any retained reporting scope has precise definitions and independently verified results; omitted proposals are marked deferred.
- [ ] Demo data, model/rule/transaction notes, setup instructions and GenAI acknowledgements are current.
- [ ] Fresh backend, web, build and browser results are recorded, and remaining limitations are explicit.

## 8. BR01–BR18 implementation/reference map

| Rule | Existing mechanism | Completion responsibility |
|---|---|---|
| BR01 | Lowercase email domain + unique customer email | Keep direct rule tests; normalise only in any future customer-creation API; T06 respects account ownership |
| BR02 | `money_aud NUMERIC(10,2)` nonnegative domain | T09/T14 exact calculations and explicit zero-value policy; do not assume the domain rejects rather than rounds extra decimals |
| BR03 | Inventory quantity nonnegative CHECK | T09 conditional deductions; T11/T14 relative restocks and race tests |
| BR04 | Deferred composite manager/store FK | Preserve bootstrap and tests; new staff/manager CRUD is not assumed |
| BR05 | Staff type ↔ nullable store CHECK | T01 actor role/store mapping |
| BR06 | Delivery-address shape CHECK + retail-collection trigger | T09 fulfilment validation; no store-type edit API in recovered scope |
| BR07 | Positive line quantity + one product per order | T09 nonempty input and unique lines; T02 historical-line guards |
| BR08 | Immutable order-line unit price trigger | T09 initial server-price snapshot; T02 prevent other historical line rewriting |
| BR09 | Allowed transitions + order-history trigger | T02 protected history; T11 legal actor-scoped progression/cancellation |
| BR10 | Unique `(customer_id, idempotency_key)` | T03/T09 payload fingerprints and concurrent replay |
| BR11 | Completed-order and 30-day return trigger | T02 authoritative time/boundaries; T13 eligibility and replay |
| BR12 | Parent-line lock + non-rejected return quantity sum | T02 close update bypasses; T13 concurrent quantity requests |
| BR13 | Composite return/order and order-line FKs | T13 trusted order/line construction and atomic failure |
| BR14 | Refund source/once-only constraints + order-locked cap | T02 immutable ledger; T03 cancellation source extension; T11/T14 transactional effects |
| BR15 | Product lock, promotion overlap/price triggers and reverse base-price check | T04 price boundaries; T02 concurrency tests; retain existing promotion admin |
| BR16 | Address content immutable; activity flag mutable | T06 add/retire API; T09 active-address checkout policy |
| BR17 | Composite order/customer/address FK | T01 customer access control; T09 owned-address validation |
| BR18 | Staff/store FK, reason/delta CHECK and append-only stock adjustment | T01 session-derived actor; preserve existing atomic adjustment service and regressions |

**Planning provenance:** This document was prepared with Codex and three read-only subsystem audits. Source inspection, duplicate-file comparison and Python syntax parsing were performed; application behavior/build/test results were not newly verified. No implementation is claimed by the unchecked task list.

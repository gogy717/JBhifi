# Progress log

Newest entries first. IDs such as R#, BR# and T1 refer to `.claude/plan.md`.

---

## 2026-10-16 — Branch `gogy717/concurrency-evidence`: what goes wrong without each concurrency technique

Design: `docs/superpowers/specs/2026-10-16-concurrency-evidence-design.md`; plan:
`docs/superpowers/plans/2026-10-16-concurrency-evidence.md`. Report §4 material; tests and one document only (no
product code, no `sql/`).

**What's on the branch.**

- **`docs/concurrency-evidence.md`**: for each anomaly, the faulty pattern, what PostgreSQL does, and ours, with the
  results the tests printed, a summary table, and an answer to tutor question 4 (plan §12) listing the test that
  pins each conditional `UPDATE` and parent-row lock — and the locks and lock orders that have no race test of
  their own.
- **`tests/test_concurrency_evidence.py`** (8 tests): a lost update (read, compute in Python, write back: one unit
  sold twice, BR03's `CHECK` silent) against the conditional `UPDATE` (one sale), plus the same statement under
  `REPEATABLE READ` failing with 40001; a deadlock from opposite lock orders (40P01, one transaction rolled back)
  against locking in `product_id` order (the second waits, both commit); write skew on BR15's rule — check then
  insert lets two overlapping promotions in under `READ COMMITTED`, `SERIALIZABLE` aborts one (40001) and its retry
  is refused, and the real trigger's product lock gives `br15_promotion_no_overlap` under `READ COMMITTED`.
- **`tests/concurrency_support.py`**: each transaction on its own connection with a `lock_timeout`; a blocked
  statement runs in a thread, and the test waits on `pg_stat_activity` (`wait_event_type = 'Lock'`) before its
  next step, so no sleep decides the order. The write-skew demo uses a throwaway table (a random name, dropped
  first and last), because the real trigger is never switched off: `ALTER TABLE … DISABLE TRIGGER` takes a
  `SHARE ROW EXCLUSIVE` lock, which would itself serialise the two racing transactions.

**Open.** Whether the Week 9 lecture covered SQL isolation levels is unconfirmed; until it is, the
`REPEATABLE READ` / `SERIALIZABLE` material is marked *optional — confirm against the Week 9 transactions lecture*.

**Verification (actually run).** `pytest` → **607 passed** (8 new); `test_concurrency_evidence.py` five times in a
row → 8/8 each; no demo table left in the test database afterwards. Dropping `AND quantity >= 1` from the
conditional `UPDATE` makes its test fail (BR03 refuses B's write).

---

## 2026-10-16 — Branch `gogy717/demo-startup`: one command for the demo, README, walkthrough

- **`scripts/demo.py`**: one command starts the demo — the database (`docker compose up -d db`, main checkout
  only; a worktree never runs compose), the API (`fastapi run`) and the web app (a production build, or
  `next dev` with `--dev`), waits until `/health` and the web app's `/api/health` answer, prints the addresses and
  personas, and stops the API and the web app on Ctrl-C. `--reset` rebuilds the dev database first;
  `--api-port` / `--web-port` for worktrees. Logs in `.demo/` (git-ignored). Python rather than shell, so it also
  runs on Windows.
- **`scripts/reset_db.py`**: drops and rebuilds the database named by `POSTGRES_DB` from `sql/*.sql` (so the
  future generated seed is included) and re-links the personas; refuses an empty name, `postgres`,
  `template0/1` and the test database; if Clerk can't be reached it says the database is rebuilt but not linked.
- **README**: the one-command demo and `reset_db.py`; the storefront and admin paragraphs describe the pages as
  they are now (they still said the customer pages were reserved). **`docs/demo-walkthrough.md`**: a checklist
  per persona (page, click, expected result, R#/BR#/T#) and a ≤ 3-minute video script; seed-specific orders are
  marked *[seed: …]* until the seed is merged.

**Decision** (coordinator): scripts instead of api/web services in `docker compose` — fewer moving parts, no
Clerk keys in images, the demo runs the code the tests run. The demo needs the internet (Clerk), so plan §10's
"works offline" no longer holds.

**Verification (actually run).** `pytest` → **610 passed** (8 new, for the scripts' safety checks).
`reset_db.py` against `jbhifi_sp4`: rebuilt and linked (exit 0); with Clerk unreachable it reports the database
rebuilt but not linked (exit 1); `POSTGRES_DB=postgres` is refused. `demo.py --api-port 8004 --web-port 3004`:
built, both health checks answered, the storefront answered 200; Ctrl-C stopped the API and the web app within
2 seconds and freed both ports. **Not done:** a run in the main checkout (where it would start the database with
compose), and the browser walkthrough itself.

---

## 2026-10-16 — Branch `gogy717/sp4-support-returns`: returns in the support lookup (R10, after SP3)

The two items SP4's design left for after SP3 (`docs/superpowers/specs/2026-10-16-reports-support-design.md` §4).

- **History** (`GET /customers/{id}/history`): a return being received, refunded or rejected now appears, with
  who did it (`LEFT JOIN staff` on `processed_by_staff_id` / `resolved_by_staff_id`) and a rejection's reason in a
  new `note` field. Same-instant events keep their real order with one rule: a payment sits just before the
  event it enables — a charge before `paid`, a cancellation's refund before `cancelled`, a return's refund (T2
  writes it with the same `now()` as the return's resolution) before `return_refunded`. That also fixes the
  earlier review's deferred minor: a charge no longer slides past later status moves that share its moment.
- **`/admin/support`**: a Returns section from SP3's `GET /customers/{id}/returns` — lines, value, refund,
  status, receiving store and time, rejection reason — each linking to `/admin/returns/{id}`.

**Verification (actually run).** `pytest` → **602 passed** (3 new: a refunded return reads requested →
received → refund → refunded; a rejected one shows who and why; a charge sits just before `paid` when later moves
share its instant), and moving a return's refund after its resolution fails the first. Web `typecheck`, `lint`,
`build` clean; `test:unit` → **35 passed**. The dev database `jbhifi_sp4` was rebuilt from `main` and the personas
re-linked. **Not done:** the in-browser walk-through (Clerk sign-in needs the personas' passwords).

---

## 2026-10-16 — Branch `gogy717/fusilier-returns-t2`: return requests, receipt, refund (T2) and rejection

Design: `docs/superpowers/specs/2026-10-16-returns-design.md`; plan: `docs/superpowers/plans/2026-10-16-returns.md`.
Sub-project 3 of 4 (orders → fulfilment & cancellation → **returns** → reports). R6, R8.

**What's on the branch.**

- **Return rules in the database** (spec §1). `return_request` gains a retry key (BR10 widened:
  `UNIQUE (order_id, idempotency_key)`), when and by whom it was received and resolved, and a rejection reason,
  held together by named `CHECK`s and a composite FK (the resolver works at the receiving store). A return is
  rejected only after it is received: `requested → rejected` is gone from the transition trigger, and the receipt
  `CHECK` now covers rejected returns too, so the resolver FK is always checked. BR14 widened: a refund for a
  return equals what its items were bought for (`v_return_value`, a view, so the amount is worked out in one
  place), and a return's lines never change after the request. BR22 (new): returns are received at a retail
  store — a fact about one moment, so unlike BR06 it needs no store-side guard.
- **Asking for a return**, `POST /api/v1/orders/{id}/returns` with an `Idempotency-Key`: T1's shape — look the key
  up, claim it with `ON CONFLICT DO NOTHING`, then insert the lines in `line_no` order. A retry that arrives after
  the 30-day window closed, or after BR12's total filled up, still gets its return back.
- **Staff actions** `receive`, `refund` (T2) and `reject`: each locks the order, then the return, `FOR UPDATE`;
  T2 then restocks the receiving store in ascending `product_id`, pays the refund and marks the return refunded,
  all or nothing. Each action needs exactly one status, so whoever comes second gets 409
  `return_status_transition` with the status it found; `UNIQUE (return_id)` on payment is the backstop. The spec
  explains why this lock order can't deadlock with cancelling (SP2) or checkout.
- **Reads**: `GET /returns/{id}`, `GET /customers/{id}/returns` (the contract SP4 uses), `GET /stores/{id}/returns`
  (the store's desk). 403 before 404, as for orders.
- **Web**: the order page's "Return items" form (what is left per line, the 30-day deadline, a key kept across an
  unanswered try), My returns, the home page's Returns card, and the admin returns desk and return page (receive,
  refund, reject with a reason).

**Decisions.** The decision table in spec §1 (retry key, refund = purchase price enforced by the database, any
retail store receives, rejection only after receipt with a reason, receiver and resolver both recorded, 409 for
a second click). Deviations from the plan: a list of returns carries each return's lines (one query), so the
form can tell what is left; `_refund(cur, return_id)` inserts from the view, as T1's `_charge` does. SP4's test
builders (`tests/reports_support.py` `a_return`, `tests/test_support.py`) now give a request its key, record a
receipt and reject only after it, as the new rules require.

**Verification (actually run).** `pytest` → **599 passed** (111 new); `test_return_transactions.py` five times in a
row, all passing; removing the order/return `FOR UPDATE` or the `ON CONFLICT` makes those tests fail. Web
`typecheck`, `lint` and `build` clean; `test:unit` → **35 passed** (15 new). A final whole-branch review found
nothing critical; its fixes (a return's lines are fixed in the database, the form keeps its key after a sign-in
failure, the warehouse desk lists no requested returns, the desk keeps a refused click's message, and a test that
T2 restocks the receiving store) were made test-first. The dev database was rebuilt from `sql/`, the personas
re-linked, and T2 run on it in a rolled-back transaction. **Not yet run:** the in-browser walk-through (it needs a
Clerk sign-in), left for after the merge.

---

## 2026-10-16 — Branch `gogy717/sp4-reports-support-queries`: manager reports and support lookup (R9, R10)

Design: `docs/superpowers/specs/2026-10-16-reports-support-design.md`; plan: `docs/superpowers/plans/2026-10-16-reports-support.md`.
Sub-project 4 of 4 that finish the Phase 1 business logic. Yuhang's report code was not ported (it doesn't follow
plan §6, and its return figures were wrong); every query was derived again.

**What's on the branch.**

- **`v_sale_line`** (the only SQL change): what counts as a sale, defined once — an order line of a paid order
  that isn't cancelled, dated by `placed_at`, credited to the fulfilling store, at the price paid.
  `sql/` runs only on an empty volume, so an existing dev database needs the view added (rebuild it, or run the
  `-- ===== SP4: reports =====` section of `sql/03_views.sql`); without it the report answers 500.
- **Store report**, `GET /api/v1/stores/{id}/report?days=` (the store's manager, or support for any store):
  low stock (plan §6 #4: down to 3, or under 14 days of cover at the last 30 days' rate — a `HAVING` on the sales
  total), sales by category with the store's total, and return rate by category and product (§6 #6: of the units
  sold in the window, how many came back; returns summed per order line before the outer join, the rejected
  filter inside that subquery, `NULLIF` for nothing sold). Every section is read in one
  `REPEATABLE READ READ ONLY` transaction: the service commits the request's sign-in step, then sets the
  isolation level as the new transaction's first statement (`app/db.py` and `app/auth.py` unchanged).
- **Relational division** (§6 #5), `GET /api/v1/reports/stocked-in-every-store?state=`: products in stock at every
  retail store of a state (double `NOT EXISTS`); a misspelt state is a 409 from the `au_state` domain, and a state
  with no retail stores lists every product (vacuous truth), with the divisor stores in the answer.
- **Support lookup** (R10): `GET /api/v1/customers?q=` searches names and emails; `GET /api/v1/customers/{id}/history`
  merges status changes (with the staff member), payments and return requests in one `UNION ALL`, newest first,
  with an explicit sort step so same-instant events read in order: placed → charge → paid at checkout, refund →
  cancelled on a cancellation.
- **Web**: `/admin/reports` (7 / 30 / 90 days, the four sections, the division panel) and `/admin/support` (search,
  profile, orders, history).

**Decisions.** Spec §1: the sale definition; `days` 1–365 (default 30) with low stock's rate fixed at 30 days;
return rate by the cohort sold in the window (recent windows read low: items have 30 days to come back);
managers plus support read reports; the returns list on the support page will use SP3's endpoint, and is hidden
until SP3 is merged; indexes and `EXPLAIN` move to a separate PR after the seed (T-8).

**Verification (actually run, after rebasing on SP2).** `pytest` → **488 passed** (92 new: 33 in
`test_reports.py`, 10 in `test_support.py`, 49 permission-matrix cases), including the report §4 evidence pair
`test_repeatable_read_keeps_a_sale_committed_mid_report_out_of_every_section` /
`test_read_committed_would_let_a_sale_committed_mid_report_into_later_sections`. Web `typecheck`, `lint` and `build`
clean; `test:unit` → **20 passed**. A final whole-branch review found nothing critical or important; its minor
findings are listed in the pull request. **Not done:** the in-browser walk-through (Clerk sign-in needs the
personas' passwords).

---

## 2026-10-16 — Branch `gogy717/sp2-order-fulfilment-cancellation`: staff status moves, store queue, cancellation (T4)

Design: `docs/superpowers/specs/2026-10-16-fulfilment-design.md`; plan: `docs/superpowers/plans/2026-10-16-fulfilment.md`.
Sub-project 2 of 4 (orders → **fulfilment & cancellation** → returns → reports). R7, R11.

**What's on the branch.**

- **Rules in the database.** BR14 widens: a refund without a return is the order's cancellation refund, and the
  trigger `br14_refund_without_return_is_cancellation` allows it only while BR09's transition table still lets the
  order move to cancelled (the payment CHECK becomes `br14_charge_has_no_return`; a refund with a return is
  unchanged). **BR21 (new):** an order moves to cancelled only when nothing it was charged is still held
  (`br21_cancelled_order_refunded`), the mirror of BR20.
- **Store queue** `GET /stores/{id}/orders?status=…`: oldest first, for that store's staff or support.
- **Status moves** `POST /orders/{id}/status` `{from_status, to_status}`: the fulfilling store's staff, or support,
  move an order one step (picking, then ready or shipped, then collected or delivered). BR09 decides which moves
  are legal and logs the mover's `staff_id` through `app.staff_id`.
- **T4 cancel** `POST /orders/{id}/cancel` `{from_status}`, one transaction: lock the order `FOR UPDATE` → who
  (the customer before picking starts; the fulfilling store's staff whenever BR09 allows; support never) → the
  status the screen showed → the transition table allows cancelling → restock at the fulfilling store, in
  ascending `product_id`, making sure the inventory row exists first (as T3) → refund what is held → cancelled →
  the order in full. Any failure changes nothing.
- **Web**: the admin "Orders" queue (staff see their store, support pick one) and order page (one button per
  allowed move, a two-step cancel for the store's staff), and a "Cancel order" button on the customer's paid order.

**Decisions.** The decision table in spec §1: refund on cancel (every committed order is paid, so "cancel only
placed" would cancel nothing); restock to the store checkout took the stock from, with no `stock_adjustment` row
(T-7 logs manual changes only); who may cancel and move as above (support moving orders was the user's choice).
The status the screen showed (`from_status`) replaces an `Idempotency-Key` for these requests: a move happens at
most once from a given status, so a second clerk or a retry gets 409 `status_changed` with the current status.
During implementation: T4 asks the transition table before refunding, so a picking order's cancel is reported as
BR09 rather than under BR14's name; the spec's deadlock argument was corrected (the two transactions can wait for
each other only on inventory rows, which both lock in ascending `product_id`); `StoreSelect` moved into
`components/admin/store-select.tsx` so the queue reuses it.

**Verification (actually run).** `pytest` → **396 passed** (73 new); `test_fulfilment_transactions.py` five times
in a row, all passing; removing the `from_status` check or the `FOR UPDATE` makes those tests fail. Web
`typecheck`, `lint` and `build` clean; `test:unit` → **20 passed** (4 new, for the cancel button). A final
whole-branch review found nothing critical; its two fixes (a customer whose cancel came too late is now told why,
and a move to the status an order already has is refused as BR09) were made test-first. **Not yet run:**
the in-browser walk-through (it needs a Clerk sign-in), left for after the merge.

---

## 2026-10-03 — Branch `ethan/orders`: checkout (T1), order reads, addresses, price filter

Design: `docs/superpowers/specs/2026-10-02-orders-design.md`; plan: `docs/superpowers/plans/2026-10-02-orders.md`.
Sub-project 1 of 4 that finish the Phase 1 business logic (then fulfilment & cancellation, returns, reports).

**What's on the branch.**

- **Order rules in the database** (spec §2.1). BR20 is new: an order moves placed → paid only when it has lines
  and has been charged exactly its total (a three-table assertion emulated by triggers), a charge is taken only
  while the order is placed, and at most once (a partial unique index). BR08 widens: lines are added only while
  the order is placed and are never changed or deleted. BR09: the order header is fixed, and the status history
  is written only by the status-log trigger and has two `CHECK`s. BR07: only products on sale, and every order
  has a line (a deferred constraint trigger, checked at `COMMIT`). BR17: deliveries go to a current address.
  BR06 is guarded from both sides: an order reads its store `FOR SHARE`, and a store with Click & Collect orders
  can't stop being retail. Payments, history, stock adjustments and order lines are append-only, including
  statement-level `BEFORE TRUNCATE` triggers.
- **Views** (spec §2.2): `v_order_summary`, `v_order_payment` (payments summed before the join, so no fan-out;
  money keeps two decimals) and `v_order_timeline` (`LEFT JOIN` staff, so the customer's own moves stay listed).
- **T1 checkout**, `POST /api/v1/orders` with an `Idempotency-Key` (BR10): one `READ COMMITTED` transaction —
  look the key up → claim it (`INSERT … ON CONFLICT DO NOTHING`) → lines at `v_product_current_price` → price
  check against the reviewed `expected_total` → stock (a conditional `UPDATE`, in `product_id` order, so two
  baskets can't deadlock) → one charge → paid. 201 for a new order, 200 for a replay of the same key.
- **Reads**: `GET /orders/{id}` (locks the order `FOR SHARE`, so a status change waits for the read; 403 before
  404) and `GET /customers/{id}/orders` (newest first). **Addresses**: add (numbered under a customer row lock)
  and retire (idempotent). **Products**: `min_price` / `max_price` on the current price, and `store_id` adds that
  store's quantity.
- **Web**: catalogue with price and store filters, product, stores, cart (integer cents), checkout (Click &
  Collect, or delivery from the warehouse or a store with stock), My orders, the order page with its timeline and
  payment, account addresses, and the home page's "My orders" card. A reviewed basket keeps its retry key in the
  browser, so a lost answer can't turn into a second order. Vitest unit tests for the cart and the checkout
  attempt.

**Decisions.** The decision table in spec §1: this scope (staff moves, cancellation, returns and reports come
later); selective reuse of Yuhang's schema; the beyond-Week-10 integrity extras (deferred constraint trigger,
partial unique index, `pg_trigger_depth` guard); BR06 guarded on both sides and its order side reading the store
`FOR SHARE`; the key looked up before it is claimed; delivery from the warehouse by default. Plan §5's T1 order
is now lookup → claim → lines → price check → stock → charge → paid. Deviations from the spec are listed in the
plan (three commits for the SQL rather than one; the dev database rebuilt in place rather than with
`docker compose down -v`; 404 when support asks for a customer that doesn't exist). After the final review a
pending checkout try is kept in `localStorage` (every tab, like the cart) instead of `sessionStorage`.

**Verification (actually run).** `pytest` → **323 passed** (131 new); the concurrency tests five times in a row;
web `typecheck`, `lint` and `build` clean; `test:unit` → **16 passed**. A final whole-branch review (five areas,
with a refuter for anything above minor) found nothing critical; its two important findings, both ways a lost
answer could still end in a second order, were fixed test-first, and the minor ones are listed in the pull
request. The dev database was rebuilt from `sql/` and the personas re-linked. **Not yet run:** the in-browser
walk-through (plan Task 10 Step 14, run in Task 11 Step 5).

---

## 2026-10-02 — Branch `ethan/clerk-auth`: real sign-in (Clerk), roles in the database

Design: `docs/superpowers/specs/2026-10-02-clerk-auth-design.md`; plan: `docs/superpowers/plans/2026-10-02-clerk-auth.md`.

**What's on the branch.**

- **Everyone signs in through Clerk**; the API verifies the session token itself (`app/identity.py`, the only
  Clerk-aware file: PyJWT against the issuer's public keys, RS256, `exp`/`nbf`/`iss`/`azp`). Only an
  `Authorization: Bearer` header counts — never a cookie, so there is nothing to forge cross-site.
- **New table `user_account` and rule BR19**: a sign-in identity is exactly one customer or one staff member,
  and each person has at most one (a `CHECK` and two `UNIQUE`s). On first sign-in `app/auth.py` links the
  token's subject: staff by verified email first (nobody becomes staff by signing up), then an existing
  customer, else a new customer. Roles stay where they were (`staff`, `store.manager_id`).
- **`GET /api/v1/me`**, and **permissions in the services** on every existing endpoint: the customer directory
  is support-only, a customer reads only their own record, stock is adjusted by that store's staff (the
  adjuster comes from the sign-in, a `staff_id` in the body is refused), the catalogue and promotions by
  managers and support. A refused caller gets 403 before any existence check, so ids can't be probed.
- **Web**: Clerk's sign-in/up pages, `proxy.ts` sends signed-out visitors to `/admin` to sign in, every API call
  carries the token, the storefront header uses Clerk's controls, and the admin follows the signed-in staff
  member (fixed to their store; catalogue edits only for managers and support).
- `scripts/clerk_personas.py` creates the demo personas (see README → Sign-in).

**Decisions.** Supersedes the 2026-09-26 "Signed in as" picker decision below, and plan §2 (real sign-in moves
into Phase 1) and §7 (Clerk instead of a demo cookie).

1. Clerk (hosted) for Phase 2 readiness; FastAPI verifies tokens itself so any client — web, mobile, the Phase 2
   agent — is checked the same way.
2. A separate `user_account` table rather than an `auth_subject` column on both `customer` and `staff`: "one
   identity is not both a customer and staff" is then a one-row `CHECK`, not a cross-table trigger.
3. Demo personas sign in with `…+clerk_test@example.com` addresses and the script links them to their seeded
   rows directly: Clerk refuses the staff rows' reserved `.example` addresses, and Clerk's Device Trust asks a
   new browser for an email code, which a test address in test mode answers with 424242 (no real inbox). Test
   mode was turned on for the development instance through the Backend API.

**Verification (actually run).** `pytest` → **192 passed** (42 before: BR19, token checks, linking incl. two
first sign-ins at once, a 7-caller × 17-endpoint permission matrix); web `typecheck` and `lint` clean;
`clerk doctor` clean; through the Next proxy, `/api/v1/stores` 200 for a guest, `/api/v1/me` and `/staff` 401,
`/admin` → `/sign-in`. **Not yet run:** the in-browser walk-through of the four personas.

**AI use.** Designed, implemented and reviewed with Claude Code on 2026-10-02 (the plan executed task by task
test-first, then one whole-branch review whose findings were fixed). Include in the AI-use acknowledgement.

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


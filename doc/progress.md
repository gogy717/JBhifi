# Progress log

Newest entries first. IDs such as R#, BR# and T1 refer to `.claude/plan.md`.

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

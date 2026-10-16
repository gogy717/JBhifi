# JB Hi-Fi DB Prototype

COMP9120 group project: a PostgreSQL-first prototype of an omnichannel electronics retailer — catalogue,
per-store stock, promotions, orders (home delivery or Click & Collect) and returns. The database itself
enforces the business rules (BR01–BR22); a FastAPI backend and a Next.js storefront + store admin sit on top.

```
web/ (Next.js, :3000) ──/api/*──▶ app/ (FastAPI, :8000) ──▶ PostgreSQL 18 in Docker (:5433)
```

## What you need

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — runs PostgreSQL, nothing to install
- Python 3.12 or newer
- Node.js 20.9 or newer (Next.js 16)

## First-time setup

```bash
git clone https://github.com/gogy717/JBhifi.git
cd JBhifi
cp .env.example .env              # Windows: copy .env.example .env
```

Python environment — macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Frontend packages:

```bash
cd web
npm install
cd ..
```

Frontend unit tests (Vitest): `npm --prefix web run test:unit`.

**Rebuilding the dev database from a branch.** `sql/*.sql` only run when the Docker volume is empty, and the
compose file mounts `./sql` from the directory you run it in. To load the SQL of the branch you are on, without
touching the volume (the database container must be running):

```bash
.venv/bin/python scripts/reset_db.py           # Windows: .venv\Scripts\python scripts\reset_db.py
```

It drops and recreates the database named by `POSTGRES_DB` in `.env` (never a system or test database), runs
`sql/*.sql` in filename order, and re-links the demo personas (`scripts/clerk_personas.py`, link only — it needs
the internet to reach Clerk; if it can't, the database is still rebuilt and the script says so).

**Generated data.** `sql/20_seed_generated.sql` adds ~300 customers and 1,500 orders over the last 182 days,
loaded through every rule (`docs/superpowers/specs/2026-10-16-seed-design.md`); `scripts/reset_db.py` loads it
with the other files. Its times are relative to Sydney midnight on the day it is loaded, so **rebuild the demo
database on demo day**. It is generated, never edited: change `scripts/generate_seed.py` or
`scripts/seed_helpers.sql`, then run `.venv/bin/python scripts/generate_seed.py`. That builds a scratch database
(`$POSTGRES_TEST_DB` + `_seed`), loads the new file into it to prove it passes, and only then writes it. `pytest`
checks the committed file in the same database (`tests/test_seed.py`), so don't run the generator and the tests
at the same time. The test database itself (`tests/conftest.py`) loads only the hand-written files, numbered
below 20.

Sign-in (Clerk). Everyone signs in through Clerk; our database decides who is a customer or staff (BR19).
Ask the team for access to the Clerk application, or create your own free development application, then:

1. Web keys: `cp web/.env.example web/.env.local` and fill in the publishable and secret keys from the Clerk
   Dashboard (API keys page). With the [Clerk CLI](https://clerk.com/docs/cli) you can instead run
   `clerk auth login` and then, in `web/`, `clerk init --app <app id>`, which writes `web/.env.local` for you.
2. API settings: fill in the `CLERK_ISSUER` (the Frontend API URL on the same page), `CLERK_SECRET_KEY` and
   `AUTH_AUTHORIZED_PARTIES` lines of `.env`. Without them every sign-in is refused.
3. Demo personas (once per Clerk application, with the database running): choose a password of at least 15
   characters that has never been in a breach, then
   `DEMO_PASSWORD='…' .venv/bin/python scripts/clerk_personas.py`. It creates Alice Morgan (customer) and three
   staff — Aiden Chen (Sydney CBD), Olivia Nguyen (Sydney CBD manager), Nora Fitzgerald (support). Each signs
   in as `<first>.<last>+clerk_test@example.com` and is linked to its seeded row by the script.
4. The Clerk development instance must be in **test mode** (on by default; Dashboard → Settings, or the
   Backend API's `PATCH /v1/instance {"test_mode": true}`): when Clerk asks a new browser for an email code
   (Device Trust), a `+clerk_test` address takes the code **424242** — no real inbox needed.

## Run it

**One command (the demo).** With the setup above done and Docker Desktop running:

```bash
.venv/bin/python scripts/demo.py               # Windows: .venv\Scripts\python scripts\demo.py
```

It starts the database (`docker compose up -d db`) if it isn't running, builds the web app (about a minute) and
starts it with the API, waits until both answer, and prints the addresses and the demo personas. Ctrl-C stops the
API and the web app; the database keeps running. `--reset` first rebuilds the dev database from `sql/`
(`scripts/reset_db.py`), `--dev` runs `next dev` instead of a production build, and `--api-port` / `--web-port`
choose other ports. Logs go to `.demo/`. Sign-in is Clerk's hosted service, so the demo needs the internet.

**For development**, three terminals, each starting in the repo root:

| # | Start | Then open |
|---|---|---|
| 1 | `docker compose up -d` | — PostgreSQL on `localhost:5433` |
| 2 | `source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`), then `fastapi dev app/main.py` | http://127.0.0.1:8000/docs — every endpoint, try them out |
| 3 | `cd web`, then `npm run dev` | **http://localhost:3000** — the storefront; the store admin is at **/admin** |

The first `docker compose up` creates the tables and loads the seed data from `sql/` (a few seconds).
Port 5433 is deliberate, so it can't clash with a PostgreSQL you may already run on 5432.

**Storefront** (`/`): current deals, categories and stores near you. Browse and filter the catalogue (keyword,
category, brand, price), see a product's stock at each store, and add it to the cart. Sign in (top right) as a
customer — or create an account, which makes you a new customer — and pick a store under "My store". Checkout places
a Click & Collect or delivery order, paid in full (simulated). **My orders** shows each order with its status
timeline; a paid order can still be cancelled (refunded and restocked), and a delivered or collected one can be
returned within 30 days. **Returns** follows each return; **Account** manages delivery addresses.

**Store admin** (`/admin`, staff only): **Orders** is the store's queue — staff move an order along (picking →
ready → collected, or shipped → delivered) or cancel it; **Returns** is the returns desk — receive a return, then
refund it (restocking the items) or reject it with a reason. Store staff use **±1** or **Adjust…** on their own
store's stock; store managers and support staff also edit products, specs and prices and create promotions;
support staff can look at any store's stock, orders and returns. When the database refuses something (stock below zero, staff from another store,
a sale price above the base price…) the page shows which rule refused it, e.g. `br03_inventory_qty_nonneg`.
**Reports** (`/admin/reports`) show a store's low stock, sales by category and return rate to its manager (support
staff pick any store), plus the products in stock at every store of a state; **Support** (`/admin/support`) lets
support staff find a customer and read their orders and full history.

## Everyday commands

| Task | Command |
|---|---|
| Start everything for a demo | `.venv/bin/python scripts/demo.py` (see Run it) |
| Stop the database (data is kept) | `docker compose down` |
| **Reset** the database to the seed data | `docker compose down -v && docker compose up -d` |
| Rebuild your dev database from `sql/`, keeping the container | `.venv/bin/python scripts/reset_db.py` |
| SQL shell | `docker compose exec db psql -U jbhifi -d jbhifi` |
| Run the tests (database must be up, venv active) | `pytest` |
| Regenerate the frontend's API types after changing the API (API running) | `cd web && npm run gen:api` |
| Check the frontend | `cd web && npm run typecheck && npm run lint && npm run build` |

`sql/*.sql` only run when the database volume is empty — **after editing or pulling changes to anything in
`sql/`, reset the database** or you won't see the change. `pytest` never touches your data: it rebuilds a separate
`jbhifi_test` database (or the one named by `POSTGRES_TEST_DB` in `.env`) from `sql/` on every run.

**Several worktrees at once.** All of them share the one `jbhifi-db` container; only the main checkout runs
`docker compose`. In each worktree's `.env`, give `POSTGRES_DB` and `POSTGRES_TEST_DB` names of its own — the test
run drops its database with `FORCE`, which would cut off another worktree's tests — and build its dev database with
`scripts/reset_db.py` (it uses that name). Run the API and the web app on their own ports
(`fastapi dev app/main.py --port 8002`, `API_URL=http://127.0.0.1:8002 npx next dev -p 3002` in `web/`), add the
web port to `AUTH_AUTHORIZED_PARTIES`, and regenerate the API types with
`npx openapi-typescript http://127.0.0.1:8002/openapi.json -o src/lib/api/schema.d.ts` (`gen:api` assumes port 8000).

## Project layout

| Path | What's in it |
|---|---|
| `sql/` | `00_domains` → `01_tables` → `02_rules` (triggers) → `03_views` → `10_seed_reference`, run in that order |
| `app/` | FastAPI. `routers/` handle HTTP only; `services/` hold the SQL (one call = one transaction); `errors.py` turns a rule violation into a 409 whose `code` is the constraint name |
| `tests/` | `test_business_rules.py` (one test per BR), one file per area (`test_checkout.py`, `test_fulfilment.py`, `test_returns.py`, `test_reports.py`, …) and its `*_transactions.py` concurrency tests, `test_permissions.py` (every caller × every endpoint) |
| `scripts/` | `demo.py` (one command for the demo), `reset_db.py` (rebuild the dev database from `sql/`), `clerk_personas.py` (the demo personas in Clerk) |
| `web/` | Next.js: the customer storefront (`/`) and the store admin (`/admin`) — see [`web/README.md`](web/README.md) |
| `doc/progress.md` | decisions, experiments and AI-use notes, newest first |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Pages stay on "Loading…" / the admin sidebar says "API unreachable" | Start the API (terminal 2). |
| API errors: `connection refused` / `KeyError: 'POSTGRES_HOST'` | Start the database (terminal 1) / create `.env` from `.env.example`. |
| `fastapi: command not found` | Activate the virtual environment first. |
| Changed `sql/` but nothing changed | Rebuild the dev database: `.venv/bin/python scripts/reset_db.py` (or `docker compose down -v && docker compose up -d`). |
| Every sign-in says "expired or isn't valid" | `.env` lacks the Clerk lines, or `web/.env.local` holds keys of a different Clerk application than `CLERK_ISSUER`. |
| "This person is already linked to a different sign-in" | A Clerk account was re-created for the same person: remove the old link with `DELETE FROM user_account WHERE auth_subject = '<old user id>'`. |
| "Sign-in couldn't load" | No connection to Clerk: guests can still browse; sign-in needs the network. |
| `port is already allocated` on 5433 | Another container uses it: `docker ps`, stop it. |
| Windows: `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `.venv\Scripts\activate.bat` in cmd. |

## Working on it

- SQL is hand-written with psycopg2 (no ORM); values always go through `%s` parameters, never f-strings.
- Business rules live in the database; name their constraints `brNN_<what>` and add a test that breaks each
  rule in `tests/test_business_rules.py`.
- Don't `pip freeze` into `requirements.txt`; it's hand-written so it installs on Windows too.
- Record any GenAI use in `doc/progress.md`.

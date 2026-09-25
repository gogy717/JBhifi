# JB Hi-Fi DB Prototype

COMP9120 group project: a PostgreSQL-first prototype of an omnichannel electronics retailer — catalogue,
per-store stock, promotions, orders (home delivery or Click & Collect) and returns. The database itself
enforces the business rules (BR01–BR18); a FastAPI backend and a Next.js admin console sit on top.

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

## Run it

Three terminals, each starting in the repo root:

| # | Start | Then open |
|---|---|---|
| 1 | `docker compose up -d` | — PostgreSQL on `localhost:5433` |
| 2 | `source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`), then `fastapi dev app/main.py` | http://127.0.0.1:8000/docs — every endpoint, try them out |
| 3 | `cd web`, then `npm run dev` | **http://localhost:3000** — the admin console |

The first `docker compose up` creates the tables and loads the seed data from `sql/` (a few seconds).
Port 5433 is deliberate, so it can't clash with a PostgreSQL you may already run on 5432.

In the admin console: pick a store and use **±1** or **Adjust…** to change stock; edit products, specs and
prices; create promotions. When the database refuses something (stock below zero, staff from another store,
a sale price above the base price…) the page shows which rule refused it, e.g. `br03_inventory_qty_nonneg`.

## Everyday commands

| Task | Command |
|---|---|
| Stop the database (data is kept) | `docker compose down` |
| **Reset** the database to the seed data | `docker compose down -v && docker compose up -d` |
| SQL shell | `docker compose exec db psql -U jbhifi -d jbhifi` |
| Run the tests (database must be up, venv active) | `pytest` |
| Regenerate the frontend's API types after changing the API (API running) | `cd web && npm run gen:api` |
| Check the frontend | `cd web && npm run typecheck && npm run lint && npm run build` |

`sql/*.sql` only run when the database volume is empty — **after editing anything in `sql/`, reset the
database** or you won't see the change. `pytest` never touches your data: it rebuilds a separate
`jbhifi_test` database from `sql/` on every run.

## Project layout

| Path | What's in it |
|---|---|
| `sql/` | `00_domains` → `01_tables` → `02_rules` (triggers) → `03_views` → `10_seed_reference`, run in that order |
| `app/` | FastAPI. `routers/` handle HTTP only; `services/` hold the SQL (one call = one transaction); `errors.py` turns a rule violation into a 409 whose `code` is the constraint name |
| `tests/` | `test_business_rules.py` (one test per BR), `test_transactions.py` (stock adjustments under concurrency), `test_api.py` |
| `web/` | Next.js admin console — see [`web/README.md`](web/README.md) |
| `doc/progress.md` | decisions, experiments and AI-use notes, newest first |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Sidebar says "API unreachable", pages stay on "Loading…" | Start the API (terminal 2). |
| API errors: `connection refused` / `KeyError: 'POSTGRES_HOST'` | Start the database (terminal 1) / create `.env` from `.env.example`. |
| `fastapi: command not found` | Activate the virtual environment first. |
| Changed `sql/` but nothing changed | Reset the database (`docker compose down -v && docker compose up -d`). |
| `port is already allocated` on 5433 | Another container uses it: `docker ps`, stop it. |
| Windows: `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `.venv\Scripts\activate.bat` in cmd. |

## Working on it

- SQL is hand-written with psycopg2 (no ORM); values always go through `%s` parameters, never f-strings.
- Business rules live in the database; name their constraints `brNN_<what>` and add a test that breaks each
  rule in `tests/test_business_rules.py`.
- Don't `pip freeze` into `requirements.txt`; it's hand-written so it installs on Windows too.
- Record any GenAI use in `doc/progress.md`.

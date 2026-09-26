# web — storefront and store admin (Next.js)

Two apps in one Next.js project, on the same FastAPI backend:

- **Storefront** at `/` — what customers see. The home page is live: current deals with stock at your store,
  shop by category, stores near you. A demo "Signed in as" picker and a "My store" picker stand in for login.
  The other customer pages are **reserved**: each shows what it will do, which requirements (R#), rules (BR#)
  and transaction it covers, the API it needs (existing or to build) and the owner slice. Their content comes
  from `src/lib/shop-pages.ts` — build a page by replacing its `<ReservedPage>`.
- **Store admin** at `/admin` — stock per store with ± adjustments, products (prices, specs), promotions.

Every rule is enforced by the database; when it refuses a request, the page shows the constraint that fired
(e.g. `br03_inventory_qty_nonneg`).

## Run

From the repo root, in three terminals:

```bash
docker compose up -d                                   # PostgreSQL on :5433
source .venv/bin/activate && fastapi dev app/main.py   # API on :8000 (docs at /docs)
cd web && npm install && npm run dev                   # http://localhost:3000 and /admin
```

The browser only talks to Next.js. `next.config.ts` forwards `/api/*` to FastAPI (set `API_URL` to point
elsewhere), so there is no CORS setup.

## Demo data

To demonstrate orders and returns rather than an empty storefront, build the seeded demo database and point
the API at it (`doc/demo.md` has the full walkthrough and the scenario list):

```bash
python scripts/seed_demo.py --database jbhifi_demo --create --seed 9120
POSTGRES_DB=jbhifi_demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd web && npm run dev
```

Then use **Signed in as** and **My store** in the storefront: Alice, Ben, Mei and Tom each have orders and
returns at a different stage, and Sydney CBD has one product deliberately out of stock.

## After changing the API

With the API running, `npm run gen:api` regenerates `src/lib/api/schema.d.ts` — the TypeScript types for
every endpoint, read from FastAPI's OpenAPI spec. Commit the regenerated file.

## Layout

| Path | What |
|---|---|
| `src/app/(shop)/` | storefront pages; `(shop)` is a route group, so it adds nothing to the URL |
| `src/app/(shop)/page.tsx` | the home page (live) |
| `src/app/(shop)/{products,cart,checkout,orders,returns,stores,account}` | reserved customer pages |
| `src/app/admin/` | store admin: `inventory`, `products`, `promotions` |
| `src/components/shop/` | storefront header, shop context (demo customer, my store), `ReservedPage` |
| `src/lib/shop-pages.ts` | the customer page list: what each does, what it covers, the API it needs |
| `src/lib/api/client.ts` | typed client (`openapi-fetch`) and `ApiError` (`code` = database constraint name) |
| `src/lib/use-load.ts` | load one resource in a client component: `isCurrent`, and `setData(key, update)` that a late response cannot aim at another store or product |
| `src/components/ui.tsx` | small UI pieces: buttons, fields, cards, modal, error box |
| `src/test/`, `vitest.config.ts` | unit tests (`npm run test:unit`) for that shared state and the dialogs |

Checks: `npm run typecheck`, `npm run lint`, `npm run test:unit`, `npm run build`.

`npm run test:unit` runs Vitest with React Testing Library in jsdom over `src/**/*.test.tsx`. They cover
what a build cannot see: an answer that arrives after the viewer switched store, product or filter, a
same-key refresh, a rejected request, and the keyboard behaviour of the shared dialog. Network responses
are mocked at the API-client boundary and resolved by hand, so the race itself is real.

This is Next.js 16: read `AGENTS.md` before relying on what you know about older versions.

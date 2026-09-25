# web — store admin (Next.js)

Phase 1 admin console on the JB Hi-Fi database: stock per store with ± adjustments, products (prices, specs)
and promotions. Every rule is enforced by the database; when it refuses a request, the page shows the
constraint that fired (e.g. `br03_inventory_qty_nonneg`).

## Run

From the repo root, in three terminals:

```bash
docker compose up -d                                   # PostgreSQL on :5433
source .venv/bin/activate && fastapi dev app/main.py   # API on :8000 (docs at /docs)
cd web && npm install && npm run dev                   # this app on http://localhost:3000
```

The browser only talks to Next.js. `next.config.ts` forwards `/api/*` to FastAPI (set `API_URL` to point
elsewhere), so there is no CORS setup.

## After changing the API

With the API running, `npm run gen:api` regenerates `src/lib/api/schema.d.ts` — the TypeScript types for
every endpoint, read from FastAPI's OpenAPI spec. Commit the regenerated file.

## Layout

| Path | What |
|---|---|
| `src/app/inventory` | stock at one store, ±1 buttons, adjust dialog, recent adjustments |
| `src/app/products`, `src/app/products/[id]` | catalogue list; edit details and specs; stock by store |
| `src/app/promotions` | list, create and delete promotions |
| `src/lib/api/client.ts` | typed client (`openapi-fetch`) and `ApiError` (`code` = database constraint name) |
| `src/lib/use-load.ts` | load data in a client component, keep the old data while reloading |
| `src/components/ui.tsx` | small UI pieces: buttons, fields, cards, modal, error box |

Checks: `npm run typecheck`, `npm run lint`, `npm run build`.

This is Next.js 16: read `AGENTS.md` before relying on what you know about older versions.

# web — storefront and store admin (Next.js)

Two apps in one Next.js project, on the same FastAPI backend:

- **Storefront** at `/` — what customers see. The home page is live: current deals with stock at your store,
  shop by category, stores near you. Clerk's sign-in controls sit in the header; a "My store" picker chooses
  the store whose stock is shown.
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
| `src/components/shop/` | storefront header (Clerk sign-in), shop context (signed-in customer, my store), `ReservedPage` |
| `src/proxy.ts` | Clerk's proxy: signed-out visitors to `/admin` go to sign-in (who may do what is the API's call) |
| `src/components/api-auth.tsx`, `src/lib/me.ts` | each API request carries the Clerk session token; `useMe()` = who the API says you are |
| `src/components/admin/staff-gate.tsx` | the admin is for staff: `useStaff()`, `canEditCatalogue()` |
| `src/lib/shop-pages.ts` | the customer page list: what each does, what it covers, the API it needs |
| `src/lib/api/client.ts` | typed client (`openapi-fetch`) and `ApiError` (`code` = database constraint name) |
| `src/lib/use-load.ts` | load data in a client component, keep the old data while reloading |
| `src/components/ui.tsx` | small UI pieces: buttons, fields, cards, modal, error box |

Checks: `npm run typecheck`, `npm run lint`, `npm run build`.

This is Next.js 16: read `AGENTS.md` before relying on what you know about older versions.

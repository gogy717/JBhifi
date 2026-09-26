# Browser journeys (`npm run test:e2e`)

Playwright drives the real storefront and `/admin` in Chromium. The suite is the delivery check of T18:
it proves the journeys end to end, and it is the only place that exercises the browser, the Next proxy,
the API and the database together.

```bash
cd web
npm run test:e2e                                  # builds its own database, starts the stack, runs everything
npx playwright test e2e/returns.spec.ts           # one journey
npx playwright test -g "delivery checkout"        # one test
npx playwright show-report                        # after a failure
```

## It never touches your stack

`playwright.config.ts` starts two servers of its own and does not reuse the developer's:

| Piece | Where it comes from |
|---|---|
| Database | `jbhifi_e2e_demo`, dropped and rebuilt from `sql/*.sql` plus the documented demo scenarios (`scripts/seed_demo.py --create --seed 9120`) before the tests run. The seeder refuses any name that is not clearly disposable, so `jbhifi` cannot be dropped. |
| API | `uvicorn` on `127.0.0.1:8100` with `POSTGRES_DB=jbhifi_e2e_demo` |
| Web | `next dev` on `127.0.0.1:3100` with `API_URL=http://127.0.0.1:8100` and `NEXT_DIST_DIR=.next/e2e` |

`NEXT_DIST_DIR` matters: `next dev` allows one server per build directory, so the browser suite gets its
own and can run while a developer's `npm run dev` is up. `E2E_API_PORT`, `E2E_WEB_PORT`, `E2E_DATABASE`
and `E2E_PYTHON` override the defaults; `E2E_PYTHON` defaults to `.venv/Scripts/python.exe` on Windows and
`.venv/bin/python` elsewhere.

## What the specs cover

| File | Journey |
|---|---|
| `purchase.spec.ts` | catalogue search and a product page; the cart; delivery checkout; Click & Collect with a lost reply retried under the same key (one order, not two); staff fulfilment to `delivered`; staff cancellation with the stock back and a refund recorded |
| `returns.spec.ts` | the return waiting at the Melbourne Central desk (receive → process → refunded); a customer requesting a return, limited to what is left; a rejection, which is final |
| `recovery.spec.ts` | the seeded empty store (`409 out_of_stock`), a product retired while it sits in the cart, an address retired between the cart and the checkout |
| `session-isolation.spec.ts` | a guest; switching customer; another customer's order by URL is `not_found`; a staff session on the storefront is a guest, never a customer |
| `layout.spec.ts` | every customer route at a phone width, with no "Reserved — not built yet" copy left |

Assertions are made twice where it matters: in the browser (what a customer sees) and against the API
(what the database actually holds). Test setup that needs an awkward state uses the API as the person
entitled to create it — an isolated `request` context, never the browser's cookies.

## CI

`.github/workflows/ci.yml` runs the backend suite, the web checks, an OpenAPI-types diff and these
journeys against a PostgreSQL 18 service. Locally the suite takes under a minute once the database is
built; the first run also downloads Chromium (`npx playwright install chromium`).

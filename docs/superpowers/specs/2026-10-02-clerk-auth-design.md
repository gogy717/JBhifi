# Clerk authentication — design

Status: approved in conversation on 2026-10-02 (sections 1–4). Branch: `ethan/clerk-auth`, from `main` at `6177788`.

## 1. Goal and what changes in the plan

Every caller of the API is identified by a real sign-in, and the database decides who that person is
(customer or staff), which store they work at and what they may do. The goal is **Phase 2 readiness**:
production-grade sign-in that will not be replaced when real customers use the storefront, and that a
future mobile app or customer-service agent can use unchanged.

This supersedes two parts of `.claude/plan.md`:

- §2 listed "real authentication" as Phase 2. It moves into Phase 1.
- §7 described a demo login (a signed cookie issued by the API). It is replaced by Clerk, with the same
  idea kept: one `Actor` dependency, and services authorise explicitly.

Decisions taken (with the reason):

| Decision | Choice | Why |
|---|---|---|
| Provider | Clerk (hosted) | Phase 2 readiness; supports Next.js 16 `proxy.ts` |
| Who signs in | Customers **and** staff, through Clerk | One mechanism; staff identity is authenticated too |
| Where roles live | In our database (`staff`, `store.manager_id`) | Permissions stay with the data they protect |
| How FastAPI trusts a caller | It verifies the Clerk token itself (approach A) | The API is secure when called directly, by any client |
| Demo switching | One seeded Clerk dev account per persona, two browser profiles | Only real sign-in exists; nothing extra to build or explain |

## 2. Architecture

```
browser (Next.js + Clerk components)
   │  every API call: Authorization: Bearer <Clerk session token>   (fresh from Clerk's getToken())
   ▼
Next.js /api/* rewrite (unchanged) ──▶ FastAPI
                                          app/identity.py   verify the token → subject        (only Clerk-aware file)
                                          app/auth.py       subject → user_account → Actor    (provider-neutral)
                                          services          require_*(actor, …) before acting
                                          ▼
                                       PostgreSQL: user_account (BR19), customer, staff, store
```

Next.js `proxy.ts` only does an *optimistic* check (signed-out visitors to `/admin` go to sign-in). The
Next.js 16 docs say the same: real checks belong "as close as possible to your data source" — here, the API
and the database.

## 3. Data model

One new table and one new business rule. Nothing else in the schema changes.

```sql
CREATE TABLE user_account (
    auth_subject TEXT        NOT NULL,   -- the verified token's `sub` (Clerk: "user_2ab…")
    customer_id  INT,
    staff_id     INT,
    linked_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_account_pk PRIMARY KEY (auth_subject),
    CONSTRAINT br19_account_one_customer UNIQUE (customer_id),
    CONSTRAINT br19_account_one_staff    UNIQUE (staff_id),
    CONSTRAINT user_account_customer_fk  FOREIGN KEY (customer_id) REFERENCES customer (customer_id),
    CONSTRAINT user_account_staff_fk     FOREIGN KEY (staff_id)    REFERENCES staff (staff_id),
    CONSTRAINT br19_account_customer_xor_staff CHECK ((customer_id IS NULL) <> (staff_id IS NULL))
);
```

**BR19** — A sign-in identity belongs to exactly one customer or exactly one staff member, and each customer
or staff member has at most one sign-in identity. Mechanism: `CHECK` + two `UNIQUE` + `PRIMARY KEY`.

- ER: `user_account` is an entity in an exclusive, optional 1:1 relationship with `customer` and with `staff`.
- A separate table rather than an `auth_subject` column on both `customer` and `staff`: with two columns,
  "one identity cannot be both a customer and a staff member" spans two tables and would need a trigger;
  here it is a single-row `CHECK`.
- The key is the token's subject, not anything Clerk-specific, so a later provider change is a re-link, not a
  schema change.
- Lives in `sql/01_tables.sql` after `staff`. The existing dev database gets it with a one-off `CREATE TABLE`
  through `psql` (no `docker compose down -v`); fresh databases get it from `sql/` as usual.

## 4. Backend

### 4.1 `app/identity.py` (new; the only file that knows about Clerk)

- `verify_token(token: str) -> str` returns the subject, or raises `ApiError(401, "invalid_token", …)`.
  Uses PyJWT: RS256 signature against the key from `{CLERK_ISSUER}/.well-known/jwks.json` (`PyJWKClient`,
  cached in-process), and checks `exp`, `nbf`, `iss == CLERK_ISSUER` and `azp ∈ AUTH_AUTHORIZED_PARTIES`
  (a missing `azp` is rejected). Any decoding failure — garbage, non-ASCII, wrong segments — is a 401, never a 500.
- `fetch_profile(subject: str) -> Profile(email, verified, full_name)`, called only when linking a new
  subject. `GET https://api.clerk.com/v1/users/{subject}` with `CLERK_SECRET_KEY`, 5 s timeout; the email is
  the primary address, `verified` is its verification status, `full_name` is first + last name (falling back
  to the email's local part). Network or Clerk errors raise `ApiError(503, "identity_provider_unavailable", …)`.

PyJWT rather than Clerk's Python SDK: it is small, standard, and verifies any OIDC provider's tokens, which is
what keeps a provider switch to this one file.

### 4.2 `app/auth.py` (new; provider-neutral; ported and trimmed from the `Yuhang_Zheng` branch)

- `Actor` (frozen dataclass): `kind` ("customer" | "staff"), `id`, `display_name`, `store_id`, `store_name`,
  `staff_type`, `runs_store`; properties `is_support`, `is_manager`.
- `current_actor(request, cur) -> Actor | None`: no `Authorization` header → `None` (guest). A header that is
  not `Bearer <token>` → 401 `invalid_token`. Otherwise `verify_token` → look up `user_account` → link if
  absent (4.3) → load the customer or staff row (staff with store name and `store.manager_id = staff_id`).
  `CurrentActor = Annotated[Actor | None, Depends(current_actor)]`.
- Only the `Authorization: Bearer` header is accepted, never Clerk's `__session` cookie: a cookie is sent
  automatically by the browser, which would make mutations forgeable cross-site (CSRF). With a header there is
  nothing to forge, so no Origin-check middleware is needed.
- Permission helpers, each raising `ApiError` (401 `not_signed_in` when `actor is None`):
  - `require_actor(actor)`
  - `require_customer(actor)` → 403 `customer_only` — added with the order endpoints, its first caller
    (nothing in this change needs it)
  - `require_customer_self(actor, customer_id)` → that customer, or support; another customer → 403
    `not_your_account`; store staff → 403 `support_only`
  - `require_staff(actor)` → 403 `staff_only`
  - `require_support(actor)` → 403 `support_only`
  - `require_store_staff(actor, store_id)` → staff of that store (not support); else 403 `staff_only` /
    `store_staff_only` / `other_store`
  - `require_store_or_support_reader(actor, store_id)` → that store's staff or support; else 403 `other_store`
  - `require_catalogue_writer(actor)` → a store manager or support; else 403 `staff_only` / `manager_only`
- `401`/`403` join `ERROR_RESPONSES` in `app/errors.py` so they appear in OpenAPI and the generated client.

### 4.3 Linking a new subject (inside the request's transaction)

1. `SELECT … FROM user_account WHERE auth_subject = %s` — found → done (no Clerk call).
2. `fetch_profile(subject)`. Not verified → 403 `email_not_verified`. Email lower-cased (BR01 stores lower case).
3. A `staff` row with that email → link to it. Staff rows are only ever created by us, so a stranger cannot
   become staff by signing up.
4. Else a `customer` row with that email → link to it (the seeded customers).
5. Else `INSERT INTO customer (email, full_name) … ON CONFLICT ON CONSTRAINT br01_customer_email_unique DO
   NOTHING RETURNING customer_id`; if nothing returned, read the customer by email (another request created
   it first). Link to it — self-service sign-up.
6. `INSERT INTO user_account … ON CONFLICT (auth_subject) DO NOTHING`, then re-read by subject. Two
   simultaneous first requests for the same subject end with one link.

The link commits with the request. If the request then fails, the link rolls back with it and the next
request links again (one extra Clerk call) — acceptable, and keeps "one request = one transaction".
The seeded staff and customer emails do not overlap, so step 3 vs 4 never conflicts in practice.

### 4.4 `GET /api/v1/me` (new)

Signed in → `200` with the actor (`kind`, `id`, `display_name`, `store_id`, `store_name`, `staff_type`,
`runs_store`). Guest → `401 not_signed_in`.

### 4.5 Who may call each existing endpoint

Checks live in the **services** (`plan.md` §7: services authorise explicitly), so a Phase 2 agent calling a
service as a customer gets the same checks. Routers pass `actor` through.

| Endpoint | Allowed | Change from `main` |
|---|---|---|
| `GET /me` | any signed-in actor | new |
| `GET /stores`, `/categories`, `/brands`, `/products`, `/products/{id}`, `/promotions`, `/stores/{id}/inventory` | everyone, incl. guests | none (R1–R3) |
| `GET /staff` | staff | was public |
| `GET /customers` | support | was public |
| `GET /customers/{id}` | that customer, or support | was public |
| `POST /stores/{id}/inventory/{pid}/adjustments` | staff of that store | `staff_id` removed from the body (`extra="forbid"` rejects it); the actor is the adjuster; BR18's FK still backs it |
| `GET /stores/{id}/adjustments` | that store's staff, or support | was public |
| `POST /products`, `PATCH /products/{id}`, `PUT /products/{id}/specs`, `POST /promotions`, `DELETE /promotions/{id}` | a store manager or support | was public |
| `GET /health` | everyone | none |

### 4.6 Configuration

| Variable | Where | Value |
|---|---|---|
| `CLERK_SECRET_KEY` | `.env` (FastAPI) and `web/.env.local` (Next.js) | `sk_test_…`, secret |
| `CLERK_ISSUER` | `.env` | the Frontend API URL, `https://<name>.clerk.accounts.dev` |
| `AUTH_AUTHORIZED_PARTIES` | `.env` | `http://localhost:3000,http://127.0.0.1:3000` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `web/.env.local` | `pk_test_…` |

`.env.example` lists the backend names with placeholders. `requirements.txt` gains `pyjwt[crypto]`, and
`httpx2` becomes `httpx` (now imported directly; `httpx2` was a different package).

## 5. Frontend (`web/`)

| File | Change |
|---|---|
| `src/proxy.ts` (new, via `clerk init`) | `clerkMiddleware()`; `/admin(.*)` requires sign-in (redirect); everything else public; matcher includes `'/(api\|trpc)(.*)'` then `'/__clerk/:path*'`. Never checks roles. |
| `src/app/layout.tsx` | `<ClerkProvider>` inside `<body>` (Clerk's rule). |
| `src/app/sign-in/[[...sign-in]]/page.tsx`, `src/app/sign-up/[[...sign-up]]/page.tsx` (new) | Clerk `<SignIn/>` / `<SignUp/>`, outside the shop and admin layouts. |
| `src/lib/api/client.ts` | openapi-fetch `onRequest` middleware adds `Authorization: Bearer <token>` from a registered token getter; on `401 invalid_token`, one retry with a fresh token. |
| `src/components/api-auth.tsx` (new) | Client component inside `ClerkProvider` that registers `useAuth().getToken` with the client. |
| `src/lib/me.ts` (new) | `useMe()`: waits until Clerk has loaded; signed in → `GET /me`; returns the actor (or guest). Identity-dependent requests wait for it, so a guest view never flashes first. |
| `src/components/shop/header.tsx`, `src/components/shop/context.tsx` | The "Signed in as" picker becomes Clerk's sign-in / sign-up buttons or `<UserButton/>` plus the name from `/me`. `customerId` comes from `/me`, not `localStorage`. The preferred-store picker stays in `localStorage`. |
| `src/components/sidebar.tsx`, `src/app/admin/**` | Sidebar shows the actor and their store; non-staff see a "Staff only" panel. Inventory: staff picker removed; store staff are fixed to their store; support may browse any store with no adjust form. Products/promotions: edit controls only for managers and support. |

After the backend changes, `npm run gen:api` regenerates `src/lib/api/schema.d.ts`.

Not ported from the `Yuhang_Zheng` branch: its cookie session (`session.ts`, session bar, `ensureSession`),
where tabs signed each other out. Clerk shares one session across tabs of a browser profile — hence two
profiles for the demo.

## 6. Testing

Backend (pytest, existing `jbhifi_test` harness). Tests never call Clerk:

- A session-scoped fixture generates an RSA key pair; tests replace the key lookup in `app/identity.py` with
  its public key and mint their own tokens (`sub`, `iss`, `azp`, `exp`, `nbf` as needed).
- `fetch_profile` is replaced by a fake that returns a chosen profile or raises 503.
- Helpers `as_customer(email)` / `as_staff(staff_id)` return headers carrying a token for a fixed test subject,
  which links to that seeded row through the normal first-sign-in path.

| File | Covers |
|---|---|
| `tests/test_identity.py` | valid → subject; expired, future `nbf`, wrong signature, wrong `iss`, wrong or missing `azp`, garbage, non-ASCII → 401 `invalid_token`; no header → guest; non-Bearer header → 401 |
| `tests/test_linking.py` | staff email → staff; seeded customer email → that customer; new email → new customer (lower-cased, name from profile); unverified → 403 and no rows; Clerk down → 503 and no rows; second request does not call `fetch_profile`; two concurrent first requests → one link |
| `tests/test_business_rules.py` | BR19: both / neither → `br19_account_customer_xor_staff`; a customer linked twice → `br19_account_one_customer`; a staff member linked twice → `br19_account_one_staff` |
| `tests/test_permissions.py` | one parametrised matrix over §4.5 × {guest, customer, other customer, store staff, other store's staff, manager, support} → expected status |
| existing `tests/test_api.py`, `tests/test_transactions.py` | updated to call protected endpoints through `as_staff` / `as_customer`; stock adjustment takes the adjuster from the token, a body `staff_id` is a 422, BR18 still applies |

Frontend: `npm run typecheck` and `npm run lint`, then a manual walk-through in the browser as each persona.
(`main` has no frontend test runner; adding one is out of scope for this change.)

## 7. Build order (one commit per step; `pytest` green after each)

1. **Scaffold** — `clerk init --app app_3K6CvFSe0TUt2S0M7ijbKnyKNDm` in `web/`; check the proxy matcher;
   `clerk doctor`; sign-up works in the browser (API untouched).
2. **Database** — `user_account` + BR19 in `sql/01_tables.sql`; BR19 tests; apply to the dev database with
   one `CREATE TABLE`; update `.claude/plan.md` (§2 scope, §3 BR19, §4 entity, §7 actor) with a pointer here.
3. **Identity** — `app/identity.py`, `app/auth.py`, linking, `GET /me`; test-first.
4. **Permissions** — wire §4.5 into services and routers; update existing tests; `.env.example`;
   `requirements.txt`.
5. **Frontend** — token hand-off, `useMe`, header/sidebar controls, admin changes; `npm run gen:api`;
   typecheck and lint.
6. **Personas and walk-through** — `scripts/clerk_personas.py` creates Clerk dev accounts for the personas
   below; sign in as each and check what they can see and do.

| Persona | Row | Shows |
|---|---|---|
| Alice Morgan | customer, `alice.morgan@example.com` | storefront as a customer; her own account only |
| Aiden Chen | staff 14, Sydney CBD | stock adjustment at his store only; no catalogue editing |
| Olivia Nguyen | staff 1, manager of Sydney CBD | as Aiden, plus catalogue and promotions |
| Nora Fitzgerald | staff 40, support | reads across stores and customers; no stock adjustment |

## 8. Risks and items to verify during implementation

- **Persona emails.** Staff emails use the reserved `.example` TLD (`@jbhifi.example`). If Clerk rejects
  them, `scripts/clerk_personas.py` creates the Clerk user with an address Clerk accepts and inserts the
  `user_account` link directly (bypassing email linking for these four personas only).
- **Verified status of Backend-API-created users** — expected to be verified; if not, the script marks them
  verified through the Backend API, or uses the direct-link fallback above.
- **The `/api/*` rewrite behind `proxy.ts`** — confirm `clerkMiddleware` on `/(api|trpc)(.*)` does not
  interfere with the rewrite to FastAPI.
- **Internet at the showcase** — Clerk is hosted; the Week 12/13 venue needs a network connection.
- **Dependence on Clerk** — pricing at scale not checked; isolated to `app/identity.py` and the web sign-in UI.

## 9. Out of scope (later)

Clerk webhooks (account deletion, email changes) once deployed with a public URL; machine-to-machine tokens
and API keys for the Phase 2 agent; Clerk Organizations; MFA policy; a frontend test runner; order and return
endpoints (built after this, using these helpers from the start).

# Clerk Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every API caller is identified by a Clerk sign-in, and the database decides whether they are a customer or staff, which store they work at, and what they may do.

**Architecture:** Next.js renders Clerk's sign-in UI and sends a fresh Clerk session token as `Authorization: Bearer` on every `/api/*` call. FastAPI verifies the token itself (PyJWT against Clerk's public keys, `app/identity.py` — the only Clerk-aware file), maps the token's subject to a customer or staff row through the new `user_account` table (BR19, `app/auth.py`), and the services check permissions before acting.

**Tech Stack:** PostgreSQL 18, FastAPI + psycopg2 (hand-written SQL), PyJWT[crypto], httpx; Next.js 16.3.6, React 19, `@clerk/nextjs`, openapi-fetch.

**Spec:** `docs/superpowers/specs/2026-10-02-clerk-auth-design.md`

## Global Constraints

- Work only in the worktree `/Users/ethan/Dev/Course/comp9120/JBhifi/.claude/worktrees/ethan+clerk-auth` (branch `ethan/clerk-auth`). Run commands from its root unless a step says `web/`.
- Python is the main checkout's venv. Every Python command starts with `PY=/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/python` (the worktree refuses `source`). Tests: `$PY -m pytest -q -p no:cacheprovider`.
- Database: reach the container with `docker exec -i jbhifi-db …`, never `docker compose …` from the worktree (a different directory name = a different compose project). Never run `docker compose down -v`.
- Hand-written SQL through psycopg2 with `%s` parameters; `psycopg2.sql` for identifiers; never f-strings or `%` formatting in SQL.
- Every constraint is named; business rules are `brNN_<what>`; every BR has a test in `tests/test_business_rules.py` that breaks it and asserts the name.
- Route handlers using psycopg2 are `def`, never `async def`. Keep `DbCursor = Annotated[..., Depends(get_cursor, scope="function")]`.
- Pydantic models check only shape (types, lengths, `extra="forbid"`), never business rules.
- Permission checks live in the services (`plan.md` §7). Order inside a service: permission check first, then existence (so a refused caller learns nothing about which ids exist).
- Only `Authorization: Bearer` is accepted; the API never reads Clerk's `__session` cookie.
- Secrets: never print, paste or commit `CLERK_SECRET_KEY`. `.env` and `web/.env.local` are gitignored; check names with `sed -E 's/=.*/=<set>/' <file>`.
- Next.js 16: read `web/node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md` before touching `proxy.ts`. `<ClerkProvider>` goes inside `<body>`. The proxy matcher includes `'/(api|trpc)(.*)'` then `'/__clerk/:path*'`.
- After any API change used by the web app: start the API, then `cd web && npm run gen:api`, and commit `web/src/lib/api/schema.d.ts`.
- Clerk application id: `app_3K6CvFSe0TUt2S0M7ijbKnyKNDm`.
- Commit messages: plain sentences prefixed `Auth:`; no `Co-Authored-By` or "Generated with" lines.

## Review Focus

The five inputs most likely to bite a real user that the spec implies but does not spell out:

1. A browser on `http://127.0.0.1:3000` (its token's `azp` differs from `localhost`) must be signed in normally — pinned by `test_either_configured_origin_is_accepted` (Task 3).
2. Clerk's key server unreachable while checking a token must be a `503 identity_provider_unavailable`, not a 500 — pinned by `test_an_unreachable_key_server_is_a_503` (Task 3).
3. A provider email in mixed case for an existing customer must link to that customer, not create a duplicate or a 409 — pinned by `test_an_existing_customer_email_links_in_any_case` (Task 4).
4. A provider email the database refuses (BR01 format, e.g. `someone@localhost`) must be a clean 409 with nothing written — pinned by `test_an_email_the_database_refuses_is_a_409_and_nothing_is_written` (Task 4).
5. Someone not allowed asking about a store or customer that does not exist must get 403, not 404 (no probing which ids exist) — pinned by the `/customers/999999` and `/stores/99/...` rows of `test_who_may_call_what` (Task 5).

---

### Task 1: Clerk in the web app (scaffold, proxy, sign-in pages, keys)

**Files:**
- Modify (via `clerk init`): `web/package.json`, `web/package-lock.json`
- Create: `web/src/proxy.ts`
- Modify: `web/src/app/layout.tsx`
- Create: `web/src/app/sign-in/[[...sign-in]]/page.tsx`, `web/src/app/sign-up/[[...sign-up]]/page.tsx`
- Local only (gitignored): `web/.env.local` (written by `clerk init`), `.env` (three lines appended)

**Interfaces:**
- Consumes: nothing.
- Produces: `@clerk/nextjs` installed; `<ClerkProvider>` around the whole app; `/sign-in`, `/sign-up`; `/admin(.*)` requires sign-in; backend `.env` has `CLERK_SECRET_KEY`, `CLERK_ISSUER`, `AUTH_AUTHORIZED_PARTIES`.

- [ ] **Step 1: Read the Next.js 16 proxy guide**

Read `web/node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md` (Proxy replaces Middleware; default or named `proxy` export; "optimistic checks" only).

- [ ] **Step 2: Initialise Clerk in `web/`**

```bash
cd web && clerk --version && clerk init --help
clerk init --app app_3K6CvFSe0TUt2S0M7ijbKnyKNDm
```

Use any non-interactive flag `--help` lists (e.g. `--yes`) if the command prompts. Expected: detects Next.js and npm, installs `@clerk/nextjs`, writes the publishable and secret keys to `web/.env.local`, and adds a provider and a proxy file.

- [ ] **Step 3: Inspect what it changed**

```bash
cd web && git status --short && git diff --stat && ls src/proxy.ts proxy.ts 2>&1
sed -E 's/=.*/=<set>/' .env.local
grep -c "export declare const Show\|Show:" node_modules/@clerk/nextjs/dist/types/index.d.ts
```

Expected: `.env.local` lists `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<set>` and `CLERK_SECRET_KEY=<set>`. If the proxy was created at `web/proxy.ts`, move it: `git mv proxy.ts src/proxy.ts` (or `mv` if untracked) — with a `src/` directory it must sit next to `app/`. If the `Show` grep prints `0`, note it: Task 6 then uses `SignedIn`/`SignedOut` instead of `<Show when=…>`. Revert any other file `clerk init` touched that this task does not list (e.g. a header it injected into a page) with `git checkout -- <file>`.

- [ ] **Step 4: Write `web/src/proxy.ts`**

```ts
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// An optimistic check only: signed-out visitors to the store admin are sent to sign-in. Who may do what is
// decided by the API (app/auth.py) and the database, never here — the Next.js docs say the same.
const isAdmin = createRouteMatcher(["/admin(.*)"]);

export default clerkMiddleware(async (auth, request) => {
  if (isAdmin(request)) await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files, unless found in search params.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/:path*",
  ],
};
```

- [ ] **Step 5: Write `web/src/app/layout.tsx`**

```tsx
import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";

import "./globals.css";

// No `title` here: every page renders its own <title> (React 19), and a metadata title would come first in
// <head> and win on every page.
export const metadata: Metadata = {
  description: "COMP9120 prototype: a storefront and a store admin on the JB Hi-Fi database",
};

// The storefront (app/(shop)) and the store admin (app/admin) each bring their own layout. Clerk's provider
// sits inside <body> (Clerk's rule for the App Router); sign-in and sign-up have their own pages.
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-neutral-50 text-neutral-900">
        <ClerkProvider signInUrl="/sign-in" signUpUrl="/sign-up">{children}</ClerkProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 6: Write the sign-in and sign-up pages**

`web/src/app/sign-in/[[...sign-in]]/page.tsx`:

```tsx
import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <title>Sign in · JB Hi-Fi</title>
      <SignIn />
    </main>
  );
}
```

`web/src/app/sign-up/[[...sign-up]]/page.tsx`:

```tsx
import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <title>Create an account · JB Hi-Fi</title>
      <SignUp />
    </main>
  );
}
```

- [ ] **Step 7: Give the backend its three settings (nothing is printed)**

From the worktree root. The issuer is the Frontend API URL, which is base64-encoded inside the (public) publishable key:

```bash
grep '^CLERK_SECRET_KEY=' web/.env.local >> .env
PY=/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/python
$PY - >> .env <<'EOF'
import base64, re
pk = re.search(r"^NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=(\S+)", open("web/.env.local").read(), re.M).group(1)
encoded = pk.split("_", 2)[2]
host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
print(f"CLERK_ISSUER=https://{host}")
EOF
echo 'AUTH_AUTHORIZED_PARTIES=http://localhost:3000,http://127.0.0.1:3000' >> .env
sed -E 's/=.*/=<set>/' .env
```

Expected: the names list now ends with `CLERK_SECRET_KEY=<set>`, `CLERK_ISSUER=<set>`, `AUTH_AUTHORIZED_PARTIES=<set>`. Also check `grep -c '^CLERK_ISSUER=https://.*clerk' .env` prints `1`.

- [ ] **Step 8: Static checks**

```bash
cd web && clerk doctor && npm run typecheck && npm run lint
```

Expected: `clerk doctor` reports no problems; typecheck and lint exit 0.

- [ ] **Step 9: Check it in the browser**

Start the API (worktree root, background): `/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/fastapi dev app/main.py`; start the web app: `cd web && npm run dev`. (Stop any API/web servers running from the main checkout first: same ports.)

1. http://localhost:3000 — the storefront still loads its stores and deals (proves the `/api/*` rewrite works behind the proxy).
2. http://localhost:3000/admin while signed out — redirected to `/sign-in`.
3. http://localhost:3000/sign-up — create a test account; after verification you are back on the site.

The storefront header still shows the old "Signed in as" picker — that is replaced in Task 6.

- [ ] **Step 10: Commit**

```bash
git status --short     # web/.env.local and .env must NOT appear
git add web/package.json web/package-lock.json web/src/proxy.ts web/src/app/layout.tsx \
  "web/src/app/sign-in" "web/src/app/sign-up"
git commit -m "Auth: Clerk sign-in and sign-up pages, and the admin behind sign-in"
```

---

### Task 2: `user_account` and BR19

**Files:**
- Modify: `sql/01_tables.sql` (insert after the `staff` table, before `CREATE TABLE category`)
- Modify: `tests/test_business_rules.py` (after the BR18 tests, before `# ---- views`)
- Modify (local only, gitignored): `/Users/ethan/Dev/Course/comp9120/JBhifi/.claude/plan.md`

**Interfaces:**
- Consumes: tables `customer`, `staff`.
- Produces: table `user_account(auth_subject TEXT PK, customer_id INT NULL UNIQUE FK, staff_id INT NULL UNIQUE FK, linked_at TIMESTAMPTZ)`; constraint names `br19_account_customer_xor_staff`, `br19_account_one_customer`, `br19_account_one_staff`.

- [ ] **Step 1: Write the failing BR19 tests**

Append to the BR18 section of `tests/test_business_rules.py`, just before the `# ---------------------------------------------------------------- views` line:

```python
# ---------------------------------------------------------------- BR19: sign-in identities

ACCOUNT = "INSERT INTO user_account (auth_subject, customer_id, staff_id) VALUES (%s, %s, %s)"


def test_br19_an_identity_is_a_customer_or_a_staff_member(customer, violates):
    violates("br19_account_customer_xor_staff", ACCOUNT, ("user_both", customer, 14))
    violates("br19_account_customer_xor_staff", ACCOUNT, ("user_neither", None, None))


def test_br19_one_identity_per_person(cur, customer, violates):
    cur.execute(ACCOUNT, ("user_first_customer", customer, None))
    violates("br19_account_one_customer", ACCOUNT, ("user_second_customer", customer, None))
    cur.execute(ACCOUNT, ("user_first_staff", None, 41))            # Omar Haddad, support
    violates("br19_account_one_staff", ACCOUNT, ("user_second_staff", None, 41))
```

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_business_rules.py -k br19`
Expected: 2 FAILED — the error is `relation "user_account" does not exist` (its `constraint_name` is `None`).

- [ ] **Step 3: Add the table to `sql/01_tables.sql`**

Insert after the closing `);` of `CREATE TABLE staff (...)`:

```sql
-- A sign-in identity (the verified token's subject — for Clerk, "user_2ab…") and who it is in our data.
-- BR19: exactly one customer or one staff member per identity, and at most one identity per person.
-- Roles are not stored here: they stay where they are (staff.staff_type, staff.store_id, store.manager_id).
CREATE TABLE user_account (
    auth_subject TEXT        NOT NULL,
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

- [ ] **Step 4: Run the tests to see them pass, then the whole suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_business_rules.py -k br19` → 2 passed.
Run: `$PY -m pytest -q -p no:cacheprovider` → all pass (42 + 2).

- [ ] **Step 5: Add the table to the dev database (no rebuild)**

```bash
docker exec jbhifi-db psql -U jbhifi -d jbhifi -tAc "SELECT to_regclass('user_account')"   # expect an empty line
sed -n '/^-- A sign-in identity/,/^);/p' sql/01_tables.sql \
  | docker exec -i jbhifi-db psql -U jbhifi -d jbhifi -v ON_ERROR_STOP=1
docker exec jbhifi-db psql -U jbhifi -d jbhifi -tAc "SELECT to_regclass('user_account')"   # expect user_account
```

- [ ] **Step 6: Bring `.claude/plan.md` up to date (local file, not committed)**

Edit `/Users/ethan/Dev/Course/comp9120/JBhifi/.claude/plan.md`:

1. §2, the "Out of scope for Phase 1" paragraph: replace `real authentication (Phase 1 uses a demo login to switch identities), ` with nothing, and add a sentence after the paragraph:
   `**Changed 2026-10-02:** real sign-in moved into Phase 1 — Clerk, with roles kept in our database (BR19). Design: docs/superpowers/specs/2026-10-02-clerk-auth-design.md on branch ethan/clerk-auth.`
2. §3 "Functional requirements": add the row
   `| R14 | Every caller signs in (customers and staff); the database decides who they are and what they may do |`
3. §3 "Business rules": add the row
   `| BR19 | A sign-in identity belongs to exactly one customer or one staff member; each person has at most one sign-in identity | \`CHECK\` + two \`UNIQUE\` + PK on \`user_account\` |`
4. §4 mermaid `erDiagram`: add the lines `customer ||--o| user_account : "signs in as"` and `staff ||--o| user_account : "signs in as"`, and an entity block:
   ```
       user_account {
           text auth_subject PK "token subject"
           int customer_id FK, UK "BR19"
           int staff_id FK, UK "BR19"
           timestamptz linked_at
       }
   ```
5. §4 "Entities" table: add `| \`user_account\` | \`auth_subject\`; \`UNIQUE (customer_id)\`, \`UNIQUE (staff_id)\` | exclusive optional 1:1 with customer **or** staff (BR19) |`
6. §7 "Actor" bullet: replace `Phase 1: demo login (signed cookie). Phase 2: real auth behind the same dependency.` with `Sign-in is Clerk: the API verifies the Bearer session token (app/identity.py) and maps its subject to a customer or staff row through user_account (app/auth.py).`

- [ ] **Step 7: Commit**

```bash
git add sql/01_tables.sql tests/test_business_rules.py
git commit -m "Auth: user_account links a sign-in identity to one customer or staff member (BR19)"
```

---

### Task 3: Verify Clerk session tokens (`app/identity.py`)

**Files:**
- Modify: `requirements.txt`
- Create: `app/identity.py`
- Create: `tests/auth_support.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_identity.py`

**Interfaces:**
- Consumes: `app.errors.ApiError(status, code, message, detail)`.
- Produces: `identity.verify_token(token: str) -> str` (subject; raises `ApiError(401, "invalid_token", …, {"reason": <str>})` or `ApiError(503, "identity_provider_unavailable", …)`); `identity.invalid(reason: str) -> ApiError`; `identity._jwks_client(url) -> object with .get_signing_key_from_jwt(token) -> obj with .key` (patched by tests). Tests: `tests.auth_support.token(subject, *, issuer, party, expires_in, valid_from, key) -> str`, `bearer(subject, **options) -> dict`, `ISSUER`, `PARTY`, `KEY`, `OTHER_KEY`, `OwnKeys`.

- [ ] **Step 1: Dependencies**

Replace `requirements.txt` with:

```
fastapi[standard]
psycopg2-binary
python-dotenv
pyjwt[crypto]            # checks the sign-in provider's session tokens (app/identity.py)
httpx                    # Clerk's Backend API (app/identity.py); also what starlette's TestClient imports

# tests
pytest
```

Run: `$PY -m pip install "pyjwt[crypto]" httpx && $PY -c "import jwt; print(jwt.__version__, jwt.exceptions.PyJWKClientConnectionError)"`
Expected: a 2.x version and the class name (no error).

- [ ] **Step 2: Test support — tokens signed by the tests' own key**

Create `tests/auth_support.py`:

```python
"""Sign-in for tests: tokens signed by a key the tests own, so no test ever calls Clerk.

conftest.py points app/identity.py at this key and sets the issuer and allowed origins below; a test then
mints whatever token it needs.
"""
import time
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://test-clerk.example"
PARTY = "http://localhost:3000"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)     # "somebody else's" key


class OwnKeys:
    """Stands in for PyJWKClient: the signing key of any token is the tests' own public key."""
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


def token(subject, *, issuer=ISSUER, party=PARTY, expires_in=60, valid_from=0, key=KEY) -> str:
    """A session token shaped like Clerk's (RS256; sub, iss, azp, iat, nbf, exp). None leaves a claim out."""
    now = int(time.time())
    claims = {"sub": subject, "iss": issuer, "azp": party, "iat": now, "nbf": now + valid_from,
              "exp": now + expires_in}
    return jwt.encode({name: value for name, value in claims.items() if value is not None}, key, algorithm="RS256")


def bearer(subject, **options) -> dict:
    return {"Authorization": f"Bearer {token(subject, **options)}"}
```

Add to `tests/conftest.py` — the imports at the top (after `from tests.support import TEST_DB, connect`, which must stay first) and a new session fixture after `test_database`:

```python
from app import identity
from tests.auth_support import ISSUER, PARTY, OwnKeys
```

```python
@pytest.fixture(scope="session", autouse=True)
def fake_clerk():
    """Tests never call Clerk: tokens are checked against the tests' own key (tests/auth_support.py)."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CLERK_ISSUER", ISSUER)
        patch.setenv("AUTH_AUTHORIZED_PARTIES", f"{PARTY},http://127.0.0.1:3000")
        patch.setattr(identity, "_jwks_client", lambda url: OwnKeys())
        yield
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_identity.py`:

```python
"""Token checks (app/identity.py): only a current token, signed by the provider for one of our sites."""
import jwt
import pytest

from app import identity
from app.errors import ApiError
from tests.auth_support import OTHER_KEY, token


def refusal(bad_token) -> str:
    """Assert the token is refused with 401 invalid_token, and return the reason."""
    with pytest.raises(ApiError) as caught:
        identity.verify_token(bad_token)
    assert (caught.value.status, caught.value.code) == (401, "invalid_token")
    return caught.value.detail["reason"]


def test_a_current_token_gives_its_subject():
    assert identity.verify_token(token("user_alice")) == "user_alice"


def test_either_configured_origin_is_accepted():
    assert identity.verify_token(token("user_alice", party="http://127.0.0.1:3000")) == "user_alice"


@pytest.mark.parametrize("options, reason", [
    ({"expires_in": -60}, "ExpiredSignatureError"),
    ({"valid_from": 60}, "ImmatureSignatureError"),
    ({"key": OTHER_KEY}, "InvalidSignatureError"),
    ({"issuer": "https://someone-else.example"}, "InvalidIssuerError"),
    ({"party": "https://evil.example"}, "azp"),
    ({"party": None}, "azp"),
])
def test_a_bad_token_is_refused(options, reason):
    assert refusal(token("user_alice", **options)) == reason


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "é.é.é"])
def test_garbage_is_refused_not_a_crash(garbage):
    refusal(garbage)


def test_an_unreachable_key_server_is_a_503(monkeypatch):
    class Unreachable:
        def get_signing_key_from_jwt(self, token):
            raise jwt.exceptions.PyJWKClientConnectionError("no network")

    monkeypatch.setattr(identity, "_jwks_client", lambda url: Unreachable())
    with pytest.raises(ApiError) as caught:
        identity.verify_token(token("user_alice"))
    assert (caught.value.status, caught.value.code) == (503, "identity_provider_unavailable")
```

- [ ] **Step 4: Run them to see them fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_identity.py`
Expected: collection error — `cannot import name 'identity' from 'app'` (conftest) / `ModuleNotFoundError: app.identity`.

- [ ] **Step 5: Write `app/identity.py`**

```python
"""Who signed this token? The one file that knows the API's sign-in provider is Clerk.

Clerk gives the signed-in browser a short-lived session token (a JWT). The API checks it against Clerk's
public keys — no shared secret, and no network call per request once the keys are cached — and takes only
its subject (`sub`) from it. Who that subject *is* (customer or staff, which store, what they may do) is
decided by our database, in app/auth.py. Moving to another OIDC provider changes this file only.
"""
import os
from functools import lru_cache

import jwt

from app.errors import ApiError


def _issuer() -> str:
    issuer = os.environ.get("CLERK_ISSUER", "").rstrip("/")
    if not issuer:
        raise ApiError(503, "auth_not_configured", "Sign-in is not configured: set CLERK_ISSUER in .env.")
    return issuer


def _authorized_parties() -> set[str]:
    raw = os.environ.get("AUTH_AUTHORIZED_PARTIES", "")
    return {party.strip().rstrip("/") for party in raw.split(",") if party.strip()}


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Fetches and caches the provider's public keys; refetches when a token names an unknown key."""
    return jwt.PyJWKClient(jwks_url)


def _signing_key(token: str):
    try:
        return _jwks_client(f"{_issuer()}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
    except jwt.exceptions.PyJWKClientConnectionError:
        raise ApiError(503, "identity_provider_unavailable",
                       "Can't reach the sign-in provider to check your sign-in. Try again shortly.") from None


def invalid(reason: str) -> ApiError:
    return ApiError(401, "invalid_token", "Your sign-in has expired or isn't valid. Sign in again.",
                    {"reason": reason})


def verify_token(token: str) -> str:
    """The token's subject if the provider signed it, for one of our sites, and it is current; else 401."""
    try:
        claims = jwt.decode(
            token, _signing_key(token), algorithms=["RS256"], issuer=_issuer(), leeway=5,
            options={"require": ["exp", "nbf", "sub", "iss"]},
        )
    except jwt.PyJWTError as error:            # bad signature, expired, wrong issuer, not a JWT at all, …
        raise invalid(type(error).__name__) from None
    if claims.get("azp") not in _authorized_parties():
        raise invalid("azp")                   # a token minted for some other site
    return claims["sub"]
```

- [ ] **Step 6: Run the tests to see them pass, then the whole suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_identity.py` → 13 passed.
Run: `$PY -m pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/identity.py tests/auth_support.py tests/conftest.py tests/test_identity.py
git commit -m "Auth: verify Clerk session tokens against the provider's public keys"
```

---

### Task 4: The actor, first-sign-in linking, and `GET /me`

**Files:**
- Modify: `app/identity.py` (add `Profile`, `fetch_profile`)
- Create: `app/auth.py`
- Create: `app/schemas/auth.py`, `app/routers/me.py`
- Modify: `app/main.py`, `app/errors.py`
- Modify: `tests/auth_support.py`, `tests/conftest.py`, `tests/support.py`, `tests/test_transactions.py`
- Create: `tests/test_linking.py`

**Interfaces:**
- Consumes: `identity.verify_token`, `identity.invalid` (Task 3); table `user_account` (Task 2).
- Produces:
  - `identity.Profile(email: str, verified: bool, full_name: str)`; `identity.fetch_profile(subject: str) -> Profile` (raises 503 `identity_provider_unavailable` / `auth_not_configured`).
  - `auth.Actor(kind: Literal["customer","staff"], id: int, display_name: str, store_id: int | None = None, store_name: str | None = None, staff_type: str | None = None, runs_store: bool = False)` with properties `is_support`, `is_manager`.
  - `auth.current_actor(request, cur) -> Actor | None`; `auth.CurrentActor` (Annotated dependency); `auth.link_account(cur, subject) -> dict` (`{"customer_id", "staff_id"}`); `auth.load_actor(cur, account) -> Actor`; `auth.require_actor(actor) -> Actor` (401 `not_signed_in`).
  - `GET /api/v1/me` → `Me` (`kind, id, display_name, store_id, store_name, staff_type, runs_store`).
  - Tests: `auth_support.PROFILES`, `fake_fetch_profile`, `as_subject(subject, email, *, name, verified) -> dict`, `as_staff(staff_id) -> dict`, `as_customer(email) -> dict`; `tests.support.run_at_once(n, work) -> list`.

- [ ] **Step 1: Move `run_at_once` to `tests/support.py`**

Cut the `run_at_once` function (and its `import threading`) from `tests/test_transactions.py`, paste it at the end of `tests/support.py` (add `import threading` to its imports), and in `tests/test_transactions.py` change the import line to:

```python
from tests.support import connect, run_at_once, unique_sku
```

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_transactions.py` → 4 passed.

- [ ] **Step 2: Test support — a fake provider directory**

Append to `tests/auth_support.py` (and add `from app.errors import ApiError` and `from app.identity import Profile` to its imports):

```python
PROFILES: dict[str, Profile] = {}


def fake_fetch_profile(subject: str) -> Profile:
    """Stands in for Clerk's Backend API: it knows only the users a test registered."""
    if subject not in PROFILES:
        raise ApiError(503, "identity_provider_unavailable", "The fake provider has no such user.")
    return PROFILES[subject]


def as_subject(subject: str, email: str, *, name: str = "Test User", verified: bool = True) -> dict:
    """Register what the provider knows about this subject, and return headers signed in as them."""
    PROFILES[subject] = Profile(email=email, verified=verified, full_name=name)
    return bearer(subject)


# Seeded staff the tests sign in as (sql/10_seed_reference.sql).
STAFF_EMAILS = {
    1: "olivia.nguyen@jbhifi.example",      # manages Sydney CBD (store 1)
    14: "aiden.chen@jbhifi.example",        # works at Sydney CBD
    16: "isla.robinson@jbhifi.example",     # works at Bondi Junction (store 2)
    40: "nora.fitzgerald@jbhifi.example",   # support
}


def as_staff(staff_id: int) -> dict:
    return as_subject(f"test_staff_{staff_id}", STAFF_EMAILS[staff_id])


def as_customer(email: str) -> dict:
    return as_subject(f"test_customer_{email}", email)
```

In `tests/conftest.py`, import `fake_fetch_profile` too (`from tests.auth_support import ISSUER, PARTY, OwnKeys, fake_fetch_profile`) and add one line inside `fake_clerk`, after the `_jwks_client` patch:

```python
        patch.setattr(identity, "fetch_profile", fake_fetch_profile)
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_linking.py`:

```python
"""The first time a subject signs in, link it to our data (app/auth.py, spec §4.3): staff by email, else an
existing customer by email, else a new customer. These tests commit, so each uses fresh emails/subjects."""
import uuid

from fastapi.testclient import TestClient

from app import identity
from app.auth import link_account
from app.main import app
from tests.auth_support import as_subject, bearer
from tests.support import connect, run_at_once

client = TestClient(app)
API = "/api/v1"


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def fresh(prefix: str) -> tuple[str, str]:
    """A new (subject, email) pair no other test uses."""
    tag = uuid.uuid4().hex[:10]
    return f"user_{prefix}_{tag}", f"{prefix}.{tag}@example.com"


def committed(query: str, params=()):
    """Run one statement in its own committed transaction; return its first row, if any."""
    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone() if cur.description else None
    conn.close()
    return row


def accounts_for(subject: str) -> int:
    return committed("SELECT count(*) AS n FROM user_account WHERE auth_subject = %s", (subject,))["n"]


def me(headers):
    return client.get(f"{API}/me", headers=headers)


def test_me_needs_a_signed_in_caller():
    assert error_of(client.get(f"{API}/me")) == (401, "not_signed_in")
    assert error_of(client.get(f"{API}/me", headers={"Authorization": "Basic YWxpY2U6cHc="})) == (401, "invalid_token")
    assert error_of(client.get(f"{API}/me", headers={"Authorization": "Bearer"})) == (401, "invalid_token")


def test_public_reads_need_no_sign_in():
    assert client.get(f"{API}/products").status_code == 200


def test_a_new_email_becomes_a_new_customer():
    subject, email = fresh("shopper")
    response = me(as_subject(subject, email, name="New Shopper"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["kind"], body["display_name"], body["store_id"]) == ("customer", "New Shopper", None)
    assert committed("SELECT email FROM customer WHERE customer_id = %s", (body["id"],))["email"] == email


def test_an_existing_customer_email_links_in_any_case():
    subject, email = fresh("existing")
    customer_id = committed("INSERT INTO customer (email, full_name) VALUES (%s, 'Existing Customer') "
                            "RETURNING customer_id", (email,))["customer_id"]
    body = me(as_subject(subject, email.upper())).json()
    assert (body["kind"], body["id"]) == ("customer", customer_id)
    assert committed("SELECT count(*) AS n FROM customer WHERE lower(email) = %s", (email,))["n"] == 1


def test_a_staff_email_links_to_that_staff_member():
    subject, email = fresh("staffer")
    staff_id = committed("INSERT INTO staff (store_id, staff_type, full_name, email) "
                         "VALUES (3, 'store', 'New Staffer', %s) RETURNING staff_id", (email,))["staff_id"]
    body = me(as_subject(subject, email)).json()
    assert (body["kind"], body["id"], body["store_id"], body["staff_type"], body["runs_store"]) \
        == ("staff", staff_id, 3, "store", False)


def test_an_unverified_email_is_refused_and_nothing_is_written():
    subject, email = fresh("unverified")
    assert error_of(me(as_subject(subject, email, verified=False))) == (403, "email_not_verified")
    assert committed("SELECT count(*) AS n FROM customer WHERE email = %s", (email,))["n"] == 0
    assert accounts_for(subject) == 0


def test_an_unreachable_provider_is_a_503_and_nothing_is_written():
    subject, _ = fresh("unknown")                         # never registered: the fake provider can't find it
    assert error_of(me(bearer(subject))) == (503, "identity_provider_unavailable")
    assert accounts_for(subject) == 0


def test_an_email_the_database_refuses_is_a_409_and_nothing_is_written():
    subject, _ = fresh("bademail")
    assert error_of(me(as_subject(subject, "someone@localhost"))) == (409, "br01_email_format")
    assert accounts_for(subject) == 0


def test_the_provider_is_asked_only_the_first_time(monkeypatch):
    subject, email = fresh("once")
    asked = []
    provider = identity.fetch_profile                      # the fake installed by conftest.py
    monkeypatch.setattr(identity, "fetch_profile", lambda s: asked.append(s) or provider(s))
    assert me(as_subject(subject, email)).status_code == 200
    assert me(bearer(subject)).status_code == 200
    assert asked == [subject]


def test_two_first_requests_at_once_make_one_link():
    subject, email = fresh("racing")
    as_subject(subject, email)

    def first_request():
        conn = connect()
        try:
            with conn, conn.cursor() as cur:
                return dict(link_account(cur, subject))
        finally:
            conn.close()

    results = run_at_once(2, first_request)
    assert all(isinstance(result, dict) for result in results), results
    assert results[0] == results[1]
    assert committed("SELECT count(*) AS n FROM customer WHERE email = %s", (email,))["n"] == 1
    assert accounts_for(subject) == 1
```

- [ ] **Step 4: Run them to see them fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_linking.py`
Expected: collection error — `cannot import name 'Profile' from 'app.identity'` (from `tests/auth_support.py`).

- [ ] **Step 5: Add `Profile` and `fetch_profile` to `app/identity.py`**

Add `from dataclasses import dataclass` and `import httpx` to the imports, and append:

```python
CLERK_API = "https://api.clerk.com/v1"


@dataclass(frozen=True)
class Profile:
    email: str
    verified: bool
    full_name: str


def fetch_profile(subject: str) -> Profile:
    """The user's primary email (and whether it is verified) and name, from Clerk's Backend API.

    Called once per person: the first time their token reaches the API (app/auth.py links them then).
    """
    secret = os.environ.get("CLERK_SECRET_KEY")
    if not secret:
        raise ApiError(503, "auth_not_configured", "Sign-in is not configured: set CLERK_SECRET_KEY in .env.")
    try:
        response = httpx.get(f"{CLERK_API}/users/{subject}", headers={"Authorization": f"Bearer {secret}"},
                             timeout=5)
        response.raise_for_status()
        user = response.json()
    except (httpx.HTTPError, ValueError):
        raise ApiError(503, "identity_provider_unavailable",
                       "Can't reach the sign-in provider. Try again shortly.") from None
    primary = next((address for address in user.get("email_addresses", [])
                    if address.get("id") == user.get("primary_email_address_id")), None)
    if primary is None:
        return Profile(email="", verified=False, full_name="")
    email = primary["email_address"]
    verified = (primary.get("verification") or {}).get("status") == "verified"
    name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part)
    return Profile(email=email, verified=verified, full_name=name or email.split("@")[0])
```

- [ ] **Step 6: Write `app/auth.py`**

```python
"""Who is calling? Provider-neutral: app/identity.py says which subject signed the request; this module
turns that subject into a customer or a staff member from our own data (user_account, BR19).

The permission checks the services make before acting (plan §7: services authorise explicitly) live here
too, so any caller — the web app today, a Phase 2 agent later — gets the same rules.
"""
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request

from app import identity
from app.db import DbCursor
from app.errors import ApiError


@dataclass(frozen=True)
class Actor:
    kind: Literal["customer", "staff"]
    id: int
    display_name: str
    store_id: int | None = None
    store_name: str | None = None
    staff_type: str | None = None
    runs_store: bool = False            # this staff member manages their store (store.manager_id, BR04)

    @property
    def is_support(self) -> bool:
        return self.kind == "staff" and self.staff_type == "support"

    @property
    def is_manager(self) -> bool:
        return self.kind == "staff" and self.staff_type == "store" and self.runs_store


def _bearer_token(request: Request) -> str | None:
    """The token from `Authorization: Bearer …`; None when there is no header (a guest).

    Only this header counts, never a cookie: a browser sends cookies by itself, so a cookie would let another
    site make requests as you (CSRF). A header has to be added on purpose, by our own code.
    """
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise identity.invalid("not a Bearer token")
    return token.strip()


def _account(cur, subject: str):
    cur.execute("SELECT customer_id, staff_id FROM user_account WHERE auth_subject = %s", (subject,))
    return cur.fetchone()


def link_account(cur, subject: str):
    """This subject's user_account row, created the first time they sign in (spec §4.3).

    Staff first (by email): staff rows are only ever created by us, so nobody becomes staff by signing up.
    Then an existing customer (by email). Else a new customer — self-service sign-up. Runs in the request's
    transaction, so a failure later in the request rolls the link back too.
    """
    account = _account(cur, subject)
    if account is not None:
        return account
    profile = identity.fetch_profile(subject)
    if not profile.verified:
        raise ApiError(403, "email_not_verified",
                       "Verify your email address with the sign-in provider, then try again.")
    email = profile.email.strip().lower()           # BR01 stores emails in lower case
    cur.execute("SELECT staff_id FROM staff WHERE email = %s", (email,))
    staff = cur.fetchone()
    customer_id = None if staff is not None else _customer_for(cur, email, profile.full_name)
    # Two first requests at once: the second waits for the first's row, then does nothing.
    cur.execute(
        """
        INSERT INTO user_account (auth_subject, customer_id, staff_id) VALUES (%s, %s, %s)
        ON CONFLICT (auth_subject) DO NOTHING
        """,
        (subject, customer_id, None if staff is None else staff["staff_id"]),
    )
    return _account(cur, subject)


def _customer_for(cur, email: str, full_name: str) -> int:
    """The customer with this email, created if there is none."""
    cur.execute(
        """
        INSERT INTO customer (email, full_name) VALUES (%s, %s)
        ON CONFLICT ON CONSTRAINT br01_customer_email_unique DO NOTHING
        RETURNING customer_id
        """,
        (email, full_name),
    )
    row = cur.fetchone()
    if row is None:                     # already a customer (seeded, or created by a request just before)
        cur.execute("SELECT customer_id FROM customer WHERE email = %s", (email,))
        row = cur.fetchone()
    return row["customer_id"]


def load_actor(cur, account) -> Actor:
    if account["customer_id"] is not None:
        cur.execute("SELECT customer_id, full_name FROM customer WHERE customer_id = %s", (account["customer_id"],))
        row = cur.fetchone()
        return Actor("customer", row["customer_id"], row["full_name"])
    cur.execute(
        """
        SELECT st.staff_id, st.full_name, st.staff_type, st.store_id, s.name AS store_name,
               COALESCE(s.manager_id = st.staff_id, FALSE) AS runs_store
        FROM staff st
        LEFT JOIN store s ON s.store_id = st.store_id
        WHERE st.staff_id = %s
        """,
        (account["staff_id"],),
    )
    row = cur.fetchone()
    return Actor("staff", row["staff_id"], row["full_name"], row["store_id"], row["store_name"],
                 row["staff_type"], row["runs_store"])


def current_actor(request: Request, cur: DbCursor) -> Actor | None:
    """Who this request is: None for a guest (no Authorization header)."""
    token = _bearer_token(request)
    if token is None:
        return None
    return load_actor(cur, link_account(cur, identity.verify_token(token)))


CurrentActor = Annotated[Actor | None, Depends(current_actor)]


def require_actor(actor: Actor | None) -> Actor:
    if actor is None:
        raise ApiError(401, "not_signed_in", "Sign in to do that.")
    return actor
```

- [ ] **Step 7: The `/me` endpoint, its schema, and the error responses**

Create `app/schemas/auth.py`:

```python
from typing import Literal

from pydantic import BaseModel


class Me(BaseModel):
    """Who the API takes the caller to be — decided by our database (user_account, BR19), not the token."""
    kind: Literal["customer", "staff"]
    id: int
    display_name: str
    store_id: int | None = None
    store_name: str | None = None
    staff_type: Literal["store", "support"] | None = None
    runs_store: bool = False
```

Create `app/routers/me.py`:

```python
from dataclasses import asdict

from fastapi import APIRouter

from app.auth import CurrentActor, require_actor
from app.errors import ERROR_RESPONSES
from app.schemas.auth import Me

router = APIRouter(tags=["auth"], responses=ERROR_RESPONSES)


@router.get("/me", response_model=Me)
def who_am_i(actor: CurrentActor):
    """The signed-in caller as our database knows them: a customer, or staff with their store and role."""
    return asdict(require_actor(actor))
```

In `app/main.py`: change the import to `from app.routers import customers, inventory, me, products, promotions, reference` and the loop tuple to `(me, reference, inventory, products, promotions, customers)`.

In `app/errors.py`, replace `ERROR_RESPONSES` with:

```python
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in, or the sign-in token is not valid"},
    403: {"model": ErrorResponse, "description": "Signed in, but not allowed to do this"},
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Rejected by a database rule; code = constraint name"},
    422: {"model": ErrorResponse, "description": "Malformed request"},
    503: {"model": ErrorResponse, "description": "The sign-in provider could not be reached"},
}
```

- [ ] **Step 8: Run the tests to see them pass, then the whole suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_linking.py` → 10 passed.
Run: `$PY -m pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 9: Commit**

```bash
git add app/identity.py app/auth.py app/schemas/auth.py app/routers/me.py app/main.py app/errors.py \
  tests/auth_support.py tests/conftest.py tests/support.py tests/test_transactions.py tests/test_linking.py
git commit -m "Auth: link a signed-in subject to a customer or staff row, and GET /me"
```

---

### Task 5: Permissions on the existing endpoints

**Files:**
- Modify: `app/auth.py` (permission helpers)
- Modify: `app/services/reference.py`, `app/services/customers.py`, `app/services/inventory.py`, `app/services/products.py`, `app/services/promotions.py`
- Modify: `app/routers/reference.py`, `app/routers/customers.py`, `app/routers/inventory.py`, `app/routers/products.py`, `app/routers/promotions.py`
- Modify: `app/schemas/inventory.py`
- Modify: `tests/test_api.py`, `tests/test_transactions.py`
- Create: `tests/test_permissions.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `Actor`, `CurrentActor`, `require_actor` (Task 4); `tests.auth_support.as_staff`, `as_customer` (Task 4).
- Produces: `require_customer_self(actor, customer_id)`, `require_staff`, `require_support`, `require_store_staff(actor, store_id)`, `require_store_or_support_reader(actor, store_id)`, `require_catalogue_writer` — each `(actor: Actor | None, …) -> Actor`, raising 401/403 `ApiError`. New service signatures (actor second): `list_staff(cur, actor, store_id=None)`, `list_customers(cur, actor)`, `get_customer(cur, actor, customer_id)`, `adjust_stock(cur, actor, store_id, product_id, delta, reason, note)`, `list_adjustments(cur, actor, store_id, product_id=None, limit=50)`, `create_product(cur, actor, new)`, `update_product(cur, actor, product_id, changes)`, `replace_specs(cur, actor, product_id, specs)`, `create_promotion(cur, actor, new)`, `delete_promotion(cur, actor, promotion_id)`. `AdjustmentCreate` has no `staff_id` and forbids extra fields.

- [ ] **Step 1: Write the failing permission matrix**

Create `tests/test_permissions.py`:

```python
"""Who may call what (spec §4.5). Each row lists the callers allowed past the permission check; everyone
else is refused — a guest with 401 not_signed_in, anyone signed in with 403. "Allowed" may still end in a
404 or 409 from the data: the ids don't exist and the bodies break rules, so nothing here changes anything.
"""
from functools import cache

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.auth_support import as_customer, as_staff

client = TestClient(app)
API = "/api/v1"
ALICE, BEN = "alice.morgan@example.com", "ben.okafor@example.com"
CALLERS = {
    "guest": lambda: {},
    "alice": lambda: as_customer(ALICE),
    "ben": lambda: as_customer(BEN),
    "aiden": lambda: as_staff(14),          # store staff, Sydney CBD (store 1)
    "isla": lambda: as_staff(16),           # store staff, Bondi Junction (store 2)
    "olivia": lambda: as_staff(1),          # manager, Sydney CBD
    "nora": lambda: as_staff(40),           # support
}
EVERYONE = set(CALLERS)
SIGNED_IN = EVERYONE - {"guest"}
STAFF = {"aiden", "isla", "olivia", "nora"}
CATALOGUE = {"olivia", "nora"}
NEW_STOCK = {"delta": 1, "reason": "received"}
PROMOTION = {"product_id": 999999, "sale_price": "1.00",
             "starts_at": "2030-01-01T00:00:00+00:00", "ends_at": "2030-01-02T00:00:00+00:00"}
PRODUCT = {"sku": "APL-AP4", "name": "Duplicate SKU", "brand_id": 1, "category_id": 1, "base_price": "1.00"}

ENDPOINTS = [
    ("GET", "/me", None, SIGNED_IN),
    ("GET", "/stores", None, EVERYONE),
    ("GET", "/products", None, EVERYONE),
    ("GET", "/promotions", None, EVERYONE),
    ("GET", "/stores/1/inventory", None, EVERYONE),
    ("GET", "/staff", None, STAFF),
    ("GET", "/customers", None, {"nora"}),
    ("GET", "/customers/{alice}", None, {"alice", "nora"}),
    ("GET", "/customers/999999", None, {"nora"}),                         # others learn nothing: 403
    ("POST", "/stores/1/inventory/999999/adjustments", NEW_STOCK, {"aiden", "olivia"}),
    ("POST", "/stores/99/inventory/999999/adjustments", NEW_STOCK, set()),  # no such store: still 403
    ("GET", "/stores/1/adjustments", None, {"aiden", "olivia", "nora"}),
    ("POST", "/products", PRODUCT, CATALOGUE),
    ("PATCH", "/products/999999", {"name": "Nothing"}, CATALOGUE),
    ("PUT", "/products/999999/specs", [], CATALOGUE),
    ("POST", "/promotions", PROMOTION, CATALOGUE),
    ("DELETE", "/promotions/999999", None, CATALOGUE),
]


@cache
def alice_id() -> int:
    return client.get(f"{API}/me", headers=as_customer(ALICE)).json()["id"]


@pytest.mark.parametrize("method, path, body, allowed", ENDPOINTS, ids=[f"{m} {p}" for m, p, _, _ in ENDPOINTS])
@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_who_may_call_what(caller, method, path, body, allowed):
    url = API + path.format(alice=alice_id())
    response = client.request(method, url, json=body, headers=CALLERS[caller]())
    if caller in allowed:
        assert response.status_code not in (401, 403), response.text
    elif caller == "guest":
        assert (response.status_code, response.json()["error"]["code"]) == (401, "not_signed_in"), response.text
    else:
        assert response.status_code == 403, response.text
```

- [ ] **Step 2: Run it to see it fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_permissions.py`
Expected: many FAILED — e.g. `guest-GET /staff` gets 200 where 401 is expected.

- [ ] **Step 3: Add the permission helpers to `app/auth.py`**

Append after `require_actor`:

```python
def require_customer_self(actor: Actor | None, customer_id: int) -> Actor:
    """A customer's own record — or support staff looking it up."""
    actor = require_actor(actor)
    if actor.kind == "customer":
        if actor.id != customer_id:
            raise ApiError(403, "not_your_account", "That account belongs to another customer.")
        return actor
    if not actor.is_support:
        raise ApiError(403, "support_only", "Only support staff can look up customers.")
    return actor


def require_staff(actor: Actor | None) -> Actor:
    actor = require_actor(actor)
    if actor.kind != "staff":
        raise ApiError(403, "staff_only", "Only staff can do that.")
    return actor


def require_support(actor: Actor | None) -> Actor:
    actor = require_staff(actor)
    if not actor.is_support:
        raise ApiError(403, "support_only", "Only support staff can do that.")
    return actor


def require_store_staff(actor: Actor | None, store_id: int) -> Actor:
    """Staff of this store. Support staff read across stores but don't handle a store's stock."""
    actor = require_staff(actor)
    if actor.is_support:
        raise ApiError(403, "store_staff_only", "Stock is adjusted by the store's own staff.")
    if actor.store_id != store_id:
        raise ApiError(403, "other_store", "You can only act on your own store.")
    return actor


def require_store_or_support_reader(actor: Actor | None, store_id: int) -> Actor:
    """Reading a store's records: that store's staff, or support from anywhere."""
    actor = require_staff(actor)
    if not actor.is_support and actor.store_id != store_id:
        raise ApiError(403, "other_store", "You can only read your own store's records.")
    return actor


def require_catalogue_writer(actor: Actor | None) -> Actor:
    """The catalogue and promotions are maintained by store managers and support staff."""
    actor = require_staff(actor)
    if not (actor.is_support or actor.is_manager):
        raise ApiError(403, "manager_only", "Only a store manager or support staff can change the catalogue.")
    return actor
```

- [ ] **Step 4: Check permissions in the services (first line of each)**

`app/services/reference.py` — add `from app.auth import require_staff` and change `list_staff`:

```python
def list_staff(cur, actor, store_id: int | None = None):
    require_staff(actor)
    where, params = sql.SQL(""), ()
```

(the rest of the function is unchanged).

`app/services/customers.py` — replace the docstring and imports, and add a first line to both functions:

```python
"""Customers: the support team's directory, and each customer's own record."""
from app.auth import require_customer_self, require_support
from app.errors import NotFound


def list_customers(cur, actor):
    require_support(actor)
    cur.execute("SELECT customer_id, full_name, email FROM customer ORDER BY customer_id")
    return cur.fetchall()


def get_customer(cur, actor, customer_id: int):
    require_customer_self(actor, customer_id)
    cur.execute(
```

(the rest of `get_customer` is unchanged).

`app/services/inventory.py` — add `from app.auth import require_store_or_support_reader, require_store_staff`; change `adjust_stock`'s signature, docstring and first line, and its INSERT parameters:

```python
def adjust_stock(cur, actor, store_id: int, product_id: int, delta: int, reason: str, note: str | None):
    """Change one store's stock of one product, and log who did it and why (BR18).

    The adjuster is the signed-in staff member, never a staff id from the request. Runs in the request's
    transaction (app/db.py): the stock change and its log row are committed together, or not at all.
    """
    require_store_staff(actor, store_id)
    if not store_exists(cur, store_id):
```

and in step 3's INSERT, change the parameter tuple's `staff_id` to `actor.id`:

```python
        (store_id, product_id, actor.id, delta, reason, note, quantity_after),
```

and `list_adjustments`:

```python
def list_adjustments(cur, actor, store_id: int, product_id: int | None = None, limit: int = 50):
    require_store_or_support_reader(actor, store_id)
    if not store_exists(cur, store_id):
```

`app/services/products.py` — add `from app.auth import require_catalogue_writer` and:

```python
def create_product(cur, actor, new):
    require_catalogue_writer(actor)
```

```python
def update_product(cur, actor, product_id: int, changes: dict):
    require_catalogue_writer(actor)
```

```python
def replace_specs(cur, actor, product_id: int, specs) -> list:
    """Replace all of a product's specs at once; other transactions see the old set or the new one."""
    require_catalogue_writer(actor)
```

`app/services/promotions.py` — add `from app.auth import require_catalogue_writer` and:

```python
def create_promotion(cur, actor, new):
    require_catalogue_writer(actor)
```

```python
def delete_promotion(cur, actor, promotion_id: int) -> None:
    require_catalogue_writer(actor)
```

- [ ] **Step 5: Pass the actor from the routers; drop `staff_id` from the body**

`app/schemas/inventory.py` — change the pydantic import to `from pydantic import BaseModel, ConfigDict, Field` and `AdjustmentCreate` to:

```python
class AdjustmentCreate(BaseModel):
    """Who makes the change is the signed-in staff member; a staff_id in the body is refused (extra)."""
    model_config = ConfigDict(extra="forbid")

    delta: int                      # relative change: +5 received, -1 damaged, ±n after a stocktake
    reason: AdjustmentReason
    note: str | None = Field(default=None, max_length=500)
```

In each router add `from app.auth import CurrentActor`, add an `actor: CurrentActor` parameter to the handlers below, and pass it as the services' second argument:

`app/routers/reference.py`:
```python
@router.get("/staff", response_model=list[StaffOut])
def list_staff(cur: DbCursor, actor: CurrentActor, store_id: int | None = None):
    return reference.list_staff(cur, actor, store_id)
```

`app/routers/customers.py`:
```python
@router.get("", response_model=list[CustomerSummary])
def list_customers(cur: DbCursor, actor: CurrentActor):
    return customers.list_customers(cur, actor)


@router.get("/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: int, cur: DbCursor, actor: CurrentActor):
    return customers.get_customer(cur, actor, customer_id)
```

`app/routers/inventory.py`:
```python
@router.post("/inventory/{product_id}/adjustments", response_model=AdjustmentOut, status_code=201)
def adjust_stock(store_id: int, product_id: int, body: AdjustmentCreate, cur: DbCursor, actor: CurrentActor):
    return inventory.adjust_stock(cur, actor, store_id, product_id, body.delta, body.reason, body.note)


@router.get("/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(
    store_id: int,
    cur: DbCursor,
    actor: CurrentActor,
    product_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    return inventory.list_adjustments(cur, actor, store_id, product_id, limit)
```

`app/routers/products.py`:
```python
@router.post("", response_model=ProductDetail, status_code=201)
def create_product(body: ProductCreate, cur: DbCursor, actor: CurrentActor):
    return products.create_product(cur, actor, body)
```
```python
@router.patch("/{product_id}", response_model=ProductDetail)
def update_product(product_id: int, body: ProductUpdate, cur: DbCursor, actor: CurrentActor):
    return products.update_product(cur, actor, product_id, body.model_dump(exclude_unset=True, exclude_none=True))


@router.put("/{product_id}/specs", response_model=list[Spec])
def replace_specs(product_id: int, body: list[Spec], cur: DbCursor, actor: CurrentActor):
    return products.replace_specs(cur, actor, product_id, body)
```

`app/routers/promotions.py`:
```python
@router.post("", response_model=PromotionOut, status_code=201)
def create_promotion(body: PromotionCreate, cur: DbCursor, actor: CurrentActor):
    return promotions.create_promotion(cur, actor, body)


@router.delete("/{promotion_id}", status_code=204)
def delete_promotion(promotion_id: int, cur: DbCursor, actor: CurrentActor):
    promotions.delete_promotion(cur, actor, promotion_id)
    return Response(status_code=204)
```

- [ ] **Step 6: Update the existing tests to sign in**

`tests/test_transactions.py` — add `from app.auth import Actor` and replace `request_adjustment`:

```python
def request_adjustment(product_id, staff_id, delta, reason):
    """One API request by staff_id, presented as Sydney CBD staff. The service checks the actor's store; the
    database checks the staff member's real one (BR18) — so even a forged actor is refused there."""
    actor = Actor("staff", staff_id, "Test staff", store_id=SYDNEY_CBD, staff_type="store")
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            return adjust_stock(cur, actor, SYDNEY_CBD, product_id, delta, reason, None)
    finally:
        conn.close()
```

Replace `tests/test_api.py` with:

```python
"""API smoke tests: every endpoint answers, and a request that breaks a database rule comes back as
409 with the rule's constraint name as the error code — rolled back as a whole. Each request here is made
by someone allowed to make it; who may call what is tests/test_permissions.py."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.auth_support import as_customer, as_staff
from tests.support import unique_sku

client = TestClient(app)
API = "/api/v1"
OLIVIA = 1          # manages Sydney CBD (store 1): may change the catalogue
AIDEN = 14          # works at Sydney CBD (store 1)
ISLA = 16           # works at Bondi Junction (store 2)
NORA = 40           # support staff
BEN = "ben.okafor@example.com"


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


@pytest.fixture
def new_product():
    """A product created through the API (committed): Sony headphones at $199.00, no stock anywhere."""
    brands = {b["name"]: b["brand_id"] for b in client.get(f"{API}/brands").json()}
    categories = {c["name"]: c["category_id"] for c in client.get(f"{API}/categories").json()}
    response = client.post(f"{API}/products", headers=as_staff(OLIVIA), json={
        "sku": unique_sku(), "name": "API test headphones", "brand_id": brands["Sony"],
        "category_id": categories["Headphones"], "base_price": "199.00",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_reference_lists():
    assert len(client.get(f"{API}/stores").json()) == 13
    staff = client.get(f"{API}/staff", params={"store_id": 1}, headers=as_staff(AIDEN)).json()
    assert [s["is_manager"] for s in staff] == [True, False, False]
    assert len(client.get(f"{API}/categories").json()) == 15
    assert len(client.get(f"{API}/brands").json()) == 16
    assert client.get(f"{API}/stores/99/inventory").status_code == 404


def test_support_looks_up_customers():
    nora = as_staff(NORA)
    customers = {c["email"]: c["customer_id"] for c in client.get(f"{API}/customers", headers=nora).json()}
    assert {"alice.morgan@example.com", BEN} <= set(customers)
    ben = client.get(f"{API}/customers/{customers[BEN]}", headers=nora).json()
    # The current address comes first; the old one is still there, inactive (BR16: never edited).
    assert [(a["address_no"], a["is_active"]) for a in ben["addresses"]] == [(2, True), (1, False)]
    assert client.get(f"{API}/customers/999999", headers=nora).status_code == 404


def test_a_customer_reads_their_own_record():
    me = client.get(f"{API}/me", headers=as_customer(BEN)).json()
    assert client.get(f"{API}/customers/{me['id']}", headers=as_customer(BEN)).json()["email"] == BEN


def test_adjust_stock_round_trip(new_product):
    pid, sku = new_product["product_id"], new_product["sku"]
    aiden = as_staff(AIDEN)
    response = client.post(f"{API}/stores/1/inventory/{pid}/adjustments", headers=aiden,
                           json={"delta": 5, "reason": "received", "note": "Delivery #123"})
    assert response.status_code == 201, response.text
    assert (response.json()["quantity_after"], response.json()["staff_name"]) == (5, "Aiden Chen")

    rows = client.get(f"{API}/stores/1/inventory", params={"q": sku}).json()
    assert [(row["product_id"], row["quantity"]) for row in rows] == [(pid, 5)]
    history = client.get(f"{API}/stores/1/adjustments", params={"product_id": pid}, headers=aiden).json()
    assert [(h["delta"], h["reason"], h["note"]) for h in history] == [(5, "received", "Delivery #123")]
    assert client.get(f"{API}/products/{pid}").json()["total_stock"] == 5


def test_rule_violations_are_409_with_the_rule_name_and_change_nothing(new_product):
    pid = new_product["product_id"]
    url = f"{API}/stores/1/inventory/{pid}/adjustments"
    aiden = as_staff(AIDEN)
    assert error_of(client.post(url, headers=aiden, json={"delta": -1, "reason": "damaged"})) \
        == (409, "br03_inventory_qty_nonneg")
    assert error_of(client.post(url, headers=aiden, json={"delta": 1, "reason": "damaged"})) \
        == (409, "br18_adjustment_delta_matches_reason")
    # Another store's staff are stopped before the database (which would refuse too: BR18), and the
    # adjuster comes from the sign-in — a staff_id in the body is refused.
    assert error_of(client.post(url, headers=as_staff(ISLA), json={"delta": 1, "reason": "received"})) \
        == (403, "other_store")
    assert error_of(client.post(url, headers=aiden, json={"staff_id": ISLA, "delta": 1, "reason": "received"})) \
        == (422, "validation_error")
    assert client.get(f"{API}/stores/1/adjustments", params={"product_id": pid}, headers=aiden).json() == []
    assert client.get(f"{API}/products/{pid}").json()["total_stock"] == 0


def test_product_rules(new_product):
    olivia = as_staff(OLIVIA)
    valid = {"sku": unique_sku(), "name": "X", "brand_id": new_product["brand_id"],
             "category_id": new_product["category_id"], "base_price": "10.00"}
    for change, expected in [
        ({"sku": "lower-case"}, "product_sku_format"),
        ({"sku": new_product["sku"]}, "product_sku_unique"),
        ({"base_price": "-1.00"}, "br02_money_nonneg"),
        ({"brand_id": 999999}, "product_brand_fk"),
    ]:
        response = client.post(f"{API}/products", headers=olivia, json={**valid, **change})
        assert error_of(response) == (409, expected), response.text
    assert error_of(client.post(f"{API}/products", headers=olivia, json={"sku": unique_sku()})) \
        == (422, "validation_error")


def test_update_product_and_replace_specs(new_product):
    pid = new_product["product_id"]
    olivia = as_staff(OLIVIA)
    response = client.patch(f"{API}/products/{pid}", headers=olivia, json={"base_price": "179.00", "is_active": False})
    assert response.status_code == 200, response.text
    assert (response.json()["base_price"], response.json()["is_active"]) == ("179.00", False)
    assert pid not in {p["product_id"] for p in client.get(f"{API}/products").json()}
    assert pid in {p["product_id"] for p in client.get(f"{API}/products", params={"include_inactive": True}).json()}

    specs = [{"spec_name": "Type", "spec_value": "Over-ear"}, {"spec_name": "Battery life", "spec_value": "40 h"}]
    assert len(client.put(f"{API}/products/{pid}/specs", headers=olivia, json=specs).json()) == 2
    duplicate = specs + [{"spec_name": "Type", "spec_value": "In-ear"}]
    assert error_of(client.put(f"{API}/products/{pid}/specs", headers=olivia, json=duplicate)) \
        == (409, "product_spec_pk")
    assert len(client.get(f"{API}/products/{pid}").json()["specs"]) == 2    # the failed replace changed nothing


def test_promotions(new_product):
    pid = new_product["product_id"]                                         # base price 199.00
    olivia = as_staff(OLIVIA)
    now = datetime.now(timezone.utc)

    def promotion(price, start_days, end_days):
        return {"product_id": pid, "sale_price": price,
                "starts_at": (now + timedelta(days=start_days)).isoformat(),
                "ends_at": (now + timedelta(days=end_days)).isoformat()}

    assert error_of(client.post(f"{API}/promotions", headers=olivia, json=promotion("199.00", 0, 7))) \
        == (409, "br15_promotion_below_base_price")
    response = client.post(f"{API}/promotions", headers=olivia, json=promotion("149.00", -1, 7))
    assert (response.status_code, response.json()["status"]) == (201, "active"), response.text
    assert response.json()["product_active"] is True
    promotion_id = response.json()["promotion_id"]
    assert client.get(f"{API}/products/{pid}").json()["current_price"] == "149.00"

    assert error_of(client.post(f"{API}/promotions", headers=olivia, json=promotion("139.00", 5, 10))) \
        == (409, "br15_promotion_no_overlap")
    assert error_of(client.patch(f"{API}/products/{pid}", headers=olivia, json={"base_price": "149.00"})) \
        == (409, "br15_promotion_below_base_price")
    naive = {**promotion("139.00", 20, 30), "starts_at": "2026-12-01T00:00:00"}     # no UTC offset
    assert error_of(client.post(f"{API}/promotions", headers=olivia, json=naive)) == (422, "validation_error")

    assert client.delete(f"{API}/promotions/{promotion_id}", headers=olivia).status_code == 204
    assert client.delete(f"{API}/promotions/{promotion_id}", headers=olivia).status_code == 404
```

- [ ] **Step 7: Run everything**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_permissions.py` → 119 passed.
Run: `$PY -m pytest -q -p no:cacheprovider` → all pass.

- [ ] **Step 8: Document the settings**

Append to `.env.example`:

```
# Sign-in (Clerk). The API checks each request's Bearer token against CLERK_ISSUER's public keys, and asks
# Clerk's Backend API (with the secret key) for a new user's email the first time they sign in.
# CLERK_ISSUER is the Frontend API URL from the Clerk Dashboard's API keys page. Never commit real keys.
CLERK_ISSUER=https://<your-app>.clerk.accounts.dev
CLERK_SECRET_KEY=sk_test_replace_me
AUTH_AUTHORIZED_PARTIES=http://localhost:3000,http://127.0.0.1:3000
```

- [ ] **Step 9: Commit**

```bash
git add app/auth.py app/services app/routers app/schemas/inventory.py tests/test_api.py \
  tests/test_transactions.py tests/test_permissions.py .env.example
git commit -m "Auth: each service checks who may call it; the adjuster comes from the sign-in"
```

---

### Task 6: The web app sends the token and knows who is signed in; storefront sign-in controls

**Files:**
- Modify: `web/src/lib/api/schema.d.ts` (regenerated)
- Modify: `web/src/lib/api/client.ts`
- Create: `web/src/components/api-auth.tsx`, `web/src/lib/me.ts`
- Modify: `web/src/app/layout.tsx`
- Modify: `web/src/components/shop/context.tsx`, `web/src/components/shop/header.tsx`, `web/src/app/(shop)/page.tsx`
- Modify: `web/src/app/admin/inventory/page.tsx` (only the request body, to keep the build green)

**Interfaces:**
- Consumes: `GET /api/v1/me` → `Me`; `AdjustmentCreate` without `staff_id` (Task 5).
- Produces: `setTokenGetter(getter)` and type `Me` in `@/lib/api/client`; `<ApiAuth />`; `useMe(): MeState` and type `MeState` (`{status:"loading"} | {status:"guest"} | {status:"signed-in"; me: Me} | {status:"error"; error: ApiError; retry: () => void}`) in `@/lib/me`; `useShop()` now has `session: MeState` and no `customers` / `customerId` / `setCustomerId`.

- [ ] **Step 1: Regenerate the typed client**

With the API running from the worktree (Task 1 step 9): `cd web && npm run gen:api && grep -c '"/api/v1/me"' src/lib/api/schema.d.ts` → `1`.

- [ ] **Step 2: `web/src/lib/api/client.ts` — the token on every request**

Add `export type Me = Schemas["Me"];` to the type exports, and insert after `export const api = createClient<paths>({ baseUrl: "" });`:

```ts
// Every request carries the signed-in user's Clerk session token. <ApiAuth/> (inside <ClerkProvider>)
// registers Clerk's getToken here; until then — and for guests — requests go without one.
type GetToken = (options?: { skipCache?: boolean }) => Promise<string | null>;
let getToken: GetToken = async () => null;

export function setTokenGetter(next: GetToken) {
  getToken = next;
}

const sent = new Map<string, Request>();   // a copy of each request in flight, in case it must be retried

api.use({
  async onRequest({ request, id }) {
    const token = await getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    sent.set(id, request.clone());
    return request;
  },
  async onResponse({ response, id }) {
    const copy = sent.get(id);
    sent.delete(id);
    // A token can expire between Clerk handing it out and the API checking it: retry once with a fresh one.
    if (response.status !== 401 || !copy) return response;
    const body = (await response.clone().json().catch(() => null)) as ErrorBody | null;
    if (body?.error?.code !== "invalid_token") return response;
    const token = await getToken({ skipCache: true });
    if (!token) return response;
    copy.headers.set("Authorization", `Bearer ${token}`);
    return fetch(copy);
  },
  onError({ id }) {
    sent.delete(id);
  },
});
```

- [ ] **Step 3: `web/src/components/api-auth.tsx`**

```tsx
"use client";

import { useAuth } from "@clerk/nextjs";
import { useLayoutEffect } from "react";

import { setTokenGetter } from "@/lib/api/client";

/** Gives the API client Clerk's getToken, so each request carries the signed-in user's session token.
 *  A layout effect runs before every component's ordinary effects, so even the first loads have it. */
export function ApiAuth() {
  const { getToken } = useAuth();
  useLayoutEffect(() => setTokenGetter(getToken), [getToken]);
  return null;
}
```

In `web/src/app/layout.tsx` add `import { ApiAuth } from "@/components/api-auth";` and change the provider line to:

```tsx
        <ClerkProvider signInUrl="/sign-in" signUpUrl="/sign-up"><ApiAuth />{children}</ClerkProvider>
```

- [ ] **Step 4: `web/src/lib/me.ts`**

```ts
import { useAuth } from "@clerk/nextjs";

import { type ApiError, api, call, type Me } from "@/lib/api/client";
import { useLoad } from "@/lib/use-load";

export type MeState =
  | { status: "loading" }
  | { status: "guest" }
  | { status: "signed-in"; me: Me }
  | { status: "error"; error: ApiError; retry: () => void };

/** Who is signed in, as the API sees them: waits for Clerk to load, then asks GET /me (which links a new
 *  sign-in to a customer or staff row the first time). */
export function useMe(): MeState {
  const { isLoaded, isSignedIn, userId } = useAuth();
  const me = useLoad(`me:${isLoaded ? (userId ?? "guest") : "loading"}`, () =>
    isLoaded && isSignedIn ? call(api.GET("/api/v1/me")) : Promise.resolve(undefined));
  if (!isLoaded || me.loading) return { status: "loading" };
  if (!isSignedIn) return { status: "guest" };
  if (me.error) return { status: "error", error: me.error, retry: me.reload };
  return me.data ? { status: "signed-in", me: me.data } : { status: "loading" };
}
```

- [ ] **Step 5: `web/src/components/shop/context.tsx` — the customer comes from the sign-in**

1. Imports: replace the client import with
   `import { type ApiError, api, call, type Category, type CustomerDetail, type Store } from "@/lib/api/client";`
   and add `import { type MeState, useMe } from "@/lib/me";`.
2. The comment above the storage helpers: change its first sentence to
   `// Which store is "mine" is a convenience for this browser only, so it lives in localStorage.`
3. Replace everything from `type Shop = {` to the end of the file with:

```tsx
type Shop = {
  /** Who is signed in, as the API sees them (a Clerk sign-in, mapped to our data by GET /me). */
  session: MeState;
  /** The signed-in customer, with addresses; undefined for a guest, for staff, or while loading. */
  customer?: CustomerDetail;
  /** Still finding out who is signed in, or their details haven't arrived yet. */
  customerLoading: boolean;
  /** Stores a customer can shop at: retail only — the warehouse doesn't do Click & Collect (BR06). */
  retailStores: Store[];
  /** "My store": the one chosen, else the first in the customer's state, else the first store.
   *  undefined while stores (or the signed-in customer, whose state decides it) are still loading. */
  store?: Store;
  /** undefined goes back to the default (nearest store). */
  setStoreId: (id: number | undefined) => void;
  /** State of the customer's current address, used for "stores near you". */
  homeState?: string;
  categories: Category[];
  /** Who-am-I, stores or categories failed to load (e.g. the API isn't running). */
  loadError?: ApiError;
  /** Try those loads again. */
  reload: () => void;
};

const ShopContext = createContext<Shop | null>(null);

export function useShop(): Shop {
  const shop = useContext(ShopContext);
  if (!shop) throw new Error("useShop() must be used inside <ShopProvider>");
  return shop;
}

export function ShopProvider({ children }: { children: ReactNode }) {
  const session = useMe();
  const [storeId, setStoreId] = useStoredId("jb.shop.storeId");
  const customerId = session.status === "signed-in" && session.me.kind === "customer" ? session.me.id : undefined;

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const detail = useLoad(`customer:${customerId}`, () =>
    customerId === undefined
      ? Promise.resolve(undefined)
      : call(api.GET("/api/v1/customers/{customer_id}", { params: { path: { customer_id: customerId } } })));

  // While another customer loads, don't show the previous one's details under the new name.
  const customer = detail.data?.customer_id === customerId ? detail.data : undefined;
  const homeState = customer?.addresses.find((a) => a.is_active)?.state;
  const retailStores = (stores.data ?? []).filter((s) => s.store_type === "retail");
  const customerLoading = session.status === "loading" || (customerId !== undefined && !customer && !detail.error);
  // Don't guess a store from the first one while the customer's state is still on its way.
  const store = retailStores.find((s) => s.store_id === storeId)
    ?? (customerLoading ? undefined : retailStores.find((s) => s.state === homeState) ?? retailStores[0]);

  const shop: Shop = {
    session,
    customer,
    customerLoading,
    retailStores,
    store,
    setStoreId,
    homeState,
    categories: categories.data ?? [],
    loadError: (session.status === "error" ? session.error : undefined) ?? stores.error ?? categories.error,
    reload: () => {
      if (session.status === "error") session.retry();
      stores.reload();
      categories.reload();
    },
  };
  return <ShopContext value={shop}>{children}</ShopContext>;
}
```

- [ ] **Step 6: `web/src/components/shop/header.tsx` — Clerk's controls replace the picker**

1. Add `import { Show, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";` and `import type { MeState } from "@/lib/me";`. (If Task 1 step 3 found no `Show` export, import `SignedIn, SignedOut` instead and use `<SignedOut>…</SignedOut>` / `<SignedIn>…</SignedIn>` in place of the two `<Show>` blocks below.)
2. Change the destructuring line to:
   `const { session, retailStores, store, setStoreId, categories } = useShop();`
3. Replace the whole `<label … title="Demo sign-in: …"> … </label>` block (the "Signed in as" picker) with:
   `<AccountControls session={session} />`
4. Add, above `function CartIcon()`:

```tsx
function AccountControls({ session }: { session: MeState }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Show when="signed-out">
        <SignInButton mode="modal">
          <button type="button" className="h-9 rounded-md px-3 font-semibold text-neutral-900 hover:bg-yellow-400">
            Sign in
          </button>
        </SignInButton>
        <SignUpButton mode="modal">
          <button type="button" className="h-9 rounded-md bg-neutral-900 px-3 font-semibold text-white hover:bg-neutral-700">
            Create account
          </button>
        </SignUpButton>
      </Show>
      <Show when="signed-in">
        {session.status === "signed-in" && (
          <span className="text-xs font-medium text-neutral-800">
            {session.me.display_name}{session.me.kind === "staff" && " · staff"}
          </span>
        )}
        <UserButton />
      </Show>
    </div>
  );
}
```

- [ ] **Step 7: `web/src/app/(shop)/page.tsx` — the guest line**

Add `session` to the `useShop()` destructuring, and replace the line
`: !customer ? "Guest: choose a customer under “Signed in as” to see a personal home page (demo sign-in)."`
with:

```tsx
              : !customer ? (session.status === "signed-in" && session.me.kind === "staff"
                ? "You're signed in as staff: the storefront shows you what a guest sees."
                : "Guest: sign in to see a personal home page.")
```

- [ ] **Step 8: Keep the admin compiling — drop `staff_id` from the stock request**

In `web/src/app/admin/inventory/page.tsx`, in `adjust()`, change the body line to
`body: { delta, reason, note: note || null },`
(the "Acting as" picker becomes cosmetic until Task 7 removes it).

- [ ] **Step 9: Static checks**

```bash
cd web && npm run typecheck && npm run lint
```

Expected: both exit 0.

- [ ] **Step 10: Check it in the browser**

With the API and `npm run dev` running: as a guest, http://localhost:3000 shows "Sign in" / "Create account" and "Guest: sign in…". Sign in with the Task 1 test account → the header shows your name and the user button; the home page says "Hi, <first name>". In the browser's network panel, `GET /api/v1/me` carries `Authorization: Bearer …` and answers 200 with `"kind": "customer"`. Sign out → back to guest.

- [ ] **Step 11: Commit**

```bash
git add web/src/lib/api/schema.d.ts web/src/lib/api/client.ts web/src/components/api-auth.tsx web/src/lib/me.ts \
  web/src/app/layout.tsx web/src/components/shop/context.tsx web/src/components/shop/header.tsx \
  "web/src/app/(shop)/page.tsx" web/src/app/admin/inventory/page.tsx
git commit -m "Auth: the web app sends the Clerk token and shows who is signed in"
```

---

### Task 7: The store admin follows the signed-in staff member

**Files:**
- Create: `web/src/components/admin/staff-gate.tsx`
- Modify: `web/src/app/admin/layout.tsx`, `web/src/components/sidebar.tsx`
- Modify: `web/src/app/admin/inventory/page.tsx`, `web/src/app/admin/products/page.tsx`, `web/src/app/admin/products/[id]/page.tsx`, `web/src/app/admin/promotions/page.tsx`

**Interfaces:**
- Consumes: `useMe`, `Me` (Task 6).
- Produces: `<StaffGate>`, `useStaff(): Me`, `canEditCatalogue(me: Me): boolean` in `@/components/admin/staff-gate`.

- [ ] **Step 1: `web/src/components/admin/staff-gate.tsx`**

```tsx
"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { createContext, type ReactNode, useContext } from "react";

import { Button, ErrorBox } from "@/components/ui";
import type { Me } from "@/lib/api/client";
import { useMe } from "@/lib/me";

const StaffContext = createContext<Me | null>(null);

/** The signed-in staff member. Only inside <StaffGate>. */
export function useStaff(): Me {
  const me = useContext(StaffContext);
  if (!me) throw new Error("useStaff() must be used inside <StaffGate>");
  return me;
}

/** Store managers and support staff maintain the catalogue and promotions (spec §4.5). */
export function canEditCatalogue(me: Me): boolean {
  return me.staff_type === "support" || me.runs_store;
}

/** The admin is for staff. proxy.ts already sent signed-out visitors to sign-in; this checks who they are.
 *  It only decides what to show: the API refuses whatever a caller may not do, whatever the screen shows. */
export function StaffGate({ children }: { children: ReactNode }) {
  const session = useMe();
  if (session.status === "loading") {
    return <p className="p-8 text-sm text-neutral-500">Checking who you are…</p>;
  }
  if (session.status === "error") {
    return (
      <div className="space-y-3 p-8">
        <ErrorBox error={session.error} />
        <Button onClick={session.retry}>Try again</Button>
      </div>
    );
  }
  if (session.status === "guest" || session.me.kind !== "staff") {
    return (
      <div className="mx-auto max-w-md space-y-4 p-8 text-sm">
        <title>Staff only · JB Admin</title>
        <h1 className="text-xl font-bold">Staff only</h1>
        <p className="text-neutral-600">
          The store admin is for staff. Sign in with a staff account, or go back to the storefront.
        </p>
        <div className="flex items-center gap-3">
          <UserButton />
          <Link href="/" className="font-medium hover:underline">← Storefront</Link>
        </div>
      </div>
    );
  }
  return <StaffContext value={session.me}>{children}</StaffContext>;
}
```

- [ ] **Step 2: `web/src/app/admin/layout.tsx`**

```tsx
import { StaffGate } from "@/components/admin/staff-gate";
import { Sidebar } from "@/components/sidebar";

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <StaffGate>
      <div className="flex min-h-screen flex-col md:flex-row">
        <Sidebar />
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </StaffGate>
  );
}
```

- [ ] **Step 3: `web/src/components/sidebar.tsx` — who is signed in**

Add `import { UserButton } from "@clerk/nextjs";` and `import { useStaff } from "@/components/admin/staff-gate";`. Insert `<SignedInAs />` between the brand `<div className="flex items-center gap-2.5 px-5 py-5">…</div>` and the `<nav …>`. Add:

```tsx
function SignedInAs() {
  const me = useStaff();
  const role = me.staff_type === "support" ? "Support"
    : me.runs_store ? `Manager · ${me.store_name}` : `Staff · ${me.store_name}`;
  return (
    <div className="mx-3 mb-3 flex items-center gap-3 rounded-md bg-neutral-800/60 px-3 py-2">
      <UserButton />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-white">{me.display_name}</div>
        <div className="truncate text-xs text-neutral-400">{role}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: `web/src/app/admin/inventory/page.tsx` — your store, your name**

1. Imports: remove `type Staff, ` from the `@/lib/api/client` import; add `import { useStaff } from "@/components/admin/staff-gate";`.
2. Replace the first two state lines with:

```tsx
  const me = useStaff();
  // Store staff adjust their own store's stock; support staff look at any store but don't adjust (spec §4.5).
  const canAdjust = me.staff_type === "store";
  const [storeId, setStoreId] = useState(me.store_id ?? 1);
```

3. Delete `const staff = useLoad("staff", …);`, the two lines `// Until someone is picked, act as the store's manager.` / `const staffId = …;` and `const actor = …;`, and the `setChosenStaffId(undefined);` line in `changeStore`.
4. Replace the "Store" and "Acting as" fields with:

```tsx
          <Field label="Store">
            {canAdjust
              ? <p className="flex h-9 items-center text-sm font-medium">{store?.name ?? "…"}</p>
              : <StoreSelect stores={stores.data ?? []} value={storeId} onChange={changeStore} />}
          </Field>
          <Field label="Signed in as"
            hint={canAdjust ? "Every change is logged under your name (BR18)."
              : "Support staff can look at any store's stock but don't adjust it."}>
            <p className="flex h-9 items-center text-sm">{me.display_name}</p>
          </Field>
```

5. Wrap the row's `<div className="flex justify-end gap-1"> … </div>` (the −1 / +1 / Adjust… buttons) as `{canAdjust && (<div className="flex justify-end gap-1"> … </div>)}`.
6. In the `<AdjustDialog …>` element, replace `actor={actor}` with `actorName={me.display_name}`. In `function AdjustDialog`, replace `actor` with `actorName` in the parameter list, `actor?: Staff;` with `actorName: string;`, and the line `<p className="text-xs text-neutral-500">Logged as {actor?.full_name ?? "…"}.</p>` with `<p className="text-xs text-neutral-500">Logged as {actorName}.</p>`.
7. Delete the whole `function StaffSelect(…) { … }`.

- [ ] **Step 5: Products and promotions — edit controls only for managers and support**

`web/src/app/admin/products/page.tsx`: add `import { canEditCatalogue, useStaff } from "@/components/admin/staff-gate";`, add `const canEdit = canEditCatalogue(useStaff());` as the first line of `ProductsPage`, and change the header's actions to
`actions={canEdit ? <Button tone="primary" onClick={() => setCreating(true)}>New product</Button> : undefined}`.

`web/src/app/admin/products/[id]/page.tsx`: add the same import; add `const canEdit = canEditCatalogue(useStaff());` as the first line of `ProductPage` (before any early return); pass `readOnly={!canEdit}` to `<DetailsForm …>` and `<SpecsEditor …>`. In `DetailsForm` and `SpecsEditor`, add `readOnly` to the destructured props and `readOnly: boolean;` to their prop types, change each `<Card title=… actions={…}>` to `actions={readOnly ? undefined : (…the existing actions…)}`, and wrap each card's inner `<div className="space-y-… p-4"> … </div>` in `<fieldset disabled={readOnly}> … </fieldset>` (a disabled fieldset disables every input and button inside it).

`web/src/app/admin/promotions/page.tsx`: add the import; add `const canEdit = canEditCatalogue(useStaff());` as the first line of `PromotionsPage`; change the header's actions to
`actions={canEdit ? <Button tone="primary" onClick={() => setCreating(true)}>New promotion</Button> : undefined}`;
and the delete cell to
`<td className="px-4 py-2.5 text-right">{canEdit && <DeleteButton onConfirm={() => remove(p)} />}</td>`.

- [ ] **Step 6: Static checks**

```bash
cd web && npm run typecheck && npm run lint
```

Expected: both exit 0, and `grep -rn "staff_id\|StaffSelect\|chosenStaffId" src/app/admin` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/admin/staff-gate.tsx web/src/app/admin web/src/components/sidebar.tsx
git commit -m "Auth: the store admin is for staff, fixed to your store, with catalogue edits for managers and support"
```

---

### Task 8: Demo personas and the end-to-end walk-through

**Files:**
- Create: `scripts/clerk_personas.py`

**Interfaces:**
- Consumes: `CLERK_SECRET_KEY` (`.env`), `DEMO_PASSWORD` (shell); the whole stack.
- Produces: four Clerk dev users whose emails match seeded rows.

- [ ] **Step 1: Write `scripts/clerk_personas.py`**

```python
"""Create the four demo personas as Clerk development users (spec §7, step 6).

    DEMO_PASSWORD='…' .venv/bin/python scripts/clerk_personas.py

Reads CLERK_SECRET_KEY from .env; DEMO_PASSWORD comes from your shell and is never stored in the repo.
Each persona uses the email of its row in sql/10_seed_reference.sql, so the API links it to that row on
first sign-in (app/auth.py). A persona that already exists is left alone. Prints each email's
verification status: the API refuses unverified emails.
"""
import os
import sys

import httpx
from dotenv import load_dotenv

CLERK_API = "https://api.clerk.com/v1"
PERSONAS = [
    ("Alice", "Morgan", "alice.morgan@example.com"),            # customer
    ("Aiden", "Chen", "aiden.chen@jbhifi.example"),             # store staff, Sydney CBD
    ("Olivia", "Nguyen", "olivia.nguyen@jbhifi.example"),       # manager, Sydney CBD
    ("Nora", "Fitzgerald", "nora.fitzgerald@jbhifi.example"),   # support
]


def verification(user: dict) -> str:
    primary = next(e for e in user["email_addresses"] if e["id"] == user["primary_email_address_id"])
    return (primary.get("verification") or {}).get("status") or "unknown"


def main() -> int:
    load_dotenv()
    secret, password = os.environ.get("CLERK_SECRET_KEY"), os.environ.get("DEMO_PASSWORD")
    if not secret or not password:
        print("Set CLERK_SECRET_KEY (in .env) and DEMO_PASSWORD (in your shell) first.", file=sys.stderr)
        return 1
    clerk = httpx.Client(base_url=CLERK_API, headers={"Authorization": f"Bearer {secret}"}, timeout=10)
    failed = False
    for first, last, email in PERSONAS:
        found = clerk.get("/users", params={"email_address": email})
        found.raise_for_status()
        if found.json():
            print(f"exists   {email}  ({verification(found.json()[0])})")
            continue
        created = clerk.post("/users", json={"email_address": [email], "password": password,
                                              "first_name": first, "last_name": last,
                                              "skip_password_checks": True})
        if created.is_success:
            print(f"created  {email}  ({verification(created.json())})")
        else:
            failed = True
            print(f"REFUSED  {email}: {created.status_code} {created.text}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it**

```bash
read -rs DEMO_PASSWORD && export DEMO_PASSWORD     # type a password; it is not echoed
/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/python scripts/clerk_personas.py
```

Expected: four `created … (verified)` lines.

If any `@jbhifi.example` persona is `REFUSED` (Clerk rejects the reserved `.example` domain), or shows a status other than `verified`: create that persona in the Clerk Dashboard with an address Clerk accepts (e.g. `aiden.chen+clerk_test@example.com`), copy its user id (`user_…`), and link it directly — the email will not match the seeded row, so linking by email cannot find it:

```bash
docker exec jbhifi-db psql -U jbhifi -d jbhifi -v ON_ERROR_STOP=1 \
  -c "INSERT INTO user_account (auth_subject, staff_id) VALUES ('user_REPLACE_WITH_ID', 14)"
```

(staff ids: Aiden 14, Olivia 1, Nora 40). Record which personas needed this in `docs/superpowers/specs/2026-10-02-clerk-auth-design.md` §8.

- [ ] **Step 3: Walk through every persona**

API and web running. Use two browser profiles (one customer, one staff) side by side.

| Sign in as | Check |
|---|---|
| Alice Morgan | Storefront header shows "Alice Morgan"; home says "Hi, Alice" with her Pyrmont address. http://localhost:3000/admin shows "Staff only". |
| Aiden Chen | `/admin/inventory`: store fixed to Sydney CBD, "Signed in as Aiden Chen"; +1 on a product works and the log shows "Aiden Chen". Products: no "New product"; a product page's fields are disabled. Promotions: no "New promotion", no Delete. |
| Olivia Nguyen | As Aiden, plus "New product", editable product pages, "New promotion" and Delete. Sidebar: "Manager · Sydney CBD". |
| Nora Fitzgerald | Sidebar: "Support". Inventory: a store picker, no ± buttons; "New product" and "New promotion" visible. |
| A brand-new sign-up | Becomes a customer: storefront shows their name; `docker exec jbhifi-db psql -U jbhifi -d jbhifi -c "SELECT auth_subject, customer_id, staff_id FROM user_account ORDER BY linked_at"` lists them with a `customer_id`. |

- [ ] **Step 4: Final checks**

```bash
PY=/Users/ethan/Dev/Course/comp9120/JBhifi/.venv/bin/python
$PY -m pytest -q -p no:cacheprovider
cd web && npm run typecheck && npm run lint && clerk doctor
git -C .. status --short     # .env and web/.env.local must not appear
```

Expected: all tests pass; typecheck, lint and doctor clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/clerk_personas.py
git commit -m "Auth: script the four demo personas as Clerk development users"
```

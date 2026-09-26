"""Demo sessions and the actor the API acts as.

The browser's identity picker is only a *hint* about who to sign in as. The identity the API trusts comes
from a signed, HTTP-only cookie this module issues and verifies, so changing a request body, a URL or
browser storage cannot make the API act as a different customer or staff member. Sign-in itself is a
demo convenience (see ``demo_mode_enabled``); a real deployment replaces ``POST /session`` with proper
authentication and leaves the rest of this module, and every permission check below, unchanged.
"""
import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request

from app.db import DbCursor
from app.errors import ApiError

COOKIE_NAME = "jbhifi_session"


def _secret() -> str:
    """The cookie's signing key. The default is for local development only."""
    return os.environ.get("SESSION_SECRET", "dev-only-insecure-session-secret")


def demo_mode_enabled() -> bool:
    """Whether the demo sign-in endpoint accepts an identity. Read per request, so tests can toggle it."""
    return os.environ.get("DEMO_MODE", "1").strip().lower() not in ("0", "false", "no", "off", "")


def cookie_is_secure() -> bool:
    """Whether the session cookie carries `Secure`.

    Off by default because the demo runs over plain HTTP on localhost; a deployment served over HTTPS sets
    `COOKIE_SECURE=1` (or `SESSION_SECURE=1`) so the browser never sends the session over an insecure
    connection.
    """
    return os.environ.get("COOKIE_SECURE", "").strip().lower() not in ("", "0", "false", "no", "off")


# Hosts allowed to send a mutation with the session cookie. `SameSite=Lax` already stops a cross-site POST
# from carrying the cookie; this is the second line, and it also covers an old browser that ignores
# SameSite. Loopback is always allowed (the demo's web app runs on localhost, often on another port behind
# the Next.js proxy); anything else has to be listed in TRUSTED_ORIGINS.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"}


def trusted_origins() -> set[str]:
    raw = os.environ.get("TRUSTED_ORIGINS", "")
    return {origin.strip().rstrip("/").lower() for origin in raw.split(",") if origin.strip()}


def origin_is_trusted(origin: str, host: str | None) -> bool:
    """Is this `Origin` allowed to mutate with the cookie? See `LOOPBACK_HOSTS`."""
    candidate = origin.strip().rstrip("/").lower()
    if candidate in trusted_origins():
        return True
    if host is not None and candidate.removeprefix("http://").removeprefix("https://") == host.lower():
        return True
    hostname = candidate.split("://", 1)[-1].split("/", 1)[0]
    if "@" in hostname:
        hostname = hostname.rsplit("@", 1)[1]
    if hostname.startswith("["):                      # an IPv6 literal, e.g. [::1]:3000
        return hostname.split("]")[0] + "]" in LOOPBACK_HOSTS
    return hostname.rsplit(":", 1)[0] in LOOPBACK_HOSTS


def sign_session(payload: dict) -> str:
    """base64url(JSON) + '.' + HMAC-SHA256, so the browser cannot invent or edit an identity."""
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    mac = hmac.new(_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def read_session(request: Request) -> dict | None:
    """The verified session payload, or None when there is no cookie or it does not check out."""
    token = request.cookies.get(COOKIE_NAME)
    if not token or "." not in token:
        return None
    body, _, mac = token.rpartition(".")
    expected = hmac.new(_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("kind") not in ("customer", "staff"):
        return None
    if not isinstance(payload.get("id"), int):
        return None
    return payload


@dataclass(frozen=True)
class Actor:
    kind: Literal["customer", "staff"]
    id: int
    display_name: str
    store_id: int | None = None
    store_name: str | None = None
    staff_type: str | None = None
    runs_store: bool = False          # True when this staff member manages their store (BR04)

    @property
    def is_support(self) -> bool:
        return self.kind == "staff" and self.staff_type == "support"

    @property
    def is_manager(self) -> bool:
        return self.kind == "staff" and self.staff_type == "store" and self.runs_store


def load_actor(cur, session: dict | None) -> Actor | None:
    """Re-read the identity from the database, so a deleted customer or staff row ends the session."""
    if session is None:
        return None
    if session["kind"] == "customer":
        cur.execute("SELECT full_name FROM customer WHERE customer_id = %s", (session["id"],))
        row = cur.fetchone()
        return None if row is None else Actor("customer", session["id"], row["full_name"])
    cur.execute(
        """
        SELECT st.full_name, st.staff_type, st.store_id, s.name AS store_name,
               COALESCE(s.manager_id = st.staff_id, FALSE) AS runs_store
        FROM staff st
        LEFT JOIN store s ON s.store_id = st.store_id
        WHERE st.staff_id = %s
        """,
        (session["id"],),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return Actor("staff", session["id"], row["full_name"], row["store_id"], row["store_name"],
                 row["staff_type"], row["runs_store"])


def current_actor(request: Request, cur: DbCursor) -> Actor | None:
    """Who this request is, from the signed cookie. None for a guest."""
    return load_actor(cur, read_session(request))


CurrentActor = Annotated[Actor | None, Depends(current_actor)]


def require_actor(actor: CurrentActor) -> Actor:
    """A dependency that turns "who is this" into "there must be somebody"."""
    if actor is None:
        raise ApiError(401, "not_signed_in", "Sign in (demo) to do that.")
    return actor


RequiredActor = Annotated[Actor, Depends(require_actor)]


def require_customer_self(actor: Actor | None, customer_id: int) -> Actor:
    """The customer's own record, or support staff looking it up."""
    actor = require_actor(actor)
    if actor.kind == "customer":
        if actor.id != customer_id:
            raise ApiError(403, "not_your_account", "That account belongs to another customer.")
        return actor
    if actor.is_support:
        return actor
    raise ApiError(403, "staff_cannot_read_this", "Store staff may only read their own store's work.")


def require_customer(actor: Actor | None) -> Actor:
    """Shopping is done by the customer whose session this is."""
    actor = require_actor(actor)
    if actor.kind != "customer":
        raise ApiError(403, "customer_only", "Sign in as a customer to shop.")
    return actor


def require_store_staff(actor: Actor | None, store_id: int) -> Actor:
    """The staff member whose store this is. Support staff read across stores but do not handle stock."""
    actor = require_actor(actor)
    if actor.kind != "staff":
        raise ApiError(403, "staff_only", "Only staff can do that.")
    if actor.is_support:
        raise ApiError(403, "store_staff_only", "Stock is adjusted by the store's own staff.")
    if actor.store_id != store_id:
        raise ApiError(403, "other_store", "You can only act on your own store.")
    return actor


def require_catalogue_writer(actor: Actor | None) -> Actor:
    """Catalogue and promotions: the stores' managers and the support team maintain them."""
    actor = require_actor(actor)
    if actor.kind != "staff":
        raise ApiError(403, "staff_only", "Only staff can change the catalogue.")
    if not (actor.is_support or actor.is_manager):
        raise ApiError(403, "manager_only", "Only a store manager or support staff can change the catalogue.")
    return actor


def require_store_or_support_reader(actor: Actor | None, store_id: int) -> Actor:
    """Reading a store's operational records: that store's staff, or support from anywhere."""
    actor = require_actor(actor)
    if actor.kind != "staff":
        raise ApiError(403, "staff_only", "Only staff can read that.")
    if not actor.is_support and actor.store_id != store_id:
        raise ApiError(403, "other_store", "You can only read your own store's records.")
    return actor


def session_payload(actor: Actor) -> dict:
    return {
        "kind": actor.kind,
        "id": actor.id,
        "display_name": actor.display_name,
        "store_id": actor.store_id,
        "store_name": actor.store_name,
        "staff_type": actor.staff_type,
        "runs_store": actor.runs_store,
    }

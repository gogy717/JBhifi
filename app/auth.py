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
    # Two first requests at once: the second waits for the first's row, then does nothing. No conflict target,
    # so this holds whichever unique index the two collide on — this subject (the PK) or this person (BR19's
    # UNIQUEs): an existing customer or staff member signing in for the first time collides on the latter.
    cur.execute(
        """
        INSERT INTO user_account (auth_subject, customer_id, staff_id) VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (subject, customer_id, None if staff is None else staff["staff_id"]),
    )
    account = _account(cur, subject)
    if account is None:                 # the person is already linked to a *different* sign-in (BR19)
        raise ApiError(409, "br19_account_one_customer" if staff is None else "br19_account_one_staff",
                       "This person is already linked to a different sign-in. Ask support to unlink the old one.")
    return account


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


def require_customer(actor: Actor | None) -> Actor:
    """Shopping, and a customer's own account, are for signed-in customers: staff sign-ins can't do them."""
    actor = require_actor(actor)
    if actor.kind != "customer":
        raise ApiError(403, "customer_only", "Sign in as a customer to shop.")
    return actor


def require_own_account(actor: Actor | None, customer_id: int) -> Actor:
    """Changing a customer's own account (their addresses): that customer only. Support staff can look an
    account up (require_customer_self) but never change it for the customer."""
    actor = require_customer(actor)
    if actor.id != customer_id:
        raise ApiError(403, "not_your_account", "That account belongs to another customer.")
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


def require_order_reader(actor: Actor | None, order: dict | None) -> Actor:
    """Reading one order: its customer, staff of the store fulfilling it, or support staff (any order).

    `order` is the order's row, or None when there is no such order. Customers and store staff get the same
    403 for a missing order as for someone else's, so they can't probe which order ids exist; only support,
    who may read every order, is then told 404 (by the service).
    """
    actor = require_actor(actor)
    if actor.is_support:
        return actor
    if actor.kind == "customer":
        if order is None or order["customer_id"] != actor.id:
            raise ApiError(403, "not_your_order", "That order isn't one of yours.")
        return actor
    if order is None or order["fulfilling_store_id"] != actor.store_id:
        raise ApiError(403, "other_store", "You can only read your own store's orders.")
    return actor

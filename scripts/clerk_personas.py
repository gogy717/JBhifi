"""Create the four demo personas as Clerk development users (spec §7, step 6) and link them to their rows.

    DEMO_PASSWORD='…' .venv/bin/python scripts/clerk_personas.py     # create, or set every persona's password
    .venv/bin/python scripts/clerk_personas.py                       # only link existing personas (after a rebuild)

Reads CLERK_SECRET_KEY and the POSTGRES_* settings from .env; DEMO_PASSWORD comes from your shell and is
never stored in the repo. Clerk checks it like any password — at least 15 characters here, and not one
found in a known breach (Clerk refuses those at sign-in) — and re-running the script sets every persona's
password to the current DEMO_PASSWORD.

Every persona signs in with a Clerk test address (`…+clerk_test@example.com`): this instance runs in test
mode, so when Clerk asks a new browser for an email code (Device Trust), the code is 424242 — nobody needs a
real inbox. Those addresses don't match the seeded rows (and Clerk refuses the staff rows' reserved `.example`
addresses anyway), so each persona is linked to its row here, in user_account, before it ever signs in
(spec §8) — otherwise the first sign-in would find no matching email and create a new customer.
A persona that already exists gets the new password (and its link, if that is missing).
"""
import os
import sys

import httpx
import psycopg2
from dotenv import load_dotenv

CLERK_API = "https://api.clerk.com/v1"
# (first name, last name, email to sign in with, the row to link: ("customer", seeded email) or ("staff", id))
PERSONAS = [
    ("Alice", "Morgan", "alice.morgan+clerk_test@example.com", ("customer", "alice.morgan@example.com")),
    ("Aiden", "Chen", "aiden.chen+clerk_test@example.com", ("staff", 14)),             # store staff, Sydney CBD
    ("Olivia", "Nguyen", "olivia.nguyen+clerk_test@example.com", ("staff", 1)),        # manager, Sydney CBD
    ("Nora", "Fitzgerald", "nora.fitzgerald+clerk_test@example.com", ("staff", 40)),   # support
]


def verification(user: dict) -> str:
    primary = next(e for e in user["email_addresses"] if e["id"] == user["primary_email_address_id"])
    return (primary.get("verification") or {}).get("status") or "unknown"


def reasons(response: httpx.Response) -> str:
    errors = response.json().get("errors", []) if response.content else []
    return "; ".join(e.get("long_message") or e.get("message", "") for e in errors) or response.text


def link(db, subject: str, row: tuple) -> str:
    """Link the Clerk user to its customer (by seeded email) or staff row; report what the link is."""
    kind, key = row
    with db, db.cursor() as cur:
        if kind == "customer":
            cur.execute("SELECT customer_id FROM customer WHERE email = %s", (key,))
            cur.execute("INSERT INTO user_account (auth_subject, customer_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (subject, cur.fetchone()[0]))
        else:
            cur.execute("INSERT INTO user_account (auth_subject, staff_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (subject, key))
        cur.execute("SELECT customer_id, staff_id FROM user_account WHERE auth_subject = %s", (subject,))
        linked = cur.fetchone()
    if linked is None:
        return f"NOT LINKED: that {kind} row already signs in with another Clerk account"
    customer_id, staff_id = linked
    return f"linked to customer {customer_id}" if customer_id is not None else f"linked to staff {staff_id}"


def main() -> int:
    load_dotenv()
    secret, password = os.environ.get("CLERK_SECRET_KEY"), os.environ.get("DEMO_PASSWORD")
    if not secret:
        print("Set CLERK_SECRET_KEY (in .env) first.", file=sys.stderr)
        return 1
    clerk = httpx.Client(base_url=CLERK_API, headers={"Authorization": f"Bearer {secret}"}, timeout=10)
    db = psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
                          dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
                          password=os.environ["POSTGRES_PASSWORD"])
    failed = False
    for first, last, email, row in PERSONAS:
        found = clerk.get("/users", params={"email_address": email})
        found.raise_for_status()
        existing = found.json()
        if existing and not password:                 # link only: leave the password alone
            user, action = existing[0], "exists "
        elif not password:
            failed = True
            print(f"MISSING  {email}: set DEMO_PASSWORD to create it", file=sys.stderr)
            continue
        else:
            if existing:
                # Password checks are not skipped: a breached or short password is refused here, not at sign-in.
                response, action = clerk.patch(f"/users/{existing[0]['id']}", json={"password": password}), "updated"
            else:
                # This Clerk application also requires a username: e.g. alice_morgan.
                response, action = clerk.post("/users", json={"email_address": [email], "password": password,
                                                               "username": f"{first}_{last}".lower(),
                                                               "first_name": first, "last_name": last}), "created"
            if not response.is_success:
                failed = True
                print(f"REFUSED  {email}: {reasons(response)}", file=sys.stderr)
                continue
            user = response.json()
        print(f"{action}  {email}  ({verification(user)}, {link(db, user['id'], row)})")
    db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

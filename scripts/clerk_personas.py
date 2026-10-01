"""Create the four demo personas as Clerk development users (spec §7, step 6) and link the staff ones.

    DEMO_PASSWORD='…' .venv/bin/python scripts/clerk_personas.py

Reads CLERK_SECRET_KEY and the POSTGRES_* settings from .env; DEMO_PASSWORD comes from your shell and is
never stored in the repo. Clerk checks it like any password — at least 15 characters here, and not one
found in a known breach (Clerk refuses those at sign-in) — and re-running the script sets every persona's
password to the current DEMO_PASSWORD.

Alice signs in with her seeded email, so the API links her to her customer row on first sign-in
(app/auth.py). Clerk refuses the staff rows' reserved `.example` addresses, so each staff persona gets a
Clerk test address instead and is linked to its staff row here, in user_account, before it ever signs in
(spec §8) — otherwise the first sign-in would find no staff email and create a customer.
A persona that already exists gets the new password (and its staff link, if that is missing).
"""
import os
import sys

import httpx
import psycopg2
from dotenv import load_dotenv

CLERK_API = "https://api.clerk.com/v1"
# (first name, last name, email to sign in with, staff_id to link directly — None links by email)
PERSONAS = [
    ("Alice", "Morgan", "alice.morgan@example.com", None),                  # customer
    ("Aiden", "Chen", "aiden.chen+clerk_test@example.com", 14),             # store staff, Sydney CBD
    ("Olivia", "Nguyen", "olivia.nguyen+clerk_test@example.com", 1),        # manager, Sydney CBD
    ("Nora", "Fitzgerald", "nora.fitzgerald+clerk_test@example.com", 40),   # support
]


def verification(user: dict) -> str:
    primary = next(e for e in user["email_addresses"] if e["id"] == user["primary_email_address_id"])
    return (primary.get("verification") or {}).get("status") or "unknown"


def reasons(response: httpx.Response) -> str:
    errors = response.json().get("errors", []) if response.content else []
    return "; ".join(e.get("long_message") or e.get("message", "") for e in errors) or response.text


def link_staff(db, subject: str, staff_id: int) -> str:
    with db, db.cursor() as cur:
        cur.execute("INSERT INTO user_account (auth_subject, staff_id) VALUES (%s, %s) "
                    "ON CONFLICT (auth_subject) DO NOTHING", (subject, staff_id))
        cur.execute("SELECT staff_id FROM user_account WHERE auth_subject = %s", (subject,))
        linked = cur.fetchone()[0]
    return f"linked to staff {linked}" if linked == staff_id else f"ALREADY LINKED to staff {linked}"


def main() -> int:
    load_dotenv()
    secret, password = os.environ.get("CLERK_SECRET_KEY"), os.environ.get("DEMO_PASSWORD")
    if not secret or not password:
        print("Set CLERK_SECRET_KEY (in .env) and DEMO_PASSWORD (in your shell) first.", file=sys.stderr)
        return 1
    clerk = httpx.Client(base_url=CLERK_API, headers={"Authorization": f"Bearer {secret}"}, timeout=10)
    db = psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
                          dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
                          password=os.environ["POSTGRES_PASSWORD"])
    failed = False
    for first, last, email, staff_id in PERSONAS:
        found = clerk.get("/users", params={"email_address": email})
        found.raise_for_status()
        if found.json():
            # Password checks are not skipped: a breached or short password is refused here, not at sign-in.
            response, action = clerk.patch(f"/users/{found.json()[0]['id']}", json={"password": password}), "updated"
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
        link = "" if staff_id is None else ", " + link_staff(db, user["id"], staff_id)
        print(f"{action}  {email}  ({verification(user)}{link})")
    db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

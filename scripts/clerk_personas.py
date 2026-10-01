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

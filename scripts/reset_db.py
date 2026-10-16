"""Rebuild the dev database from sql/ and re-link the demo personas.

    .venv/bin/python scripts/reset_db.py          (Windows: .venv\\Scripts\\python scripts\\reset_db.py)

Drops and recreates the database named by POSTGRES_DB in .env, runs sql/*.sql in filename order — as the
container does on an empty volume, and as the tests do — then links the Clerk demo personas to their rows
(scripts/clerk_personas.py without DEMO_PASSWORD: link only, no Clerk account is changed). The database server
must be up (`docker compose up -d` in the main checkout). Only POSTGRES_DB is touched, and never a system
database or the test database. scripts/demo.py --reset calls this, so it asks no questions.
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
SYSTEM_DATABASES = {"postgres", "template0", "template1"}
# The test database when .env names none: the same default as tests/support.py, which pytest drops and rebuilds.
# tests/test_reset_db.py checks the two stay equal (this script can't import tests/support.py: importing it
# points POSTGRES_DB at the test database).
DEFAULT_TEST_DB = "jbhifi_test"


def test_database_name() -> str:
    """The database pytest uses: POSTGRES_TEST_DB, or the tests' default when .env names none."""
    return os.environ.get("POSTGRES_TEST_DB", DEFAULT_TEST_DB)


def refusal(dbname: str | None, test_dbname: str | None) -> str | None:
    """Why dbname must not be dropped, or None when it may be."""
    if not dbname:
        return "POSTGRES_DB is empty in .env"
    if dbname in SYSTEM_DATABASES:
        return f"{dbname} is a PostgreSQL system database"
    if dbname == test_dbname:
        return (f"{dbname} is the test database (POSTGRES_TEST_DB, by default {DEFAULT_TEST_DB}), which pytest drops "
                "and rebuilds: give the dev database another name in .env")
    return None


def connect(dbname: str):
    return psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"], dbname=dbname,
                            user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"])


def rebuild(dbname: str) -> None:
    """Drop and create dbname, then run every sql/ file in it, in filename order."""
    admin = connect("postgres")
    admin.autocommit = True                         # CREATE / DROP DATABASE can't run inside a transaction
    with admin.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    admin.close()

    conn = connect(dbname)
    conn.autocommit = True                          # the files manage their own transactions
    with conn.cursor() as cur:
        for path in sorted(SQL_DIR.glob("*.sql")):
            print(f"  {path.name}")
            cur.execute(path.read_text(encoding="utf-8"))   # the files are UTF-8; Windows defaults to cp1252
    conn.close()


def link_personas() -> bool:
    """Link the demo personas (clerk_personas.py, link only). False, with the reason printed, when it can't."""
    import httpx

    sys.path.insert(0, str(ROOT / "scripts"))
    import clerk_personas

    os.environ.pop("DEMO_PASSWORD", None)           # link only: never change a persona's password from here
    try:
        return clerk_personas.main() == 0
    except httpx.HTTPError as error:
        print(f"Couldn't reach Clerk ({error}).", file=sys.stderr)
        return False


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)     # keep stdout and stderr in order when piped to a log
    load_dotenv(ROOT / ".env")
    dbname = os.environ.get("POSTGRES_DB")
    reason = refusal(dbname, test_database_name())
    if reason:
        print(f"Not resetting: {reason}.", file=sys.stderr)
        return 1
    print(f"About to drop and rebuild the database {dbname} from sql/:")
    try:
        rebuild(dbname)
    except psycopg2.OperationalError as error:
        print(f"Can't reach the database server: {error}Start it first (docker compose up -d, in the main "
              "checkout).", file=sys.stderr)
        return 1
    print(f"Rebuilt {dbname}. Linking the demo personas (needs the internet: Clerk)…")
    if not link_personas():
        print(f"The database {dbname} is rebuilt, but the demo personas are not linked yet. Once Clerk can be "
              "reached, run scripts/clerk_personas.py (no password needed to link).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

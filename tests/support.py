"""How tests reach the test database. Imported by conftest.py before the app, so the app uses it too.

The test database is deliberately separate from the demo database, and its name is asserted before any
fixture drops or rebuilds it (see ``assert_is_test_database``). Point ``POSTGRES_TEST_DB`` at another
database only when that database is disposable.
"""
import os
import uuid

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()

# The name of the disposable database the fixtures drop and rebuild. Overridable, but must stay clearly
# test-shaped so a misconfiguration can't point it at the demo database.
#
# `pytest-xdist` runs several workers inside one session, and each one rebuilds the database at the start.
# Sharing one name means one worker drops the database another is halfway through, which shows up as
# unrelated failures, so a worker gets its own database unless `POSTGRES_TEST_DB` says otherwise.
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
TEST_DB = os.environ.get("POSTGRES_TEST_DB") or (f"jbhifi_{_WORKER}_test" if _WORKER else "jbhifi_test")
# app/db.py reads POSTGRES_DB on every connect, so the API under test talks to the test database.
os.environ["POSTGRES_DB"] = TEST_DB


def assert_is_test_database(dbname: str) -> None:
    """Refuse to let a fixture destroy a database that doesn't look like a test one.

    Every fixture that drops or rebuilds a database runs this first. ``jbhifi`` (the demo database named
    in docker-compose.yml) can never be selected, so ``pytest`` is safe to run against the running stack.
    """
    if dbname == os.environ.get("POSTGRES_DB_DEMO", "jbhifi"):
        raise RuntimeError(
            f"refusing to run tests against the demo database {dbname!r}: "
            f"set POSTGRES_TEST_DB to a disposable database name"
        )
    if not dbname.endswith(("_test", "_demo")):
        raise RuntimeError(
            f"refusing to drop/rebuild {dbname!r}: the test database name must end in _test or _demo "
            f"(POSTGRES_TEST_DB)"
        )


def connect(dbname: str = TEST_DB):
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=dbname,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        cursor_factory=RealDictCursor,
    )


APP_USER = os.environ.get("POSTGRES_APP_USER", "jbhifi_app")
APP_PASSWORD = os.environ.get("POSTGRES_APP_PASSWORD", "apppassword")


def connect_app(dbname: str = TEST_DB):
    """A connection as the least-privilege application role, for permission tests."""
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=dbname,
        user=APP_USER,
        password=APP_PASSWORD,
        cursor_factory=RealDictCursor,
    )


def unique_sku() -> str:
    return f"TEST-{uuid.uuid4().hex[:10].upper()}"

"""Test harness: a separate database (POSTGRES_TEST_DB, default jbhifi_test) in the same container, rebuilt
from sql/ once per run.

Each test gets its own connection, and everything it does is rolled back afterwards, so every test
starts from the seed data. Tests that have to commit (API and concurrency tests) work on rows they
create themselves.
"""
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from tests.support import TEST_DB, connect               # first: points the app at the test database

from app import identity                                # noqa: E402
from tests.auth_support import ISSUER, PARTY, OwnKeys, fake_fetch_profile   # noqa: E402

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Drop and recreate the test database, then run sql/*.sql in filename order, as Docker does."""
    admin = connect("postgres")
    admin.autocommit = True                     # CREATE DATABASE can't run inside a transaction
    with admin.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    admin.close()

    conn = connect()
    conn.autocommit = True                      # the files manage their own transactions
    with conn.cursor() as cur:
        for path in sorted(SQL_DIR.glob("*.sql")):
            cur.execute(path.read_text())
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def fake_clerk():
    """Tests never call Clerk: tokens are checked against the tests' own key (tests/auth_support.py)."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CLERK_ISSUER", ISSUER)
        patch.setenv("AUTH_AUTHORIZED_PARTIES", f"{PARTY},http://127.0.0.1:3000")
        patch.setattr(identity, "_jwks_client", lambda url: OwnKeys())
        patch.setattr(identity, "fetch_profile", fake_fetch_profile)
        yield


@pytest.fixture
def db():
    """A connection to the test database. Whatever the test did is rolled back afterwards."""
    conn = connect()
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def cur(db):
    with db.cursor() as cur:
        yield cur


@pytest.fixture
def violates(cur):
    """violates(constraint, query, params): assert the statement is rejected by that named constraint.

    The statement runs inside a savepoint, so the test's transaction survives the error and the test
    can carry on.
    """
    def check(constraint: str, query: str, params=None):
        cur.execute("SAVEPOINT rule_check")
        with pytest.raises(psycopg2.Error) as caught:
            cur.execute(query, params)
        cur.execute("ROLLBACK TO SAVEPOINT rule_check")
        error = caught.value
        assert error.diag.constraint_name == constraint, error.pgerror
        assert error.pgcode.startswith("23"), error.pgerror   # integrity violation → the API's 409
    return check


@pytest.fixture
def product_id(cur):
    """product_id(sku) → the id of a seeded product."""
    def lookup(sku: str) -> int:
        cur.execute("SELECT product_id FROM product WHERE sku = %s", (sku,))
        return cur.fetchone()["product_id"]
    return lookup

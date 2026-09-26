"""Test harness: a separate database, jbhifi_test, in the same container, rebuilt from sql/ once per run.

Each test gets its own connection, and everything it does is rolled back afterwards, so every test
starts from the seed data. Tests that have to commit (API and concurrency tests) work on rows they
create themselves.
"""
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from tests.support import TEST_DB, assert_is_test_database, connect

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Drop and recreate jbhifi_test, then run sql/*.sql in filename order, as Docker does."""
    assert_is_test_database(TEST_DB)            # never let a misconfiguration drop the demo database
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

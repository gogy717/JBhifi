"""How tests reach the test database. Imported by conftest.py before the app, so the app uses it too."""
import os
import uuid

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()
TEST_DB = "jbhifi_test"
# app/db.py reads POSTGRES_DB on every connect, so the API under test talks to the test database.
os.environ["POSTGRES_DB"] = TEST_DB


def connect(dbname: str = TEST_DB):
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=dbname,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        cursor_factory=RealDictCursor,
    )


def unique_sku() -> str:
    return f"TEST-{uuid.uuid4().hex[:10].upper()}"

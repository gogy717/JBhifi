import os
from typing import Annotated

import psycopg2
from dotenv import load_dotenv
from fastapi import Depends
from psycopg2.extras import RealDictCursor

load_dotenv()


def credentials() -> tuple[str, str]:
    """Who the API connects as.

    The API runs as the least-privilege application role (`POSTGRES_APP_USER`, created by
    sql/05_permissions.sql) whenever one is configured, so a request cannot rewrite history or change the
    schema. Without that setting it falls back to the owner credentials, which is what the demo's
    bootstrap and the test harness use.
    """
    user = os.environ.get("POSTGRES_APP_USER") or os.environ["POSTGRES_USER"]
    password = os.environ.get("POSTGRES_APP_PASSWORD") or os.environ["POSTGRES_PASSWORD"]
    return user, password


def get_connection():
    user, password = credentials()
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=user,
        password=password,
    )


def get_cursor():
    conn = get_connection()
    try:
        with conn:                      # 正常结束 → commit；抛异常 → rollback
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur               # ← 路由函数在这一刻执行
    finally:
        conn.close()


DbCursor = Annotated[RealDictCursor, Depends(get_cursor, scope="function")]

import os
from typing import Annotated

import psycopg2
from dotenv import load_dotenv
from fastapi import Depends
from psycopg2.extras import RealDictCursor

load_dotenv()


def get_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
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

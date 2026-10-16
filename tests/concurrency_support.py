"""Running two transactions against each other, one step at a time (concurrency evidence spec §1).

Each transaction is its own connection: not in autocommit, its isolation level its first statement, and a
lock_timeout, so a locking regression fails a test instead of hanging it. Steps that can't block run in the test's
own thread, in a fixed order. A statement that will block runs in another thread (concurrent.futures), and
wait_until_blocked() polls pg_stat_activity until that connection is waiting for a lock, so the test takes its next
step only once it is. No sleeps decide the order.
"""
import time

import psycopg2
from psycopg2 import sql

from tests.support import connect

ISOLATION_LEVELS = ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE")
LOCK_TIMEOUT = "10s"


def begin(isolation: str = "READ COMMITTED"):
    """A new connection with a transaction open at this isolation level. In REPEATABLE READ and SERIALIZABLE the
    transaction's snapshot is taken here, by the first query (set_config), before any later step."""
    assert isolation in ISOLATION_LEVELS, isolation
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(sql.SQL(isolation)))
        cur.execute("SELECT set_config('lock_timeout', %s, true)", (LOCK_TIMEOUT,))
    return conn


def run(conn, query, params=()) -> int:
    """One statement on this transaction; returns how many rows it touched."""
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.rowcount


def timed(work):
    """work() in a thread's terms: returns (its result, seconds it took) — for a statement that waits for a lock,
    how long it waited. Measured around the call, so it includes the polling step that released it."""
    started = time.monotonic()
    result = work()
    return result, round(time.monotonic() - started, 2)


def wait_until_blocked(conn, timeout: float = 5.0) -> None:
    """Return once the backend behind conn is waiting for a lock (pg_stat_activity.wait_event_type = 'Lock');
    fail if it never is, so a test can't pass without the wait it is about."""
    pid = conn.get_backend_pid()
    watcher = connect()
    watcher.autocommit = True                 # every poll its own transaction, so it reads fresh activity
    try:
        with watcher.cursor() as cur:
            deadline = time.monotonic() + timeout
            while True:
                cur.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (pid,))
                row = cur.fetchone()
                if row is not None and row["wait_event_type"] == "Lock":
                    return
                if time.monotonic() > deadline:
                    raise AssertionError(f"backend {pid} never waited for a lock")
                time.sleep(0.01)
    finally:
        watcher.close()


def outcome(future, timeout: float = 15.0):
    """A finished thread's result, or the database error it raised (any other exception still fails the test)."""
    try:
        return future.result(timeout=timeout)
    except psycopg2.Error as error:
        return error


def close_all(*conns) -> None:
    """Roll back whatever is still open and close every connection, even after a failed step."""
    for conn in conns:
        if conn is None or conn.closed:
            continue
        try:
            conn.rollback()
        except psycopg2.Error:
            pass
        conn.close()

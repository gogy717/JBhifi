"""Concurrency evidence for report §4 (docs/concurrency-evidence.md): for each anomaly, a test of the faulty pattern
— what goes wrong, and how PostgreSQL reports it — and a test of the pattern this project uses. Every transaction
is its own connection, interleaved step by step (tests/concurrency_support.py). Each test prints one line of
results; `pytest -s` shows them, and the document quotes them.

These tests commit, so each works on rows it makes itself.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg2
from psycopg2 import errors

from tests.checkout_support import a_product, quantity_at
from tests.concurrency_support import begin, close_all, outcome, run, timed, wait_until_blocked

SYDNEY_CBD = 1
# After a racing transaction is seen waiting, the holder keeps its lock this long before committing. Only so the
# printed waits show what B waited for; the order of the steps comes from wait_until_blocked, never from sleeping.
HOLD = 0.3


def say(scenario: str, text: str) -> None:
    print(f"\n[{scenario}] {text}")


# ---------------------------------------------------------------- 1. lost update: two customers, the last unit

READ_STOCK = "SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s"
WRITE_BACK = "UPDATE inventory SET quantity = %s WHERE store_id = %s AND product_id = %s"
SELL_ONE = """UPDATE inventory SET quantity = quantity - 1
              WHERE store_id = %s AND product_id = %s AND quantity >= 1"""


def test_read_then_write_back_loses_an_update_and_sells_the_last_unit_twice():
    """Faulty: read the stock, work out the new quantity in Python, write it back as a value. Both customers read 1
    before either writes, so both write 0: one unit, two sales. No statement writes a negative number, so BR03's
    CHECK (quantity >= 0) never fires — it can't catch this."""
    product = a_product("999.00", stock=1)["product_id"]
    a, b = begin(), begin()
    try:
        seen = []
        for conn in (a, b):                                   # both read before either writes
            with conn.cursor() as cur:
                cur.execute(READ_STOCK, (SYDNEY_CBD, product))
                seen.append(cur.fetchone()["quantity"])
        sales = 0
        for conn, quantity in zip((a, b), seen):
            if quantity >= 1:                                 # "in stock", by what this customer read
                run(conn, WRITE_BACK, (quantity - 1, SYDNEY_CBD, product))
                conn.commit()
                sales += 1
        left = quantity_at(SYDNEY_CBD, product)
        say("1 lost update · faulty", f"A read {seen[0]}, B read {seen[1]}; both wrote back {seen[0] - 1} and "
            f"committed -> {sales} sales, stock left {left}, no CHECK violation")
        assert (seen, sales, left) == ([1, 1], 2, 0)
    finally:
        close_all(a, b)


def test_conditional_update_sells_the_last_unit_once():
    """Ours (T1's stock step): the decrement and the check are one statement. B's UPDATE waits for A's row lock;
    when A commits, PostgreSQL re-evaluates B's WHERE on the newest version of the row (quantity 0) and B updates
    no row — refused cleanly, under READ COMMITTED."""
    product = a_product("999.00", stock=1)["product_id"]
    a, b = begin(), begin()
    try:
        a_rows = run(a, SELL_ONE, (SYDNEY_CBD, product))
        with ThreadPoolExecutor(max_workers=1) as pool:
            b_sale = pool.submit(timed, lambda: run(b, SELL_ONE, (SYDNEY_CBD, product)))
            wait_until_blocked(b)                             # B is waiting for A's row lock
            time.sleep(HOLD)
            a.commit()
            b_rows, b_waited = outcome(b_sale)
        b.commit()
        left = quantity_at(SYDNEY_CBD, product)
        say("1 lost update · ours", f"A updated {a_rows} row; B waited {b_waited}s for A's row lock (polled until "
            f"blocked), then updated {b_rows} rows -> 1 sale, stock left {left}")
        assert (a_rows, b_rows, left) == (1, 0, 0)
    finally:
        close_all(a, b)


def test_conditional_update_under_repeatable_read_fails_with_a_serialization_error_instead():
    """What changes under REPEATABLE READ (plan §5): B still waits for A's row lock, but when A commits B may not
    update a row that changed after its snapshot, so it fails with 40001 instead of updating 0 rows. Every service
    would then have to catch the error and retry the whole transaction."""
    product = a_product("999.00", stock=1)["product_id"]
    a, b = begin("REPEATABLE READ"), begin("REPEATABLE READ")
    try:
        a_rows = run(a, SELL_ONE, (SYDNEY_CBD, product))
        with ThreadPoolExecutor(max_workers=1) as pool:
            b_sale = pool.submit(lambda: run(b, SELL_ONE, (SYDNEY_CBD, product)))
            wait_until_blocked(b)
            a.commit()
            b_result = outcome(b_sale)
        left = quantity_at(SYDNEY_CBD, product)
        say("1 lost update · repeatable read", f"A updated {a_rows} row; B -> {type(b_result).__name__} "
            f"{getattr(b_result, 'pgcode', '')}: {str(b_result).strip()} -> stock left {left}")
        assert isinstance(b_result, errors.SerializationFailure), b_result
        assert (b_result.pgcode, a_rows, left) == ("40001", 1, 0)
    finally:
        close_all(a, b)


# ---------------------------------------------------------------- 2. deadlock: two rows locked in opposite orders

TAKE_ONE = "UPDATE inventory SET quantity = quantity - 1 WHERE store_id = %s AND product_id = %s"


def two_stocked_products() -> tuple[int, int]:
    """Two new products with 5 units each at Sydney CBD, lower product_id first."""
    first, second = sorted(a_product("10.00", stock=5)["product_id"] for _ in range(2))
    return first, second


def take_and_commit(conn, product_id: int) -> str:
    run(conn, TAKE_ONE, (SYDNEY_CBD, product_id))
    conn.commit()
    return "committed"


def test_locking_two_rows_in_opposite_orders_deadlocks_and_postgres_aborts_one():
    """Faulty: A takes P1 then P2, B takes P2 then P1. Each holds the row the other wants next, so neither can go on.
    PostgreSQL finds the cycle (after deadlock_timeout, lowered here to keep the test fast), aborts one transaction
    with 40P01 deadlock_detected — rolling back what it did — and the other then gets its lock and commits."""
    p1, p2 = two_stocked_products()
    a, b = begin(), begin()
    try:
        for conn in (a, b):
            run(conn, "SELECT set_config('deadlock_timeout', '100ms', true)")
        run(a, TAKE_ONE, (SYDNEY_CBD, p1))                    # A holds P1
        run(b, TAKE_ONE, (SYDNEY_CBD, p2))                    # B holds P2
        with ThreadPoolExecutor(max_workers=2) as pool:
            a_next = pool.submit(take_and_commit, a, p2)      # A waits for B's P2
            wait_until_blocked(a)
            b_next = pool.submit(take_and_commit, b, p1)      # B waits for A's P1: a cycle
            results = {"A": outcome(a_next), "B": outcome(b_next)}
        aborted = [name for name, result in results.items() if isinstance(result, errors.DeadlockDetected)]
        committed = [name for name, result in results.items() if result == "committed"]
        left = (quantity_at(SYDNEY_CBD, p1), quantity_at(SYDNEY_CBD, p2))
        victim = results[aborted[0]] if aborted else None
        say("2 deadlock · faulty", f"{', '.join(aborted)} aborted with {getattr(victim, 'pgcode', '-')} "
            f"({type(victim).__name__}: {str(victim).splitlines()[0] if victim else '-'}); {', '.join(committed)} "
            f"committed -> stock P1 {left[0]}, P2 {left[1]} (5 each before)")
        if victim is not None:
            say("2 deadlock · faulty", "PostgreSQL's detail: " + " ".join(victim.diag.message_detail.split()))
        assert (len(aborted), len(committed)) == (1, 1), results
        assert victim.pgcode == "40P01"
        assert left == (4, 4)                                 # only the survivor's two units are gone
    finally:
        close_all(a, b)


def test_locking_rows_in_product_id_order_makes_the_second_wait_and_both_succeed():
    """Ours (T1's stock step, T2's restock, T4's cancel): every transaction locks the rows it shares in ascending
    product_id. B asks for P1 first, so it waits while holding nothing A needs; A finishes, then B — no cycle."""
    p1, p2 = two_stocked_products()
    a, b = begin(), begin()
    try:
        run(a, TAKE_ONE, (SYDNEY_CBD, p1))                    # A holds P1

        def b_takes_both():
            run(b, TAKE_ONE, (SYDNEY_CBD, p1))                # waits for A, holding nothing
            return take_and_commit(b, p2)

        with ThreadPoolExecutor(max_workers=1) as pool:
            b_work = pool.submit(timed, b_takes_both)
            wait_until_blocked(b)
            time.sleep(HOLD)
            run(a, TAKE_ONE, (SYDNEY_CBD, p2))
            a.commit()
            b_result, b_waited = outcome(b_work)
        left = (quantity_at(SYDNEY_CBD, p1), quantity_at(SYDNEY_CBD, p2))
        say("2 deadlock · ours", f"A committed; B waited {b_waited}s (polled until blocked) on P1 holding nothing, "
            f"then {b_result} -> stock P1 {left[0]}, P2 {left[1]} (5 each before)")
        assert (b_result, left) == ("committed", (3, 3))
    finally:
        close_all(a, b)

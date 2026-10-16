"""Concurrency evidence for report §4 (docs/concurrency-evidence.md): for each anomaly, a test of the faulty pattern
— what goes wrong, and how PostgreSQL reports it — and a test of the pattern this project uses. Every transaction
is its own connection, interleaved step by step (tests/concurrency_support.py). Each test prints one line of
results; `pytest -s` shows them, and the document quotes them.

These tests commit, so each works on rows it makes itself.
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg2 import errors, sql

from tests.checkout_support import a_product, committed, quantity_at
from tests.concurrency_support import begin, close_all, outcome, run, timed, wait_until_blocked
from tests.support import connect

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


# ---------------------------------------------------------------- 3. write skew: BR15, promotions never overlap

A_PERIOD = ("2031-01-01T00:00:00+11:00", "2031-01-10T00:00:00+11:00")
B_PERIOD = ("2031-01-05T00:00:00+11:00", "2031-01-15T00:00:00+11:00")    # overlaps A's
DEMO_PRODUCT = 1


@pytest.fixture
def demo_promotions():
    """A committed table shaped like promotion but with no trigger, for the faulty check-then-insert pattern. The
    real trigger can't be bypassed fairly: ALTER TABLE … DISABLE TRIGGER takes an ACCESS EXCLUSIVE lock, which would
    itself serialise the two transactions and hide the anomaly. The name is random, and the table is dropped first
    and last, so a failed test leaves nothing behind for the next."""
    table = sql.Identifier(f"demo_promotion_{uuid.uuid4().hex[:8]}")
    admin = connect()
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
        cur.execute(sql.SQL("CREATE TABLE {} (product_id INT NOT NULL, starts_at TIMESTAMPTZ NOT NULL, "
                            "ends_at TIMESTAMPTZ NOT NULL)").format(table))
    try:
        yield table
    finally:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
        admin.close()


def overlaps(conn, table, period) -> bool:
    """The application-side check: does a promotion for the product overlap this period already?"""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE product_id = %s AND starts_at < %s "
                            "AND %s < ends_at) AS clash").format(table), (DEMO_PRODUCT, period[1], period[0]))
        return cur.fetchone()["clash"]


def add_promotion(conn, table, period) -> None:
    run(conn, sql.SQL("INSERT INTO {} (product_id, starts_at, ends_at) VALUES (%s, %s, %s)").format(table),
        (DEMO_PRODUCT, *period))


def demo_rows(table) -> int:
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(table))
            return cur.fetchone()["n"]
    finally:
        conn.close()


def test_check_then_insert_under_read_committed_lets_two_overlapping_promotions_in(demo_promotions):
    """Faulty: check for an overlap with a SELECT, then INSERT, locking nothing. Each check reads the rows committed
    so far, and neither transaction's new row is there yet, so both pass and both insert: write skew. No row was
    written twice, so no row lock ever made one wait."""
    a, b = begin(), begin()
    try:
        a_clash, b_clash = overlaps(a, demo_promotions, A_PERIOD), overlaps(b, demo_promotions, B_PERIOD)
        add_promotion(a, demo_promotions, A_PERIOD)
        add_promotion(b, demo_promotions, B_PERIOD)
        a.commit()
        b.commit()
        rows = demo_rows(demo_promotions)
        say("3 write skew · read committed", f"A's check saw an overlap: {a_clash}; B's: {b_clash}; both inserted "
            f"and committed -> {rows} overlapping promotions for one product")
        assert (a_clash, b_clash, rows) == (False, False, 2)
    finally:
        close_all(a, b)


def test_check_then_insert_under_serializable_aborts_one_and_its_retry_is_refused(demo_promotions):
    """The same steps under SERIALIZABLE: PostgreSQL tracks what each transaction read, sees that each one's insert
    falls in what the other read, and aborts one with 40001 (at its insert or at commit) rather than let both
    commit. Retried in a new transaction, that check now sees the other promotion, and nothing is inserted."""
    a, b = begin("SERIALIZABLE"), begin("SERIALIZABLE")
    retry = None
    try:
        failed = {}                                           # name -> (the step it failed at, the error)
        steps = [("A", "check", lambda: overlaps(a, demo_promotions, A_PERIOD)),
                 ("B", "check", lambda: overlaps(b, demo_promotions, B_PERIOD)),
                 ("A", "insert", lambda: add_promotion(a, demo_promotions, A_PERIOD)),
                 ("B", "insert", lambda: add_promotion(b, demo_promotions, B_PERIOD)),
                 ("A", "commit", a.commit),
                 ("B", "commit", b.commit)]
        for name, what, work in steps:
            if name in failed:                                # an aborted transaction takes no further steps
                continue
            try:
                work()
            except errors.SerializationFailure as error:
                failed[name] = (what, error)
        assert len(failed) == 1, failed
        (loser, (at, error)), = failed.items()

        retry = begin("SERIALIZABLE")
        period = A_PERIOD if loser == "A" else B_PERIOD
        clash = overlaps(retry, demo_promotions, period)
        if not clash:
            add_promotion(retry, demo_promotions, period)
        retry.commit()
        rows = demo_rows(demo_promotions)
        say("3 write skew · serializable", f"{loser} failed at {at} with {error.pgcode} "
            f"({type(error).__name__}: {str(error).splitlines()[0]}); retried, its check saw an overlap: {clash}, so "
            f"it inserted nothing -> {rows} promotion")
        assert (error.pgcode, clash, rows) == ("40001", True, 1)
    finally:
        close_all(a, b, retry)


def test_br15_locks_the_product_so_two_overlapping_promotions_have_one_winner():
    """Ours, under READ COMMITTED: BR15's trigger (br15_promotion_rules) first locks the product FOR UPDATE, then
    looks for an overlap. B's insert waits in that lock until A commits; the overlap check is the next statement in
    the PL/pgSQL function, and under READ COMMITTED each statement takes a fresh snapshot, so it sees A's
    promotion — br15_promotion_no_overlap. Locking the parent row turns the two checks into one after the other."""
    product = a_product("100.00")["product_id"]
    insert = "INSERT INTO promotion (product_id, sale_price, starts_at, ends_at) VALUES (%s, 80.00, %s, %s)"
    a, b = begin(), begin()
    try:
        run(a, insert, (product, *A_PERIOD))                  # the trigger locks the product, finds no overlap
        with ThreadPoolExecutor(max_workers=1) as pool:
            b_try = pool.submit(timed, lambda: run(b, insert, (product, *B_PERIOD)))
            wait_until_blocked(b)                             # B's trigger waits for the product row
            time.sleep(HOLD)
            a.commit()
            b_result, b_waited = outcome(b_try)
        promotions = committed("SELECT count(*) AS n FROM promotion WHERE product_id = %s", (product,))[0]["n"]
        say("3 write skew · ours", f"B's trigger waited {b_waited}s (polled until blocked) for A's lock on the "
            f"product, then -> {getattr(b_result.diag, 'constraint_name', b_result)}: {str(b_result).splitlines()[0]}"
            f" -> {promotions} promotion")
        assert isinstance(b_result, errors.CheckViolation), b_result
        assert (b_result.diag.constraint_name, promotions) == ("br15_promotion_no_overlap", 1)
    finally:
        close_all(a, b)

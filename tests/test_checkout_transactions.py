"""Order rules when transactions race (T1, plan §5). Each "request" here is what the API does: its own
connection and one transaction, committed or rolled back, released at the same moment as the others
(run_at_once). These tests commit, so each one works on rows it creates itself and puts back anything else
it changes.
"""
import time
import uuid

import psycopg2

from tests.support import connect, run_at_once

ROBINA = 12             # a retail store that no other test orders from
HOLD = 0.3              # seconds a racing transaction stays open after its check, so the two always overlap


def test_br06_a_store_type_change_and_a_collect_order_race_has_one_winner():
    """A Click & Collect order at Robina, and Robina becoming a warehouse, at the same moment. Each BR06 check
    passes on what is committed, so without a lock both would commit: a Click & Collect order at a warehouse.
    The order's trigger reads the store FOR SHARE, which the store's UPDATE must wait for (and the other way
    round), so whichever comes second waits for the first to commit, then sees it and is refused."""
    setup = connect()
    with setup, setup.cursor() as cur:
        cur.execute("""SELECT count(*) AS n FROM customer_order
                       WHERE fulfilling_store_id = %s AND fulfilment_method = 'click_collect'""", (ROBINA,))
        assert cur.fetchone()["n"] == 0, "Robina already has a Click & Collect order, so there is no race"
        cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Race Tester') RETURNING customer_id",
                    (f"race.{uuid.uuid4().hex[:10]}@example.com",))
        customer_id = cur.fetchone()["customer_id"]
        cur.execute("SELECT product_id FROM product WHERE sku = 'APL-AP4'")
        airpods = cur.fetchone()["product_id"]
    setup.close()

    def place_collect_order():
        conn = connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")   # a lock regression fails the test, never hangs it
                cur.execute("""INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method,
                                                           fulfilling_store_id)
                               VALUES (%s, gen_random_uuid(), 'click_collect', %s)
                               RETURNING order_id""", (customer_id, ROBINA))
                cur.execute("""INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price)
                               VALUES (%s, 1, %s, 1, 189.00)""", (cur.fetchone()["order_id"], airpods))
                time.sleep(HOLD)
            return "order"
        finally:
            conn.close()

    def make_robina_a_warehouse():
        conn = connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")
                cur.execute("UPDATE store SET store_type = 'warehouse' WHERE store_id = %s", (ROBINA,))
                time.sleep(HOLD)
            return "warehouse"
        finally:
            conn.close()

    jobs = [place_collect_order, make_robina_a_warehouse]
    try:
        results = run_at_once(2, lambda: jobs.pop()())      # each thread takes one of the two jobs
        winners = [result for result in results if isinstance(result, str)]
        refused = [result for result in results if isinstance(result, psycopg2.Error)]
        assert (len(winners), len(refused)) == (1, 1), results
        assert refused[0].diag.constraint_name == "br06_collect_at_retail_store"

        check = connect()
        with check, check.cursor() as cur:
            cur.execute("SELECT store_type FROM store WHERE store_id = %s", (ROBINA,))
            store_type = cur.fetchone()["store_type"]
            cur.execute("SELECT count(*) AS n FROM customer_order WHERE customer_id = %s", (customer_id,))
            orders = cur.fetchone()["n"]
        check.close()
        # Exactly the winner's work was committed.
        assert (store_type, orders) == {"order": ("retail", 1), "warehouse": ("warehouse", 0)}[winners[0]]
    finally:
        cleanup = connect()
        with cleanup, cleanup.cursor() as cur:
            # Robina goes back to retail (always allowed: BR06 only stops a store *leaving* retail).
            cur.execute("UPDATE store SET store_type = 'retail' WHERE store_id = %s", (ROBINA,))
            # The customer goes too, unless the order won: orders are purchase records that are never deleted
            # (BR08, BR09), so a winning order stays. The test database is rebuilt on every run.
            cur.execute("""DELETE FROM customer c
                           WHERE c.customer_id = %s
                             AND NOT EXISTS (SELECT 1 FROM customer_order o WHERE o.customer_id = c.customer_id)""",
                        (customer_id,))
        cleanup.close()


COLLECT_ORDER = """
    INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id)
    SELECT customer_id, gen_random_uuid(), 'click_collect', 2 FROM customer ORDER BY customer_id LIMIT 1
"""


def test_collect_orders_at_one_store_do_not_wait_for_each_other():
    """BR06's order-side check reads the store FOR SHARE. Shared locks don't conflict with each other, so two
    Click & Collect orders at one store never queue behind each other; only a store-type change waits. Were
    the lock FOR UPDATE, the second insert would wait and hit the lock timeout. Nothing is committed."""
    held, other = connect(), connect()
    try:
        with held.cursor() as cur:
            cur.execute(COLLECT_ORDER)                  # keeps its lock on store 2 until the rollback below
        with other.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute(COLLECT_ORDER)                  # must not wait for the open transaction
    finally:
        held.rollback()
        other.rollback()
        held.close()
        other.close()

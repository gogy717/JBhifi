"""Order rules when transactions race (T1, plan §5). Each "request" here is what the API does: its own
connection and one transaction, committed or rolled back, released at the same moment as the others
(run_at_once). These tests commit, so each one works on rows it creates itself and puts back anything else
it changes.
"""
import time
import uuid

import psycopg2
import pytest

from app.errors import ApiError
from tests import checkout_support as shop
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


# ---------------------------------------------------------------- T1 checkout under concurrency
# Each "request" is what POST /orders does: its own connection and one transaction (shop.checkout_request).
# These commit, so each test makes its own products and customers.

def test_concurrent_same_key_creates_one_order():
    """A double click: two requests with one key at the same moment. Whichever claims the key first places
    the order; the other waits on that claim in br10_order_idempotency_unique (or finds the order at its
    lookup) and answers with the same order instead of placing a second one."""
    product = shop.a_product("189.00", stock=5)
    actor = shop.a_shopper()
    body = shop.order_body([(product, 1)])
    key = uuid.uuid4()

    results = run_at_once(2, lambda: shop.checkout_request(actor, key, body, lock_timeout="10s"))
    assert all(isinstance(result, tuple) for result in results), results
    (first, first_replayed), (second, second_replayed) = results
    assert first["order_id"] == second["order_id"]
    assert sorted([first_replayed, second_replayed]) == [False, True]
    assert shop.orders_with_key(key) == [first["order_id"]]
    assert shop.committed("SELECT count(*) AS n FROM payment WHERE order_id = %s", (first["order_id"],))[0]["n"] == 1
    assert shop.quantity_at(shop.SYDNEY_CBD, product["product_id"]) == 4


def test_last_unit_has_one_buyer():
    """Two customers want the last unit. The first stock UPDATE locks the inventory row; the second waits,
    then re-checks `quantity >= 1` against the committed 0 and takes nothing: one order, one out_of_stock."""
    product = shop.a_product("499.00", stock=1)
    body = shop.order_body([(product, 1)])
    first, second = shop.a_shopper(), shop.a_shopper()

    results = shop.run_together(lambda: shop.checkout_request(first, uuid.uuid4(), body, lock_timeout="10s"),
                                lambda: shop.checkout_request(second, uuid.uuid4(), body, lock_timeout="10s"))
    sold = [result for result in results if isinstance(result, tuple)]
    refused = [result for result in results if isinstance(result, ApiError)]
    assert (len(sold), len(refused)) == (1, 1), results
    assert (refused[0].status, refused[0].code, refused[0].detail["available"]) == (409, "out_of_stock", 0)
    assert shop.quantity_at(shop.SYDNEY_CBD, product["product_id"]) == 0
    assert shop.committed("SELECT count(*) AS n FROM order_line WHERE product_id = %s",
                          (product["product_id"],))[0]["n"] == 1


def test_stock_is_locked_per_store_not_per_product():
    """A checkout locks the inventory rows of its own store, and nothing about the product itself. While a
    checkout of P at Bondi Junction is still open, one of P at Sydney CBD commits without waiting; another
    at Bondi Junction has to wait for the open one. (One customer throughout: nothing locks the customer.)"""
    product = shop.a_product("25.00", stock=5, store_id=shop.SYDNEY_CBD)
    shop.committed("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, 5)",
                   (shop.BONDI, product["product_id"]))
    actor = shop.a_shopper()
    at_bondi = shop.order_body([(product, 1)], store_id=shop.BONDI)
    at_sydney = shop.order_body([(product, 1)], store_id=shop.SYDNEY_CBD)

    held = connect()
    try:
        shop.checkout_in(held, actor, uuid.uuid4(), at_bondi)            # open: not committed yet
        # Another store's row: nothing to wait for, so the 5-second lock timeout is never reached.
        detail, _ = shop.checkout_request(actor, uuid.uuid4(), at_sydney, lock_timeout="5s")
        assert detail["status"] == "paid"
        # The same store's row: this one must wait for the open checkout, so its 1-second timeout runs out.
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            shop.checkout_request(actor, uuid.uuid4(), at_bondi, lock_timeout="1s")
        held.commit()
    finally:
        held.close()
    assert shop.quantity_at(shop.SYDNEY_CBD, product["product_id"]) == 4
    assert shop.quantity_at(shop.BONDI, product["product_id"]) == 4


def test_baskets_in_opposite_product_order_do_not_deadlock():
    """[first, second] and [second, first] at the same moment, ten times over. Checkout takes stock in
    product_id order whatever order the basket lists, so neither can hold one row while it waits for the
    other's: no deadlock_detected, and both orders are placed every time."""
    first = shop.a_product("10.00", stock=50)
    second = shop.a_product("20.00", stock=50)
    forward = shop.order_body([(first, 1), (second, 1)])
    backward = shop.order_body([(second, 1), (first, 1)])
    one, other = shop.a_shopper(), shop.a_shopper()

    for _ in range(10):
        results = shop.run_together(lambda: shop.checkout_request(one, uuid.uuid4(), forward, lock_timeout="10s"),
                                    lambda: shop.checkout_request(other, uuid.uuid4(), backward, lock_timeout="10s"))
        assert all(isinstance(result, tuple) for result in results), results
    assert shop.quantity_at(shop.SYDNEY_CBD, first["product_id"]) == 30
    assert shop.quantity_at(shop.SYDNEY_CBD, second["product_id"]) == 30

"""T09 under real concurrency: one unit, one buyer; one key, one order; no hangs, no overselling."""
import threading
import uuid

import psycopg2

from tests.concurrency import run_at_once
from tests.shop import SYDNEY_CBD, a_customer, a_product, order_body, place, shop_client
from tests.support import connect


def one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def checkout_in_thread(customer_id, body, key=None):
    """One API call in its own thread and its own client, exactly as two browsers would."""
    client = shop_client(customer_id)
    try:
        response = place(client, body, key)
    finally:
        client.close()
    if response.status_code in (200, 201):
        return response.json()
    return psycopg2.Error(response.json()["error"]["message"])


def error_message(result) -> str:
    """The message of the psycopg2.Error the helper returns for a refused request."""
    return str(result)


def test_the_last_unit_has_exactly_one_buyer():
    product = a_product(price="499.00", stock=1)
    buyers = [a_customer()[0] for _ in range(2)]
    body = order_body([(product, 1)])

    results = run_at_once(2, lambda i: checkout_in_thread(buyers[i], body, uuid.uuid4()))
    successes = [r for r in results if isinstance(r, dict)]
    refusals = [r for r in results if isinstance(r, psycopg2.Error)]

    assert len(successes) == 1, results
    assert len(refusals) == 1
    assert "Only 0 left of" in error_message(refusals[0])
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 0
    assert one("""SELECT count(*) AS n FROM customer_order o JOIN order_line l USING (order_id)
                  WHERE l.product_id = %s""", (product["product_id"],))["n"] == 1


def test_the_same_key_from_two_threads_creates_one_order():
    product = a_product(price="189.00", stock=5)
    customer_id = a_customer()[0]
    body = order_body([(product, 1)])
    key = uuid.uuid4()

    results = run_at_once(2, lambda _: checkout_in_thread(customer_id, body, key))
    assert all(isinstance(r, dict) for r in results), results
    assert results[0]["order_id"] == results[1]["order_id"]

    assert one("SELECT count(*) AS n FROM customer_order WHERE customer_id = %s", (customer_id,))["n"] == 1
    assert one("""SELECT count(*) AS n FROM payment p JOIN customer_order o USING (order_id)
                  WHERE o.customer_id = %s""", (customer_id,))["n"] == 1
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 4


def test_overlapping_baskets_do_not_hang_and_never_oversell():
    # 3 units, two customers each wanting 2: at most one can succeed, and the loser is told why.
    product = a_product(price="30.00", stock=3)
    buyers = [a_customer()[0] for _ in range(2)]

    results = run_at_once(2, lambda i: checkout_in_thread(buyers[i], order_body([(product, 2)]), uuid.uuid4()))
    successes = [r for r in results if isinstance(r, dict)]
    refusals = [r for r in results if isinstance(r, psycopg2.Error)]
    assert len(successes) + len(refusals) == 2, results
    assert len(successes) <= 1
    stock = one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
                (SYDNEY_CBD, product["product_id"]))["quantity"]
    assert stock == 3 - 2 * len(successes)
    assert stock >= 0
    sold = one("SELECT COALESCE(sum(l.quantity), 0) AS n FROM order_line l WHERE l.product_id = %s",
               (product["product_id"],))["n"]
    assert sold == 2 * len(successes)


def test_checkout_races_a_retirement_and_leaves_a_consistent_result():
    """Whoever gets the product row lock first wins: the order commits, or the retire does."""
    product = a_product(price="89.00", stock=4)
    customer_id = a_customer()[0]
    body = order_body([(product, 1)])
    barrier = threading.Barrier(2, timeout=20)
    outcome = {}

    def retire():
        conn = connect()
        try:
            barrier.wait()
            with conn, conn.cursor() as cur:
                cur.execute("UPDATE product SET is_active = FALSE WHERE product_id = %s",
                            (product["product_id"],))
            outcome["retired"] = True
        finally:
            conn.close()

    def buy():
        client = shop_client(customer_id)
        try:
            barrier.wait()
            outcome["buy"] = place(client, body, uuid.uuid4())
        finally:
            client.close()

    threads = [threading.Thread(target=retire), threading.Thread(target=buy)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads), "a transaction never finished"

    response = outcome["buy"]
    stock = one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
                (SYDNEY_CBD, product["product_id"]))["quantity"]
    orders = one("SELECT count(*) AS n FROM customer_order WHERE customer_id = %s", (customer_id,))["n"]
    if response.status_code == 201:
        # Bought first: the retired flag landed afterwards, and the purchase is whole.
        assert (stock, orders) == (3, 1)
        assert one("SELECT count(*) AS n FROM payment p JOIN customer_order o USING (order_id) "
                   "WHERE o.customer_id = %s", (customer_id,))["n"] == 1
    else:
        assert (response.status_code, response.json()["error"]["code"]) == (409, "product_unavailable")
        assert (stock, orders) == (4, 0)

"""T14 under concurrency: processing refunds and restocks once, and a failure leaves neither."""
import threading
from decimal import Decimal

from tests.concurrency import run_at_once
from tests.shop import AIDEN, SYDNEY_CBD, a_completed_order, request_return, return_action, staff_client
from tests.support import connect


def one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def stock_at(store_id, product_id):
    return one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (store_id, product_id))["quantity"]


def a_received_return(*, quantity=1, price="19.95", stock=1):
    customer, staff, product, order = a_completed_order(quantity=quantity, price=price, stock=stock)
    created = request_return(customer, order["order_id"], [(1, quantity)]).json()
    assert return_action(staff, created["return_id"], "receive", "requested").status_code == 200
    return customer, product, order, created


def test_processing_twice_from_two_threads_refunds_and_restocks_once():
    _, product, _, created = a_received_return()

    def process(_):
        client = staff_client(AIDEN)
        try:
            response = return_action(client, created["return_id"], "process", "received")
        finally:
            client.close()
        return response.status_code

    results = run_at_once(2, process)
    assert all(code in (200, 409) for code in results), results
    assert 200 in results

    assert stock_at(SYDNEY_CBD, product["product_id"]) == 1
    assert one("SELECT count(*) AS n FROM payment WHERE return_id = %s", (created["return_id"],))["n"] == 1
    assert one("SELECT amount FROM payment WHERE return_id = %s", (created["return_id"],))["amount"] \
        == Decimal("19.95")
    assert one("SELECT status FROM return_request WHERE return_id = %s",
               (created["return_id"],))["status"] == "refunded"


def test_a_failure_while_refunding_leaves_no_restock_and_no_status_change(monkeypatch):
    _, product, _, created = a_received_return()
    monkeypatch.setattr("app.services.returns.record_refund",
                       lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated")))

    client = staff_client(AIDEN)
    try:
        return_action(client, created["return_id"], "process", "received")
    except RuntimeError:
        pass
    else:
        raise AssertionError("the simulated failure should have propagated")

    assert stock_at(SYDNEY_CBD, product["product_id"]) == 0
    assert one("SELECT status FROM return_request WHERE return_id = %s",
               (created["return_id"],))["status"] == "received"
    assert one("SELECT count(*) AS n FROM payment WHERE return_id = %s", (created["return_id"],))["n"] == 0


def test_rejecting_races_with_processing_and_only_one_wins():
    _, product, _, created = a_received_return()
    barrier = threading.Barrier(2, timeout=20)
    outcome = {}

    def act(name, action):
        client = staff_client(AIDEN)
        try:
            barrier.wait()
            outcome[name] = return_action(client, created["return_id"], action, "received")
        finally:
            client.close()

    threads = [threading.Thread(target=act, args=("process", "process")),
               threading.Thread(target=act, args=("reject", "reject"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads), "an action never finished"

    statuses = {name: response.status_code for name, response in outcome.items()}
    assert sorted(statuses.values()) == [200, 409], statuses
    final = one("SELECT status FROM return_request WHERE return_id = %s", (created["return_id"],))["status"]
    refunds = one("SELECT count(*) AS n FROM payment WHERE return_id = %s", (created["return_id"],))["n"]
    stock = stock_at(SYDNEY_CBD, product["product_id"])
    if outcome["process"].status_code == 200:
        assert (final, refunds, stock) == ("refunded", 1, 1)
    else:
        assert (final, refunds, stock) == ("rejected", 0, 0)


def test_two_partial_returns_together_refund_no_more_than_was_charged():
    customer, staff, product, order = a_completed_order(quantity=4, price="10.00", stock=4)
    charged = Decimal("40.00")

    for _ in range(2):
        created = request_return(customer, order["order_id"], [(1, 2)]).json()
        return_action(staff, created["return_id"], "receive", "requested")
        processed = return_action(staff, created["return_id"], "process", "received")
        assert processed.status_code == 200, processed.text
        assert processed.json()["refund_amount"] == "20.00"

    refunded = one("SELECT sum(amount) AS total FROM payment WHERE order_id = %s AND kind = 'refund'",
                   (order["order_id"],))["total"]
    assert refunded == Decimal("40.00") <= charged
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 4

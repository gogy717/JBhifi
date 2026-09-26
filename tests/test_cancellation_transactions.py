"""T11: cancelling is one transaction — restock once, refund once, and a failure leaves nothing behind."""
import threading
from decimal import Decimal

from tests.shop import (AIDEN, BONDI, SYDNEY_CBD, WAREHOUSE, a_customer, a_product, error_of, order_body,
                        place, shop_client, staff_client)
from tests.support import connect


def one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def a_paid_order(*, method="click_collect", store_id=SYDNEY_CBD, quantity=2, price="19.95", stock=5):
    customer_id, numbers = a_customer()
    product = a_product(price=price, stock=stock, store_id=store_id)
    client = shop_client(customer_id)
    response = place(client, order_body([(product, quantity)], method=method, store_id=store_id,
                                        address_no=numbers[0] if method == "delivery" else None))
    assert response.status_code == 201, response.text
    return product, response.json()


def cancel(client, order, reason="Customer changed their mind", expected_status=None):
    return client.post(f"/api/v1/orders/{order['order_id']}/cancel", json={
        "expected_status": expected_status or order["status"], "reason": reason,
    })


def test_a_paid_cancellation_restores_the_stock_and_refunds_exactly_once():
    product, order = a_paid_order(quantity=2, price="19.95", stock=5)
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 3

    response = cancel(staff_client(AIDEN), order)
    assert response.status_code == 200, response.text
    cancelled = response.json()

    assert cancelled["status"] == "cancelled"
    assert [(payment["kind"], payment["amount"], payment["cancellation_id"] is not None)
            for payment in cancelled["payments"]] == [("charge", "39.90", False), ("refund", "39.90", True)]
    assert cancelled["history"][-1]["to_status"] == "cancelled"
    assert cancelled["history"][-1]["changed_by_staff_id"] == AIDEN
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 5
    assert one("SELECT count(*) AS n FROM payment WHERE order_id = %s AND kind = 'refund'",
               (order["order_id"],))["n"] == 1
    assert one("SELECT count(*) AS n FROM order_cancellation WHERE order_id = %s",
               (order["order_id"],))["n"] == 1


def test_a_repeated_cancellation_repeats_nothing():
    product, order = a_paid_order(quantity=1, price="19.95", stock=2)
    staff = staff_client(AIDEN)
    assert cancel(staff, order).status_code == 200

    again = cancel(staff, order)
    assert again.status_code == 200                       # same details: the same result, no new effects
    assert again.json()["status"] == "cancelled"
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 2
    assert one("SELECT count(*) AS n FROM payment WHERE order_id = %s AND kind = 'refund'",
               (order["order_id"],))["n"] == 1
    assert one("SELECT count(*) AS n FROM order_status_history WHERE order_id = %s AND to_status = 'cancelled'",
               (order["order_id"],))["n"] == 1

    conflicting = cancel(staff, order, reason="Something else entirely")
    assert error_of(conflicting) == (409, "cancellation_conflict")
    assert one("SELECT count(*) AS n FROM payment WHERE order_id = %s AND kind = 'refund'",
               (order["order_id"],))["n"] == 1


def test_an_unpaid_order_does_not_invent_stock_when_cancelled():
    """A `placed` order took no stock (only checkout takes stock, and it commits as `paid`)."""
    customer_id, _ = a_customer()
    product = a_product(price="19.95", stock=4)
    order_id = None
    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint, "
            "fulfilment_method, fulfilling_store_id) VALUES (%s, gen_random_uuid(), 'fixture', "
            "'click_collect', %s) RETURNING order_id",
            (customer_id, SYDNEY_CBD),
        )
        order_id = cur.fetchone()["order_id"]
        cur.execute("INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) "
                    "VALUES (%s, 1, %s, 3, 19.95)", (order_id, product["product_id"]))
    conn.close()

    response = cancel(staff_client(AIDEN), {"order_id": order_id, "status": "placed"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert response.json()["payments"] == []
    # The stock is untouched: nothing had been taken, so nothing comes back.
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 4


def test_a_ready_collection_can_still_be_cancelled():
    product, order = a_paid_order(quantity=1, price="19.95", stock=3)
    staff = staff_client(AIDEN)
    staff.patch(f"/api/v1/orders/{order['order_id']}/status",
                json={"to_status": "picking", "expected_status": "paid"})
    ready = staff.patch(f"/api/v1/orders/{order['order_id']}/status",
                        json={"to_status": "ready", "expected_status": "picking"}).json()

    response = cancel(staff, ready)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 3


def test_an_order_that_is_already_delivered_cannot_be_cancelled():
    product, order = a_paid_order(method="delivery", store_id=WAREHOUSE, quantity=1, stock=3)
    warehouse_staff = staff_client(38)
    for to_status in ("picking", "shipped", "delivered"):
        order = warehouse_staff.patch(f"/api/v1/orders/{order['order_id']}/status",
                                      json={"to_status": to_status, "expected_status": order["status"]}).json()

    response = cancel(warehouse_staff, order)
    assert error_of(response) == (409, "br09_order_status_transition")
    # Nothing moved: no refund, no restock, still delivered.
    assert one("SELECT count(*) AS n FROM payment WHERE order_id = %s AND kind = 'refund'",
               (order["order_id"],))["n"] == 0
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (WAREHOUSE, product["product_id"]))["quantity"] == 2
    assert one("SELECT status FROM customer_order WHERE order_id = %s", (order["order_id"],))["status"] \
        == "delivered"


def test_a_failure_while_refunding_rolls_the_whole_cancellation_back(monkeypatch):
    product, order = a_paid_order(quantity=1, price="19.95", stock=4)
    staff = staff_client(AIDEN)

    def explode(*args, **kwargs):
        raise RuntimeError("simulated payment failure")

    monkeypatch.setattr("app.services.cancellations.record_refund", explode)
    try:
        cancel(staff, order)
    except RuntimeError as error:
        assert "simulated payment failure" in str(error)
    else:
        raise AssertionError("the simulated failure should have propagated")

    # The rollback undid the restock, the cancellation record and the status change.
    assert one("SELECT status FROM customer_order WHERE order_id = %s", (order["order_id"],))["status"] == "paid"
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 3
    assert one("SELECT count(*) AS n FROM order_cancellation WHERE order_id = %s",
               (order["order_id"],))["n"] == 0
    assert one("SELECT sum(CASE WHEN kind = 'charge' THEN amount ELSE -amount END) AS net "
               "FROM payment WHERE order_id = %s", (order["order_id"],))["net"] == Decimal("19.95")


def test_cancelling_and_fulfilling_the_same_order_have_one_winner():
    product, order = a_paid_order(quantity=1, price="19.95", stock=3)
    barrier = threading.Barrier(2, timeout=20)
    outcome = {}

    def work(name, action):
        client = staff_client(AIDEN)
        try:
            barrier.wait()
            outcome[name] = action(client)
        finally:
            client.close()

    def do_cancel(client):
        return cancel(client, order)

    def do_pick(client):
        return client.patch(f"/api/v1/orders/{order['order_id']}/status",
                            json={"to_status": "picking", "expected_status": "paid"})

    threads = [threading.Thread(target=work, args=("cancel", do_cancel)),
               threading.Thread(target=work, args=("pick", do_pick))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads), "a transaction never finished"

    statuses = {name: response.status_code for name, response in outcome.items()}
    winners = [name for name, code in statuses.items() if code == 200]
    assert len(winners) == 1, (statuses, {n: r.text for n, r in outcome.items()})

    final = one("SELECT status FROM customer_order WHERE order_id = %s", (order["order_id"],))["status"]
    refunds = one("SELECT count(*) AS n FROM payment WHERE order_id = %s AND kind = 'refund'",
                  (order["order_id"],))["n"]
    stock = one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
                (SYDNEY_CBD, product["product_id"]))["quantity"]
    if winners == ["cancel"]:
        assert (final, refunds, stock) == ("cancelled", 1, 3)
    else:
        assert (final, refunds, stock) == ("picking", 0, 2)

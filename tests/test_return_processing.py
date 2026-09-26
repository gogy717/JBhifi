"""T14: receiving records who and where; processing restocks and refunds exactly once, at sold prices."""
from tests.shop import (AIDEN, ISLA, SUPPORT, SYDNEY_CBD, a_completed_order, a_customer, error_of,
                        request_return, return_action, shop_client, staff_client)
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


def a_requested_return(*, quantity=1, price="19.95", stock=1, method="click_collect"):
    customer, staff, product, order = a_completed_order(quantity=quantity, price=price, stock=stock,
                                                        method=method)
    created = request_return(customer, order["order_id"], [(1, quantity)]).json()
    return customer, staff, product, order, created


def test_receive_records_actor_and_store():
    _, staff, product, _, created = a_requested_return()
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 0            # sold out

    response = return_action(staff, created["return_id"], "receive", "requested")
    assert response.status_code == 200, response.text
    received = response.json()

    assert received["status"] == "received"
    assert received["receiving_store"] == {"store_id": SYDNEY_CBD, "name": "Sydney CBD"}
    assert [(change["from_status"], change["to_status"], change["changed_by_staff_id"])
            for change in received["history"]] == [(None, "requested", None), ("requested", "received", AIDEN)]
    assert received["allowed_actions"] == ["reject", "process"]
    assert received["refund_amount"] is None


def test_receiving_does_not_restock():
    """Taking the item in records where it is; the shelf is only touched when the return is processed."""
    _, staff, product, _, created = a_requested_return(quantity=1, price="19.95", stock=1)
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 0            # the one unit was sold

    assert return_action(staff, created["return_id"], "receive", "requested").status_code == 200
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 0            # still nothing back on the shelf
    assert one("SELECT count(*) AS n FROM payment WHERE return_id = %s",
               (created["return_id"],))["n"] == 0


def test_processing_restocks_and_refunds_the_sold_price_once():
    _, staff, product, order, created = a_requested_return(quantity=1, price="19.95", stock=1)
    return_action(staff, created["return_id"], "receive", "requested")

    # The product's price moves after the sale: the refund still uses what was paid.
    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE product SET base_price = 99.00 WHERE product_id = %s", (product["product_id"],))
    conn.close()

    response = return_action(staff, created["return_id"], "process", "received")
    assert response.status_code == 200, response.text
    refunded = response.json()

    assert refunded["status"] == "refunded"
    assert refunded["refund_amount"] == "19.95"
    assert [(payment["kind"], payment["amount"]) for payment in
            shop_client(order["customer_id"]).get(f"/api/v1/orders/{order['order_id']}").json()["payments"]] \
        == [("charge", "19.95"), ("refund", "19.95")]
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 1
    assert refunded["allowed_actions"] == []                            # refunded is final

    # Processing again changes nothing at all.
    again = return_action(staff, created["return_id"], "process", "refunded")
    assert again.status_code == 200
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 1
    assert one("SELECT count(*) AS n FROM payment WHERE return_id = %s", (created["return_id"],))["n"] == 1


def test_partial_refund_uses_sold_price():
    customer, staff, product, order = a_completed_order(quantity=3, price="19.95", stock=3)
    # Return two of the three, so the refund is exactly two units at the price paid.
    partial = request_return(customer, order["order_id"], [(1, 2)]).json()
    assert partial["refund_preview"] == "39.90"

    return_action(staff, partial["return_id"], "receive", "requested")
    processed = return_action(staff, partial["return_id"], "process", "received").json()
    assert processed["refund_amount"] == "39.90"
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 2      # only the two that came back
    remaining = customer.get(f"/api/v1/orders/{order['order_id']}").json()["return_eligibility"]["lines"][0]
    assert remaining["remaining_quantity"] == 1


def test_rejected_return_has_no_refund():
    _, staff, product, _, created = a_requested_return()
    response = return_action(staff, created["return_id"], "reject", "requested")
    assert response.status_code == 200, response.text
    rejected = response.json()

    assert rejected["status"] == "rejected"
    assert rejected["refund_amount"] is None
    assert rejected["allowed_actions"] == []
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 0
    assert one("SELECT count(*) AS n FROM payment WHERE return_id = %s", (created["return_id"],))["n"] == 0


def test_wrong_store_cannot_process():
    customer, staff, _, order, created = a_requested_return()

    # Support reads returns but never handles one.
    assert error_of(return_action(staff_client(SUPPORT), created["return_id"], "receive", "requested")) \
        == (403, "store_staff_only")
    # A customer cannot act on their own return either.
    assert error_of(return_action(customer, created["return_id"], "receive", "requested")) \
        == (403, "staff_only")

    # Any retail store can take the item in — and then only that store may finish it.
    assert return_action(staff_client(ISLA), created["return_id"], "receive", "requested").status_code == 200
    assert error_of(return_action(staff, created["return_id"], "process", "received")) == (403, "other_store")
    assert return_action(staff_client(ISLA), created["return_id"], "process", "received").status_code == 200
    assert order["order_id"] is not None


def test_a_store_that_did_not_fulfil_it_cannot_refuse_an_unseen_return():
    _, _, _, _, created = a_requested_return()
    assert error_of(return_action(staff_client(ISLA), created["return_id"], "reject", "requested")) \
        == (403, "other_store")
    # The fulfilling store can.
    assert return_action(staff_client(AIDEN), created["return_id"], "reject", "requested").status_code == 200


def test_zero_value_return_has_no_payment_row():
    customer, staff, product, order = a_completed_order(quantity=1, price="0.00", stock=1)
    created = request_return(customer, order["order_id"], [(1, 1)]).json()
    assert created["refund_preview"] == "0.00"

    return_action(staff, created["return_id"], "receive", "requested")
    processed = return_action(staff, created["return_id"], "process", "received")
    assert processed.status_code == 200, processed.text
    assert processed.json()["status"] == "refunded"
    assert processed.json()["refund_amount"] is None           # a zero refund is not a payment row
    assert stock_at(SYDNEY_CBD, product["product_id"]) == 1
    assert one("SELECT count(*) AS n FROM payment WHERE return_id = %s", (created["return_id"],))["n"] == 0


def test_a_stale_expected_status_is_refused():
    _, staff, _, _, created = a_requested_return()
    first = return_action(staff, created["return_id"], "receive", "requested")
    assert first.status_code == 200
    # Repeating the same receipt is harmless — the same result, no second effect.
    assert return_action(staff, created["return_id"], "receive", "received").status_code == 200
    # A screen still showing `requested` that tries something else is told the return has moved on.
    stale = return_action(staff, created["return_id"], "reject", "requested")
    assert error_of(stale) == (409, "stale_status")
    assert stale.json()["error"]["detail"] == {"status": "received"}


def test_the_stores_returns_queue_shows_requests_to_take_in_and_ones_already_taken_in():
    customer, staff, _, order, created = a_requested_return()
    queue = staff.get(f"/api/v1/stores/{SYDNEY_CBD}/returns").json()
    assert created["return_id"] in {row["return_id"] for row in queue}

    return_action(staff, created["return_id"], "receive", "requested")
    still_there = staff.get(f"/api/v1/stores/{SYDNEY_CBD}/returns", params={"status": "received"}).json()
    assert created["return_id"] in {row["return_id"] for row in still_there}
    assert a_customer()[0] is not None

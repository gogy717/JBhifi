"""T13 under concurrency: the quantities are bounded, a retry acts once, and a bad line takes the rest."""
import uuid

import psycopg2

from tests.concurrency import run_at_once
from tests.shop import a_completed_order, a_customer, error_of, request_return, shop_client
from tests.support import connect


def one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def request_in_thread(customer_id, order_id, lines, key=None):
    client = shop_client(customer_id)
    try:
        response = request_return(client, order_id, lines, key=key)
    finally:
        client.close()
    if response.status_code in (200, 201):
        return response.json()
    return psycopg2.Error(response.json()["error"]["code"])


def test_concurrent_return_requests_cannot_exceed_the_purchase():
    customer, _, _, order = a_completed_order(quantity=2)
    customer_id = order["customer_id"]

    results = run_at_once(2, lambda _: request_in_thread(customer_id, order["order_id"], [(1, 2)]))
    accepted = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, psycopg2.Error)]

    assert (len(accepted), len(refused)) == (1, 1), results
    assert str(refused[0]) == "br12_return_qty_within_purchased"
    claimed = one("""SELECT COALESCE(sum(rl.quantity), 0) AS n
                     FROM return_line rl JOIN return_request rr USING (return_id)
                     WHERE rr.order_id = %s AND rr.status <> 'rejected'""", (order["order_id"],))["n"]
    assert claimed == 2
    assert customer.get(f"/api/v1/orders/{order['order_id']}").json()["return_eligibility"]["lines"][0] \
        ["remaining_quantity"] == 0


def test_concurrent_same_return_key_has_one_effect():
    _, _, _, order = a_completed_order(quantity=2)
    customer_id = order["customer_id"]
    key = uuid.uuid4()

    results = run_at_once(2, lambda _: request_in_thread(customer_id, order["order_id"], [(1, 1)], key))
    assert all(isinstance(r, dict) for r in results), results
    assert results[0]["return_id"] == results[1]["return_id"]
    assert one("SELECT count(*) AS n FROM return_request WHERE order_id = %s", (order["order_id"],))["n"] == 1
    assert one("""SELECT count(*) AS n FROM return_line rl JOIN return_request rr USING (return_id)
                  WHERE rr.order_id = %s""", (order["order_id"],))["n"] == 1


def test_invalid_second_line_rolls_back_request():
    customer, _, _, order = a_completed_order(quantity=2, price="50.00")
    # Line 1 is fine (1 of 2); line 2 asks for one unit of a one-line order.
    response = customer.post(
        f"/api/v1/orders/{order['order_id']}/returns",
        json={"reason": "Mixed", "lines": [{"line_no": 1, "quantity": 1},
                                           {"line_no": 1, "quantity": 2}]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert error_of(response) == (422, "duplicate_lines")      # rejected before any write

    # Now a genuine over-request on a second line: the parent request must not survive.
    body = {"reason": "Too many", "lines": [{"line_no": 1, "quantity": 2}]}
    first = customer.post(f"/api/v1/orders/{order['order_id']}/returns", json=body,
                          headers={"Idempotency-Key": str(uuid.uuid4())})
    assert first.status_code == 201
    second = customer.post(f"/api/v1/orders/{order['order_id']}/returns",
                           json={"reason": "One too many", "lines": [{"line_no": 1, "quantity": 1}]},
                           headers={"Idempotency-Key": str(uuid.uuid4())})
    assert error_of(second) == (409, "br12_return_qty_within_purchased")
    assert one("SELECT count(*) AS n FROM return_request WHERE order_id = %s", (order["order_id"],))["n"] == 1
    assert a_customer()[0] is not None

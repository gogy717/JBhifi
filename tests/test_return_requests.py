"""T13: a customer requests a return with a reliable deadline, real remaining quantities and safe retries."""
from datetime import datetime, timedelta, timezone

from tests.shop import (AIDEN, SUPPORT, a_completed_order, a_customer, backdate_completion, error_of,
                        request_return, shop_client)
from tests.support import connect


def one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def test_a_completed_order_reports_its_eligibility_and_deadline():
    customer, _, _, order = a_completed_order(quantity=2)
    detail = customer.get(f"/api/v1/orders/{order['order_id']}").json()

    eligibility = detail["return_eligibility"]
    assert eligibility["eligible"] is True
    assert eligibility["reason"] is None
    assert eligibility["lines"][0]["quantity"] == 2
    assert eligibility["lines"][0]["remaining_quantity"] == 2
    assert eligibility["lines"][0]["unit_price"] == "189.00"
    deadline = datetime.fromisoformat(eligibility["deadline"])
    changed_at = datetime.fromisoformat(detail["history"][-1]["changed_at"])
    assert timedelta(days=29) < deadline - changed_at <= timedelta(days=30, seconds=1)
    assert detail["allowed_actions"] == ["request_return"]


def test_only_owner_can_request_return():
    _, _, _, order = a_completed_order()
    stranger = shop_client(a_customer()[0])
    # Another customer's order is a 404 — the same answer as an order that is not there.
    assert error_of(request_return(stranger, order["order_id"], [(1, 1)])) == (404, "not_found")
    assert error_of(shop_client(a_customer()[0]).get(f"/api/v1/orders/{order['order_id']}")) \
        == (404, "not_found")


def test_returns_require_completed_order():
    from tests.shop import SYDNEY_CBD, a_product, order_body, place
    customer_id, _ = a_customer()
    product = a_product(stock=2)
    client = shop_client(customer_id)
    order = place(client, order_body([(product, 1)])).json()          # only `paid`

    detail = client.get(f"/api/v1/orders/{order['order_id']}").json()
    assert detail["return_eligibility"]["eligible"] is False
    assert "delivered or collected" in detail["return_eligibility"]["reason"]
    assert detail["allowed_actions"] == []
    assert error_of(request_return(client, order["order_id"], [(1, 1)])) == (409, "br11_return_window")
    assert SYDNEY_CBD is not None


def test_the_window_closes_after_thirty_days():
    customer, _, _, order = a_completed_order()
    just_inside = datetime.now(timezone.utc) - timedelta(days=29, hours=23)
    backdate_completion(order["order_id"], just_inside)
    assert customer.get(f"/api/v1/orders/{order['order_id']}").json()["return_eligibility"]["eligible"] is True

    closed = datetime.now(timezone.utc) - timedelta(days=31)
    backdate_completion(order["order_id"], closed)
    detail = customer.get(f"/api/v1/orders/{order['order_id']}").json()
    assert detail["return_eligibility"]["eligible"] is False
    assert "30-day return window closed" in detail["return_eligibility"]["reason"]
    assert error_of(request_return(customer, order["order_id"], [(1, 1)])) == (409, "br11_return_window")


def test_a_request_creates_its_lines_and_keeps_the_bought_price():
    customer, _, _, order = a_completed_order(quantity=3, price="19.95")
    response = request_return(customer, order["order_id"], [(1, 2)], reason="Wrong colour")
    assert response.status_code == 201, response.text
    detail = response.json()

    assert detail["status"] == "requested"
    assert detail["reason"] == "Wrong colour"
    assert detail["refund_amount"] is None                      # nothing refunded yet
    assert detail["refund_preview"] == "39.90"                  # 2 × 19.95
    assert [(line["line_no"], line["quantity"], line["unit_price"]) for line in detail["lines"]] \
        == [(1, 2, "19.95")]
    assert [(change["from_status"], change["to_status"], change["changed_by_staff_id"])
            for change in detail["history"]] == [(None, "requested", None)]
    # The order now reports what is left.
    remaining = customer.get(f"/api/v1/orders/{order['order_id']}").json()["return_eligibility"]["lines"][0]
    assert (remaining["returned_quantity"], remaining["remaining_quantity"]) == (2, 1)


def test_cumulative_quantities_are_bounded():
    customer, _, _, order = a_completed_order(quantity=2)
    assert request_return(customer, order["order_id"], [(1, 2)]).status_code == 201

    # Nothing left: the order is no longer eligible, and asking again breaks BR12.
    detail = customer.get(f"/api/v1/orders/{order['order_id']}").json()
    assert detail["return_eligibility"]["eligible"] is False
    assert "already been returned" in detail["return_eligibility"]["reason"]
    assert error_of(request_return(customer, order["order_id"], [(1, 1)])) \
        == (409, "br12_return_qty_within_purchased")


def test_rejected_quantities_are_released():
    customer, staff, _, order = a_completed_order(quantity=2)
    first = request_return(customer, order["order_id"], [(1, 2)]).json()
    staff.post(f"/api/v1/returns/{first['return_id']}/reject", json={"expected_status": "requested"})

    # Rejected returns stay visible but no longer hold the quantity back.
    listed = customer.get(f"/api/v1/customers/{order['customer_id']}/returns").json()
    assert [(row["return_id"], row["status"]) for row in listed] == [(first["return_id"], "rejected")]
    remaining = customer.get(f"/api/v1/orders/{order['order_id']}").json()["return_eligibility"]["lines"][0]
    assert remaining["remaining_quantity"] == 2
    assert request_return(customer, order["order_id"], [(1, 2)]).status_code == 201


def test_a_malformed_request_is_refused():
    from fastapi.testclient import TestClient
    from app.main import app
    customer, _, _, order = a_completed_order(quantity=2)
    url = f"/api/v1/orders/{order['order_id']}/returns"
    key = {"Idempotency-Key": "6b1d0a52-7c9e-4a6f-9a0b-2f3c4d5e6f70"}

    assert customer.post(url, json={"reason": "x", "lines": []}, headers=key).status_code == 422
    assert customer.post(url, json={"reason": "x", "lines": [{"line_no": 1, "quantity": 0}]},
                         headers=key).status_code == 422
    duplicate = {"reason": "x", "lines": [{"line_no": 1, "quantity": 1}, {"line_no": 1, "quantity": 1}]}
    assert error_of(customer.post(url, json=duplicate, headers=key)) == (422, "duplicate_lines")
    # The customer, the order, the time and the refund are never part of the request.
    extra = {"reason": "x", "lines": [{"line_no": 1, "quantity": 1}], "refund_amount": "999.00"}
    assert error_of(customer.post(url, json=extra, headers=key)) == (422, "validation_error")
    assert customer.post(url, json={"reason": "x", "lines": [{"line_no": 9, "quantity": 1}]},
                         headers=key).status_code == 404            # no such order line
    assert TestClient(app) is not None


def test_request_cannot_supply_time():
    """The request time, the customer, the order and the refund are the server's: supplying any of them
    is refused as an unknown field, so a caller cannot claim an earlier request or a bigger refund."""
    customer, _, _, order = a_completed_order(quantity=2)
    url = f"/api/v1/orders/{order['order_id']}/returns"
    key = {"Idempotency-Key": "7c2b1a90-4d3e-4f5a-8b6c-9d0e1f2a3b4c"}
    base = {"reason": "x", "lines": [{"line_no": 1, "quantity": 1}]}

    for extra in (
        {"requested_at": "2020-01-01T00:00:00Z"},       # an earlier request would beat the 30-day window
        {"customer_id": 999},
        {"order_id": order["order_id"] + 1},
        {"refund_amount": "999.00"},
        {"status": "refunded"},
    ):
        response = customer.post(url, json={**base, **extra}, headers=key)
        assert error_of(response) == (422, "validation_error"), (extra, response.text)

    # And the time that was recorded is the server's own, not anything from the body.
    created = request_return(customer, order["order_id"], [(1, 1)]).json()
    assert created["requested_at"] > order["placed_at"]


def test_a_replay_returns_the_same_request_without_touching_it_again():
    customer, _, _, order = a_completed_order(quantity=2)
    key = "0f9c2d7e-3b41-4c8a-96d5-1e2f3a4b5c6d"
    first = request_return(customer, order["order_id"], [(1, 1)], key=key)
    again = request_return(customer, order["order_id"], [(1, 1)], key=key)

    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["return_id"] == again.json()["return_id"]
    assert one("SELECT count(*) AS n FROM return_request WHERE order_id = %s", (order["order_id"],))["n"] == 1
    assert one("SELECT count(*) AS n FROM return_line", None)["n"] >= 1

    changed = request_return(customer, order["order_id"], [(1, 2)], key=key)
    assert error_of(changed) == (409, "idempotency_conflict")


def test_return_replay_after_window_closes():
    customer, _, _, order = a_completed_order(quantity=2)
    key = "5c7e1a90-2d4b-4f6a-8e3c-9b0a1d2e3f40"
    first = request_return(customer, order["order_id"], [(1, 1)], key=key)
    assert first.status_code == 201

    backdate_completion(order["order_id"], datetime.now(timezone.utc) - timedelta(days=45))
    replay = request_return(customer, order["order_id"], [(1, 1)], key=key)
    assert replay.status_code == 200
    assert replay.json()["return_id"] == first.json()["return_id"]


def test_another_customer_cannot_read_a_return_and_staff_reads_are_scoped():
    customer, staff, _, order = a_completed_order()
    created = request_return(customer, order["order_id"], [(1, 1)]).json()
    return_id = created["return_id"]

    assert shop_client(a_customer()[0]).get(f"/api/v1/returns/{return_id}").status_code == 404
    assert staff.get(f"/api/v1/returns/{return_id}").status_code == 200        # the fulfilling store
    from tests.shop import ISLA, staff_client
    assert staff_client(ISLA).get(f"/api/v1/returns/{return_id}").status_code == 404
    assert staff_client(SUPPORT).get(f"/api/v1/returns/{return_id}").status_code == 200
    assert shop_client(a_customer()[0]).get(f"/api/v1/customers/{order['customer_id']}/returns").status_code == 403
    assert AIDEN is not None

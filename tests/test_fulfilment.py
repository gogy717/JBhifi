"""T11: staff move an order along the transitions the database allows, and nothing else."""
from tests.shop import (AIDEN, BONDI, ISLA, SUPPORT, SYDNEY_CBD, WAREHOUSE, a_customer, a_product,
                        error_of, order_body, place, shop_client, staff_client)

WAREHOUSE_STAFF = 38      # Samuel Baker, the delivery store


def a_paid_order(*, method="click_collect", store_id=SYDNEY_CBD, quantity=1, price="189.00", stock=5):
    """A committed, charged order plus a client signed in as the customer who owns it."""
    customer_id, numbers = a_customer()
    product = a_product(price=price, stock=stock, store_id=store_id)
    client = shop_client(customer_id)
    body = order_body([(product, quantity)], method=method, store_id=store_id,
                      address_no=numbers[0] if method == "delivery" else None)
    response = place(client, body)
    assert response.status_code == 201, response.text
    return response.json()


def move(client, order, to_status, expected_status=None):
    return client.patch(f"/api/v1/orders/{order['order_id']}/status", json={
        "to_status": to_status, "expected_status": expected_status or order["status"],
    })


def test_a_delivery_order_moves_paid_picking_shipped_delivered():
    order = a_paid_order(method="delivery", store_id=WAREHOUSE)
    staff = staff_client(WAREHOUSE_STAFF)

    for to_status in ("picking", "shipped", "delivered"):
        response = move(staff, order, to_status)
        assert response.status_code == 200, response.text
        order = response.json()
        assert order["status"] == to_status

    assert [(change["to_status"], change["changed_by_staff_id"]) for change in order["history"]] == [
        ("placed", None), ("paid", None),
        ("picking", WAREHOUSE_STAFF), ("shipped", WAREHOUSE_STAFF), ("delivered", WAREHOUSE_STAFF),
    ]
    assert order["allowed_actions"] == []              # delivered: nothing left to do


def test_a_collection_order_moves_paid_picking_ready_collected():
    order = a_paid_order()
    staff = staff_client(AIDEN)

    for to_status in ("picking", "ready", "collected"):
        response = move(staff, order, to_status)
        assert response.status_code == 200, response.text
        order = response.json()

    assert order["status"] == "collected"
    assert [change["to_status"] for change in order["history"]] == [
        "placed", "paid", "picking", "ready", "collected"]
    assert {change["changed_by_staff_id"] for change in order["history"][2:]} == {AIDEN}


def test_an_illegal_move_is_refused_with_the_rule_name():
    order = a_paid_order()
    staff = staff_client(AIDEN)
    # A click & collect order never ships: the transition table has no such row (BR09).
    assert error_of(move(staff, order, "shipped")) == (409, "br09_order_status_transition")
    # And the order is untouched.
    assert staff.get(f"/api/v1/orders/{order['order_id']}").json()["status"] == "paid"


def test_a_stale_screen_is_told_the_order_moved_on():
    order = a_paid_order()
    staff = staff_client(AIDEN)
    assert move(staff, order, "picking").status_code == 200

    # The screen still showed `paid` and is now offering the next move from there; the order has moved on.
    stale = move(staff, order, "ready", expected_status="paid")
    assert error_of(stale) == (409, "stale_status")
    assert stale.json()["error"]["detail"] == {"status": "picking"}


def test_repeating_the_same_move_adds_no_second_history_entry():
    order = a_paid_order()
    staff = staff_client(AIDEN)
    first = move(staff, order, "picking").json()
    again = move(staff, first, "picking")
    assert again.status_code == 200
    assert [change["to_status"] for change in again.json()["history"]] == ["placed", "paid", "picking"]


def test_only_the_fulfilling_stores_staff_may_move_the_order():
    order = a_paid_order()                                   # fulfilled by store 1
    assert error_of(move(staff_client(ISLA), order, "picking")) == (403, "other_store")
    assert error_of(move(staff_client(SUPPORT), order, "picking")) == (403, "store_staff_only")
    # Support may still read it.
    assert staff_client(SUPPORT).get(f"/api/v1/orders/{order['order_id']}").status_code == 200


def test_cancelling_through_the_status_route_is_refused():
    order = a_paid_order()
    assert error_of(move(staff_client(AIDEN), order, "cancelled")) == (409, "cancellation_required")
    assert staff_client(AIDEN).get(f"/api/v1/orders/{order['order_id']}").json()["status"] == "paid"


def test_the_store_queue_lists_that_stores_orders_with_a_status_filter():
    mine = a_paid_order()
    other = a_paid_order(store_id=BONDI)
    staff = staff_client(AIDEN)
    move(staff, mine, "picking")

    # Earlier tests commit orders too, so the queue is checked by membership, not by exact contents.
    queue = staff.get(f"/api/v1/stores/{SYDNEY_CBD}/orders").json()
    by_id = {order["order_id"]: order for order in queue}
    assert by_id[mine["order_id"]]["status"] == "picking"
    assert other["order_id"] not in by_id                       # BONDI's order is not store 1's queue
    assert all(order["fulfilling_store_id"] == SYDNEY_CBD for order in queue)

    picking = staff.get(f"/api/v1/stores/{SYDNEY_CBD}/orders", params={"status": "picking"}).json()
    assert mine["order_id"] in {order["order_id"] for order in picking}
    assert {order["status"] for order in picking} == {"picking"}


def test_the_queue_needs_a_staff_session_for_that_store():
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get(f"/api/v1/stores/{SYDNEY_CBD}/orders").status_code == 401
    assert error_of(staff_client(ISLA).get(f"/api/v1/stores/{SYDNEY_CBD}/orders")) == (403, "other_store")
    assert staff_client(SUPPORT).get(f"/api/v1/stores/{SYDNEY_CBD}/orders").status_code == 200

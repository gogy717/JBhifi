"""Cancelling an order (T4): POST /orders/{id}/cancel.

Who may cancel when (the customer before picking starts; the fulfilling store's staff whenever BR09 allows;
support never), and that a cancellation gives back what checkout took: the stock, to the store it came from, and
the money (BR21). Orders are placed by a real checkout, so stock really was taken (tests/fulfilment_support.py).
"""
from fastapi.testclient import TestClient

from app.main import app
from tests.auth_support import as_customer, as_staff
from tests.checkout_support import WAREHOUSE, a_customer, committed, quantity_at
from tests.fulfilment_support import bought, history_of, payments_of, status_of
from tests.orders_support import move

client = TestClient(app)
API = "/api/v1"
AIDEN = 14                      # Sydney CBD (store 1)
ISLA = 16                       # Bondi Junction (store 2)
NORA = 40                       # support


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def cancel(order_id: int, from_status: str, headers: dict):
    return client.post(f"{API}/orders/{order_id}/cancel", json={"from_status": from_status}, headers=headers)


def test_a_customer_cancels_a_paid_order_and_gets_stock_and_money_back():
    order = bought(quantity=2, stock=5)             # 2 × 100.00 taken from Sydney CBD's 5
    assert quantity_at(order.store_id, order.product_id) == 3
    response = cancel(order.order_id, "paid", as_customer(order.email))
    assert response.status_code == 200, response.json()
    detail = response.json()
    assert detail["status"] == "cancelled"
    assert detail["payment"] == {"charged": "200.00", "refunded": "200.00", "balance": "0.00"}
    assert detail["allowed_next_statuses"] == []
    assert payments_of(order.order_id) == [("charge", "200.00", None), ("refund", "200.00", None)]
    assert quantity_at(order.store_id, order.product_id) == 5
    assert history_of(order.order_id)[-1] == ("paid", "cancelled", None)   # the customer's own move


def test_a_customer_cannot_cancel_once_picking_has_started():
    order = bought()
    move(order.order_id, "picking", "ready", staff_id=AIDEN)
    assert error_of(cancel(order.order_id, "ready", as_customer(order.email))) == (403, "customer_cancel_before_picking")
    assert status_of(order.order_id) == "ready"
    assert quantity_at(order.store_id, order.product_id) == 3


def test_store_staff_cancel_an_uncollected_order():
    order = bought()
    move(order.order_id, "picking", "ready", staff_id=AIDEN)
    response = cancel(order.order_id, "ready", as_staff(AIDEN))
    assert response.status_code == 200, response.json()
    assert history_of(order.order_id)[-1] == ("ready", "cancelled", AIDEN)
    assert payments_of(order.order_id)[-1] == ("refund", "200.00", None)
    assert quantity_at(order.store_id, order.product_id) == 5          # back on the shelf it was picked from


def test_store_staff_cannot_cancel_while_picking():
    order = bought()
    move(order.order_id, "picking", staff_id=AIDEN)
    assert error_of(cancel(order.order_id, "picking", as_staff(AIDEN))) == (409, "br09_order_status_transition")
    assert status_of(order.order_id) == "picking"
    assert payments_of(order.order_id) == [("charge", "200.00", None)]    # the refund rolled back too
    assert quantity_at(order.store_id, order.product_id) == 3


def test_support_cannot_cancel():
    order = bought()
    assert error_of(cancel(order.order_id, "paid", as_staff(NORA))) == (403, "support_cannot_cancel")
    assert status_of(order.order_id) == "paid"


def test_only_the_customer_and_the_fulfilling_store_cancel():
    order = bought()
    _, stranger = a_customer()
    assert error_of(cancel(order.order_id, "paid", as_customer(stranger))) == (403, "not_your_order")
    assert error_of(cancel(order.order_id, "paid", as_staff(ISLA))) == (403, "other_store")
    assert error_of(cancel(order.order_id, "paid", {})) == (401, "not_signed_in")
    assert status_of(order.order_id) == "paid"
    # A missing order: the same 403s, so nobody can probe which ids exist.
    assert error_of(cancel(999999, "paid", as_customer(stranger))) == (403, "not_your_order")
    assert error_of(cancel(999999, "paid", as_staff(ISLA))) == (403, "other_store")


def test_a_stale_screen_does_not_cancel_an_order_that_moved_on():
    order = bought()
    move(order.order_id, "picking", "ready", staff_id=AIDEN)
    response = cancel(order.order_id, "paid", as_staff(AIDEN))       # the screen still shows paid
    assert error_of(response) == (409, "status_changed")
    assert response.json()["error"]["detail"] == {"status": "ready"}
    assert status_of(order.order_id) == "ready"


def test_cancelling_twice_is_told_it_is_already_cancelled():
    order = bought()
    assert cancel(order.order_id, "paid", as_customer(order.email)).status_code == 200
    response = cancel(order.order_id, "paid", as_customer(order.email))   # a retry after a lost answer
    assert error_of(response) == (409, "status_changed")
    assert response.json()["error"]["detail"] == {"status": "cancelled"}
    assert [kind for kind, _, _ in payments_of(order.order_id)] == ["charge", "refund"]
    assert quantity_at(order.store_id, order.product_id) == 5


def test_a_zero_total_order_is_cancelled_without_a_refund():
    order = bought(price="0.00")
    assert cancel(order.order_id, "paid", as_customer(order.email)).status_code == 200
    assert payments_of(order.order_id) == []
    assert quantity_at(order.store_id, order.product_id) == 5


def test_a_delivery_restocks_the_warehouse_it_ships_from():
    order = bought(method="delivery", store_id=WAREHOUSE)
    assert cancel(order.order_id, "paid", as_customer(order.email)).status_code == 200
    assert quantity_at(WAREHOUSE, order.product_id) == 5


def test_a_restock_recreates_an_inventory_row_that_was_deleted():
    order = bought(quantity=2)
    committed("DELETE FROM inventory WHERE store_id = %s AND product_id = %s", (order.store_id, order.product_id))
    assert cancel(order.order_id, "paid", as_customer(order.email)).status_code == 200
    assert quantity_at(order.store_id, order.product_id) == 2          # not silently lost

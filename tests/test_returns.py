"""Returns through the API (spec §2–§3): a customer asks to return part of a completed order, and staff receive
it, then refund it (T2) or reject it.

Requests commit, so each test makes its own products and customer (tests/checkout_support.py) and its own
completed order (tests/returns_support.py).
"""
import uuid

from fastapi.testclient import TestClient

from app.main import app
from tests.auth_support import as_customer, as_staff
from tests.checkout_support import a_customer, a_product, committed
from tests.orders_support import paid_order
from tests.returns_support import completed_days_ago, completed_order, returns_of

client = TestClient(app)
API = "/api/v1"
SUPPORT = 40


def ask(headers: dict, order_id: int, lines: list[tuple[int, int]], key=None, reason: str = "Changed my mind"):
    """POST a return of lines = [(line_no, quantity), ...] with this Idempotency-Key (a new one if none)."""
    body = {"reason": reason, "lines": [{"line_no": line_no, "quantity": quantity} for line_no, quantity in lines]}
    return client.post(f"{API}/orders/{order_id}/returns", json=body,
                       headers={**headers, "Idempotency-Key": str(key or uuid.uuid4())})


def error_of(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def an_order(*prices_and_quantities: tuple[str, int]) -> tuple[int, str, int]:
    """A new customer's collected order at store 1 with one line per (price, quantity), in that order.
    Returns (customer_id, email, order_id)."""
    customer, email = a_customer()
    products = [(a_product(price)["sku"], quantity) for price, quantity in prices_and_quantities]
    return customer, email, completed_order(email, products)


# ---------------------------------------------------------------- asking for a return

def test_a_request_keeps_its_lines_at_the_prices_they_were_bought_at():
    customer, email, order_id = an_order(("189.00", 2), ("149.95", 1))
    response = ask(as_customer(email), order_id, [(1, 1), (2, 1)], reason="  Too loud  ")
    assert response.status_code == 201, response.text
    detail = response.json()
    assert (detail["order_id"], detail["customer_id"], detail["status"], detail["reason"]) == \
        (order_id, customer, "requested", "Too loud")
    assert [(line["line_no"], line["quantity"], line["unit_price"], line["line_total"]) for line in detail["lines"]] \
        == [(1, 1, "189.00", "189.00"), (2, 1, "149.95", "149.95")]
    assert (detail["quantity"], detail["value"], detail["refunded"]) == (2, "338.95", None)
    assert (detail["received_store_id"], detail["received_at"], detail["resolved_at"]) == (None, None, None)
    assert returns_of(order_id) == [detail["return_id"]]


def test_the_same_key_again_returns_the_first_return_and_changes_nothing():
    _, email, order_id = an_order(("189.00", 2))
    key = uuid.uuid4()
    first = ask(as_customer(email), order_id, [(1, 1)], key)
    again = ask(as_customer(email), order_id, [(1, 1)], key)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert returns_of(order_id) == [first.json()["return_id"]]


def test_a_replay_with_a_different_body_returns_the_first_return():
    # The body is not compared (no fingerprint): a changed request comes with a new key, as at checkout.
    _, email, order_id = an_order(("189.00", 2))
    key = uuid.uuid4()
    first = ask(as_customer(email), order_id, [(1, 1)], key)
    changed = ask(as_customer(email), order_id, [(1, 2)], key, reason="Something else")
    assert changed.status_code == 200, changed.text
    assert changed.json() == first.json()
    assert returns_of(order_id) == [first.json()["return_id"]]


def test_a_retry_after_the_window_closed_replays_the_return():
    _, email, order_id = an_order(("189.00", 2))
    key = uuid.uuid4()
    first = ask(as_customer(email), order_id, [(1, 1)], key)
    completed_days_ago(order_id, 31)
    # The key is looked up before anything is claimed, so BR11 never sees the retry ...
    again = ask(as_customer(email), order_id, [(1, 1)], key)
    assert again.status_code == 200, again.text
    assert again.json()["return_id"] == first.json()["return_id"]
    # ... while a new request is now outside the window.
    assert error_of(ask(as_customer(email), order_id, [(1, 1)])) == (409, "br11_return_window")


def test_only_a_completed_order_can_be_returned():
    _, email = a_customer()
    order_id = paid_order(email, [(a_product("189.00")["sku"], 1)])
    assert error_of(ask(as_customer(email), order_id, [(1, 1)])) == (409, "br11_return_window")
    assert returns_of(order_id) == []


def test_more_than_was_bought_is_refused_and_saves_nothing():
    _, email, order_id = an_order(("189.00", 2), ("149.95", 1))
    # Line 1 is fine on its own; line 2 asks for 5 of 1. The whole request is one transaction.
    assert error_of(ask(as_customer(email), order_id, [(1, 1), (2, 5)])) == (409, "br12_return_qty_within_purchased")
    assert returns_of(order_id) == []
    assert ask(as_customer(email), order_id, [(1, 2)]).status_code == 201
    assert error_of(ask(as_customer(email), order_id, [(1, 1)])) == (409, "br12_return_qty_within_purchased")


def test_the_same_line_twice_is_refused_and_saves_nothing():
    _, email, order_id = an_order(("189.00", 2))
    assert error_of(ask(as_customer(email), order_id, [(1, 1), (1, 1)])) == (409, "return_line_pk")
    assert returns_of(order_id) == []


def test_lines_the_order_does_not_have_or_quantities_below_one_are_refused():
    _, email, order_id = an_order(("189.00", 2))
    assert error_of(ask(as_customer(email), order_id, [(9, 1)])) == (409, "return_line_order_line_fk")
    assert error_of(ask(as_customer(email), order_id, [(1, 0)])) == (409, "return_line_qty_positive")
    assert returns_of(order_id) == []


def test_a_blank_reason_is_a_validation_error():
    _, email, order_id = an_order(("189.00", 2))
    assert error_of(ask(as_customer(email), order_id, [(1, 1)], reason="   ")) == (422, "validation_error")
    assert error_of(ask(as_customer(email), order_id, [])) == (422, "validation_error")
    no_key = client.post(f"{API}/orders/{order_id}/returns", headers=as_customer(email),
                         json={"reason": "Too big", "lines": [{"line_no": 1, "quantity": 1}]})
    assert error_of(no_key) == (422, "validation_error")
    assert returns_of(order_id) == []


def test_only_the_orders_customer_can_ask_to_return_it():
    _, _, order_id = an_order(("189.00", 2))
    _, stranger = a_customer()
    assert error_of(ask(as_customer(stranger), order_id, [(1, 1)])) == (403, "not_your_order")
    assert error_of(ask(as_customer(stranger), 999999, [(1, 1)])) == (403, "not_your_order")     # 403 before 404
    assert error_of(ask(as_staff(14), order_id, [(1, 1)])) == (403, "customer_only")
    assert error_of(ask({}, order_id, [(1, 1)])) == (401, "not_signed_in")
    assert returns_of(order_id) == []


# ---------------------------------------------------------------- the customer's reads

def test_a_customers_returns_are_listed_newest_first_for_them_and_support():
    customer, email, order_id = an_order(("189.00", 2), ("149.95", 1))
    first = ask(as_customer(email), order_id, [(1, 1)]).json()
    second = ask(as_customer(email), order_id, [(2, 1)]).json()
    mine = client.get(f"{API}/customers/{customer}/returns", headers=as_customer(email))
    assert mine.status_code == 200, mine.text
    assert [(row["return_id"], row["value"], row["status"]) for row in mine.json()] == \
        [(second["return_id"], "149.95", "requested"), (first["return_id"], "189.00", "requested")]
    assert client.get(f"{API}/customers/{customer}/returns", headers=as_staff(SUPPORT)).json() == mine.json()

    _, stranger = a_customer()
    assert error_of(client.get(f"{API}/customers/{customer}/returns", headers=as_customer(stranger))) == \
        (403, "not_your_account")
    assert error_of(client.get(f"{API}/customers/{customer}/returns", headers=as_staff(14))) == (403, "support_only")
    assert error_of(client.get(f"{API}/customers/999999/returns", headers=as_staff(SUPPORT))) == (404, "not_found")


def test_a_return_is_read_by_its_customer_and_support():
    _, email, order_id = an_order(("189.00", 2))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    url = f"{API}/returns/{asked['return_id']}"
    assert client.get(url, headers=as_customer(email)).json() == asked
    assert client.get(url, headers=as_staff(SUPPORT)).json() == asked

    _, stranger = a_customer()
    assert error_of(client.get(url, headers=as_customer(stranger))) == (403, "not_your_return")
    assert error_of(client.get(f"{API}/returns/999999", headers=as_customer(stranger))) == (403, "not_your_return")
    assert error_of(client.get(f"{API}/returns/999999", headers=as_staff(SUPPORT))) == (404, "not_found")
    assert error_of(client.get(url)) == (401, "not_signed_in")

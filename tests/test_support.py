"""R10: support staff look a customer up — search the directory, then read the customer's whole history.

The customers, orders and returns are committed (the API reads them on its own connections) and belong to
customers created inside each test, so nothing here depends on what other tests committed.
"""
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from tests.auth_support import as_customer, as_staff
from tests.checkout_support import a_product, committed
from tests.orders_support import customer_id, move, paid_order

client = TestClient(app)
API = "/api/v1"
AIDEN, NORA = 14, 40            # works at Sydney CBD (store 1); support


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def new_email() -> str:
    return f"support.{uuid.uuid4().hex[:10]}@example.com"


# ---------------------------------------------------------------- search: GET /customers?q=

def a_named_customer(name: str, email: str) -> int:
    return committed("INSERT INTO customer (email, full_name) VALUES (%s, %s) RETURNING customer_id",
                     (email, name))[0]["customer_id"]


def search(q: str, headers=None):
    return client.get(f"{API}/customers", params={"q": q}, headers=headers or as_staff(NORA))


def found(q: str) -> set[int]:
    response = search(q)
    assert response.status_code == 200, response.text
    return {row["customer_id"] for row in response.json()}


def test_support_finds_a_customer_by_part_of_their_name_or_email():
    tag = uuid.uuid4().hex[:8]
    by_name = a_named_customer(f"Wren Tag{tag}", f"wren.{uuid.uuid4().hex[:6]}@example.com")
    by_email = a_named_customer("Someone Else", f"tag{tag}@example.com")
    assert found(f"tag{tag}") == {by_name, by_email}                  # either column, any case
    assert found(f"TAG{tag}") == {by_name, by_email}


def test_a_percent_sign_in_the_search_is_matched_literally():
    tag = uuid.uuid4().hex[:8]
    percent = a_named_customer(f"Pct {tag}% Fan", new_email())
    a_named_customer(f"Pct {tag}X Fan", new_email())                   # an unescaped % would match this too
    assert found(f"{tag}%") == {percent}


def test_only_support_searches_customers():
    assert error_of(search("a", headers=as_staff(AIDEN))) == (403, "support_only")


# ---------------------------------------------------------------- history: GET /customers/{id}/history

def history(customer: int, headers=None):
    return client.get(f"{API}/customers/{customer}/history", headers=headers or as_staff(NORA))


def events(customer: int) -> list[tuple]:
    response = history(customer)
    assert response.status_code == 200, response.text
    return [(e["kind"], e["to_status"], e["amount"], e["staff_name"]) for e in response.json()]


def a_return_request(order_id: int) -> int:
    return committed("INSERT INTO return_request (order_id, reason) VALUES (%s, 'Too big') RETURNING return_id",
                     (order_id,))[0]["return_id"]


def refund(return_id: int, order_id: int, amount: str) -> None:
    committed("UPDATE return_request SET status = 'received', received_store_id = 1, processed_by_staff_id = %s "
              "WHERE return_id = %s", (AIDEN, return_id))
    committed("INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)",
              (order_id, amount, return_id))


def test_history_merges_status_changes_payments_and_returns_newest_first():
    email = new_email()
    product = a_product("40.00")
    order_id = paid_order(email, [(product["sku"], 1)])
    move(order_id, "picking", "ready", "collected", staff_id=AIDEN)
    return_id = a_return_request(order_id)
    refund(return_id, order_id, "40.00")
    assert events(customer_id(email)) == [
        ("refund", None, "40.00", None),
        ("return_requested", None, None, None),
        ("status", "collected", None, "Aiden Chen"),
        ("status", "ready", None, "Aiden Chen"),
        ("status", "picking", None, "Aiden Chen"),
        ("status", "paid", None, None),                     # the customer's own move: no staff member
        ("charge", None, "40.00", None),
        ("status", "placed", None, None),
    ]


def test_checkout_events_at_one_instant_read_placed_charge_paid():
    """Checkout writes placed, its charge and paid in one transaction, so all three carry one now(). The sort
    column puts the charge between the two status changes, whatever else shares that moment."""
    email = new_email()
    paid_order(email, [(a_product("15.00")["sku"], 2)])
    response = history(customer_id(email)).json()
    assert len({event["at"] for event in response}) == 1
    assert [(e["kind"], e["to_status"]) for e in reversed(response)] == [
        ("status", "placed"), ("charge", None), ("status", "paid")]
    assert response[1]["amount"] == str(Decimal("30.00"))


def test_a_cancellation_reads_refund_then_cancelled():
    """T4 (SP2) refunds the order and moves it to cancelled in one transaction, so both carry one now(): the
    refund lands just before the status change it enables."""
    email = new_email()
    order_id = paid_order(email, [(a_product("25.00")["sku"], 2)])
    response = client.post(f"{API}/orders/{order_id}/cancel", headers=as_customer(email), json={"from_status": "paid"})
    assert response.status_code == 200, response.text
    newest = history(customer_id(email)).json()[:2]
    assert [(e["kind"], e["to_status"], e["amount"]) for e in newest] == [
        ("status", "cancelled", None), ("refund", None, "50.00")]
    assert newest[0]["at"] == newest[1]["at"]


def test_history_shows_only_this_customers_events():
    email, other = new_email(), new_email()
    sku = a_product("10.00")["sku"]
    mine = paid_order(email, [(sku, 1)])
    paid_order(other, [(sku, 1)])
    assert {event["order_id"] for event in history(customer_id(email)).json()} == {mine}


def test_a_customer_reads_their_own_history_but_nobody_elses():
    email, other = new_email(), new_email()
    assert history(customer_id(email), headers=as_customer(email)).status_code == 200
    assert error_of(history(customer_id(other), headers=as_customer(email))) == (403, "not_your_account")


def test_store_staff_cannot_read_a_customers_history():
    assert error_of(history(customer_id(new_email()), headers=as_staff(AIDEN))) == (403, "support_only")


def test_support_is_told_when_the_customer_does_not_exist():
    assert error_of(history(999999)) == (404, "not_found")

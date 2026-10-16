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
from tests.returns_support import completed_days_ago, completed_order, refunds_of, returns_of

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
    # Each row lists its lines, so the order page can tell what is left to return, and My returns what came back.
    assert [[(line["line_no"], line["quantity"], line["name"]) for line in row["lines"]] for row in mine.json()] == \
        [[(2, 1, "Checkout test item")], [(1, 1, "Checkout test item")]]
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


# ---------------------------------------------------------------- staff: receive, then refund (T2) or reject

def act(headers: dict, return_id: int, action: str, reason: str | None = None):
    """POST /returns/{id}/receive, /refund or /reject (with a reason) as the signed-in caller."""
    body = None if reason is None else {"reason": reason}
    return client.post(f"{API}/returns/{return_id}/{action}", json=body, headers=headers)


def stock_of(store_id: int, product_id: int) -> int | None:
    """The committed stock of a product at a store, or None when the store has never had a row for it."""
    rows = committed("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s", (store_id, product_id))
    return rows[0]["quantity"] if rows else None


def test_receiving_records_the_store_the_receiver_and_the_time_and_moves_no_stock():
    product = a_product("189.00", stock=5)
    _, email = a_customer()
    order_id = completed_order(email, [(product["sku"], 2)])
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    # Collected at Sydney CBD, brought back to Bondi Junction: any retail store takes returns in.
    received = act(as_staff(16), asked["return_id"], "receive")
    assert received.status_code == 200, received.text
    detail = received.json()
    assert (detail["status"], detail["received_store_id"], detail["received_store_name"],
            detail["processed_by_name"]) == ("received", 2, "Bondi Junction", "Isla Robinson")
    assert detail["received_at"] is not None and detail["resolved_at"] is None
    assert (stock_of(1, product["product_id"]), stock_of(2, product["product_id"])) == (5, None)


def test_receiving_twice_is_a_status_conflict_with_the_current_status():
    _, email, order_id = an_order(("189.00", 2))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    assert act(as_staff(14), asked["return_id"], "receive").status_code == 200
    again = act(as_staff(14), asked["return_id"], "receive")
    assert error_of(again) == (409, "return_status_transition")
    assert again.json()["error"]["detail"] == {"status": "received"}


def test_the_warehouse_cannot_receive_a_return():
    _, email, order_id = an_order(("189.00", 2))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    assert error_of(act(as_staff(13), asked["return_id"], "receive")) == (409, "br22_return_received_at_retail_store")


def test_refunding_restocks_the_receiving_store_and_refunds_the_value_once():
    stocked = a_product("189.00", stock=3)             # stocked at Sydney CBD
    unstocked = a_product("149.95")                    # never stocked anywhere: the refund gives it a row
    _, email = a_customer()
    order_id = completed_order(email, [(stocked["sku"], 2), (unstocked["sku"], 1)])
    asked = ask(as_customer(email), order_id, [(1, 2), (2, 1)]).json()
    assert act(as_staff(14), asked["return_id"], "receive").status_code == 200

    refunded = act(as_staff(15), asked["return_id"], "refund")      # another staff member of the store
    assert refunded.status_code == 200, refunded.text
    detail = refunded.json()
    assert (detail["status"], detail["refunded"], detail["value"]) == ("refunded", "527.95", "527.95")
    assert (detail["processed_by_name"], detail["resolved_by_name"]) == ("Aiden Chen", "Zara Ahmed")
    assert detail["resolved_at"] is not None
    assert (stock_of(1, stocked["product_id"]), stock_of(1, unstocked["product_id"])) == (5, 1)
    assert refunds_of(asked["return_id"]) == ["527.95"]
    order = client.get(f"{API}/orders/{order_id}", headers=as_customer(email)).json()
    assert order["payment"] == {"charged": "527.95", "refunded": "527.95", "balance": "0.00"}
    assert error_of(act(as_staff(14), asked["return_id"], "refund")) == (409, "return_status_transition")


def test_a_refund_pays_the_price_the_items_were_bought_at():
    product = a_product("189.00")
    _, email = a_customer()
    order_id = completed_order(email, [(product["sku"], 2)])
    committed("UPDATE product SET base_price = 249.00 WHERE product_id = %s", (product["product_id"],))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    act(as_staff(14), asked["return_id"], "receive")
    assert act(as_staff(14), asked["return_id"], "refund").json()["refunded"] == "189.00"
    assert refunds_of(asked["return_id"]) == ["189.00"]


def test_a_return_worth_nothing_is_refunded_without_a_payment():
    product = a_product("0.00")
    _, email = a_customer()
    order_id = completed_order(email, [(product["sku"], 1)])
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    act(as_staff(14), asked["return_id"], "receive")
    refunded = act(as_staff(14), asked["return_id"], "refund")
    assert refunded.status_code == 200, refunded.text
    assert (refunded.json()["status"], refunded.json()["refunded"]) == ("refunded", None)
    assert refunds_of(asked["return_id"]) == []                     # payment_amount_positive: no 0.00 row
    assert stock_of(1, product["product_id"]) == 1


def test_a_rejection_keeps_its_reason_and_moves_no_stock_or_money():
    product = a_product("189.00", stock=3)
    _, email = a_customer()
    order_id = completed_order(email, [(product["sku"], 2)])
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    act(as_staff(14), asked["return_id"], "receive")
    assert error_of(act(as_staff(14), asked["return_id"], "reject", "   ")) == (422, "validation_error")
    rejected = act(as_staff(15), asked["return_id"], "reject", "  Screen cracked  ")
    assert rejected.status_code == 200, rejected.text
    detail = rejected.json()
    assert (detail["status"], detail["rejection_reason"], detail["resolved_by_name"], detail["refunded"]) == \
        ("rejected", "Screen cracked", "Zara Ahmed", None)
    assert stock_of(1, product["product_id"]) == 3
    assert refunds_of(asked["return_id"]) == []
    assert error_of(act(as_staff(14), asked["return_id"], "refund")) == (409, "return_status_transition")


def test_a_return_is_refunded_or_rejected_only_once_it_is_received():
    _, email, order_id = an_order(("189.00", 2))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    for response in (act(as_staff(14), asked["return_id"], "refund"),
                     act(as_staff(14), asked["return_id"], "reject", "Not seen yet")):
        assert error_of(response) == (409, "return_status_transition")
        assert response.json()["error"]["detail"] == {"status": "requested"}


def test_only_the_receiving_store_refunds_or_rejects_a_return():
    _, email, order_id = an_order(("189.00", 2))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    act(as_staff(14), asked["return_id"], "receive")
    assert error_of(act(as_staff(16), asked["return_id"], "refund")) == (403, "other_store")
    assert error_of(act(as_staff(16), asked["return_id"], "reject", "Scratched")) == (403, "other_store")
    assert error_of(act(as_staff(16), 999999, "receive")) == (403, "other_store")     # 403 before 404


def test_only_store_staff_handle_returns():
    _, email, order_id = an_order(("189.00", 2))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    assert error_of(act(as_staff(SUPPORT), asked["return_id"], "receive")) == (403, "store_staff_only")
    assert error_of(act(as_customer(email), asked["return_id"], "receive")) == (403, "staff_only")
    assert error_of(act({}, asked["return_id"], "receive")) == (401, "not_signed_in")
    assert client.get(f"{API}/returns/{asked['return_id']}", headers=as_customer(email)).json()["status"] == "requested"


def test_store_staff_read_requested_returns_and_the_ones_their_store_received():
    _, email, order_id = an_order(("189.00", 2))
    asked = ask(as_customer(email), order_id, [(1, 1)]).json()
    url = f"{API}/returns/{asked['return_id']}"
    assert client.get(url, headers=as_staff(16)).status_code == 200            # any retail store may receive it
    assert error_of(client.get(url, headers=as_staff(13))) == (403, "other_store")    # the warehouse can't
    act(as_staff(14), asked["return_id"], "receive")
    assert client.get(url, headers=as_staff(14)).status_code == 200
    assert error_of(client.get(url, headers=as_staff(16))) == (403, "other_store")
    assert error_of(client.get(f"{API}/returns/999999", headers=as_staff(14))) == (403, "other_store")


def test_a_stores_desk_lists_its_orders_requested_returns_and_the_returns_it_received():
    _, email = a_customer()
    here = completed_order(email, [(a_product("189.00")["sku"], 1)], store_id=1)
    there = completed_order(email, [(a_product("189.00")["sku"], 1)], store_id=2)
    brought_here = completed_order(email, [(a_product("189.00")["sku"], 1)], store_id=2)
    requested_here = ask(as_customer(email), here, [(1, 1)]).json()["return_id"]
    requested_there = ask(as_customer(email), there, [(1, 1)]).json()["return_id"]
    received_here = ask(as_customer(email), brought_here, [(1, 1)]).json()["return_id"]
    act(as_staff(14), received_here, "receive")

    desk = client.get(f"{API}/stores/1/returns", headers=as_staff(14))
    assert desk.status_code == 200, desk.text
    listed = [row["return_id"] for row in desk.json()]
    mine = {row["return_id"]: row for row in desk.json() if row["return_id"] in (requested_here, received_here)}
    assert [len(mine[return_id]["lines"]) for return_id in (requested_here, received_here)] == [1, 1]
    assert received_here in listed and requested_here in listed and requested_there not in listed
    assert listed.index(received_here) < listed.index(requested_here)          # newest first
    assert [row["return_id"] for row in client.get(f"{API}/stores/1/returns", headers=as_staff(SUPPORT)).json()] \
        == listed
    assert error_of(client.get(f"{API}/stores/2/returns", headers=as_staff(14))) == (403, "other_store")
    assert error_of(client.get(f"{API}/stores/1/returns", headers=as_customer(email))) == (403, "staff_only")
    assert error_of(client.get(f"{API}/stores/999/returns", headers=as_staff(SUPPORT))) == (404, "not_found")

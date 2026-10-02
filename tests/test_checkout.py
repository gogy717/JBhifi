"""T1 checkout through the API (spec §3). One request is one transaction: the order, its lines at the
database's prices, the stock, the charge and the move to paid are committed together, or none of them is.

Checkout commits, so each test makes its own products (tests/checkout_support.py), and its own customer
whenever it changes one or counts its orders.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import orders
from tests.auth_support import as_customer, as_staff
from tests.checkout_support import (BONDI, SYDNEY_CBD, WAREHOUSE, a_customer, a_product, a_shopper,
                                    checkout_request, committed, order_body, orders_with_key, quantity_at)
from tests.orders_support import customer_id, move

client = TestClient(app)
API = "/api/v1"
ALICE = "alice.morgan@example.com"      # address 1: 12 Harris St, Pyrmont NSW 2009
BEN = "ben.okafor@example.com"          # address 1 retired (he moved out), address 2 current


def place(headers: dict, body: dict, key=None):
    """POST /orders as the signed-in caller, with this Idempotency-Key (a new one if none is given)."""
    return client.post(f"{API}/orders", json=body, headers={**headers, "Idempotency-Key": str(key or uuid.uuid4())})


def error_of(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def payments_of(order_id: int) -> list[tuple[str, str]]:
    """The order's committed payment rows as (kind, amount)."""
    rows = committed("SELECT kind, amount FROM payment WHERE order_id = %s ORDER BY payment_id", (order_id,))
    return [(row["kind"], str(row["amount"])) for row in rows]


# ---------------------------------------------------------------- the two ways to get an order

def test_click_and_collect_writes_the_order_lines_stock_charge_and_history():
    customer, email = a_customer()
    plain = a_product("189.00", stock=5)
    on_sale = a_product("100.00", stock=5, sale="80.00")        # made second: the higher product_id
    response = place(as_customer(email), order_body([(on_sale, 1), (plain, 2)]))
    assert response.status_code == 201, response.text
    order = response.json()

    assert (order["customer_id"], order["status"], order["fulfilment_method"]) == (customer, "paid", "click_collect")
    assert (order["fulfilling_store_id"], order["fulfilling_store_name"]) == (SYDNEY_CBD, "Sydney CBD")
    assert order["delivery_address"] is None
    # Priced by v_product_current_price at checkout: the running promotion's 80.00, not the 100.00 base price.
    assert [(line["line_no"], line["product_id"], line["quantity"], line["unit_price"], line["line_total"])
            for line in order["lines"]] == [(1, plain["product_id"], 2, "189.00", "378.00"),
                                            (2, on_sale["product_id"], 1, "80.00", "80.00")]
    assert (order["total"], order["line_count"]) == ("458.00", 2)
    assert (quantity_at(SYDNEY_CBD, plain["product_id"]), quantity_at(SYDNEY_CBD, on_sale["product_id"])) == (3, 4)
    assert payments_of(order["order_id"]) == [("charge", "458.00")]
    assert order["payment"] == {"charged": "458.00", "refunded": "0.00", "balance": "458.00"}
    # Placed and paid in one transaction, by the customer: no staff member on either history row.
    assert [(h["seq"], h["from_status"], h["to_status"], h["changed_by_staff_id"], h["changed_by_name"])
            for h in order["history"]] == [(1, None, "placed", None, None), (2, "placed", "paid", None, None)]


def test_delivery_ships_from_the_warehouse_to_the_customers_address():
    product = a_product("99.95", stock=3, store_id=WAREHOUSE)
    body = order_body([(product, 1)], method="delivery", store_id=WAREHOUSE, address_no=1)
    response = place(as_customer(ALICE), body)
    assert response.status_code == 201, response.text
    order = response.json()

    assert (order["customer_id"], order["status"], order["fulfilment_method"]) == (customer_id(ALICE), "paid",
                                                                                  "delivery")
    assert (order["fulfilling_store_id"], order["fulfilling_store_name"]) == (WAREHOUSE, "Eastern Creek DC")
    assert order["delivery_address"] == {"address_no": 1, "line1": "12 Harris St", "suburb": "Pyrmont",
                                         "state": "NSW", "postcode": "2009"}
    assert [(line["line_no"], line["quantity"], line["unit_price"]) for line in order["lines"]] == [(1, 1, "99.95")]
    assert order["total"] == "99.95"
    assert quantity_at(WAREHOUSE, product["product_id"]) == 2
    assert payments_of(order["order_id"]) == [("charge", "99.95")]
    assert [(h["from_status"], h["to_status"], h["changed_by_staff_id"]) for h in order["history"]] == [
        (None, "placed", None), ("placed", "paid", None)]


def test_delivery_can_ship_from_a_retail_store_with_stock():
    """The web app pre-selects the warehouse for delivery, but the customer may ship from any store with stock."""
    _, email = a_customer()
    product = a_product("50.00", stock=2, store_id=SYDNEY_CBD)              # none at the warehouse
    response = place(as_customer(email),
                     order_body([(product, 1)], method="delivery", store_id=SYDNEY_CBD, address_no=1))
    assert response.status_code == 201, response.text
    order = response.json()
    assert (order["fulfilment_method"], order["fulfilling_store_id"], order["fulfilling_store_name"]) == (
        "delivery", SYDNEY_CBD, "Sydney CBD")
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 1
    assert committed("SELECT count(*) AS n FROM inventory WHERE store_id = %s AND product_id = %s",
                     (WAREHOUSE, product["product_id"]))[0]["n"] == 0
    # The fulfilling store's staff can read it; another store's cannot.
    assert client.get(f"{API}/orders/{order['order_id']}", headers=as_staff(14)).status_code == 200
    assert error_of(client.get(f"{API}/orders/{order['order_id']}", headers=as_staff(16))) == (403, "other_store")


# ---------------------------------------------------------------- retries (BR10)

def test_a_key_retried_after_its_order_moved_on_still_replays_it():
    """A tab left open after a network error retries long after: the store has started picking the order. The
    retry still answers 200 with that order as it is now; nothing is placed, taken or charged again."""
    _, email = a_customer()
    product = a_product("30.00", stock=3)
    headers, body, key = as_customer(email), order_body([(product, 1)]), uuid.uuid4()
    first = place(headers, body, key)
    assert first.status_code == 201, first.text
    move(first.json()["order_id"], "picking", staff_id=14)
    again = place(headers, body, key)
    assert again.status_code == 200, again.text
    assert (again.json()["order_id"], again.json()["status"]) == (first.json()["order_id"], "picking")
    assert orders_with_key(key) == [first.json()["order_id"]]
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 2
    assert payments_of(first.json()["order_id"]) == [("charge", "30.00")]


def test_the_same_key_again_returns_the_first_order_and_changes_nothing():
    _, email = a_customer()
    product = a_product("189.00", stock=5)
    headers = as_customer(email)
    key = uuid.uuid4()

    first = place(headers, order_body([(product, 1)]), key)
    assert first.status_code == 201, first.text
    # Since then the price went up, and the customer changed the basket: the key still means the first order.
    committed("UPDATE product SET base_price = 249.00 WHERE product_id = %s", (product["product_id"],))
    again = place(headers, order_body([(product, 1)]), key)
    changed = place(headers, order_body([(product, 2)], expected_total="498.00"), key)
    assert (again.status_code, changed.status_code) == (200, 200)
    assert again.json() == first.json() and changed.json() == first.json()      # sold at 189.00 (BR08)
    assert orders_with_key(key) == [first.json()["order_id"]]
    assert payments_of(first.json()["order_id"]) == [("charge", "189.00")]
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 4                 # taken once


def test_a_retry_after_the_address_was_retired_replays_the_order():
    """The answer to a delivery checkout was lost, and the customer retired the address before retrying. The
    key is looked up before it is claimed, so the retry never reaches BR17's trigger: it gets its order."""
    customer, email = a_customer()
    product = a_product("99.95", stock=3, store_id=WAREHOUSE)
    headers = as_customer(email)
    body = order_body([(product, 1)], method="delivery", store_id=WAREHOUSE, address_no=1)
    key = uuid.uuid4()

    first = place(headers, body, key)
    assert first.status_code == 201, first.text
    committed("UPDATE customer_address SET is_active = FALSE WHERE customer_id = %s AND address_no = 1", (customer,))

    retry = place(headers, body, key)
    assert retry.status_code == 200, retry.text
    assert retry.json()["order_id"] == first.json()["order_id"]
    assert retry.json()["delivery_address"]["address_no"] == 1                  # where it was sent
    # A new attempt to that address is refused: the 200 above really was the replay.
    assert error_of(place(headers, body)) == (409, "br17_order_address_active")
    assert orders_with_key(key) == [first.json()["order_id"]]
    assert quantity_at(WAREHOUSE, product["product_id"]) == 2


def test_another_customers_key_never_replays_their_order():
    """BR10's key is unique per customer: someone else sending the same key places their own order."""
    product = a_product(stock=5)
    key = uuid.uuid4()
    placed = {}
    for _ in range(2):
        customer, email = a_customer()
        response = place(as_customer(email), order_body([(product, 1)]), key)
        assert response.status_code == 201, response.text
        assert response.json()["customer_id"] == customer
        placed[customer] = response.json()["order_id"]
    rows = committed("SELECT customer_id, order_id FROM customer_order WHERE idempotency_key = %s", (str(key),))
    assert {row["customer_id"]: row["order_id"] for row in rows} == placed
    assert len(set(placed.values())) == 2


def test_a_refused_checkout_does_not_use_up_its_key():
    """A refusal rolls the key's claim back with everything else, so the same reviewed basket can be sent
    again with the same key once the problem is gone (the web app keeps the key across retries)."""
    _, email = a_customer()
    product = a_product("50.00", stock=1)
    headers = as_customer(email)
    body = order_body([(product, 2)])
    key = uuid.uuid4()

    assert error_of(place(headers, body, key)) == (409, "out_of_stock")
    committed("UPDATE inventory SET quantity = 2 WHERE store_id = %s AND product_id = %s",
              (SYDNEY_CBD, product["product_id"]))
    retry = place(headers, body, key)
    assert retry.status_code == 201, retry.text
    assert orders_with_key(key) == [retry.json()["order_id"]]


# ---------------------------------------------------------------- the price the customer reviewed

def test_a_promotion_starting_after_review_is_a_price_change():
    """The customer reviewed $100.00, then a promotion started before they placed the order. A lower price is
    still a change: nothing is charged that wasn't reviewed, and the page gets the new lines to show."""
    _, email = a_customer()
    product = a_product("100.00", stock=5)
    headers = as_customer(email)
    assert client.get(f"{API}/products/{product['product_id']}").json()["current_price"] == "100.00"   # the review
    committed("""INSERT INTO promotion (product_id, sale_price, starts_at, ends_at)
                 VALUES (%s, 80.00, now(), now() + interval '1 day')""", (product["product_id"],))

    key = uuid.uuid4()
    response = place(headers, order_body([(product, 1)]), key)                  # still expects 100.00
    assert error_of(response) == (409, "price_changed")
    assert response.json()["error"]["detail"] == {
        "total": "80.00",
        "lines": [{"line_no": 1, "product_id": product["product_id"], "sku": product["sku"],
                   "name": "Checkout test item", "quantity": 1, "unit_price": "80.00", "line_total": "80.00"}],
    }
    assert orders_with_key(key) == []
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 5

    # Reviewed again at the new price, under a new key: placed at 80.00.
    again = place(headers, order_body([(product, 1)], expected_total="80.00"))
    assert again.status_code == 201, again.text
    assert again.json()["lines"][0]["unit_price"] == "80.00"


def test_a_zero_total_order_gets_no_charge_row():
    """A free item (a promotion at $0.00). A payment is always positive, so there is nothing to charge, and
    BR20 lets the order be paid because 0 charged = 0 due."""
    _, email = a_customer()
    product = a_product("10.00", stock=1, sale="0.00")
    response = place(as_customer(email), order_body([(product, 1)]))
    assert response.status_code == 201, response.text
    order = response.json()
    assert (order["status"], order["total"]) == ("paid", "0.00")
    assert order["payment"] == {"charged": "0.00", "refunded": "0.00", "balance": "0.00"}
    assert payments_of(order["order_id"]) == []
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 0


# ---------------------------------------------------------------- what the database refuses

def test_an_unknown_product_is_404_and_saves_nothing():
    _, email = a_customer()
    product = a_product(stock=5)
    body = order_body([(product, 1)])
    body["items"].append({"product_id": 999999, "quantity": 1})    # sorts last: the order and line 1 are in first
    key = uuid.uuid4()
    assert error_of(place(as_customer(email), body, key)) == (404, "not_found")
    assert orders_with_key(key) == []


def test_a_retired_product_cannot_be_ordered():
    _, email = a_customer()
    product = a_product(stock=5, active=False)
    key = uuid.uuid4()
    assert error_of(place(as_customer(email), order_body([(product, 1)]), key)) == (409, "br07_product_on_sale")
    assert orders_with_key(key) == []
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 5


def test_a_retired_address_cannot_be_delivered_to():
    """Ben's address 1 is retired in the seed (he moved): a new delivery there is refused by BR17's trigger."""
    product = a_product(stock=5, store_id=WAREHOUSE)
    key = uuid.uuid4()
    body = order_body([(product, 1)], method="delivery", store_id=WAREHOUSE, address_no=1)
    assert error_of(place(as_customer(BEN), body, key)) == (409, "br17_order_address_active")
    assert orders_with_key(key) == []


def test_the_address_must_fit_the_method_and_be_the_customers_own():
    _, email = a_customer()                                         # has address 1 only
    product = a_product(stock=5, store_id=WAREHOUSE)
    headers = as_customer(email)
    no_address = place(headers, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE))
    assert error_of(no_address) == (409, "br06_order_address_matches_method")
    assert no_address.json()["error"]["message"] == \
        "A delivery order needs one of your addresses, and a Click & Collect order has none."
    collect_with_address = place(headers, order_body([(product, 1)], address_no=1))
    assert error_of(collect_with_address) == (409, "br06_order_address_matches_method")
    not_theirs = place(headers, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE, address_no=99))
    assert error_of(not_theirs) == (409, "br17_order_address_is_customers")
    assert not_theirs.json()["error"]["message"] == "That address isn't one of yours."


def test_click_and_collect_is_refused_at_the_warehouse():
    _, email = a_customer()
    product = a_product(stock=5, store_id=WAREHOUSE)
    key = uuid.uuid4()
    body = order_body([(product, 1)], store_id=WAREHOUSE)
    assert error_of(place(as_customer(email), body, key)) == (409, "br06_collect_at_retail_store")
    assert orders_with_key(key) == []


def test_an_unknown_store_is_refused_by_its_foreign_key():
    _, email = a_customer()
    product = a_product(stock=5)
    body = order_body([(product, 1)], method="delivery", store_id=999999, address_no=1)
    response = place(as_customer(email), body)
    assert error_of(response) == (409, "customer_order_store_fk")
    assert response.json()["error"]["message"] == "That store doesn't exist."


def test_a_product_listed_twice_is_refused_by_br07():
    _, email = a_customer()
    product = a_product(stock=5)
    key = uuid.uuid4()
    response = place(as_customer(email), order_body([(product, 1), (product, 1)]), key)
    assert error_of(response) == (409, "br07_order_line_product_once")
    assert orders_with_key(key) == []
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 5


def test_a_quantity_below_one_is_refused_by_br07():
    """Quantity is only typed in the request model; BR07's CHECK refuses 0 and below, before any stock moves
    (a negative quantity must never add stock)."""
    _, email = a_customer()
    product = a_product(stock=5)
    headers = as_customer(email)
    for quantity in (0, -1):
        response = place(headers, order_body([(product, quantity)]))
        assert error_of(response) == (409, "br07_order_line_qty_positive")
        assert response.json()["error"]["message"] == "Each quantity must be at least 1."
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 5


def test_lines_are_numbered_in_product_id_order():
    _, email = a_customer()
    older = a_product("10.00", stock=5)
    newer = a_product("20.00", stock=5)                            # made second: the higher product_id
    response = place(as_customer(email), order_body([(newer, 1), (older, 1)]))
    assert response.status_code == 201, response.text
    assert [(line["line_no"], line["product_id"]) for line in response.json()["lines"]] == [
        (1, older["product_id"]), (2, newer["product_id"])]


def test_staff_cannot_check_out():
    """Shopping is for customers: store staff and support are refused before anything is read or written."""
    product = a_product(stock=5)
    for staff_id in (14, 40):                                       # Aiden (Sydney CBD), Nora (support)
        key = uuid.uuid4()
        assert error_of(place(as_staff(staff_id), order_body([(product, 1)]), key)) == (403, "customer_only")
        assert orders_with_key(key) == []
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 5


def test_out_of_stock_saves_nothing():
    """The second line is short. By then the order, both lines and the first line's stock were written; all
    of it is rolled back, and the page is told which product, how many were asked for and how many are left."""
    _, email = a_customer()
    plenty = a_product("10.00", stock=5)                            # made first: its stock is taken first
    short = a_product("20.00", stock=1)
    headers = as_customer(email)
    key = uuid.uuid4()

    response = place(headers, order_body([(plenty, 2), (short, 3)]), key)
    assert error_of(response) == (409, "out_of_stock")
    assert response.json()["error"]["detail"] == {"store_id": SYDNEY_CBD, "product_id": short["product_id"],
                                                  "sku": short["sku"], "requested": 3, "available": 1}
    assert orders_with_key(key) == []
    assert (quantity_at(SYDNEY_CBD, plenty["product_id"]), quantity_at(SYDNEY_CBD, short["product_id"])) == (5, 1)

    # A store that never stocked it has no inventory row at all: 0 left there.
    elsewhere = place(headers, order_body([(plenty, 1)], store_id=BONDI))
    assert error_of(elsewhere) == (409, "out_of_stock")
    assert elsewhere.json()["error"]["detail"]["available"] == 0


def test_a_failed_charge_rolls_back_everything(monkeypatch):
    """Plan §5's simulated payment failure. The charge is the last step before paid, so by then the order, its
    line, its first history row and the stock change are all written; the failure takes every one of them
    back, and the key is free for the retry."""
    actor = a_shopper()
    product = a_product("30.00", stock=4)
    body = order_body([(product, 1)])
    key = uuid.uuid4()
    seen = {}

    def declined(cur, order_id):
        cur.execute(
            """
            SELECT (SELECT count(*) FROM order_line WHERE order_id = %(id)s)           AS lines,
                   (SELECT count(*) FROM order_status_history WHERE order_id = %(id)s) AS history,
                   (SELECT quantity FROM inventory WHERE store_id = %(store)s AND product_id = %(product)s) AS stock
            """,
            {"id": order_id, "store": SYDNEY_CBD, "product": product["product_id"]},
        )
        seen.update(cur.fetchone(), order_id=order_id)
        raise RuntimeError("card declined")

    monkeypatch.setattr(orders, "_charge", declined)
    with pytest.raises(RuntimeError, match="card declined"):
        checkout_request(actor, key, body)
    assert (seen["lines"], seen["history"], seen["stock"]) == (1, 1, 3)     # written, inside the transaction
    left = committed(
        """
        SELECT (SELECT count(*) FROM customer_order       WHERE order_id = %(id)s) AS orders,
               (SELECT count(*) FROM order_line           WHERE order_id = %(id)s) AS lines,
               (SELECT count(*) FROM payment              WHERE order_id = %(id)s) AS payments,
               (SELECT count(*) FROM order_status_history WHERE order_id = %(id)s) AS history
        """,
        {"id": seen["order_id"]},
    )[0]
    assert left == {"orders": 0, "lines": 0, "payments": 0, "history": 0}
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 4

    monkeypatch.undo()                                              # this time the payment goes through
    detail, replayed = checkout_request(actor, key, body)
    assert (detail["status"], replayed) == ("paid", False)          # a new order: the key was free
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 3


# ---------------------------------------------------------------- the request's shape (422)

def test_a_request_of_the_wrong_shape_is_a_422():
    """Shape only: the price and the customer come from the server, so sending either is an error, not ignored."""
    _, email = a_customer()
    product = a_product(stock=5)
    headers = as_customer(email)
    body = order_body([(product, 1)])
    line = {"product_id": product["product_id"], "quantity": 1}
    for wrong in ({**body, "items": []},
                  {**body, "items": [{**line, "unit_price": "1.00"}]},
                  {**body, "customer_id": 1},
                  {**body, "expected_total": "100.001"},
                  {**body, "fulfilment_method": "drone"}):
        assert error_of(place(headers, wrong)) == (422, "validation_error"), wrong
    missing_key = client.post(f"{API}/orders", json=body, headers=headers)
    assert error_of(missing_key) == (422, "validation_error")
    not_a_uuid = client.post(f"{API}/orders", json=body, headers={**headers, "Idempotency-Key": "twice"})
    assert error_of(not_a_uuid) == (422, "validation_error")
    assert quantity_at(SYDNEY_CBD, product["product_id"]) == 5

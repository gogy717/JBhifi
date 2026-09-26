"""T09: checkout is one all-or-nothing transaction, and a retry is told from a changed request."""
import uuid
from decimal import Decimal

import pytest

from tests.shop import (AIDEN, BONDI, SYDNEY_CBD, WAREHOUSE, a_customer, a_product, error_of, order_body,
                        place, shop_client)
from tests.support import connect


def query(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def one(sql, params=None):
    return query(sql, params)[0]


# ---------------------------------------------------------------- the happy paths

def test_click_collect_checkout_writes_order_lines_stock_payment_and_history():
    customer_id, _ = a_customer()
    product = a_product(price="189.00", stock=5)
    client = shop_client(customer_id)

    response = place(client, order_body([(product, 2)]))
    assert response.status_code == 201, response.text
    order = response.json()

    assert order["status"] == "paid"
    assert order["fulfilment_method"] == "click_collect"
    assert order["fulfilling_store_name"] == "Sydney CBD"
    assert [(line["line_no"], line["quantity"], line["unit_price"]) for line in order["lines"]] \
        == [(1, 2, "189.00")]
    assert order["total"] == "378.00"
    assert [(payment["kind"], payment["amount"]) for payment in order["payments"]] == [("charge", "378.00")]
    assert [(change["from_status"], change["to_status"], change["changed_by_staff_id"])
            for change in order["history"]] == [(None, "placed", None), ("placed", "paid", None)]
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 3


def test_delivery_checkout_keeps_the_address_it_was_placed_with():
    customer_id, numbers = a_customer()
    product = a_product(price="99.95", stock=3, store_id=WAREHOUSE)
    client = shop_client(customer_id)

    response = place(client, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE,
                                        address_no=numbers[0]))
    assert response.status_code == 201, response.text
    assert response.json()["delivery_address"]["address_no"] == numbers[0]
    assert response.json()["delivery_address"]["line1"] == "1 Test St"


def test_a_running_promotion_sets_the_price_that_is_charged():
    customer_id, _ = a_customer()
    product = a_product(price="100.00", sale="80.00", stock=2)
    client = shop_client(customer_id)

    response = place(client, order_body([(product, 1)]))
    assert response.status_code == 201, response.text
    assert response.json()["lines"][0]["unit_price"] == "80.00"       # the sale price, not the base price
    assert response.json()["total"] == "80.00"


def test_a_zero_total_order_still_advances_without_a_payment_row():
    customer_id, _ = a_customer()
    product = a_product(price="0.00", stock=1)
    client = shop_client(customer_id)

    response = place(client, order_body([(product, 1)]))
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "paid"
    assert response.json()["payments"] == []                          # nothing to charge
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 0


# ---------------------------------------------------------------- validation

def test_click_collect_is_refused_at_the_warehouse():
    customer_id, _ = a_customer()
    product = a_product(stock=5, store_id=WAREHOUSE)
    client = shop_client(customer_id)

    response = place(client, order_body([(product, 1)], store_id=WAREHOUSE))
    assert error_of(response) == (409, "br06_collect_at_retail_store")


def test_delivery_needs_one_of_the_customers_own_active_addresses():
    customer_id, numbers = a_customer(addresses=2, active=False)
    product = a_product(stock=5)
    client = shop_client(customer_id)

    assert error_of(place(client, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE))) \
        == (422, "delivery_needs_address")
    # Address 1 exists but is retired (BR16: never edited, only replaced).
    assert error_of(place(client, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE,
                                             address_no=numbers[0]))) == (409, "address_inactive")
    assert error_of(place(client, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE,
                                             address_no=99))) == (404, "not_found")

    # The other customer's address 3 is not one this customer has at all.
    a_customer(addresses=3)
    assert error_of(place(client, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE,
                                             address_no=3))) == (404, "not_found")
    assert one("SELECT count(*) AS n FROM customer_order WHERE customer_id = %s", (customer_id,))["n"] == 0


def test_a_malformed_basket_is_rejected():
    customer_id, _ = a_customer()
    product = a_product(stock=5)
    client = shop_client(customer_id)

    body = order_body([(product, 1)])
    assert error_of(client.post("/api/v1/orders", json={**body, "items": []},
                                headers={"Idempotency-Key": str(uuid.uuid4())})) == (422, "validation_error")
    duplicates = {**body, "items": [{"product_id": product["product_id"], "quantity": 1},
                                    {"product_id": product["product_id"], "quantity": 1}]}
    assert error_of(client.post("/api/v1/orders", json=duplicates,
                                headers={"Idempotency-Key": str(uuid.uuid4())})) == (422, "duplicate_items")
    assert error_of(client.post("/api/v1/orders", json={**body, "items": [
        {"product_id": product["product_id"], "quantity": 0}]},
        headers={"Idempotency-Key": str(uuid.uuid4())})) == (422, "validation_error")
    missing_header = client.post("/api/v1/orders", json=body)
    assert missing_header.status_code == 422          # the retry key is required


def test_the_client_cannot_supply_a_price_or_a_customer():
    customer_id, _ = a_customer()
    product = a_product(price="100.00", stock=5)
    client = shop_client(customer_id)
    body = order_body([(product, 1)])

    # Extra fields are refused outright: the price and the customer come from the server.
    extra_price = {**body, "items": [{"product_id": product["product_id"], "quantity": 1,
                                      "unit_price": "1.00"}]}
    assert error_of(client.post("/api/v1/orders", json=extra_price,
                                headers={"Idempotency-Key": str(uuid.uuid4())})) == (422, "validation_error")
    assert error_of(client.post("/api/v1/orders", json={**body, "customer_id": customer_id},
                                headers={"Idempotency-Key": str(uuid.uuid4())})) == (422, "validation_error")


def test_a_retired_product_cannot_be_bought():
    customer_id, _ = a_customer()
    product = a_product(stock=5, active=False)
    client = shop_client(customer_id)

    assert error_of(place(client, order_body([(product, 1)]))) == (409, "product_unavailable")


def test_an_unknown_product_is_not_found():
    customer_id, _ = a_customer()
    client = shop_client(customer_id)
    body = order_body([])
    body["items"] = [{"product_id": 999999, "quantity": 1}]
    body["expected_total"] = "1.00"
    assert error_of(place(client, body)) == (404, "not_found")


def test_the_reviewed_total_is_checked_and_nothing_commits_when_it_differs():
    customer_id, _ = a_customer()
    product = a_product(price="189.00", stock=5)
    client = shop_client(customer_id)

    response = place(client, order_body([(product, 1)], expected_total="150.00"))
    assert error_of(response) == (409, "price_changed")
    assert response.json()["error"]["detail"]["total"] == "189.00"    # the refreshed review data
    assert query("SELECT 1 FROM customer_order WHERE customer_id = %s", (customer_id,)) == []
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 5


def test_out_of_stock_saves_nothing():
    customer_id, _ = a_customer()
    product = a_product(price="50.00", stock=1)
    client = shop_client(customer_id)

    response = place(client, order_body([(product, 3)]))
    assert error_of(response) == (409, "out_of_stock")
    assert response.json()["error"]["detail"] == {
        "store_id": SYDNEY_CBD, "product_id": product["product_id"], "sku": product["sku"],
        "requested": 3, "available": 1,
    }
    assert query("SELECT 1 FROM customer_order WHERE customer_id = %s", (customer_id,)) == []
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 1


def test_a_later_line_failure_rolls_back_every_earlier_line():
    customer_id, _ = a_customer()
    plenty = a_product(price="10.00", stock=5)
    short = a_product(price="20.00", stock=1)
    client = shop_client(customer_id)

    response = place(client, order_body([(plenty, 2), (short, 4)]))
    assert error_of(response) == (409, "out_of_stock")
    assert query("SELECT 1 FROM customer_order WHERE customer_id = %s", (customer_id,)) == []
    assert query("SELECT 1 FROM payment p JOIN customer_order o USING (order_id) WHERE o.customer_id = %s",
                 (customer_id,)) == []
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, plenty["product_id"]))["quantity"] == 5     # the first line was taken back too
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, short["product_id"]))["quantity"] == 1


# ---------------------------------------------------------------- retries

def test_repeating_the_same_request_returns_the_same_order_without_a_second_effect():
    customer_id, _ = a_customer()
    product = a_product(price="189.00", stock=5)
    client = shop_client(customer_id)
    body = order_body([(product, 1)])
    key = uuid.uuid4()

    first = place(client, body, key)
    second = place(client, body, key)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["order_id"] == second.json()["order_id"]
    assert one("SELECT count(*) AS n FROM customer_order WHERE customer_id = %s", (customer_id,))["n"] == 1
    assert one("""SELECT count(*) AS n FROM payment p JOIN customer_order o USING (order_id)
                  WHERE o.customer_id = %s""", (customer_id,))["n"] == 1
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 4    # taken once, not twice


def test_the_same_key_with_a_different_body_is_a_conflict():
    customer_id, _ = a_customer()
    product = a_product(price="189.00", stock=5)
    client = shop_client(customer_id)
    key = uuid.uuid4()

    assert place(client, order_body([(product, 1)]), key).status_code == 201
    assert error_of(place(client, order_body([(product, 2)]), key)) == (409, "idempotency_conflict")
    assert one("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
               (SYDNEY_CBD, product["product_id"]))["quantity"] == 4


def test_a_replay_still_works_after_the_price_changed():
    customer_id, _ = a_customer()
    product = a_product(price="189.00", stock=5)
    client = shop_client(customer_id)
    body = order_body([(product, 1)])
    key = uuid.uuid4()

    first = place(client, body, key)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE product SET base_price = 249.00 WHERE product_id = %s", (product["product_id"],))
    replay = place(client, body, key)
    assert replay.status_code == 200
    assert replay.json()["order_id"] == first.json()["order_id"]
    assert replay.json()["lines"][0]["unit_price"] == "189.00"        # the price it was sold at (BR08)


def test_a_changed_price_needs_a_new_review_and_a_new_key():
    customer_id, _ = a_customer()
    product = a_product(price="189.00", stock=5)
    client = shop_client(customer_id)

    assert place(client, order_body([(product, 1)]), uuid.uuid4()).status_code == 201
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE product SET base_price = 249.00 WHERE product_id = %s", (product["product_id"],))

    reviewed = order_body([(product, 1)])                    # still the old, reviewed total
    response = place(client, reviewed, uuid.uuid4())
    assert error_of(response) == (409, "price_changed")
    assert response.json()["error"]["detail"]["total"] == "249.00"

    # Reviewing the new total and retrying under a fresh key places the order at the new price.
    fresh = place(client, order_body([(product, 1)], expected_total="249.00"), uuid.uuid4())
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["lines"][0]["unit_price"] == "249.00"


def test_a_guest_cannot_check_out():
    from tests.shop import API
    from fastapi.testclient import TestClient
    from app.main import app
    product = a_product(stock=1)
    response = place(TestClient(app), order_body([(product, 1)]))
    assert error_of(response) == (401, "not_signed_in")
    assert API is not None

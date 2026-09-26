"""T09: who may read which order, and what a committed order still shows afterwards."""
from tests.shop import (AIDEN, ISLA, SUPPORT, a_customer, a_product, error_of, order_body, place,
                        shop_client, staff_client)
from tests.support import connect


def one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def a_placed_order(client, **kwargs):
    product = kwargs.pop("product", None) or a_product(price="189.00", stock=5)
    response = place(client, order_body([(product, 1)], **kwargs))
    assert response.status_code == 201, response.text
    return product, response.json()


def test_the_customer_lists_their_own_orders_newest_first():
    customer_id, _ = a_customer()
    client = shop_client(customer_id)
    _, first = a_placed_order(client, product=a_product(price="10.00", stock=2))
    _, second = a_placed_order(client, product=a_product(price="20.00", stock=2))

    listed = client.get(f"/api/v1/customers/{customer_id}/orders").json()
    assert [order["order_id"] for order in listed] == [second["order_id"], first["order_id"]]
    assert [order["total"] for order in listed] == ["20.00", "10.00"]


def test_a_customer_cannot_list_or_read_another_customers_order():
    owner_id, _ = a_customer()
    owner = shop_client(owner_id)
    _, order = a_placed_order(owner)

    stranger_id, _ = a_customer()
    stranger = shop_client(stranger_id)
    # Another customer's order is a 404 — the same answer as one that does not exist.
    assert error_of(stranger.get(f"/api/v1/orders/{order['order_id']}")) == (404, "not_found")
    assert error_of(stranger.get(f"/api/v1/customers/{owner_id}/orders")) == (403, "not_your_account")
    assert error_of(stranger.get("/api/v1/orders/999999")) == (404, "not_found")


def test_a_guest_cannot_read_orders_at_all():
    from fastapi.testclient import TestClient
    from app.main import app
    guest = TestClient(app)
    assert error_of(guest.get("/api/v1/orders/1")) == (401, "not_signed_in")
    assert error_of(guest.get("/api/v1/customers/1/orders")) == (401, "not_signed_in")


def test_store_staff_see_their_own_stores_orders_and_no_others():
    customer_id, _ = a_customer()
    client = shop_client(customer_id)
    _, order = a_placed_order(client)                      # collected at store 1

    assert staff_client(AIDEN).get(f"/api/v1/orders/{order['order_id']}").status_code == 200
    assert error_of(staff_client(ISLA).get(f"/api/v1/orders/{order['order_id']}")) == (404, "not_found")


def test_support_staff_can_read_any_order_but_may_not_move_it():
    customer_id, _ = a_customer()
    client = shop_client(customer_id)
    _, order = a_placed_order(client)

    support = staff_client(SUPPORT)
    assert support.get(f"/api/v1/orders/{order['order_id']}").status_code == 200
    assert order["allowed_actions"] == []                  # support reads; it does not fulfil


def test_the_customer_sees_what_they_may_do_next_and_a_store_member_sees_the_moves():
    customer_id, _ = a_customer()
    client = shop_client(customer_id)
    _, order = a_placed_order(client)

    assert order["allowed_actions"] == []                   # customer cancellation is not promised
    as_staff = staff_client(AIDEN).get(f"/api/v1/orders/{order['order_id']}").json()
    assert as_staff["allowed_actions"] == ["picking", "cancel"]


def test_the_detail_keeps_the_sold_price_the_address_and_the_whole_timeline():
    customer_id, numbers = a_customer()
    client = shop_client(customer_id)
    product, order = a_placed_order(client, product=a_product(price="189.00", stock=5),
                                    method="delivery", address_no=numbers[0])

    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE product SET base_price = 999.00 WHERE product_id = %s", (product["product_id"],))
        cur.execute("UPDATE customer_address SET is_active = FALSE WHERE customer_id = %s", (customer_id,))
    conn.close()

    detail = client.get(f"/api/v1/orders/{order['order_id']}").json()
    assert detail["lines"][0]["unit_price"] == "189.00"     # BR08: the purchase price is kept
    assert detail["total"] == "189.00"
    assert detail["delivery_address"]["line1"] == "1 Test St"    # the address it was placed with
    assert [change["to_status"] for change in detail["history"]] == ["placed", "paid"]
    assert one("SELECT count(*) AS n FROM payment WHERE order_id = %s", (order["order_id"],))["n"] == 1

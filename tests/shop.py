"""Helpers for the shop tests: committed products, customers and signed-in clients.

Checkout commits, so every test builds its own product and customer rather than sharing seed rows.
"""
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from tests.support import connect, unique_sku

API = "/api/v1"
SYDNEY_CBD = 1
BONDI = 2
WAREHOUSE = 13
AIDEN = 14        # store staff at Sydney CBD (store 1)
ISLA = 16         # store staff at Bondi Junction (store 2)
SUPPORT = 40      # support staff, no store


def committed(work):
    """Run work(cur) on its own connection and commit."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            return work(cur)
    finally:
        conn.close()


def a_product(price="100.00", stock=None, store_id=SYDNEY_CBD, active=True, name="Test item", sale=None):
    """A committed product, optionally stocked at one store and/or on an active promotion."""
    def work(cur):
        sku = unique_sku()
        cur.execute(
            """
            INSERT INTO product (sku, name, brand_id, category_id, base_price, is_active)
            SELECT %s, %s, b.brand_id, c.category_id, %s, %s
            FROM brand b, category c WHERE b.name = 'JBL' AND c.name = 'Speakers'
            RETURNING product_id
            """,
            (sku, name, price, active),
        )
        product_id = cur.fetchone()["product_id"]
        if stock is not None:
            cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                        (store_id, product_id, stock))
        if sale is not None:
            cur.execute("INSERT INTO promotion (product_id, sale_price, starts_at, ends_at) "
                        "VALUES (%s, %s, now() - interval '1 day', now() + interval '1 day')",
                        (product_id, sale))
        return {"product_id": product_id, "sku": sku, "price": price, "current": sale or price}
    return committed(work)


def a_customer(addresses=1, active=True):
    """A committed customer. Returns (customer_id, [address_no, ...])."""
    def work(cur):
        cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Shop Test') RETURNING customer_id",
                    (f"shop.{uuid.uuid4().hex[:8]}@example.com",))
        customer_id = cur.fetchone()["customer_id"]
        numbers = list(range(1, addresses + 1))
        for number in numbers:
            cur.execute(
                "INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode, is_active) "
                "VALUES (%s, %s, %s, 'Sydney', 'NSW', '2000', %s)",
                (customer_id, number, f"{number} Test St", active),
            )
        return customer_id, numbers
    return committed(work)


def sign_in(client: TestClient, kind: str, identity: int) -> TestClient:
    response = client.post(f"{API}/session", json={"kind": kind, "id": identity})
    assert response.status_code == 201, response.text
    return client


def shop_client(customer_id: int) -> TestClient:
    return sign_in(TestClient(app), "customer", customer_id)


def staff_client(staff_id: int) -> TestClient:
    return sign_in(TestClient(app), "staff", staff_id)


def order_body(items, *, method="click_collect", store_id=SYDNEY_CBD, address_no=None,
               expected_total=None):
    """An OrderCreate payload. `items` is [(product, quantity)] using a_product()'s dict."""
    # Decimal, never float: 19.95 * 3 must be exactly 59.85, as the server computes it.
    total = sum((Decimal(product["current"]) * quantity for product, quantity in items), Decimal("0.00"))
    return {
        "fulfilment_method": method,
        "fulfilling_store_id": store_id,
        "delivery_address_no": address_no,
        "items": [{"product_id": product["product_id"], "quantity": quantity} for product, quantity in items],
        "expected_total": expected_total if expected_total is not None else str(total),
    }


def place(client: TestClient, body, key=None):
    """POST /orders with an Idempotency-Key; returns the response."""
    return client.post(f"{API}/orders", json=body, headers={"Idempotency-Key": str(key or uuid.uuid4())})


def error_of(response):
    return response.status_code, response.json()["error"]["code"]

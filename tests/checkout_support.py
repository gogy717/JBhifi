"""Helpers for the checkout tests (T1, spec §3): committed products and customers, order bodies, and one
checkout run the way the API runs it. Ported from the branch's tests/shop.py without its demo-cookie
clients: API tests sign in with tests.auth_support.

Checkout commits, so each test makes its own products, and its own customer whenever it changes one.
"""
import threading
import uuid
from decimal import Decimal

from app.auth import Actor
from app.schemas.orders import OrderCreate
from app.services import orders
from tests.support import connect, unique_sku

SYDNEY_CBD = 1          # retail
BONDI = 2               # Bondi Junction, retail
WAREHOUSE = 13          # Eastern Creek DC: ships deliveries, can't be a Click & Collect store (BR06)


def committed(query: str, params=()) -> list:
    """Run one statement in its own committed transaction; return its rows ([] if it returns none)."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else []
    finally:
        conn.close()


def a_product(price: str = "100.00", *, stock: int | None = None, store_id: int = SYDNEY_CBD,
              sale: str | None = None, active: bool = True) -> dict:
    """A committed product (a JBL speaker) at `price`: optionally stocked at one store, on a promotion that is
    running now (`sale`), or already retired. Returns {product_id, sku, price}, price being what it sells for."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            sku = unique_sku()
            cur.execute(
                """
                INSERT INTO product (sku, name, brand_id, category_id, base_price, is_active)
                SELECT %s, 'Checkout test item', b.brand_id, c.category_id, %s, %s
                FROM brand b, category c
                WHERE b.name = 'JBL' AND c.name = 'Speakers'
                RETURNING product_id
                """,
                (sku, price, active),
            )
            product_id = cur.fetchone()["product_id"]
            if stock is not None:
                cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                            (store_id, product_id, stock))
            if sale is not None:
                cur.execute(
                    """
                    INSERT INTO promotion (product_id, sale_price, starts_at, ends_at)
                    VALUES (%s, %s, now() - interval '1 day', now() + interval '1 day')
                    """,
                    (product_id, sale),
                )
    finally:
        conn.close()
    return {"product_id": product_id, "sku": sku, "price": price if sale is None else sale}


def a_customer(addresses: int = 1) -> tuple[int, str]:
    """A committed customer with that many current addresses, numbered 1, 2, … Returns (customer_id, email):
    tests.auth_support.as_customer(email) signs in as them."""
    email = f"checkout.{uuid.uuid4().hex[:10]}@example.com"
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Checkout Tester') RETURNING customer_id",
                        (email,))
            customer_id = cur.fetchone()["customer_id"]
            for address_no in range(1, addresses + 1):
                cur.execute(
                    """
                    INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
                    VALUES (%s, %s, %s, 'Sydney', 'NSW', '2000')
                    """,
                    (customer_id, address_no, f"{address_no} Test St"),
                )
    finally:
        conn.close()
    return customer_id, email


def order_body(items, *, method: str = "click_collect", store_id: int = SYDNEY_CBD,
               address_no: int | None = None, expected_total: str | None = None) -> dict:
    """A POST /orders body for items = [(product, quantity), …], reviewed at the products' current prices."""
    # Decimal, never float: 3 × 19.95 must be exactly 59.85, as the database computes it.
    total = sum((Decimal(product["price"]) * quantity for product, quantity in items), Decimal("0.00"))
    return {
        "fulfilment_method": method,
        "fulfilling_store_id": store_id,
        "delivery_address_no": address_no,
        "items": [{"product_id": product["product_id"], "quantity": quantity} for product, quantity in items],
        "expected_total": str(total) if expected_total is None else expected_total,
    }


def quantity_at(store_id: int, product_id: int) -> int:
    """The committed stock of a product at a store."""
    rows = committed("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s", (store_id, product_id))
    return rows[0]["quantity"]


def orders_with_key(key) -> list[int]:
    """The committed orders placed with this Idempotency-Key, by any customer."""
    rows = committed("SELECT order_id FROM customer_order WHERE idempotency_key = %s ORDER BY order_id", (str(key),))
    return [row["order_id"] for row in rows]


def a_shopper() -> Actor:
    """A new committed customer, as the signed-in actor a service is given."""
    customer_id, _ = a_customer()
    return Actor("customer", customer_id, "Checkout Tester")


def checkout_request(actor, key, body: dict, *, lock_timeout: str | None = None) -> tuple[dict, bool]:
    """One checkout the way the API runs it: its own connection and one transaction, committed if it returns
    and rolled back if it raises (app/db.py). lock_timeout bounds how long it may wait for a row lock."""
    conn = connect()
    try:
        with conn:
            return checkout_in(conn, actor, key, body, lock_timeout=lock_timeout)
    finally:
        conn.close()


def checkout_in(conn, actor, key, body: dict, *, lock_timeout: str | None = None) -> tuple[dict, bool]:
    """A checkout inside the transaction open on conn, left uncommitted: the caller commits or rolls back."""
    with conn.cursor() as cur:
        if lock_timeout is not None:
            cur.execute("SELECT set_config('lock_timeout', %s, true)", (lock_timeout,))
        return orders.checkout(cur, actor, key, OrderCreate.model_validate(body))


def run_together(*works) -> list:
    """Run each work() in its own thread, all released at the same moment; return each result or exception.
    (tests.support.run_at_once runs one work n times; a race between two different requests needs this.)"""
    start = threading.Barrier(len(works))
    results = [None] * len(works)

    def worker(i):
        start.wait()
        try:
            results[i] = works[i]()
        except Exception as error:
            results[i] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(works))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results

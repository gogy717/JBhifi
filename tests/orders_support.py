"""Committed orders for the order tests, built in SQL exactly as a checkout (T1) leaves them.

Read tests don't go through POST /orders — checkout has its own tests — so they can't break when checkout
does. Each helper is one transaction on its own connection, committed, so the API (on other connections)
sees the result. Stock is not touched.
"""
from tests.support import connect


def customer_id(email: str) -> int:
    """The id of the customer with this email — created, with no addresses, the first time it is asked for
    (as a first sign-in with a new email would be)."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO customer (email, full_name) VALUES (%s, 'Order Test Customer')
                ON CONFLICT ON CONSTRAINT br01_customer_email_unique DO NOTHING
                """,
                (email,),
            )
            cur.execute("SELECT customer_id FROM customer WHERE email = %s", (email,))
            return cur.fetchone()["customer_id"]
    finally:
        conn.close()


def paid_order(email: str, items: list[tuple[str, int]], *, method: str = "click_collect", store_id: int = 1,
               address_no: int | None = None) -> int:
    """A paid order for items = [(sku, quantity), ...]: lines at today's prices, numbered in product_id order;
    one charge of the total (none for a zero total); status placed → paid by the customer. Returns its id."""
    buyer = customer_id(email)
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id,
                                            delivery_address_no)
                VALUES (%s, gen_random_uuid(), %s, %s, %s)
                RETURNING order_id
                """,
                (buyer, method, store_id, address_no),
            )
            order_id = cur.fetchone()["order_id"]
            lines = []
            for sku, quantity in items:
                cur.execute("SELECT product_id FROM product WHERE sku = %s", (sku,))
                lines.append((cur.fetchone()["product_id"], quantity))
            for line_no, (product_id, quantity) in enumerate(sorted(lines), start=1):
                cur.execute(
                    """
                    INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price)
                    SELECT %s, %s, product_id, %s, current_price
                    FROM v_product_current_price
                    WHERE product_id = %s
                    """,
                    (order_id, line_no, quantity, product_id),
                )
            cur.execute(
                """
                INSERT INTO payment (order_id, kind, amount)
                SELECT order_id, 'charge', total FROM v_order_total WHERE order_id = %s AND total > 0
                """,
                (order_id,),
            )
            cur.execute("SELECT set_config('app.staff_id', '', true)")
            cur.execute("UPDATE customer_order SET status = 'paid' WHERE order_id = %s", (order_id,))
        return order_id
    finally:
        conn.close()


def move(order_id: int, *statuses: str, staff_id: int | None = None) -> None:
    """Commit the order's moves through statuses, made by staff_id (None = the customer or the system). BR09
    checks each move against the transition table and logs it."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT set_config('app.staff_id', %s, true)", ("" if staff_id is None else str(staff_id),))
            for status in statuses:
                cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))
    finally:
        conn.close()

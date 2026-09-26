"""Helpers for building valid order/return histories in tests.

Everything here goes through the same statements the application uses — real INSERTs and real status
transitions — so a fixture cannot create a state the application could not reach. The one exception is
``backdate_history``, which is explicitly a maintenance operation (it needs table ownership) and is used
only to age a completed order past the 30-day return window.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
import uuid

ORDER = """
    INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint, fulfilment_method,
                                fulfilling_store_id, delivery_address_no)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING order_id
"""
LINE = "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s, %s)"
RETURN_REQUEST = """
    INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason)
    VALUES (%s, %s, %s, 'Changed my mind')
    RETURNING return_id
"""
RETURN_LINE = "INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, %s, %s, %s)"
CHARGE = "INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', %s) RETURNING payment_id"


def make_customer(cur, email: str, with_address: bool = True) -> int:
    cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Test Customer') RETURNING customer_id",
                (email,))
    customer_id = cur.fetchone()["customer_id"]
    if with_address:
        cur.execute(
            """
            INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
            VALUES (%s, 1, '1 George St', 'Sydney', 'NSW', '2000')
            """,
            (customer_id,),
        )
    return customer_id


def place_order(cur, customer_id, lines, method="click_collect", store_id=1, address_no=None) -> int:
    """Insert a placed order and its lines; lines = [(product_id, quantity, unit_price), ...]."""
    key = str(uuid.uuid4())
    cur.execute(ORDER, (customer_id, key, f"fingerprint:{key}", method, store_id, address_no))
    order_id = cur.fetchone()["order_id"]
    for line_no, (product_id, quantity, unit_price) in enumerate(lines, start=1):
        cur.execute(LINE, (order_id, line_no, product_id, quantity, unit_price))
    return order_id


def advance(cur, order_id, *statuses, staff_id=None):
    """Move an order through the statuses in turn, acting as staff_id (None = the customer or system)."""
    cur.execute("SELECT set_config('app.staff_id', %s, true)", ("" if staff_id is None else str(staff_id),))
    for status in statuses:
        cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))


def request_return(cur, order_id, lines) -> int:
    """A return of lines = [(line_no, quantity), ...]; the request time is the server's own (BR11)."""
    cur.execute(RETURN_REQUEST, return_request_args(order_id))
    return_id = cur.fetchone()["return_id"]
    for line_no, quantity in lines:
        cur.execute(RETURN_LINE, (return_id, line_no, order_id, quantity))
    return return_id


def return_request_args(order_id, key=None):
    """The parameters RETURN_REQUEST expects; `key` lets a test deliberately reuse an idempotency key."""
    key = str(key or uuid.uuid4())
    return (order_id, key, f"fingerprint:{key}")


def order_total(lines) -> Decimal:
    return sum((Decimal(str(price)) * quantity for _, quantity, price in lines), Decimal("0.00"))


def completed_order(cur, customer_id, lines, *, method="click_collect", store_id=1, address_no=None,
                    staff_id=14) -> int:
    """A charged order taken all the way to collected (click & collect) or delivered (delivery)."""
    order_id = place_order(cur, customer_id, lines, method=method, store_id=store_id, address_no=address_no)
    advance(cur, order_id, "paid")
    total = order_total(lines)
    if total > 0:
        cur.execute(CHARGE, (order_id, total))
    if method == "delivery":
        advance(cur, order_id, "picking", "shipped", "delivered", staff_id=staff_id)
    else:
        advance(cur, order_id, "picking", "ready", "collected", staff_id=staff_id)
    return order_id


@contextmanager
def backdate_history(cur, order_id: int, when: datetime):
    """Move one order's recorded status times to `when`. Maintenance only: needs table ownership.

    The append-only guard is suspended for the single UPDATE and restored immediately. Both the ALTER and
    the UPDATE are rolled back with the test's transaction, so nothing is left disabled.
    """
    cur.execute("ALTER TABLE order_status_history DISABLE TRIGGER order_status_history_append_only")
    try:
        cur.execute(
            "UPDATE order_status_history SET changed_at = %s WHERE order_id = %s",
            (when, order_id),
        )
    finally:
        cur.execute("ALTER TABLE order_status_history ENABLE TRIGGER order_status_history_append_only")


def days_ago(days: int) -> datetime:
    return datetime.now().astimezone() - timedelta(days=days)

"""Committed orders and returns for the return tests (spec §2). Each helper is one committed transaction on
its own connection, so the API (on other connections) sees the result.
"""
from tests.checkout_support import committed
from tests.orders_support import move, paid_order
from tests.support import connect

COLLECTED_BY = {1: 14, 2: 16}           # a staff member of each store the tests collect orders at


def completed_order(email: str, items: list[tuple[str, int]], *, store_id: int = 1) -> int:
    """A Click & Collect order for items = [(sku, quantity), ...], paid and collected just now at store_id, so
    it can be returned (BR11). Lines are numbered in product_id order, at the products' current prices."""
    order_id = paid_order(email, items, store_id=store_id)
    move(order_id, "picking", "ready", "collected", staff_id=COLLECTED_BY[store_id])
    return order_id


def completed_days_ago(order_id: int, days: int) -> None:
    """Move the order's whole status history back by `days`, as if it had been collected that long ago. History
    is append-only (BR09), so its guard is switched off inside this one transaction and back on before commit."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("ALTER TABLE order_status_history DISABLE TRIGGER br09_history_append_only")
            cur.execute("UPDATE order_status_history SET changed_at = changed_at - %s * interval '1 day' "
                        "WHERE order_id = %s", (days, order_id))
            cur.execute("ALTER TABLE order_status_history ENABLE TRIGGER br09_history_append_only")
    finally:
        conn.close()


def returns_of(order_id: int) -> list[int]:
    """The committed returns of an order, oldest first."""
    rows = committed("SELECT return_id FROM return_request WHERE order_id = %s ORDER BY return_id", (order_id,))
    return [row["return_id"] for row in rows]


def refunds_of(return_id: int) -> list[str]:
    """The committed refund amounts paid for a return."""
    rows = committed("SELECT amount FROM payment WHERE return_id = %s ORDER BY payment_id", (return_id,))
    return [str(row["amount"]) for row in rows]

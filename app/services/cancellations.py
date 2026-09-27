"""Cancelling an order before it is completed (T11).

An order that is cancelled has not been delivered, so there is nothing for the customer to send back:
the refund is a cancellation refund, not a merchandise return (BR14's second legal source). The stock the
customer paid for goes back to the store that was going to ship it, the refund is exactly the money still
captured, and the status becomes `cancelled` — all in one transaction, once.
"""
from app.errors import ApiError
from app.services import orders
from app.services.payments import record_refund


def cancel_order(cur, actor, order_id: int, body) -> dict:
    order = orders.lock_order(cur, order_id)          # lock first: the status cannot change under us
    orders.require_own_store(actor, order)
    reason = body.reason.strip()

    cur.execute("SELECT cancellation_id, reason FROM order_cancellation WHERE order_id = %s", (order_id,))
    existing = cur.fetchone()
    if order["status"] == "cancelled":
        # A retry of the same cancellation returns the same result and repeats nothing.
        if existing is not None and existing["reason"] == reason:
            return orders.get_order(cur, actor, order_id)
        raise ApiError(409, "cancellation_conflict",
                       "This order was already cancelled with different details.")

    if order["status"] != body.expected_status:
        raise ApiError(409, "stale_status", "This order has already moved on.",
                       {"status": order["status"]})
    cur.execute(
        "SELECT 1 FROM order_status_transition WHERE fulfilment_method = %s AND from_status = %s "
        "AND to_status = 'cancelled'",
        (order["fulfilment_method"], order["status"]),
    )
    if cur.fetchone() is None:
        raise ApiError(409, "br09_order_status_transition",
                       f"An order that is already {order['status']} cannot be cancelled.")

    # Allocation evidence: checkout takes the stock and commits as `paid`, so anything past `placed` has
    # stock to give back. A `placed` row (only reachable from a test fixture today) took none.
    allocated = order["status"] != "placed"
    cur.execute(
        "INSERT INTO order_cancellation (order_id, reason, cancelled_by_staff_id) VALUES (%s, %s, %s) "
        "RETURNING cancellation_id",
        (order_id, reason, actor.id),
    )
    cancellation_id = cur.fetchone()["cancellation_id"]

    if allocated:
        _restock(cur, order["fulfilling_store_id"], order_id)

    cur.execute("SELECT order_captured_balance(%s, NULL) AS balance", (order_id,))
    balance = cur.fetchone()["balance"]
    record_refund(cur, order_id, balance, cancellation_id=cancellation_id)   # None when nothing was charged

    orders.set_status(cur, order_id, "cancelled", staff_id=actor.id)
    orders.flush_deferred(cur)
    return orders.get_order(cur, actor, order_id)


def _restock(cur, store_id: int, order_id: int) -> None:
    """Put each purchased quantity back, in ascending product order, the same order checkout locks in."""
    cur.execute(
        "SELECT line_no, product_id, quantity FROM order_line WHERE order_id = %s ORDER BY product_id",
        (order_id,),
    )
    lines = cur.fetchall()
    if not lines:
        return
    # Lock the products first, ascending, so this cannot deadlock against a checkout for the same items.
    cur.execute("SELECT product_id FROM product WHERE product_id = ANY(%s) ORDER BY product_id FOR UPDATE",
                ([line["product_id"] for line in lines],))
    for line in lines:
        cur.execute(
            "INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, 0) "
            "ON CONFLICT (store_id, product_id) DO NOTHING",
            (store_id, line["product_id"]),
        )
        cur.execute(
            "UPDATE inventory SET quantity = quantity + %s WHERE store_id = %s AND product_id = %s",
            (line["quantity"], store_id, line["product_id"]),
        )

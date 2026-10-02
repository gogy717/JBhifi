"""Orders: checkout (transaction T1, POST /orders) and reading orders.

Locks (report §4). T1 takes no explicit row locks; its statements and the rule triggers take them:
  - FOR KEY SHARE on the customer, the store, the delivery address and each product: the foreign-key checks
    of the order and line INSERTs, so none of those rows can be deleted (or its key changed) meanwhile;
  - FOR SHARE on a Click & Collect store: the BR06 trigger, so the store can't stop being retail meanwhile;
  - FOR NO KEY UPDATE on the inventory rows, in ascending product_id order: two baskets lock the products
    they share in the same order, so they can't deadlock;
  - FOR UPDATE on the order row: the BR08 and charge triggers, so no line or charge can race placed → paid.

Reading: get_order first locks the order row FOR SHARE. Other readers go ahead, but a status change waits
until the read's transaction ends, so the header, lines, payments and timeline describe the same moment.

Rule for later services that change an order (status moves, cancellation, returns): lock the order
FOR UPDATE first and call get_order last. Taking FOR SHARE first and upgrading it later can deadlock: two
transactions would each hold the shared lock and wait for the other to let it go.
"""
from psycopg2 import sql

from app.auth import require_actor, require_customer_self, require_order_reader
from app.errors import NotFound

# The columns of OrderSummary. The view works out the store's name, the total, the line count and when the
# status last changed, so every list and detail shows the same numbers.
SUMMARY_SELECT = sql.SQL(
    """
    SELECT order_id, customer_id, placed_at, status, fulfilment_method, fulfilling_store_id,
           fulfilling_store_name, total, line_count, last_updated_at
    FROM v_order_summary
    """
)


def get_order(cur, actor, order_id: int) -> dict:
    """One order in full (OrderDetail): for its customer, the staff of the store fulfilling it, or support."""
    actor = require_actor(actor)                    # a guest is turned away before any row is locked
    cur.execute(
        """
        SELECT order_id, customer_id, status, fulfilment_method, fulfilling_store_id, delivery_address_no
        FROM customer_order
        WHERE order_id = %s
        FOR SHARE
        """,
        (order_id,),
    )
    order = cur.fetchone()
    require_order_reader(actor, order)              # 403 before 404: the order may not even exist
    if order is None:                               # only support gets here for a missing order
        raise NotFound("Order", order_id)

    cur.execute(SUMMARY_SELECT + sql.SQL("WHERE order_id = %s"), (order_id,))
    detail = cur.fetchone()
    detail["lines"] = _lines(cur, order_id)
    detail["delivery_address"] = None
    if order["delivery_address_no"] is not None:
        # The address as placed, even if retired since: addresses are never edited (BR16).
        cur.execute(
            """
            SELECT address_no, line1, suburb, state, postcode
            FROM customer_address
            WHERE customer_id = %s AND address_no = %s
            """,
            (order["customer_id"], order["delivery_address_no"]),
        )
        detail["delivery_address"] = cur.fetchone()
    cur.execute("SELECT charged, refunded, balance FROM v_order_payment WHERE order_id = %s", (order_id,))
    detail["payment"] = cur.fetchone()
    # By seq, not changed_at: a checkout's placed and paid rows share one transaction's now().
    cur.execute(
        """
        SELECT seq, from_status, to_status, changed_at, changed_by_staff_id, changed_by_name
        FROM v_order_timeline
        WHERE order_id = %s
        ORDER BY seq
        """,
        (order_id,),
    )
    detail["history"] = cur.fetchall()
    # BR09's transition table for this order's method and status. `to_status = 'cancelled'` is false for
    # every other move, and false sorts first: the way forward, then cancelling.
    cur.execute(
        """
        SELECT to_status
        FROM order_status_transition
        WHERE fulfilment_method = %s AND from_status = %s
        ORDER BY to_status = 'cancelled', to_status
        """,
        (order["fulfilment_method"], order["status"]),
    )
    detail["allowed_next_statuses"] = [row["to_status"] for row in cur.fetchall()]
    return detail


def _lines(cur, order_id: int) -> list[dict]:
    """The order's lines (OrderLine) in line order, at the prices they were sold at."""
    cur.execute(
        """
        SELECT l.line_no, l.product_id, p.sku, p.name, l.quantity, l.unit_price,
               l.quantity * l.unit_price AS line_total
        FROM order_line l
        JOIN product p ON p.product_id = l.product_id
        WHERE l.order_id = %s
        ORDER BY l.line_no
        """,
        (order_id,),
    )
    return cur.fetchall()


def list_customer_orders(cur, actor, customer_id: int) -> list[dict]:
    """A customer's orders, newest first (OrderSummary): for that customer, or support staff."""
    require_customer_self(actor, customer_id)
    cur.execute("SELECT 1 FROM customer WHERE customer_id = %s", (customer_id,))
    if cur.fetchone() is None:
        raise NotFound("Customer", customer_id)     # only support can ask about someone who doesn't exist
    cur.execute(SUMMARY_SELECT + sql.SQL("WHERE customer_id = %s ORDER BY placed_at DESC, order_id DESC"),
                (customer_id,))
    return cur.fetchall()

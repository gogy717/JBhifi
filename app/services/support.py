"""R10: what support staff need to answer a customer — everything that happened to them, in one list."""
from app.auth import require_customer_self
from app.errors import NotFound

# Three kinds of event, one UNION ALL: each branch selects the same columns (types from the first branch), and
# the whole list is sorted once. `step` orders events that share one instant: checkout writes placed, its charge
# and paid in one transaction, so all three carry the same now(). A status row's step is 2 × seq; a payment's is
# one less than the newest status row of its order at exactly its moment, so it lands just before the change it
# enables — placed → charge → paid — and a payment alone at its moment gets −1. A return request gets 0. Newest
# first; the payment or return id breaks any tie left.
HISTORY = """
    SELECT at, kind, order_id, return_id, from_status, to_status, amount, staff_name
    FROM (
        SELECT t.changed_at        AS at,
               'status'            AS kind,
               t.order_id,
               NULL::int           AS return_id,
               t.from_status,
               t.to_status,
               NULL::numeric(10,2) AS amount,
               t.changed_by_name   AS staff_name,
               2 * t.seq           AS step,
               0                   AS tiebreak
        FROM v_order_timeline t
        JOIN customer_order o ON o.order_id = t.order_id
        WHERE o.customer_id = %(customer_id)s

        UNION ALL

        SELECT p.created_at, p.kind, p.order_id, p.return_id, NULL, NULL, p.amount, NULL,
               2 * COALESCE((SELECT max(h.seq)
                             FROM order_status_history h
                             WHERE h.order_id = p.order_id AND h.changed_at = p.created_at), 0) - 1,
               p.payment_id
        FROM payment p
        JOIN customer_order o ON o.order_id = p.order_id
        WHERE o.customer_id = %(customer_id)s

        UNION ALL

        SELECT r.requested_at, 'return_requested', r.order_id, r.return_id, NULL, NULL, NULL, NULL, 0, r.return_id
        FROM return_request r
        JOIN customer_order o ON o.order_id = r.order_id
        WHERE o.customer_id = %(customer_id)s
    ) AS event
    ORDER BY at DESC, order_id DESC, step DESC, tiebreak DESC
"""


def customer_history(cur, actor, customer_id: int) -> list[dict]:
    """Every order status change (who made it, from v_order_timeline), payment and return request of one
    customer, newest first: for that customer, or support staff (who alone are told 404)."""
    require_customer_self(actor, customer_id)
    cur.execute("SELECT 1 FROM customer WHERE customer_id = %s", (customer_id,))
    if cur.fetchone() is None:
        raise NotFound("Customer", customer_id)
    cur.execute(HISTORY, {"customer_id": customer_id})
    return cur.fetchall()

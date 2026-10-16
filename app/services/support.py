"""R10: what support staff need to answer a customer — everything that happened to them, in one list."""
from app.auth import require_customer_self
from app.errors import NotFound

# Five kinds of event, one UNION ALL: each branch selects the same columns (types from the first branch), and the
# whole list is sorted once, newest first. Events of one order can share an instant, because one transaction
# writes them all with one now(): checkout writes placed, its charge and paid; a cancellation (T4) its refund and
# cancelled; a return's refund (T2) the refund payment and the return's refunded event. `step` puts them in the
# order they happened. A status row's step is 2 × seq, and a return event's is 0. A payment lands just before the
# event it enables, so its step is one less than that event's:
#   - a charge: just before the order's `paid` row;
#   - a refund without a return (a cancellation's): just before the `cancelled` row;
#   - a return's refund: −1, just before the return's refunded event (0).
# The enabled row counts only at exactly the payment's moment (the same transaction); at any other moment there's
# nothing to order the payment against, and its step doesn't matter. The payment or return id breaks any tie left.
HISTORY = """
    SELECT at, kind, order_id, return_id, from_status, to_status, amount, staff_name, note
    FROM (
        SELECT t.changed_at        AS at,
               'status'            AS kind,
               t.order_id,
               NULL::int           AS return_id,
               t.from_status,
               t.to_status,
               NULL::numeric(10,2) AS amount,
               t.changed_by_name   AS staff_name,
               NULL::text          AS note,
               2 * t.seq           AS step,
               0                   AS tiebreak
        FROM v_order_timeline t
        JOIN customer_order o ON o.order_id = t.order_id
        WHERE o.customer_id = %(customer_id)s

        UNION ALL

        SELECT p.created_at, p.kind, p.order_id, p.return_id, NULL, NULL, p.amount, NULL, NULL,
               CASE WHEN p.return_id IS NOT NULL THEN -1
                    ELSE 2 * COALESCE((SELECT h.seq
                                       FROM order_status_history h
                                       WHERE h.order_id = p.order_id
                                         AND h.changed_at = p.created_at
                                         AND h.to_status = CASE p.kind WHEN 'charge' THEN 'paid'
                                                                       ELSE 'cancelled' END), 0) - 1
               END,
               p.payment_id
        FROM payment p
        JOIN customer_order o ON o.order_id = p.order_id
        WHERE o.customer_id = %(customer_id)s

        UNION ALL

        SELECT r.requested_at, 'return_requested', r.order_id, r.return_id, NULL, NULL, NULL, NULL, NULL,
               0, r.return_id
        FROM return_request r
        JOIN customer_order o ON o.order_id = r.order_id
        WHERE o.customer_id = %(customer_id)s

        UNION ALL

        -- Received at a store (SP3): who took it in. A LEFT JOIN, as v_order_timeline does for its staff.
        SELECT r.received_at, 'return_received', r.order_id, r.return_id, NULL, NULL, NULL, st.full_name, NULL,
               0, r.return_id
        FROM return_request r
        JOIN customer_order o ON o.order_id = r.order_id
        LEFT JOIN staff st    ON st.staff_id = r.processed_by_staff_id
        WHERE o.customer_id = %(customer_id)s AND r.received_at IS NOT NULL

        UNION ALL

        -- Refunded or rejected (SP3): who decided, and a rejection's reason.
        SELECT r.resolved_at, 'return_' || r.status, r.order_id, r.return_id, NULL, NULL, NULL, st.full_name,
               r.rejection_reason, 0, r.return_id
        FROM return_request r
        JOIN customer_order o ON o.order_id = r.order_id
        LEFT JOIN staff st    ON st.staff_id = r.resolved_by_staff_id
        WHERE o.customer_id = %(customer_id)s AND r.resolved_at IS NOT NULL
    ) AS event
    ORDER BY at DESC, order_id DESC, step DESC, tiebreak DESC
"""


def customer_history(cur, actor, customer_id: int) -> list[dict]:
    """Every order status change (who made it, from v_order_timeline), payment, and return request, receipt and
    resolution of one customer, newest first: for that customer, or support staff (who alone are told 404)."""
    require_customer_self(actor, customer_id)
    cur.execute("SELECT 1 FROM customer WHERE customer_id = %s", (customer_id,))
    if cur.fetchone() is None:
        raise NotFound("Customer", customer_id)
    cur.execute(HISTORY, {"customer_id": customer_id})
    return cur.fetchall()

"""Returns: a customer asks to return part of a completed order (R6); store staff receive it, then refund it
(transaction T2) or reject it (R8). Spec: docs/superpowers/specs/2026-10-16-returns-design.md.

Asking (request_return) has T1's shape: look the Idempotency-Key up, then claim it, then insert the lines.
It takes no explicit lock and doesn't change the order: its foreign-key checks hold FOR KEY SHARE on the order,
and BR12's trigger locks each order line FOR UPDATE, in line_no order, so two requests lock the same lines in
the same order.

Reading (get_return) takes no row locks: one statement reads the return, its value and its refund (one
snapshot), and a return's lines don't change after the request.
"""
from uuid import UUID

from psycopg2 import sql

from app.auth import require_actor, require_customer, require_customer_self
from app.errors import ApiError, NotFound
from app.schemas.returns import ReturnCreate

# The columns of ReturnSummary. quantity and value come from v_return_value, so every list, detail and
# refund agrees on what a return is worth.
SUMMARY_COLUMNS = sql.SQL(
    """
    SELECT r.return_id, r.order_id, r.status, r.reason, r.requested_at, v.quantity, v.value,
           (SELECT p.amount FROM payment p WHERE p.return_id = r.return_id) AS refunded,
           r.received_store_id, s.name AS received_store_name, r.received_at, r.resolved_at, r.rejection_reason
    """
)
SUMMARY_FROM = sql.SQL(
    """
    FROM return_request r
    JOIN v_return_value v ON v.return_id = r.return_id
    JOIN customer_order o ON o.order_id = r.order_id
    LEFT JOIN store s ON s.store_id = r.received_store_id
    """
)
DETAIL_SELECT = SUMMARY_COLUMNS + sql.SQL(
    """
         , o.customer_id, o.fulfilling_store_id,
           receiver.full_name AS processed_by_name, resolver.full_name AS resolved_by_name
    """
) + SUMMARY_FROM + sql.SQL(
    """
    LEFT JOIN staff receiver ON receiver.staff_id = r.processed_by_staff_id
    LEFT JOIN staff resolver ON resolver.staff_id = r.resolved_by_staff_id
    """
)
NEWEST_FIRST = sql.SQL(" ORDER BY r.requested_at DESC, r.return_id DESC")


# ---------------------------------------------------------------- reads

def get_return(cur, actor, return_id: int) -> dict:
    """One return in full (ReturnDetail): for its customer, store staff who may handle it, or support."""
    actor = require_actor(actor)
    cur.execute(DETAIL_SELECT + sql.SQL("WHERE r.return_id = %s"), (return_id,))
    detail = cur.fetchone()
    _require_return_reader(cur, actor, detail)      # 403 before 404: the return may not even exist
    if detail is None:                              # only support gets here for a missing return
        raise NotFound("Return", return_id)
    detail["lines"] = _lines(cur, return_id)
    return detail


def _require_return_reader(cur, actor, detail: dict | None) -> None:
    """Support reads every return; a customer their own; store staff a requested return if their store is
    retail (any retail store may receive it, BR22), and otherwise only returns received at their store."""
    if actor.is_support:
        return
    if actor.kind == "customer":
        if detail is None or detail["customer_id"] != actor.id:
            raise ApiError(403, "not_your_return", "That return isn't one of yours.")
        return
    if detail is not None:
        if detail["received_store_id"] == actor.store_id:
            return
        if detail["status"] == "requested":
            cur.execute("SELECT store_type FROM store WHERE store_id = %s", (actor.store_id,))
            if cur.fetchone()["store_type"] == "retail":
                return
    raise ApiError(403, "other_store", "That return is handled by another store.")


def _lines(cur, return_id: int) -> list[dict]:
    """The return's lines (ReturnLine) in line order, at the prices they were bought at."""
    cur.execute(
        """
        SELECT rl.line_no, ol.product_id, p.sku, p.name, rl.quantity, ol.unit_price,
               rl.quantity * ol.unit_price AS line_total
        FROM return_line rl
        JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no
        JOIN product p     ON p.product_id = ol.product_id
        WHERE rl.return_id = %s
        ORDER BY rl.line_no
        """,
        (return_id,),
    )
    return cur.fetchall()


def list_customer_returns(cur, actor, customer_id: int) -> list[dict]:
    """A customer's returns, newest first (ReturnSummary): for that customer, or support staff."""
    require_customer_self(actor, customer_id)
    cur.execute("SELECT 1 FROM customer WHERE customer_id = %s", (customer_id,))
    if cur.fetchone() is None:
        raise NotFound("Customer", customer_id)     # only support can ask about someone who doesn't exist
    cur.execute(SUMMARY_COLUMNS + SUMMARY_FROM + sql.SQL("WHERE o.customer_id = %s") + NEWEST_FIRST, (customer_id,))
    return cur.fetchall()


# ---------------------------------------------------------------- asking for a return (R6)

def request_return(cur, actor, order_id: int, key: UUID, body: ReturnCreate) -> tuple[dict, bool]:
    """Ask to return lines of a completed order, in the request's one transaction (spec §2).

    Returns (return detail, replayed). replayed is True when this order already has a return asked for with
    this key: that return is returned as it is now, and nothing is written. Any error rolls back everything this
    call wrote, its claim on the key included, so the same key can be sent again.
    """
    actor = require_customer(actor)
    cur.execute("SELECT customer_id FROM customer_order WHERE order_id = %s", (order_id,))
    order = cur.fetchone()
    if order is None or order["customer_id"] != actor.id:
        raise ApiError(403, "not_your_order", "That order isn't one of yours.")   # missing ones too

    # 1. Lookup, before anything is claimed: a retry whose answer was lost gets its return back even after the
    #    30-day window closed or BR12's total filled up. The body is not compared: a changed request has a new key.
    asked = _return_with_key(cur, order_id, key)
    if asked is not None:
        return get_return(cur, actor, asked), True

    # 2. Claim the key; BR11 checks the order is completed and inside the window. No row: a concurrent request
    #    with this key committed first (ON CONFLICT waited for it), so that is the return to answer with.
    cur.execute(
        """
        INSERT INTO return_request (order_id, idempotency_key, reason)
        VALUES (%s, %s, %s)
        ON CONFLICT ON CONSTRAINT br10_return_idempotency_unique DO NOTHING
        RETURNING return_id
        """,
        (order_id, str(key), body.reason),
    )
    claimed = cur.fetchone()
    if claimed is None:
        return get_return(cur, actor, _return_with_key(cur, order_id, key)), True
    return_id = claimed["return_id"]

    # 3. Lines in line_no order. The database answers a line the order doesn't have (return_line_order_line_fk),
    #    the same line twice (return_line_pk), a quantity below 1 and more than was bought (BR12).
    for line in sorted(body.lines, key=lambda line: line.line_no):
        cur.execute(
            "INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, %s, %s, %s)",
            (return_id, line.line_no, order_id, line.quantity),
        )
    return get_return(cur, actor, return_id), False


def _return_with_key(cur, order_id: int, key: UUID) -> int | None:
    cur.execute("SELECT return_id FROM return_request WHERE order_id = %s AND idempotency_key = %s",
                (order_id, str(key)))
    row = cur.fetchone()
    return None if row is None else row["return_id"]

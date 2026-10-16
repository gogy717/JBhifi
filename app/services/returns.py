"""Returns: a customer asks to return part of a completed order (R6); store staff receive it, then refund it
(transaction T2) or reject it (R8). Spec: docs/superpowers/specs/2026-10-16-returns-design.md.

Asking (request_return) has T1's shape: look the Idempotency-Key up, then claim it, then insert the lines.
It takes no explicit lock and doesn't change the order: its foreign-key checks hold FOR KEY SHARE on the order,
and BR12's trigger locks each order line FOR UPDATE, in line_no order, so two requests lock the same lines in
the same order.

Staff actions (receive, refund, reject) lock, in this order: the order FOR UPDATE, then the return FOR UPDATE,
then (refund) inventory rows in ascending product_id, then the refund insert, whose BR14 triggers lock the order
again (already held). Orders first, as every service that writes for an order does (plan §5). It can't
deadlock with cancelling (SP2: the order, then inventory in ascending product_id): an order that can still be
cancelled is never a completed one, so the two never wait for the same order, and both take inventory rows in
the same order. Checkout (T1) takes inventory, then its own new order. A return request holds FOR KEY SHARE
on the order: an action waits for it, or it waits for the action, but neither then waits for the other.

Each action needs exactly one status (receive: requested; refund and reject: received), and each status has
at most one way in, so the action itself is the stale-page check: whoever comes second gets 409
return_status_transition with the status it found. The database's transition trigger of the same name is the
backstop, and UNIQUE (return_id) on payment (BR14) the backstop for the refund.

Reading (get_return) takes no row locks: one statement reads the return, its value and its refund (one
snapshot), and a return's lines don't change after the request.
"""
from uuid import UUID

from psycopg2 import sql

from app.auth import (require_actor, require_customer, require_customer_self, require_staff,
                      require_store_or_support_reader)
from app.errors import ApiError, NotFound
from app.schemas.returns import ReturnCreate, ReturnReject

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


def list_store_returns(cur, actor, store_id: int) -> list[dict]:
    """A store's returns desk, newest first (ReturnSummary): the requested returns of orders this store
    fulfilled (where their customers are most likely to bring them), and every return received here. For that
    store's staff, or support."""
    require_store_or_support_reader(actor, store_id)
    cur.execute("SELECT 1 FROM store WHERE store_id = %s", (store_id,))
    if cur.fetchone() is None:
        raise NotFound("Store", store_id)           # only support can ask about another store
    cur.execute(
        SUMMARY_COLUMNS + SUMMARY_FROM
        + sql.SQL("WHERE (r.status = 'requested' AND o.fulfilling_store_id = %s) OR r.received_store_id = %s")
        + NEWEST_FIRST,
        (store_id, store_id),
    )
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


# ---------------------------------------------------------------- staff: receive, then refund (T2) or reject (R8)

def receive_return(cur, actor, return_id: int) -> dict:
    """Take the item in at the actor's own store, which must be retail (BR22). Nothing is restocked yet: the
    store first sees what came back, then refunds or rejects it."""
    actor = _require_return_handler(actor)
    current = _lock_return(cur, return_id)
    _require_status(actor, current, "requested", "received")
    cur.execute(
        """
        UPDATE return_request
        SET status = 'received', received_store_id = %s, processed_by_staff_id = %s, received_at = now()
        WHERE return_id = %s
        """,
        (actor.store_id, actor.id, return_id),
    )
    return get_return(cur, actor, return_id)


def refund_return(cur, actor, return_id: int) -> dict:
    """T2: put what came back into the receiving store's stock, refund what it is worth, and mark the return
    refunded, in the request's one transaction. Any failure rolls back all three."""
    actor = _require_return_handler(actor)
    current = _lock_return(cur, return_id)
    _require_status(actor, current, "received", "refunded")

    # Restock, in ascending product_id (a product is on an order once, BR07): two transactions that restock or
    # sell the same products at this store lock their inventory rows in the same order, so they can't deadlock.
    cur.execute(
        """
        SELECT ol.product_id, rl.quantity
        FROM return_line rl
        JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no
        WHERE rl.return_id = %s
        ORDER BY ol.product_id
        """,
        (return_id,),
    )
    for line in cur.fetchall():
        # The receiving store may never have stocked this product: give it a row first (as T3 does), then add.
        cur.execute(
            """
            INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, 0)
            ON CONFLICT ON CONSTRAINT inventory_pk DO NOTHING
            """,
            (actor.store_id, line["product_id"]),
        )
        cur.execute("UPDATE inventory SET quantity = quantity + %s WHERE store_id = %s AND product_id = %s",
                    (line["quantity"], actor.store_id, line["product_id"]))

    _refund(cur, return_id)
    cur.execute(
        """
        UPDATE return_request
        SET status = 'refunded', resolved_by_staff_id = %s, resolved_at = now()
        WHERE return_id = %s
        """,
        (actor.id, return_id),
    )
    return get_return(cur, actor, return_id)


def _refund(cur, return_id: int) -> None:
    """The refund: one payment of the return's value (v_return_value), which BR14 checks is exactly that and
    within what the order was charged. A return worth nothing gets no row (payment amounts are > 0), as a zero
    total gets no charge. Its own function, so a test can make it fail."""
    cur.execute(
        """
        INSERT INTO payment (order_id, kind, amount, return_id)
        SELECT order_id, 'refund', value, return_id
        FROM v_return_value
        WHERE return_id = %s AND value > 0
        """,
        (return_id,),
    )


def reject_return(cur, actor, return_id: int, body: ReturnReject) -> dict:
    """Refuse a received return, saying why. Nothing is restocked and nothing refunded: the item goes back to
    the customer, and its units can be asked for again (BR12 doesn't count rejected returns)."""
    actor = _require_return_handler(actor)
    current = _lock_return(cur, return_id)
    _require_status(actor, current, "received", "rejected")
    cur.execute(
        """
        UPDATE return_request
        SET status = 'rejected', rejection_reason = %s, resolved_by_staff_id = %s, resolved_at = now()
        WHERE return_id = %s
        """,
        (body.reason, actor.id, return_id),
    )
    return get_return(cur, actor, return_id)


def _require_return_handler(actor):
    """Returns are handled by a store's own staff; support staff read them but don't act on them."""
    actor = require_staff(actor)
    if actor.is_support:
        raise ApiError(403, "store_staff_only", "Returns are handled by a store's own staff.")
    return actor


def _lock_return(cur, return_id: int) -> dict:
    """Lock the return's order, then the return (the module docstring's order), and return the return."""
    cur.execute("SELECT order_id FROM return_request WHERE return_id = %s", (return_id,))
    found = cur.fetchone()
    if found is None:                               # as for reads: store staff get 403 for a missing return
        raise ApiError(403, "other_store", "That return is handled by another store.")
    cur.execute("SELECT 1 FROM customer_order WHERE order_id = %s FOR UPDATE", (found["order_id"],))
    cur.execute("SELECT return_id, status, received_store_id FROM return_request WHERE return_id = %s FOR UPDATE",
                (return_id,))
    return cur.fetchone()


def _require_status(actor, current: dict, needed: str, becoming: str) -> None:
    """Once a return has been received, only its receiving store acts on it; and the action needs `needed`.
    Checked under the locks, so a second click, or a page that is out of date, sees the status as it now is."""
    if current["status"] != "requested" and current["received_store_id"] != actor.store_id:
        raise ApiError(403, "other_store", "Only the store that received this return can act on it.")
    if current["status"] != needed:
        raise ApiError(409, "return_status_transition",
                       f"This return is already {current['status']}, so it can't be {becoming} now.",
                       {"status": current["status"]})

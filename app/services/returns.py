"""Returns: the customer's request (T13) and the staff side of it (T14).

Requesting is one transaction that creates the request and every line, so a later line that BR12 refuses
takes the whole request with it. Processing is one transaction that restocks what came back and refunds
the purchase-time value of it — or neither.

Lock order everywhere: the order, then the return, then the order/return lines in order, then the
products in ascending id order, then inventory.
"""
from decimal import Decimal

from app.auth import Actor
from app.errors import ApiError, NotFound
from app.services import orders
from app.services.idempotency import return_fingerprint
from app.services.orders import flush_deferred
from app.services.payments import record_refund

ZERO = Decimal("0.00")
RECEIVED_OR_LATER = ("received", "refunded", "rejected")


# ---------------------------------------------------------------- customer request (T13)

def request_return(cur, actor: Actor, order_id: int, key, body) -> tuple[dict, bool]:
    """Ask to return part of a completed order. Returns (detail, was this a replay?)."""
    fingerprint = return_fingerprint(body)
    order = orders.lock_order(cur, order_id)              # locking the order makes BR11/BR12 decisive
    if actor.kind != "customer" or order["customer_id"] != actor.id:
        raise NotFound("Order", order_id)                 # another customer's order is simply not there

    # A retry is resolved before the mutable checks, so a request that succeeded can still be replayed
    # after the 30-day window has closed.
    cur.execute(
        "SELECT return_id, request_fingerprint FROM return_request WHERE order_id = %s AND idempotency_key = %s",
        (order_id, str(key)),
    )
    existing = cur.fetchone()
    if existing is not None:
        if existing["request_fingerprint"] != fingerprint:
            raise ApiError(409, "idempotency_conflict",
                           "That Idempotency-Key was already used for a different request.")
        return get_return(cur, actor, existing["return_id"]), True

    _validate_lines(body)
    _act_as(cur, None)                                   # a customer's own request: no staff actor
    # BR11 is the rule that guards the request itself: the order must be completed and inside the window.
    # Asking for more than is left is BR12's business, and BR12 is what reports it (below).
    window = orders.return_window(cur, order)
    if not window["open"]:
        # The same constraint BR11's trigger raises, so one rule has one name everywhere.
        reason = ("Only a delivered or collected order can be returned." if window["completed_at"] is None
                  else f"The 30-day return window closed on {window['deadline'].date().isoformat()}.")
        raise ApiError(409, "br11_return_window", reason, {"deadline": window["deadline"]})

    # Lock the purchased lines we are about to return, in line order (BR12 does the same).
    cur.execute("SELECT line_no, quantity FROM order_line WHERE order_id = %s ORDER BY line_no", (order_id,))
    purchased = {row["line_no"]: row["quantity"] for row in cur.fetchall()}
    unknown = [line.line_no for line in body.lines if line.line_no not in purchased]
    if unknown:
        raise NotFound("Order line", unknown[0])

    cur.execute(
        "INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason) "
        "VALUES (%s, %s, %s, %s) RETURNING return_id",
        (order_id, str(key), fingerprint, body.reason.strip()),
    )
    return_id = cur.fetchone()["return_id"]
    for line in sorted(body.lines, key=lambda line: line.line_no):
        cur.execute(
            "INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, %s, %s, %s)",
            (return_id, line.line_no, order_id, line.quantity),
        )
    flush_deferred(cur)
    return get_return(cur, actor, return_id), False


def _validate_lines(body) -> None:
    seen = set()
    for line in body.lines:
        if line.line_no in seen:
            raise ApiError(422, "duplicate_lines",
                           f"Order line {line.line_no} appears more than once. Send one line per item.",
                           {"line_no": line.line_no})
        seen.add(line.line_no)


# ---------------------------------------------------------------- reads

RETURN_SELECT = """
    SELECT rr.return_id, rr.order_id, rr.status, rr.requested_at, rr.reason,
           rr.received_store_id, rr.processed_by_staff_id,
           o.customer_id, o.fulfilment_method, o.fulfilling_store_id, o.status AS order_status,
           s.name AS receiving_store_name,
           (SELECT p.amount FROM payment p WHERE p.return_id = rr.return_id) AS refund_amount
    FROM return_request rr
    JOIN customer_order o ON o.order_id = rr.order_id
    LEFT JOIN store s     ON s.store_id = rr.received_store_id
"""


def list_customer_returns(cur, actor: Actor, customer_id: int) -> list[dict]:
    cur.execute(
        RETURN_SELECT + " WHERE o.customer_id = %s ORDER BY rr.requested_at DESC, rr.return_id DESC",
        (customer_id,),
    )
    return [_summary(row) for row in cur.fetchall()]


def list_store_returns(cur, store_id: int, status: str | None = None) -> list[dict]:
    """Requests this store must act on: asked for here, or already received here."""
    conditions = ["(o.fulfilling_store_id = %s OR rr.received_store_id = %s)"]
    params: list = [store_id, store_id]
    if status is not None:
        conditions.append("rr.status = %s")
        params.append(status)
    cur.execute(
        RETURN_SELECT + " WHERE " + " AND ".join(conditions)
        + " ORDER BY rr.requested_at DESC, rr.return_id DESC",
        params,
    )
    return [_summary(row) for row in cur.fetchall()]


def get_return(cur, actor: Actor, return_id: int) -> dict:
    row = _load_return(cur, return_id)
    _authorise(actor, row)
    return _detail(cur, actor, row)


def _load_return(cur, return_id: int) -> dict:
    cur.execute(RETURN_SELECT + " WHERE rr.return_id = %s", (return_id,))
    row = cur.fetchone()
    if row is None:
        raise NotFound("Return", return_id)
    return row


def _authorise(actor: Actor, row: dict) -> None:
    """A return the actor has nothing to do with does not exist, as far as they are told."""
    if actor.kind == "customer":
        if row["customer_id"] != actor.id:
            raise NotFound("Return", row["return_id"])
        return
    if actor.is_support:
        return
    if actor.store_id not in (row["fulfilling_store_id"], row["received_store_id"]):
        raise NotFound("Return", row["return_id"])


def _summary(row: dict) -> dict:
    return {
        "return_id": row["return_id"],
        "order_id": row["order_id"],
        "status": row["status"],
        "requested_at": row["requested_at"],
        "reason": row["reason"],
        "refund_amount": row["refund_amount"],
    }


def _detail(cur, actor: Actor, row: dict) -> dict:
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
        (row["return_id"],),
    )
    lines = cur.fetchall()
    cur.execute(
        """
        SELECT h.seq, h.from_status, h.to_status, h.changed_at, h.changed_by_staff_id,
               st.full_name AS changed_by_name
        FROM return_status_history h
        LEFT JOIN staff st ON st.staff_id = h.changed_by_staff_id
        WHERE h.return_id = %s
        ORDER BY h.seq
        """,
        (row["return_id"],),
    )
    history = cur.fetchall()
    detail = _summary(row)
    detail.update({
        "lines": lines,
        "receiving_store": ({"store_id": row["received_store_id"], "name": row["receiving_store_name"]}
                            if row["received_store_id"] is not None else None),
        "history": history,
        "allowed_actions": allowed_actions(cur, actor, row),
        "refund_preview": expected_refund(cur, row["return_id"]),
    })
    return detail


def allowed_actions(cur, actor: Actor, row: dict) -> list[str]:
    if actor.kind != "staff" or actor.is_support:
        return []                                        # support reads returns; stores act on them
    status = row["status"]
    if status == "requested":
        # Any retail store can take the item in; only the fulfilling store can refuse it unseen.
        actions = ["receive"]
        if actor.store_id == row["fulfilling_store_id"]:
            actions.append("reject")
        return actions
    if status == "received" and actor.store_id == row["received_store_id"]:
        return ["reject", "process"]                     # only the receiving store finishes it
    return []


def expected_refund(cur, return_id: int) -> Decimal:
    """What this return is worth, from the prices it was bought at (the same SQL the trigger uses)."""
    cur.execute("SELECT return_expected_refund(%s) AS amount", (return_id,))
    return cur.fetchone()["amount"]


# ---------------------------------------------------------------- staff actions (T14)

def _lock_return_for_update(cur, return_id: int) -> dict:
    """Lock the parent order, then the return — the order others are also waiting on."""
    cur.execute("SELECT order_id FROM return_request WHERE return_id = %s", (return_id,))
    found = cur.fetchone()
    if found is None:
        raise NotFound("Return", return_id)
    orders.lock_order(cur, found["order_id"])
    cur.execute(
        "SELECT rr.return_id, rr.order_id, rr.status, rr.received_store_id, o.fulfilling_store_id "
        "FROM return_request rr JOIN customer_order o USING (order_id) WHERE rr.return_id = %s FOR UPDATE OF rr",
        (return_id,),
    )
    return cur.fetchone()


def _store_staff(actor: Actor) -> int:
    if actor.kind != "staff":
        raise ApiError(403, "staff_only", "Only staff handle returns.")
    if actor.is_support or actor.store_id is None:
        raise ApiError(403, "store_staff_only", "Returns are handled by a store's own staff.")
    return actor.store_id


def _act_as(cur, staff_id: int | None) -> None:
    """Tell the status-history trigger who made the change (BR09's convention, reused for returns)."""
    cur.execute("SELECT set_config('app.staff_id', %s, true)",
                ("" if staff_id is None else str(staff_id),))


def _require_retail(cur, store_id: int) -> None:
    cur.execute("SELECT store_type FROM store WHERE store_id = %s", (store_id,))
    row = cur.fetchone()
    if row is None or row["store_type"] != "retail":
        raise ApiError(409, "br06_collect_at_retail_store", "Returns are received at a retail store.")


def receive_return(cur, actor: Actor, return_id: int, body) -> dict:
    """Take the item in at the actor's own store. Nothing is restocked yet."""
    row = _lock_return_for_update(cur, return_id)
    store_id = _store_staff(actor)
    if row["status"] == "received" and row["received_store_id"] == store_id:
        return get_return(cur, actor, return_id)         # the same receipt, repeated: no second effect
    if row["status"] != body.expected_status:
        raise ApiError(409, "stale_status", "This return has already moved on.", {"status": row["status"]})
    if row["status"] != "requested":
        raise ApiError(409, "return_status_transition",
                       f"A {row['status']} return cannot be received.")
    _require_retail(cur, store_id)
    _act_as(cur, actor.id)
    cur.execute(
        "UPDATE return_request SET status = 'received', received_store_id = %s, processed_by_staff_id = %s "
        "WHERE return_id = %s",
        (store_id, actor.id, return_id),
    )
    flush_deferred(cur)
    return get_return(cur, actor, return_id)


def reject_return(cur, actor: Actor, return_id: int, body) -> dict:
    """Refuse a return. Nothing is restocked, because nothing was: rejection is final."""
    row = _lock_return_for_update(cur, return_id)
    store_id = _store_staff(actor)
    if row["status"] == "rejected":
        return get_return(cur, actor, return_id)
    if row["status"] != body.expected_status:
        raise ApiError(409, "stale_status", "This return has already moved on.", {"status": row["status"]})
    if row["status"] == "requested":
        # Unseen: only the store that was going to fulfil it can refuse it.
        if row["fulfilling_store_id"] != store_id:
            raise ApiError(403, "other_store", "Only the fulfilling store can refuse an unseen return.")
    elif row["status"] == "received":
        if row["received_store_id"] != store_id:
            raise ApiError(403, "other_store", "Only the store that received it can refuse it now.")
    else:
        raise ApiError(409, "return_status_transition", f"A {row['status']} return is already final.")
    _act_as(cur, actor.id)
    cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (return_id,))
    flush_deferred(cur)
    return get_return(cur, actor, return_id)

def process_return(cur, actor: Actor, return_id: int, body) -> dict:
    """Restock what came back and refund what it was worth — one transaction, once."""
    row = _lock_return_for_update(cur, return_id)
    store_id = _store_staff(actor)
    if row["status"] == "refunded":
        return get_return(cur, actor, return_id)
    if row["status"] != body.expected_status:
        raise ApiError(409, "stale_status", "This return has already moved on.", {"status": row["status"]})
    if row["status"] != "received":
        raise ApiError(409, "return_status_transition", f"A {row['status']} return cannot be processed.")
    if row["received_store_id"] != store_id:
        raise ApiError(403, "other_store", "Only the store that received the item can refund it.")

    amount = expected_refund(cur, return_id)
    _restock(cur, store_id, return_id)
    record_refund(cur, row["order_id"], amount, return_id=return_id)   # None when the lines were free
    _act_as(cur, actor.id)
    cur.execute("UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))
    flush_deferred(cur)
    return get_return(cur, actor, return_id)


def _restock(cur, store_id: int, return_id: int) -> None:
    """Add the returned quantities at the receiving store, products locked in ascending id order."""
    cur.execute(
        "SELECT ol.product_id, rl.quantity FROM return_line rl "
        "JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no "
        "WHERE rl.return_id = %s ORDER BY ol.product_id",
        (return_id,),
    )
    lines = cur.fetchall()
    if not lines:
        return
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

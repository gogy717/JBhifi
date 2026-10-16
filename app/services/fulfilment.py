"""Fulfilment (R7, R11): a store's order queue, moving an order along its status path, and cancelling it (T4).

Moving an order: one transaction, READ COMMITTED (spec §3).
  1. Lock the order FOR UPDATE, before anything is read from it. Every service that changes an order locks it
     first and calls get_order last (plan §5): get_order's FOR SHARE on a row this transaction already holds
     FOR UPDATE takes nothing new, while taking FOR SHARE first and upgrading later could deadlock.
  2. Who: the fulfilling store's staff, or support. Store staff get the same 403 for a missing order as for
     another store's, so they can't probe which ids exist; only support is told 404.
  3. from_status, the status the caller's screen showed, must be the order's status now. Two clerks making the
     same move: the second waits on the row lock, then reads the first one's committed status (READ COMMITTED
     re-reads a row it waited for), so it gets 409 status_changed — one move, one history row. The same check
     makes a retry after a lost answer safe without an Idempotency-Key: a move happens at most once from a given
     status.
  4. app.staff_id names the mover for BR09's log trigger, then the UPDATE: BR09 decides whether the move is legal
     (409 br09_order_status_transition) and logs it. The service doesn't repeat the transition table.

T4, cancelling an order: one transaction, READ COMMITTED, in this order (spec §3):
  1. Lock the order FOR UPDATE.
  2. Who: the order's customer, or the fulfilling store's staff; support never (403 support_cannot_cancel).
     Customers and store staff get the same 403 for a missing order as for someone else's.
  3. from_status must be the order's status now (409 status_changed), as for a move.
  4. A customer cancels only before picking starts (placed or paid; 403 customer_cancel_before_picking). Store
     staff may cancel whenever BR09 allows: placed, paid, or ready ("not collected in time").
  5. BR09's transition table must allow the move to cancelled (409 br09_order_status_transition): asked here
     because the refund comes before the status change, and BR14 would otherwise refuse it under its own name.
  6. Restock, if checkout took stock (paid or ready — checkout takes the stock and pays in one transaction, so a
     placed order took none): each line's quantity back to the fulfilling store, in ascending product_id.
  7. Refund what is still held (v_order_payment.balance), if anything: a refund without a return, which BR14
     allows only while the order can still be cancelled.
  8. The move to cancelled, as the caller: BR09 checks it and logs who made it, BR21 checks nothing is held.
  9. get_order. Any failure rolls back everything: no status change, no stock change, no refund, no history.

Locks: the order FOR UPDATE, then the inventory rows (FOR NO KEY UPDATE, from the UPDATEs) in ascending
product_id; the payment triggers lock the order again (already held). Checkout (T1) can't deadlock with it: the
only order row T1 locks is its own uncommitted one, which nobody else can wait for, so the two can wait for each
other only on inventory rows, and both take those in ascending product_id — a cycle would need one of them to wait
for a product_id below one it already holds. Two cancellations share products the same way; a cancellation and a
move of the same order both lock the order first, so one waits for the other and then sees its status.
"""
from psycopg2 import sql

from app.auth import require_actor, require_staff, require_store_or_support_reader
from app.errors import ApiError, NotFound
from app.schemas.fulfilment import CancelRequest, StatusMove
from app.services.orders import SUMMARY_SELECT, get_order


def list_store_orders(cur, actor, store_id: int, statuses: list[str] | None = None) -> list[dict]:
    """The store's orders (OrderSummary), oldest first — the order staff work them in — optionally only those
    in `statuses`: for that store's staff, or support."""
    require_store_or_support_reader(actor, store_id)
    cur.execute("SELECT 1 FROM store WHERE store_id = %s", (store_id,))
    if cur.fetchone() is None:
        raise NotFound("Store", store_id)           # only support gets here for a store that doesn't exist
    query = SUMMARY_SELECT + sql.SQL("WHERE fulfilling_store_id = %s")
    params: list = [store_id]
    if statuses:
        query += sql.SQL(" AND status = ANY(%s)")
        params.append(list(statuses))
    cur.execute(query + sql.SQL(" ORDER BY placed_at, order_id"), params)
    return cur.fetchall()


def advance_order(cur, actor, order_id: int, body: StatusMove) -> dict:
    """Move the order one step along its path (picking, then ready or shipped, then collected or delivered)."""
    actor = require_staff(actor)                    # a customer is turned away before any row is locked
    order = _lock_order(cur, order_id)
    _require_mover(actor, order, order_id)
    _check_from_status(order, body.from_status)
    _set_status(cur, actor, order_id, body.to_status)
    return get_order(cur, actor, order_id)


def cancel_order(cur, actor, order_id: int, body: CancelRequest) -> dict:
    """T4: cancel the order, giving back the stock and the money checkout took, in one transaction."""
    actor = require_actor(actor)
    if actor.is_support:                            # before any row is locked
        raise ApiError(403, "support_cannot_cancel",
                       "Support staff can look orders up but not cancel them: ask the customer or the store.")
    order = _lock_order(cur, order_id)
    _require_canceller(actor, order)
    _check_from_status(order, body.from_status)
    if actor.kind == "customer" and order["status"] not in ("placed", "paid"):
        raise ApiError(403, "customer_cancel_before_picking",
                       "The store has started on this order, so it can't be cancelled online. Ask the store.")
    _require_cancellable(cur, order)
    if order["status"] in ("paid", "ready"):
        _restock(cur, order)
    _refund(cur, order_id)
    _set_status(cur, actor, order_id, "cancelled")
    return get_order(cur, actor, order_id)


def _require_canceller(actor, order: dict | None) -> None:
    """Cancelling: the order's customer, or the staff of the store fulfilling it."""
    if actor.kind == "customer":
        if order is None or order["customer_id"] != actor.id:
            raise ApiError(403, "not_your_order", "That order isn't one of yours.")
    elif order is None or order["fulfilling_store_id"] != actor.store_id:
        raise ApiError(403, "other_store", "That order is fulfilled by another store.")


def _require_cancellable(cur, order: dict) -> None:
    """BR09's transition table says whether this order can still be cancelled. The trigger checks it again at the
    status change, but the refund comes first (BR21 wants nothing held by then), and BR14 would refuse that refund
    with its own name; asking the table first reports a picking or shipped order as the BR09 move it is."""
    cur.execute(
        """
        SELECT 1 FROM order_status_transition
        WHERE fulfilment_method = %s AND from_status = %s AND to_status = 'cancelled'
        """,
        (order["fulfilment_method"], order["status"]),
    )
    if cur.fetchone() is None:
        raise ApiError(409, "br09_order_status_transition",
                       f"A {order['status']} order can't be cancelled.", {"status": order["status"]})


def _restock(cur, order: dict) -> None:
    """Put each line's quantity back at the fulfilling store, where checkout took it, in ascending product_id.

    As in T3: first make sure the inventory row exists (nothing stops a row being deleted, and an UPDATE of a
    missing row would match nothing, losing the stock without an error), then a relative UPDATE, so a concurrent
    sale or adjustment of the same row waits and then adds to the committed quantity: no update is lost.
    """
    cur.execute("SELECT product_id, quantity FROM order_line WHERE order_id = %s ORDER BY product_id",
                (order["order_id"],))
    for line in cur.fetchall():
        cur.execute(
            """
            INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, 0)
            ON CONFLICT ON CONSTRAINT inventory_pk DO NOTHING
            """,
            (order["fulfilling_store_id"], line["product_id"]),
        )
        cur.execute(
            "UPDATE inventory SET quantity = quantity + %s WHERE store_id = %s AND product_id = %s",
            (line["quantity"], order["fulfilling_store_id"], line["product_id"]),
        )


def _refund(cur, order_id: int) -> None:
    """Refund what the shop still holds for the order — plan §5's stand-in for a payment provider. Nothing held
    (a zero total) is no refund at all: a payment is always positive.

    Its own function so a test can make the refund fail (test_a_failed_refund_rolls_back_the_whole_cancellation).
    """
    cur.execute(
        """
        INSERT INTO payment (order_id, kind, amount)
        SELECT order_id, 'refund', balance FROM v_order_payment WHERE order_id = %s AND balance > 0
        """,
        (order_id,),
    )


def _lock_order(cur, order_id: int) -> dict | None:
    """The order's row, locked FOR UPDATE until the transaction ends; None when there is no such order."""
    cur.execute(
        """
        SELECT order_id, customer_id, status, fulfilment_method, fulfilling_store_id
        FROM customer_order
        WHERE order_id = %s
        FOR UPDATE
        """,
        (order_id,),
    )
    return cur.fetchone()


def _require_mover(actor, order: dict | None, order_id: int) -> None:
    """Moving an order along: the staff of the store fulfilling it, or support staff (any store)."""
    if actor.is_support:
        if order is None:
            raise NotFound("Order", order_id)
        return
    if order is None or order["fulfilling_store_id"] != actor.store_id:
        raise ApiError(403, "other_store", "That order is fulfilled by another store.")


def _check_from_status(order: dict, from_status: str) -> None:
    if order["status"] != from_status:
        raise ApiError(409, "status_changed", f"This order is {order['status']} now, not {from_status}.",
                       {"status": order["status"]})


def _set_status(cur, actor, order_id: int, status: str) -> None:
    """Change the status as `actor`: a staff member is named in BR09's history, a customer isn't (NULL)."""
    staff_id = str(actor.id) if actor.kind == "staff" else ""
    cur.execute("SELECT set_config('app.staff_id', %s, true)", (staff_id,))
    cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))

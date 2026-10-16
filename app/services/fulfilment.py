"""Fulfilment (R7, R11): a store's order queue, and moving an order along its status path.

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
"""
from psycopg2 import sql

from app.auth import require_staff, require_store_or_support_reader
from app.errors import ApiError, NotFound
from app.schemas.fulfilment import StatusMove
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

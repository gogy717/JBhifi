"""Checkout (transaction T1) and order reads.

One POST = one transaction: resolve the retry key, validate the reviewed request against the database's
current state, write the order and its lines at the server's prices, take the stock, record the charge and
move the status to `paid` — or nothing at all.

Lock order (see doc/data-model.md): the customer, then the fulfilment address, then the products in
ascending id order, then inventory in ascending (store, product) order. Every workflow that touches these
tables uses the same order, so two of them cannot deadlock.
"""
from decimal import Decimal
from uuid import UUID

from psycopg2 import sql

from app.auth import Actor
from app.errors import ApiError, NotFound
from app.services.idempotency import money, order_fingerprint
from app.services.payments import record_charge

ZERO = Decimal("0.00")


# ---------------------------------------------------------------- checkout

def checkout(cur, actor: Actor, key: UUID, body) -> tuple[dict, bool]:
    """Place the order the customer reviewed. Returns (order detail, was this a replay?)."""
    customer_id = actor.id
    # 1. Lock the customer first: two requests from the same customer then queue here, which makes the
    #    key lookup below decisive and stops the order INSERT's foreign-key lock from deadlocking.
    cur.execute("SELECT 1 FROM customer WHERE customer_id = %s FOR UPDATE", (customer_id,))
    if cur.fetchone() is None:
        raise NotFound("Customer", customer_id)

    fingerprint = order_fingerprint(body)
    # 2. A retry of a committed request replays it, even if prices, stock or the address have changed
    #    since — the customer is asking for the same order, not a new one.
    cur.execute(
        "SELECT order_id, request_fingerprint FROM customer_order "
        "WHERE customer_id = %s AND idempotency_key = %s",
        (customer_id, str(key)),
    )
    existing = cur.fetchone()
    if existing is not None:
        if existing["request_fingerprint"] != fingerprint:
            raise ApiError(409, "idempotency_conflict",
                           "That Idempotency-Key was already used for a different request.")
        return get_order(cur, actor, existing["order_id"]), True

    items = _validate_items(body)
    store = _read_store(cur, body)
    if body.fulfilment_method == "delivery":
        _lock_active_address(cur, customer_id, body.delivery_address_no)
    products = _lock_products(cur, items)

    lines = [
        {
            "line_no": line_no,
            "product_id": product["product_id"],
            "sku": product["sku"],
            "name": product["name"],
            "quantity": items[product["product_id"]],
            "unit_price": product["current_price"],
            "line_total": product["current_price"] * items[product["product_id"]],
        }
        for line_no, product in enumerate(products, start=1)
    ]
    total = sum((line["line_total"] for line in lines), ZERO)
    if total != Decimal(body.expected_total):
        # Nothing has been written yet: the customer can review the new total and try again.
        raise ApiError(409, "price_changed", "The price changed while you were reviewing your order.",
                       {"total": money(total), "lines": [_line_json(line) for line in lines]})

    cur.execute(
        """
        INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint, fulfilment_method,
                                    fulfilling_store_id, delivery_address_no)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING order_id
        """,
        (customer_id, str(key), fingerprint, body.fulfilment_method, store["store_id"],
         body.delivery_address_no),
    )
    order_id = cur.fetchone()["order_id"]

    for line in lines:
        cur.execute(
            "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) "
            "VALUES (%s, %s, %s, %s, %s)",
            (order_id, line["line_no"], line["product_id"], line["quantity"], line["unit_price"]),
        )

    _take_stock(cur, store["store_id"], lines)
    record_charge(cur, order_id, total)               # nothing at all for a zero-total order
    set_status(cur, order_id, "paid", staff_id=None)   # the customer's own change: no staff actor
    flush_deferred(cur)
    return get_order(cur, actor, order_id), False


def _validate_items(body) -> dict[int, int]:
    """product_id → quantity, rejecting duplicate rows rather than guessing which one was meant."""
    items: dict[int, int] = {}
    for item in body.items:
        if item.product_id in items:
            raise ApiError(422, "duplicate_items",
                           f"Product {item.product_id} appears more than once. Send one line with the total.",
                           {"product_id": item.product_id})
        items[item.product_id] = item.quantity
    return items


def _read_store(cur, body) -> dict:
    # Read, not lock: no API changes a store, so there is nothing to serialise against here.
    cur.execute("SELECT store_id, name, store_type FROM store WHERE store_id = %s",
                (body.fulfilling_store_id,))
    store = cur.fetchone()
    if store is None:
        raise NotFound("Store", body.fulfilling_store_id)
    if body.fulfilment_method == "click_collect" and store["store_type"] != "retail":
        # Same code the database's BR06 trigger raises, so the UI shows one name for one rule.
        raise ApiError(409, "br06_collect_at_retail_store",
                       "Click & Collect orders must be collected from a retail store.")
    return store


def _lock_active_address(cur, customer_id: int, address_no: int | None) -> None:
    if address_no is None:
        raise ApiError(422, "delivery_needs_address", "A delivery order needs one of your addresses.")
    cur.execute(
        "SELECT is_active FROM customer_address WHERE customer_id = %s AND address_no = %s FOR UPDATE",
        (customer_id, address_no),
    )
    address = cur.fetchone()
    if address is None:
        raise NotFound("Address", address_no)
    if not address["is_active"]:
        raise ApiError(409, "address_inactive",
                       "That address has been retired. Choose a current one, or add a new address.",
                       {"address_no": address_no})


def _lock_products(cur, items: dict[int, int]) -> list[dict]:
    """Lock the requested products in ascending id order and read their current prices as of now."""
    cur.execute(
        """
        SELECT p.product_id, p.sku, p.name, p.is_active, cp.current_price
        FROM product p
        JOIN v_product_current_price cp ON cp.product_id = p.product_id
        WHERE p.product_id = ANY(%s)
        ORDER BY p.product_id
        FOR UPDATE OF p
        """,
        (list(items),),
    )
    products = cur.fetchall()
    missing = sorted(set(items) - {product["product_id"] for product in products})
    if missing:
        raise NotFound("Product", missing[0]) if len(missing) == 1 else ApiError(
            404, "not_found", f"Products not found: {missing}", {"product_ids": missing})
    retired = [product["sku"] for product in products if not product["is_active"]]
    if retired:
        raise ApiError(409, "product_unavailable",
                       f"{', '.join(retired)} is no longer sold.", {"skus": retired})
    return products


def _take_stock(cur, store_id: int, lines: list[dict]) -> None:
    """Take each line's quantity, in ascending product order, conditional on there being enough (BR03)."""
    for line in sorted(lines, key=lambda line: line["product_id"]):
        cur.execute(
            """
            UPDATE inventory SET quantity = quantity - %s
            WHERE store_id = %s AND product_id = %s AND quantity >= %s
            RETURNING quantity
            """,
            (line["quantity"], store_id, line["product_id"], line["quantity"]),
        )
        if cur.fetchone() is None:
            cur.execute("SELECT COALESCE(quantity, 0) AS quantity FROM inventory "
                        "WHERE store_id = %s AND product_id = %s", (store_id, line["product_id"]))
            row = cur.fetchone()
            available = row["quantity"] if row else 0
            raise ApiError(409, "out_of_stock",
                           f"Only {available} left of {line['sku']} at this store.",
                           {"store_id": store_id, "product_id": line["product_id"], "sku": line["sku"],
                            "requested": line["quantity"], "available": available})


def set_status(cur, order_id: int, status: str, staff_id: int | None) -> None:
    """Move the status, telling BR09's log who did it (NULL = the customer or the system)."""
    cur.execute("SELECT set_config('app.staff_id', %s, true)", ("" if staff_id is None else str(staff_id),))
    cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))


def flush_deferred(cur) -> None:
    """Run any DEFERRED constraints now, so a rule that only fails at COMMIT fails inside the request."""
    cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


# ---------------------------------------------------------------- reads

ORDER_SELECT = """
    SELECT o.order_id, o.customer_id, o.placed_at, o.status, o.fulfilment_method, o.fulfilling_store_id,
           o.delivery_address_no, s.name AS fulfilling_store_name, t.total, t.line_count,
           o.request_fingerprint, o.idempotency_key
    FROM customer_order o
    JOIN store s        ON s.store_id = o.fulfilling_store_id
    JOIN v_order_total t ON t.order_id = o.order_id
"""


def list_customer_orders(cur, actor: Actor, customer_id: int) -> list[dict]:
    cur.execute(ORDER_SELECT + " WHERE o.customer_id = %s ORDER BY o.placed_at DESC, o.order_id DESC",
                (customer_id,))
    return [_summary(row) for row in cur.fetchall()]


def get_order(cur, actor: Actor, order_id: int) -> dict:
    cur.execute(ORDER_SELECT + " WHERE o.order_id = %s", (order_id,))
    order = cur.fetchone()
    if order is None:
        raise NotFound("Order", order_id)
    _authorise(actor, order)
    return _detail(cur, actor, order)


def _authorise(actor: Actor, order: dict) -> None:
    """Another customer's order, or another store's, is a 404 — the same answer as one that isn't there."""
    if actor.kind == "customer":
        if order["customer_id"] != actor.id:
            raise NotFound("Order", order["order_id"])
        return
    if actor.is_support:
        return
    if order["fulfilling_store_id"] != actor.store_id:
        raise NotFound("Order", order["order_id"])


def _summary(row: dict) -> dict:
    return {
        "order_id": row["order_id"],
        "customer_id": row["customer_id"],
        "placed_at": row["placed_at"],
        "status": row["status"],
        "fulfilment_method": row["fulfilment_method"],
        "fulfilling_store_id": row["fulfilling_store_id"],
        "fulfilling_store_name": row["fulfilling_store_name"],
        "total": row["total"],
        "line_count": row["line_count"],
    }


def _detail(cur, actor: Actor, order: dict) -> dict:
    cur.execute(
        """
        SELECT l.line_no, l.product_id, p.sku, p.name, l.quantity, l.unit_price,
               l.quantity * l.unit_price AS line_total
        FROM order_line l
        JOIN product p ON p.product_id = l.product_id
        WHERE l.order_id = %s
        ORDER BY l.line_no
        """,
        (order["order_id"],),
    )
    lines = cur.fetchall()

    address = None
    if order["delivery_address_no"] is not None:
        cur.execute(
            "SELECT address_no, line1, suburb, state, postcode FROM customer_address "
            "WHERE customer_id = %s AND address_no = %s",
            (order["customer_id"], order["delivery_address_no"]),
        )
        address = cur.fetchone()

    cur.execute(
        "SELECT payment_id, kind, amount, return_id, cancellation_id, created_at FROM payment "
        "WHERE order_id = %s ORDER BY payment_id",
        (order["order_id"],),
    )
    payments = cur.fetchall()

    cur.execute(
        """
        SELECT h.seq, h.from_status, h.to_status, h.changed_at, h.changed_by_staff_id,
               st.full_name AS changed_by_name
        FROM order_status_history h
        LEFT JOIN staff st ON st.staff_id = h.changed_by_staff_id
        WHERE h.order_id = %s
        ORDER BY h.seq
        """,
        (order["order_id"],),
    )
    history = cur.fetchall()

    detail = _summary(order)
    detail.update({
        "lines": lines,
        "delivery_address": address,
        "payments": payments,
        "history": history,
        "allowed_actions": allowed_actions(cur, actor, order),
    })
    return detail


def allowed_actions(cur, actor: Actor, order: dict) -> list[str]:
    """What this actor may do next — the server's answer, so no page keeps its own copy of the rules."""
    if actor.kind != "staff" or actor.is_support:
        return customer_actions(cur, actor, order)
    if order["fulfilling_store_id"] != actor.store_id:
        return []
    cur.execute(
        "SELECT to_status FROM order_status_transition "
        "WHERE fulfilment_method = %s AND from_status = %s ORDER BY to_status",
        (order["fulfilment_method"], order["status"]),
    )
    moves = [row["to_status"] for row in cur.fetchall()]
    actions = [move for move in moves if move != "cancelled"]
    if "cancelled" in moves:
        actions.append("cancel")                     # cancellation is its own transaction (T11)
    return actions


def customer_actions(cur, actor: Actor, order: dict) -> list[str]:
    """A customer may ask to return a completed order (T13 fills in the deadline and quantities)."""
    return []


# ---------------------------------------------------------------- staff fulfilment (T11)

def lock_order(cur, order_id: int) -> dict:
    """Lock the order row, which is what makes every status check below decisive."""
    cur.execute(
        "SELECT order_id, customer_id, status, fulfilment_method, fulfilling_store_id "
        "FROM customer_order WHERE order_id = %s FOR UPDATE",
        (order_id,),
    )
    order = cur.fetchone()
    if order is None:
        raise NotFound("Order", order_id)
    return order


def require_own_store(actor: Actor, order: dict) -> None:
    """Fulfilment is done by the fulfilling store's own staff; support may look but not move."""
    if actor.kind != "staff":
        raise ApiError(403, "staff_only", "Only staff can move an order along.")
    if actor.is_support:
        raise ApiError(403, "store_staff_only", "Support staff can read orders but not fulfil them.")
    if actor.store_id != order["fulfilling_store_id"]:
        raise ApiError(403, "other_store", "That order is fulfilled by another store.")


def transition_order(cur, actor: Actor, order_id: int, body) -> dict:
    """One legal status move, or a precise reason it did not happen."""
    order = lock_order(cur, order_id)
    require_own_store(actor, order)
    if body.to_status == "cancelled":
        raise ApiError(409, "cancellation_required",
                       "Cancelling an order restores stock and refunds money, so it has its own endpoint: "
                       "POST /api/v1/orders/{order_id}/cancel.")
    if order["status"] == body.to_status:
        return get_order(cur, actor, order_id)        # already there: no second history entry
    if order["status"] != body.expected_status:
        raise ApiError(409, "stale_status", "This order has already moved on.",
                       {"status": order["status"]})
    cur.execute(
        "SELECT 1 FROM order_status_transition WHERE fulfilment_method = %s AND from_status = %s "
        "AND to_status = %s",
        (order["fulfilment_method"], order["status"], body.to_status),
    )
    if cur.fetchone() is None:
        raise ApiError(409, "br09_order_status_transition",
                       f"A {order['fulfilment_method']} order cannot move from {order['status']} "
                       f"to {body.to_status}.")
    set_status(cur, order_id, body.to_status, staff_id=actor.id)
    flush_deferred(cur)
    return get_order(cur, actor, order_id)


def list_store_orders(cur, store_id: int, status: str | None = None) -> list[dict]:
    """The store's queue: newest first, optionally one status."""
    conditions, params = [sql.SQL("o.fulfilling_store_id = %s")], [store_id]
    if status is not None:
        conditions.append(sql.SQL("o.status = %s"))
        params.append(status)
    cur.execute(
        sql.SQL(ORDER_SELECT) + sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        + sql.SQL(" ORDER BY o.placed_at DESC, o.order_id DESC"),
        params,
    )
    return [_summary(row) for row in cur.fetchall()]


def _line_json(line: dict) -> dict:
    return {
        "product_id": line["product_id"],
        "sku": line["sku"],
        "name": line["name"],
        "quantity": line["quantity"],
        "unit_price": money(line["unit_price"]),
        "line_total": money(line["line_total"]),
    }

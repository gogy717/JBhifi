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
from decimal import Decimal
from uuid import UUID

from psycopg2 import sql

from app.auth import require_actor, require_customer, require_customer_self, require_order_reader
from app.errors import ApiError, NotFound
from app.schemas.orders import OrderCreate

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


# ---------------------------------------------------------------- checkout (T1)

def checkout(cur, actor, key: UUID, body: OrderCreate) -> tuple[dict, bool]:
    """T1: place and pay for the basket the customer reviewed, in the request's one transaction (spec §3).

    Returns (order detail, replayed). replayed is True when this customer already placed an order with this
    key: that order is returned as it is now, and nothing is written. Any error rolls back everything this
    call wrote, its claim on the key included (app/db.py), so the same key can be sent again.
    """
    actor = require_customer(actor)

    # 1. Lookup. A retry whose first answer was lost gets that order back untouched, even if the address was
    #    retired or a price changed since. The body is not compared: a changed basket comes with a new key.
    placed = _order_with_key(cur, actor.id, key)
    if placed is not None:
        return get_order(cur, actor, placed), True

    # 2. Claim the key (BR10). If a request with the same key is still running (a double click), this INSERT
    #    waits for it: when it commits, DO NOTHING skips our row and we answer with its order; when it rolls
    #    back, ours goes in. The header's rules run here: BR06 (an address exactly when delivering; Click &
    #    Collect at a retail store), BR17 (the customer's own, current address) and the store's foreign key.
    cur.execute(
        """
        INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id,
                                    delivery_address_no)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT br10_order_idempotency_unique DO NOTHING
        RETURNING order_id
        """,
        (actor.id, str(key), body.fulfilment_method, body.fulfilling_store_id, body.delivery_address_no),
    )
    claimed = cur.fetchone()
    if claimed is None:
        return get_order(cur, actor, _order_with_key(cur, actor.id, key)), True
    order_id = claimed["order_id"]

    # 3. Lines, numbered in product_id order, each priced by the view as of now: the client never sends a
    #    price (BR08). BR07 checks every line: still on sale, quantity above 0, each product once.
    items = sorted(body.items, key=lambda item: item.product_id)
    for line_no, item in enumerate(items, start=1):
        cur.execute(
            """
            INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price)
            SELECT %s, %s, product_id, %s, current_price
            FROM v_product_current_price
            WHERE product_id = %s
            RETURNING line_no
            """,
            (order_id, line_no, item.quantity, item.product_id),
        )
        if cur.fetchone() is None:                  # the view has no such product
            raise NotFound("Product", item.product_id)

    # 4. Price check: the customer pays exactly the total they reviewed, or nothing.
    cur.execute("SELECT total FROM v_order_total WHERE order_id = %s", (order_id,))
    total = cur.fetchone()["total"]
    if total != body.expected_total:
        raise _price_changed(cur, order_id, total)

    # 5. Stock, in the same product_id order, so two baskets that share products lock those rows in one order.
    for item in items:
        _take_stock(cur, body.fulfilling_store_id, item.product_id, item.quantity)

    # 6. Charge, then 7. the customer's own move to paid: no staff member in BR09's log (app.staff_id empty),
    #    and BR20 checks the charge equals the total. The COMMIT then runs the deferred br07_order_has_lines.
    _charge(cur, order_id)
    cur.execute("SELECT set_config('app.staff_id', '', true)")
    cur.execute("UPDATE customer_order SET status = 'paid' WHERE order_id = %s", (order_id,))
    return get_order(cur, actor, order_id), False


def _order_with_key(cur, customer_id: int, key: UUID) -> int | None:
    """The order this customer placed with this retry key, if any (BR10: at most one)."""
    cur.execute(
        "SELECT order_id FROM customer_order WHERE customer_id = %s AND idempotency_key = %s",
        (customer_id, str(key)),
    )
    row = cur.fetchone()
    return None if row is None else row["order_id"]


def _price_changed(cur, order_id: int, total: Decimal) -> ApiError:
    """The 409 for a total that moved since the review. It carries the lines as they would be bought now, so
    the page can show them for the customer to review again.

    Money goes in as strings, as everywhere else in the API: the error handler's jsonable_encoder would turn
    a Decimal into a float (189.0). The lines come from Task 6's _lines, so they read exactly like the order's.
    """
    lines = [{**line, "unit_price": str(line["unit_price"]), "line_total": str(line["line_total"])}
             for line in _lines(cur, order_id)]
    return ApiError(409, "price_changed", "The price changed while you were reviewing your order.",
                    {"total": str(total), "lines": lines})


def _take_stock(cur, store_id: int, product_id: int, quantity: int) -> None:
    """Take `quantity` units from the store's stock, only if it has that many (BR03 stays the backstop).

    A relative, conditional UPDATE. Its row lock makes a second checkout of the same row wait; under READ
    COMMITTED that one then re-evaluates its WHERE clause against the first one's committed row, so the last
    unit is sold once, with no lock on the product (spec §3, step 5).
    """
    cur.execute(
        """
        UPDATE inventory SET quantity = quantity - %s
        WHERE store_id = %s AND product_id = %s AND quantity >= %s
        RETURNING quantity
        """,
        (quantity, store_id, product_id, quantity),
    )
    if cur.fetchone() is not None:
        return
    # Too few, or never stocked here (no inventory row at all): say how many there are.
    cur.execute(
        """
        SELECT p.sku, COALESCE(i.quantity, 0) AS available
        FROM product p
        LEFT JOIN inventory i ON i.product_id = p.product_id AND i.store_id = %s
        WHERE p.product_id = %s
        """,
        (store_id, product_id),
    )
    stock = cur.fetchone()
    raise ApiError(409, "out_of_stock", f"Only {stock['available']} left of {stock['sku']} at this store.",
                   {"store_id": store_id, "product_id": product_id, "sku": stock["sku"],
                    "requested": quantity, "available": stock["available"]})


def _charge(cur, order_id: int) -> None:
    """Take payment of the order's total: plan §5's stand-in for a payment provider. A zero total is no
    charge at all (a payment is always positive), and BR20 still holds: 0 charged = 0 due.

    Its own function so a test can make the payment fail (test_a_failed_charge_rolls_back_everything).
    """
    cur.execute(
        """
        INSERT INTO payment (order_id, kind, amount)
        SELECT order_id, 'charge', total FROM v_order_total WHERE order_id = %s AND total > 0
        """,
        (order_id,),
    )

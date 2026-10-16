"""Data for the report tests, built in SQL on the cursor it is given, and never committed by these helpers.

Figure tests build everything inside their own transaction (the `cur` fixture, rolled back afterwards): a fresh
store with its manager, a fresh category, products, orders and returns. The report then sees exactly what the
test built, and nothing is left behind — other tests count the seeded stores and categories.

Orders are inserted with their `placed_at` already set ("n days ago"): BR09 forbids changing it afterwards.
"""
import uuid


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def a_store(cur, state: str = "ACT") -> tuple[int, int]:
    """A new retail store and its manager, (store_id, manager_staff_id). The store names its manager before the
    manager exists: BR04's FK is checked at COMMIT, and a test never commits."""
    tag = _tag()
    cur.execute("SELECT nextval(pg_get_serial_sequence('staff', 'staff_id')) AS staff_id")
    manager_id = cur.fetchone()["staff_id"]
    cur.execute(
        """
        INSERT INTO store (name, store_type, suburb, state, manager_id)
        VALUES (%s, 'retail', 'Testville', %s, %s)
        RETURNING store_id
        """,
        (f"Report test store {tag}", state, manager_id),
    )
    store_id = cur.fetchone()["store_id"]
    cur.execute(
        """
        INSERT INTO staff (staff_id, store_id, staff_type, full_name, email)
        VALUES (%s, %s, 'store', 'Report Test Manager', %s)
        """,
        (manager_id, store_id, f"manager.{tag}@jbhifi.example"),
    )
    return store_id, manager_id


def a_category(cur) -> int:
    """A new leaf category under Audio."""
    cur.execute(
        """
        INSERT INTO category (name, parent_id)
        SELECT %s, category_id FROM category WHERE name = 'Audio'
        RETURNING category_id
        """,
        (f"Report test category {_tag()}",),
    )
    return cur.fetchone()["category_id"]


def a_product(cur, category_id: int, price: str = "100.00", *, stock: int | None = None,
              store_id: int | None = None, active: bool = True) -> int:
    """A new product (a JBL item) in that category at `price`, optionally stocked at one store."""
    cur.execute(
        """
        INSERT INTO product (sku, name, brand_id, category_id, base_price, is_active)
        SELECT %s, 'Report test item', brand_id, %s, %s, %s FROM brand WHERE name = 'JBL'
        RETURNING product_id
        """,
        (f"RPT-{_tag().upper()}", category_id, price, active),
    )
    product_id = cur.fetchone()["product_id"]
    if stock is not None:
        cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (store_id, product_id, stock))
    return product_id


def a_customer(cur) -> int:
    cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Report Test Customer') RETURNING customer_id",
                (f"report.{_tag()}@example.com",))
    return cur.fetchone()["customer_id"]


def a_sale(cur, store_id: int, items: list[tuple[int, int]], *, days_ago: int = 0, paid: bool = True,
           customer_id: int | None = None) -> int:
    """A Click & Collect order at store_id for items = [(product_id, quantity), ...], placed `days_ago` days ago,
    built as checkout (T1) leaves it: lines at today's price in product_id order, one charge of the total, then
    placed → paid. paid=False leaves it placed, with no charge. Stock is not touched. Returns the order id."""
    if customer_id is None:
        customer_id = a_customer(cur)
    cur.execute(
        """
        INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id, placed_at)
        VALUES (%s, gen_random_uuid(), 'click_collect', %s, now() - make_interval(days => %s))
        RETURNING order_id
        """,
        (customer_id, store_id, days_ago),
    )
    order_id = cur.fetchone()["order_id"]
    for line_no, (product_id, quantity) in enumerate(sorted(items), start=1):
        cur.execute(
            """
            INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price)
            SELECT %s, %s, product_id, %s, current_price FROM v_product_current_price WHERE product_id = %s
            """,
            (order_id, line_no, quantity, product_id),
        )
    if paid:
        cur.execute(
            """
            INSERT INTO payment (order_id, kind, amount)
            SELECT order_id, 'charge', total FROM v_order_total WHERE order_id = %s AND total > 0
            """,
            (order_id,),
        )
        _move(cur, order_id, "paid")
    return order_id


def _move(cur, order_id: int, *statuses: str, staff_id: int | None = None) -> None:
    cur.execute("SELECT set_config('app.staff_id', %s, true)", ("" if staff_id is None else str(staff_id),))
    for status in statuses:
        cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))


def collect(cur, order_id: int, staff_id: int | None = None) -> None:
    """paid → picking → ready → collected, so the order can be returned (BR11)."""
    _move(cur, order_id, "picking", "ready", "collected", staff_id=staff_id)


def cancel(cur, order_id: int) -> None:
    """Cancel as T4 does (SP2): refund the balance with a refund that names no return (allowed only while the
    order can still be cancelled), then move to cancelled, which BR21 allows only once nothing is held.
    Stock is not put back: these orders never took any."""
    cur.execute(
        """
        INSERT INTO payment (order_id, kind, amount)
        SELECT order_id, 'refund', balance FROM v_order_payment WHERE order_id = %s AND balance > 0
        """,
        (order_id,),
    )
    _move(cur, order_id, "cancelled")


def a_return(cur, order_id: int, lines: list[tuple[int, int]], *, status: str = "requested",
             at_store: tuple[int, int] | None = None) -> int:
    """A return of lines = [(line_no, quantity), ...] from a collected order, left `requested`, or moved on to
    `received` or `rejected` — received at at_store = (store_id, staff_id), by default the order's own store and
    its manager."""
    cur.execute("INSERT INTO return_request (order_id, reason) VALUES (%s, 'Report test') RETURNING return_id",
                (order_id,))
    return_id = cur.fetchone()["return_id"]
    for line_no, quantity in lines:
        cur.execute("INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, %s, %s, %s)",
                    (return_id, line_no, order_id, quantity))
    if status in ("received", "rejected"):
        if at_store is None:
            cur.execute(
                """
                SELECT s.store_id, s.manager_id FROM customer_order o JOIN store s ON s.store_id = o.fulfilling_store_id
                WHERE o.order_id = %s
                """,
                (order_id,),
            )
            at_store = tuple(cur.fetchone().values())
        cur.execute(
            "UPDATE return_request SET status = %s, received_store_id = %s, processed_by_staff_id = %s "
            "WHERE return_id = %s",
            (status, *at_store, return_id),
        )
    return return_id

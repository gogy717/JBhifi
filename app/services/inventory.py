"""Store stock and manual stock adjustments (BR03, BR18)."""
from psycopg2 import sql

from app.errors import NotFound
from app.services.filters import product_conditions, where
from app.services.reference import store_exists

ADJUSTMENT_SELECT = sql.SQL(
    """
    SELECT a.adjustment_id, a.store_id, a.product_id, p.sku, p.name AS product_name,
           a.staff_id, st.full_name AS staff_name, a.delta, a.reason, a.note, a.quantity_after, a.adjusted_at
    FROM stock_adjustment a
    JOIN product p ON p.product_id = a.product_id
    JOIN staff st  ON st.staff_id = a.staff_id
    """
)


def list_store_inventory(cur, store_id: int, q=None, category_id=None, low_stock_only=False,
                         low_stock_threshold=3):
    """Every product with its quantity at one store (0 if it was never stocked there)."""
    if not store_exists(cur, store_id):
        raise NotFound("Store", store_id)
    conditions, params = product_conditions(q, category_id, None)
    conditions.append(sql.SQL("(p.is_active OR i.quantity > 0)"))  # retired products show while stock is left
    if low_stock_only:
        conditions.append(sql.SQL("COALESCE(i.quantity, 0) <= %s"))
        params.append(low_stock_threshold)
    cur.execute(
        sql.SQL(
            """
            SELECT p.product_id, p.sku, p.name, b.name AS brand, c.name AS category,
                   cp.current_price, cp.promotion_id IS NOT NULL AS on_sale, p.is_active,
                   COALESCE(i.quantity, 0) AS quantity
            FROM product p
            JOIN brand b                    ON b.brand_id = p.brand_id
            JOIN category c                 ON c.category_id = p.category_id
            JOIN v_product_current_price cp ON cp.product_id = p.product_id
            LEFT JOIN inventory i           ON i.product_id = p.product_id AND i.store_id = %s
            {where}
            ORDER BY c.name, b.name, p.name
            """
        ).format(where=where(conditions)),
        [store_id, *params],
    )
    return cur.fetchall()


def adjust_stock(cur, store_id: int, product_id: int, staff_id: int, delta: int, reason: str,
                 note: str | None):
    """Change one store's stock of one product, and log who did it and why (BR18).

    Runs in the request's transaction (app/db.py): the stock change and its log row are committed
    together, or not at all.
    """
    if not store_exists(cur, store_id):
        raise NotFound("Store", store_id)
    cur.execute("SELECT 1 FROM product WHERE product_id = %s", (product_id,))
    if cur.fetchone() is None:
        raise NotFound("Product", product_id)

    # 1. A product never stocked at this store has no inventory row yet: create it at 0.
    #    ON CONFLICT DO NOTHING keeps this safe when two requests try it at the same moment.
    cur.execute(
        """
        INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, 0)
        ON CONFLICT (store_id, product_id) DO NOTHING
        """,
        (store_id, product_id),
    )
    # 2. Change the quantity *relative to its current value*, inside the database. A concurrent
    #    adjustment of the same row waits for our row lock and then adds to our result, so no update
    #    is lost (compare doc/progress.md, scenario 1). Below zero violates BR03 and aborts everything.
    cur.execute(
        """
        UPDATE inventory SET quantity = quantity + %s
        WHERE store_id = %s AND product_id = %s
        RETURNING quantity
        """,
        (delta, store_id, product_id),
    )
    quantity_after = cur.fetchone()["quantity"]
    # 3. Log it. If the log is rejected (BR18: e.g. the staff member works at another store),
    #    step 2 is rolled back with it — stock never changes without a log row.
    cur.execute(
        """
        INSERT INTO stock_adjustment (store_id, product_id, staff_id, delta, reason, note, quantity_after)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING adjustment_id
        """,
        (store_id, product_id, staff_id, delta, reason, note, quantity_after),
    )
    adjustment_id = cur.fetchone()["adjustment_id"]
    cur.execute(ADJUSTMENT_SELECT + sql.SQL("WHERE a.adjustment_id = %s"), (adjustment_id,))
    return cur.fetchone()


def list_adjustments(cur, store_id: int, product_id: int | None = None, limit: int = 50):
    if not store_exists(cur, store_id):
        raise NotFound("Store", store_id)
    conditions, params = [sql.SQL("a.store_id = %s")], [store_id]
    if product_id is not None:
        conditions.append(sql.SQL("a.product_id = %s"))
        params.append(product_id)
    cur.execute(
        ADJUSTMENT_SELECT + where(conditions)
        + sql.SQL(" ORDER BY a.adjusted_at DESC, a.adjustment_id DESC LIMIT %s"),
        [*params, limit],
    )
    return cur.fetchall()

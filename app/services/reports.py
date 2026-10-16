"""R9: a store manager's report — low stock, sales by category, return rate (plan §6 #4–#6).

"What is a sale" is defined once, in the view v_sale_line (sql/03_views.sql): an order line of a paid order that
isn't cancelled, credited to the store that fulfils it, at the price paid. Every query here builds on it.
"""
from app.errors import NotFound

# Low stock: down to this many units, or fewer days of cover than COVER_DAYS at the rate of the last RATE_DAYS
# days. Reordering is about the shelf, so these don't follow the report's window.
LOW_STOCK_QUANTITY = 3
COVER_DAYS = 14
RATE_DAYS = 30


def _low_stock(cur, store_id: int) -> list[dict]:
    """Plan §6 #4 (join + GROUP BY + HAVING). Products this store stocks (it has an inventory row, sold out or
    not) and still sells, that are down to LOW_STOCK_QUANTITY or would run out within COVER_DAYS at the last
    RATE_DAYS days' rate. The HAVING condition needs the sales total, so it can't be a WHERE: WHERE filters rows
    before they are grouped, HAVING filters the groups. `quantity * 30 < sold * 14` compares whole numbers, so
    there is no division (and no dividing by zero) in the test itself."""
    cur.execute(
        """
        SELECT p.product_id, p.sku, p.name, c.name AS category, i.quantity,
               COALESCE(sum(s.quantity), 0) AS sold_30d,
               round(i.quantity * %(rate_days)s::numeric / NULLIF(sum(s.quantity), 0), 1) AS days_of_cover
        FROM inventory i
        JOIN product p  ON p.product_id = i.product_id
        JOIN category c ON c.category_id = p.category_id
        LEFT JOIN v_sale_line s
               ON s.product_id = i.product_id
              AND s.store_id = i.store_id
              AND s.placed_at >= now() - make_interval(days => %(rate_days)s)
        WHERE i.store_id = %(store_id)s AND p.is_active
        GROUP BY p.product_id, p.sku, p.name, c.name, i.quantity
        HAVING i.quantity <= %(low)s
            OR i.quantity * %(rate_days)s < COALESCE(sum(s.quantity), 0) * %(cover_days)s
        ORDER BY i.quantity, p.sku
        """,
        {"store_id": store_id, "rate_days": RATE_DAYS, "low": LOW_STOCK_QUANTITY, "cover_days": COVER_DAYS},
    )
    return cur.fetchall()


def build_store_report(cur, store_id: int, days: int) -> dict:
    """Every section of one store's report, read on `cur` in its current transaction. store_report runs this in
    one REPEATABLE READ snapshot; tests run it inside their own transaction."""
    cur.execute("SELECT store_id, name AS store_name, now() AS generated_at FROM store WHERE store_id = %s",
                (store_id,))
    store = cur.fetchone()
    if store is None:
        raise NotFound("Store", store_id)
    return {**store, "days": days, "low_stock": _low_stock(cur, store_id)}

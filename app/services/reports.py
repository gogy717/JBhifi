"""R9: a store manager's report — low stock, sales by category, return rate (plan §6 #4–#6).

"What is a sale" is defined once, in the view v_sale_line (sql/03_views.sql): an order line of a paid order that
isn't cancelled, credited to the store that fulfils it, at the price paid. Every query here builds on it.
"""
from psycopg2 import sql

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


def _sales_by_category(cur, store_id: int, days: int) -> list[dict]:
    """Orders, units and revenue per category over the window, at this store. Every category that has products
    is listed, so the LEFT JOIN keeps a category with no sales: count() then counts no rows (0) and sum() is
    NULL, hence COALESCE. The second LEFT JOIN, category to itself, names the parent (the recursive relationship;
    a top-level category has none). The window conditions sit in the join's ON clause: in a WHERE they would drop
    the categories with no sales, which is the outer join undone."""
    cur.execute(
        """
        SELECT c.category_id, c.name AS category, parent.name AS parent_category,
               count(DISTINCT s.order_id)                                AS orders,
               COALESCE(sum(s.quantity), 0)                              AS units,
               CAST(COALESCE(sum(s.line_total), 0) AS NUMERIC(12,2))     AS revenue
        FROM category c
        LEFT JOIN category parent ON parent.category_id = c.parent_id
        LEFT JOIN v_sale_line s
               ON s.category_id = c.category_id
              AND s.store_id = %(store_id)s
              AND s.placed_at >= now() - make_interval(days => %(days)s)
        WHERE EXISTS (SELECT 1 FROM product p WHERE p.category_id = c.category_id)
        GROUP BY c.category_id, c.name, parent.name
        ORDER BY revenue DESC, c.name
        """,
        {"store_id": store_id, "days": days},
    )
    return cur.fetchall()


def _sales_total(cur, store_id: int, days: int) -> dict:
    """The whole store over the window. An order with lines in two categories counts once here, but once in each
    category above, so the category order counts don't add up to this one (units and revenue do)."""
    cur.execute(
        """
        SELECT count(DISTINCT order_id)                              AS orders,
               COALESCE(sum(quantity), 0)                            AS units,
               CAST(COALESCE(sum(line_total), 0) AS NUMERIC(12,2))   AS revenue
        FROM v_sale_line
        WHERE store_id = %(store_id)s AND placed_at >= now() - make_interval(days => %(days)s)
        """,
        {"store_id": store_id, "days": days},
    )
    return cur.fetchone()


# Units returned from each order line, over its returns that weren't rejected (BR12's count). Summed per order
# line *before* it is joined, so each sale line meets at most one row: joined to return_line first, a line with two
# partial returns would appear twice and its sold units would be counted twice (fan-out). The rejected filter is
# in here too: on the outer query, `WHERE status <> 'rejected'` would also drop every sale line that has no return
# (its status is NULL), turning the outer join into an inner one and the rate into "returned / returned lines".
RETURNED_PER_LINE = sql.SQL("""
    SELECT rl.order_id, rl.line_no, sum(rl.quantity) AS returned
    FROM return_line rl
    JOIN return_request rr ON rr.return_id = rl.return_id
    WHERE rr.status <> 'rejected'
    GROUP BY rl.order_id, rl.line_no
""")

# The rate: returned ÷ sold over the same lines, to four places. sum() of an INT column is a bigint, and
# bigint / bigint is integer division — 1 of 4 back would read 0. (Here the numerator happens to be a sum of
# sums, which PostgreSQL makes numeric, but the explicit ::numeric keeps the division exact whatever the inputs.)
# NULLIF turns "nothing sold" into NULL instead of a division by zero; nothing back out of some sold is 0.0000.
RATE = sql.SQL("round(COALESCE(sum(r.returned), 0)::numeric / NULLIF(sum(s.quantity), 0), 4)")


def _return_rate_by_category(cur, store_id: int, days: int) -> list[dict]:
    """Plan §6 #6 (outer join + aggregates + NULLIF). Of the units this store sold in the window, the share that
    came back, per category. Returns count for the store that sold the item, whichever store received it, so
    numerator and denominator are the same units; and only lines sold in the window are counted, whenever they
    came back. Units sold in the last 30 days can still be returned (BR11), so a recent window reads low."""
    cur.execute(
        sql.SQL("""
        SELECT c.category_id, c.name AS category,
               COALESCE(sum(s.quantity), 0)::int  AS units_sold,
               COALESCE(sum(r.returned), 0)::int  AS units_returned,
               {rate}                             AS return_rate
        FROM category c
        LEFT JOIN v_sale_line s
               ON s.category_id = c.category_id
              AND s.store_id = %(store_id)s
              AND s.placed_at >= now() - make_interval(days => %(days)s)
        LEFT JOIN ({returned}) r
               ON r.order_id = s.order_id AND r.line_no = s.line_no
        WHERE EXISTS (SELECT 1 FROM product p WHERE p.category_id = c.category_id)
        GROUP BY c.category_id, c.name
        ORDER BY return_rate DESC NULLS LAST, units_returned DESC, c.name
        """).format(rate=RATE, returned=RETURNED_PER_LINE),
        {"store_id": store_id, "days": days},
    )
    return cur.fetchall()


def _return_rate_by_product(cur, store_id: int, days: int) -> list[dict]:
    """The same rate per product, for the products this store sold in the window, highest first."""
    cur.execute(
        sql.SQL("""
        SELECT p.product_id, p.sku, p.name,
               sum(s.quantity)::int               AS units_sold,
               COALESCE(sum(r.returned), 0)::int  AS units_returned,
               {rate}                             AS return_rate
        FROM v_sale_line s
        JOIN product p ON p.product_id = s.product_id
        LEFT JOIN ({returned}) r
               ON r.order_id = s.order_id AND r.line_no = s.line_no
        WHERE s.store_id = %(store_id)s
          AND s.placed_at >= now() - make_interval(days => %(days)s)
        GROUP BY p.product_id, p.sku, p.name
        ORDER BY return_rate DESC, units_returned DESC, p.sku
        """).format(rate=RATE, returned=RETURNED_PER_LINE),
        {"store_id": store_id, "days": days},
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
    return {
        **store,
        "days": days,
        "low_stock": _low_stock(cur, store_id),
        "sales_by_category": _sales_by_category(cur, store_id, days),
        "sales_total": _sales_total(cur, store_id, days),
        "return_rate_by_category": _return_rate_by_category(cur, store_id, days),
        "return_rate_by_product": _return_rate_by_product(cur, store_id, days),
    }

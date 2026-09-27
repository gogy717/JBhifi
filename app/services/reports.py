"""The three reports: sales, low stock and returns.

Definitions (also in `doc/reports.md`, which is the source of truth for the reviewer):

* **Sales.** Money is counted by the *payment's* own event time, orders by when they were placed, and each
  aggregate is computed in its own CTE before any join — joining payments to order lines first would
  multiply a charge by the number of lines on that order. Attributed to the fulfilling store.
* **Low stock.** Active products at or below the threshold at one store, including products with no
  inventory row there (which is a quantity of zero, not a missing row).
* **Returns.** The *cohort* of requests created in the window, attributed to the store that fulfilled the
  order, with their current status and the refund linked to the request rather than to the refund's date.
  The receiving store is shown separately, because an item can be handed back anywhere.

Dates are Sydney calendar dates: `from_date` inclusive, `to_date` exclusive. The SQL turns the local date
into the instant the day starts, so the boundary does not move with the server's time zone.
"""
from datetime import date, timedelta

from psycopg2 import sql

from app.errors import ApiError

SYDNEY = "Australia/Sydney"
DEFAULT_DAYS = 30

# The two ends of the window are different placeholders: `from_date` is inclusive, `to_date` exclusive.
FROM_AT = sql.SQL("(%(from_date)s::timestamp AT TIME ZONE 'Australia/Sydney')")
TO_AT = sql.SQL("(%(to_date)s::timestamp AT TIME ZONE 'Australia/Sydney')")


def _window(from_date: date | None, to_date: date | None) -> dict:
    """Default to the last 30 Sydney days including today, and refuse an impossible interval."""
    today = date.today()
    start = from_date or today - timedelta(days=DEFAULT_DAYS - 1)
    end = to_date or today + timedelta(days=1)
    if end <= start:
        raise ApiError(422, "invalid_date_range", "The end of the period must be after its start.",
                       {"from_date": start.isoformat(), "to_date": end.isoformat()})
    return {"from_date": start, "to_date": end}


def _store_filter(store_id: int | None) -> sql.Composable:
    return sql.SQL("AND (%(store_id)s::int IS NULL OR o.fulfilling_store_id = %(store_id)s::int)")


# ---------------------------------------------------------------- sales

SALES_SQL = sql.SQL("""
    WITH captured AS (
        SELECT o.fulfilling_store_id AS store_id, COALESCE(sum(p.amount), 0) AS captured_amount,
               count(DISTINCT p.order_id) AS charged_orders
        FROM payment p
        JOIN customer_order o ON o.order_id = p.order_id
        WHERE p.kind = 'charge'
          AND p.created_at >= {from_at} AND p.created_at < {to_at}
          {store_filter}
        GROUP BY o.fulfilling_store_id
    ),
    refunded AS (
        SELECT o.fulfilling_store_id AS store_id, COALESCE(sum(p.amount), 0) AS refunded_amount,
               count(*) AS refund_count
        FROM payment p
        JOIN customer_order o ON o.order_id = p.order_id
        WHERE p.kind = 'refund'
          AND p.created_at >= {from_at} AND p.created_at < {to_at}
          {store_filter}
        GROUP BY o.fulfilling_store_id
    ),
    placed AS (
        SELECT o.fulfilling_store_id AS store_id, count(*) AS order_count
        FROM customer_order o
        WHERE o.placed_at >= {from_at} AND o.placed_at < {to_at}
          {store_filter}
        GROUP BY o.fulfilling_store_id
    )
    SELECT s.store_id, s.name AS store_name,
           COALESCE(c.captured_amount, 0)::numeric(12,2) AS captured_amount,
           COALESCE(r.refunded_amount, 0)::numeric(12,2) AS refunded_amount,
           (COALESCE(c.captured_amount, 0) - COALESCE(r.refunded_amount, 0))::numeric(12,2) AS net_receipts,
           COALESCE(pl.order_count, 0) AS order_count,
           COALESCE(c.charged_orders, 0) AS charged_orders,
           COALESCE(r.refund_count, 0) AS refund_count
    FROM store s
    LEFT JOIN captured c  ON c.store_id = s.store_id
    LEFT JOIN refunded r  ON r.store_id = s.store_id
    LEFT JOIN placed   pl ON pl.store_id = s.store_id
    WHERE c.store_id IS NOT NULL OR r.store_id IS NOT NULL OR pl.store_id IS NOT NULL
    ORDER BY s.store_id
""").format(from_at=FROM_AT, to_at=TO_AT, store_filter=_store_filter(None))


def sales(cur, store_id: int | None, from_date: date | None, to_date: date | None) -> dict:
    window = _window(from_date, to_date)
    params = {**window, "store_id": store_id}
    cur.execute(SALES_SQL, params)
    rows = cur.fetchall()
    return {"window": _window_json(cur, window), "rows": rows, "totals": _totals(rows)}


# ---------------------------------------------------------------- low stock

LOW_STOCK_SQL = """
    SELECT p.product_id, p.sku, p.name, b.name AS brand, c.name AS category, cp.current_price,
           COALESCE(i.quantity, 0) AS quantity, i.store_id IS NOT NULL AS has_inventory_row
    FROM product p
    JOIN brand b                    ON b.brand_id = p.brand_id
    JOIN category c                 ON c.category_id = p.category_id
    JOIN v_product_current_price cp ON cp.product_id = p.product_id
    LEFT JOIN inventory i           ON i.product_id = p.product_id AND i.store_id = %s
    WHERE p.is_active AND COALESCE(i.quantity, 0) <= %s
    ORDER BY COALESCE(i.quantity, 0), p.name
"""


def low_stock(cur, store_id: int, threshold: int) -> dict:
    from app.errors import NotFound
    from app.services.reference import store_exists

    if not store_exists(cur, store_id):
        raise NotFound("Store", store_id)
    cur.execute("SELECT name FROM store WHERE store_id = %s", (store_id,))
    store_name = cur.fetchone()["name"]
    cur.execute(LOW_STOCK_SQL, (store_id, threshold))
    rows = cur.fetchall()
    return {"store_id": store_id, "store_name": store_name, "threshold": threshold, "rows": rows}


# ---------------------------------------------------------------- returns

RETURNS_SQL = sql.SQL("""
    WITH cohort AS (
        SELECT rr.return_id, rr.status, rr.received_store_id, o.fulfilling_store_id
        FROM return_request rr
        JOIN customer_order o ON o.order_id = rr.order_id
        WHERE rr.requested_at >= {from_at} AND rr.requested_at < {to_at}
          {store_filter}
    ),
    refunds AS (
        SELECT return_id, sum(amount) AS refunded_amount
        FROM payment WHERE kind = 'refund' GROUP BY return_id
    )
    SELECT c.fulfilling_store_id AS store_id, s.name AS store_name,
           count(*) AS requested_count,
           count(*) FILTER (WHERE c.status = 'received') AS received_count,
           count(*) FILTER (WHERE c.status = 'refunded') AS refunded_count,
           count(*) FILTER (WHERE c.status = 'rejected') AS rejected_count,
           COALESCE(sum(rf.refunded_amount), 0)::numeric(12,2) AS refunded_amount,
           (SELECT string_agg(rstore.name || ' (' || counts.received || ')', ', ' ORDER BY rstore.name)
            FROM (SELECT received_store_id, count(*) AS received
                  FROM cohort WHERE received_store_id IS NOT NULL
                  GROUP BY received_store_id) counts
            JOIN store rstore ON rstore.store_id = counts.received_store_id) AS receiving_stores
    FROM cohort c
    JOIN store s         ON s.store_id = c.fulfilling_store_id
    LEFT JOIN refunds rf ON rf.return_id = c.return_id
    GROUP BY c.fulfilling_store_id, s.name
    ORDER BY c.fulfilling_store_id
""").format(from_at=FROM_AT, to_at=TO_AT, store_filter=_store_filter(None))


def returns(cur, store_id: int | None, from_date: date | None, to_date: date | None) -> dict:
    window = _window(from_date, to_date)
    params = {**window, "store_id": store_id}
    cur.execute(RETURNS_SQL, params)
    rows = cur.fetchall()
    totals = {
        "store_id": 0,
        "store_name": "All stores",
        "requested_count": sum(row["requested_count"] for row in rows),
        "received_count": sum(row["received_count"] for row in rows),
        "refunded_count": sum(row["refunded_count"] for row in rows),
        "rejected_count": sum(row["rejected_count"] for row in rows),
        "refunded_amount": sum((row["refunded_amount"] for row in rows), 0),
        "receiving_stores": None,
    }
    return {"window": _window_json(cur, window), "rows": rows, "totals": totals}


# ---------------------------------------------------------------- shared

def _window_json(cur, window: dict) -> dict:
    """The window as given, plus the instants it resolved to — so a report can be checked by hand.

    The instants come from the *database's* time-zone data rather than Python's: PostgreSQL always has
    `Australia/Sydney`, whereas a bare Windows Python install often has no zone database at all.
    """
    cur.execute(
        "SELECT (%s::timestamp AT TIME ZONE 'Australia/Sydney') AS from_at, "
        "       (%s::timestamp AT TIME ZONE 'Australia/Sydney') AS to_at",
        (window["from_date"], window["to_date"]),
    )
    instants = cur.fetchone()
    return {"from_date": window["from_date"], "to_date": window["to_date"],
            "from_at": instants["from_at"], "to_at": instants["to_at"]}


def _totals(rows: list[dict]) -> dict:
    captured = sum((row["captured_amount"] for row in rows), 0)
    refunded = sum((row["refunded_amount"] for row in rows), 0)
    return {
        "store_id": 0,
        "store_name": "All stores",
        "captured_amount": captured,
        "refunded_amount": refunded,
        "net_receipts": captured - refunded,
        "order_count": sum(row["order_count"] for row in rows),
        "charged_orders": sum(row["charged_orders"] for row in rows),
        "refund_count": sum(row["refund_count"] for row in rows),
    }

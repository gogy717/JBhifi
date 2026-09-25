"""Promotions. BR15 (sale price below base price, no overlapping periods) is a trigger in sql/02_rules.sql,
so a rejected promotion arrives here as a CheckViolation and app/errors.py turns it into a 409."""
from psycopg2 import sql

from app.errors import NotFound
from app.services.filters import where

STATUS_CONDITIONS = {
    "upcoming": sql.SQL("now() < pr.starts_at"),
    "active": sql.SQL("pr.starts_at <= now() AND now() < pr.ends_at"),
    "ended": sql.SQL("pr.ends_at <= now()"),
}

PROMOTION_SELECT = sql.SQL(
    """
    SELECT pr.promotion_id, pr.product_id, p.sku, b.name AS brand, p.name AS product_name, p.base_price,
           pr.sale_price, pr.starts_at, pr.ends_at,
           CASE WHEN now() < pr.starts_at THEN 'upcoming'
                WHEN now() < pr.ends_at   THEN 'active'
                ELSE 'ended'
           END AS status
    FROM promotion pr
    JOIN product p ON p.product_id = pr.product_id
    JOIN brand b   ON b.brand_id = p.brand_id
    """
)


def list_promotions(cur, product_id=None, status=None, promotion_id=None):
    conditions, params = [], []
    if product_id is not None:
        conditions.append(sql.SQL("pr.product_id = %s"))
        params.append(product_id)
    if promotion_id is not None:
        conditions.append(sql.SQL("pr.promotion_id = %s"))
        params.append(promotion_id)
    if status is not None:
        conditions.append(STATUS_CONDITIONS[status])
    cur.execute(PROMOTION_SELECT + where(conditions) + sql.SQL(" ORDER BY pr.starts_at DESC, pr.promotion_id DESC"),
                params)
    return cur.fetchall()


def get_promotion(cur, promotion_id: int):
    rows = list_promotions(cur, promotion_id=promotion_id)
    if not rows:
        raise NotFound("Promotion", promotion_id)
    return rows[0]


def create_promotion(cur, new):
    cur.execute(
        """
        INSERT INTO promotion (product_id, sale_price, starts_at, ends_at)
        VALUES (%s, %s, %s, %s)
        RETURNING promotion_id
        """,
        (new.product_id, new.sale_price, new.starts_at, new.ends_at),
    )
    return get_promotion(cur, cur.fetchone()["promotion_id"])


def delete_promotion(cur, promotion_id: int) -> None:
    cur.execute("DELETE FROM promotion WHERE promotion_id = %s", (promotion_id,))
    if cur.rowcount == 0:
        raise NotFound("Promotion", promotion_id)

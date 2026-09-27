"""WHERE-clause pieces shared by the product and inventory lists.

Optional filters are composed with psycopg2.sql (doc/progress.md): the SQL text only ever contains
fixed fragments written here, and every user-supplied value still goes through a %s parameter.
"""
from psycopg2 import sql


def contains_pattern(text: str) -> str:
    """An ILIKE pattern (a parameter value, not SQL) matching text anywhere, with its wildcards escaped."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def product_conditions(q: str | None, category_id: int | None, brand_id: int | None):
    """Conditions on product p, brand b and category c, as (list of sql.SQL, list of params)."""
    conditions, params = [], []
    if q:
        conditions.append(sql.SQL("(p.name ILIKE %s OR p.sku ILIKE %s OR b.name ILIKE %s)"))
        params += [contains_pattern(q)] * 3
    if category_id is not None:
        # A top-level category includes its subcategories (the hierarchy has two levels).
        conditions.append(sql.SQL("(c.category_id = %s OR c.parent_id = %s)"))
        params += [category_id, category_id]
    if brand_id is not None:
        conditions.append(sql.SQL("b.brand_id = %s"))
        params.append(brand_id)
    return conditions, params


def where(conditions) -> sql.Composable:
    if not conditions:
        return sql.SQL("")
    return sql.SQL("WHERE ") + sql.SQL(" AND ").join(conditions)

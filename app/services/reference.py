"""Read-only reference data: stores, staff, categories, brands."""
from psycopg2 import sql

from app.auth import require_staff


def list_stores(cur):
    cur.execute(
        """
        SELECT s.store_id, s.name, s.store_type, s.suburb, s.state, s.manager_id, m.full_name AS manager_name
        FROM store s
        JOIN staff m ON m.staff_id = s.manager_id
        ORDER BY s.store_id
        """
    )
    return cur.fetchall()


def store_exists(cur, store_id: int) -> bool:
    cur.execute("SELECT 1 FROM store WHERE store_id = %s", (store_id,))
    return cur.fetchone() is not None


def list_staff(cur, actor, store_id: int | None = None):
    require_staff(actor)
    where, params = sql.SQL(""), ()
    if store_id is not None:
        where, params = sql.SQL("WHERE st.store_id = %s"), (store_id,)
    cur.execute(
        sql.SQL(
            """
            SELECT st.staff_id, st.full_name, st.staff_type, st.store_id, s.name AS store_name,
                   COALESCE(s.manager_id = st.staff_id, FALSE) AS is_manager
            FROM staff st
            LEFT JOIN store s ON s.store_id = st.store_id
            {where}
            ORDER BY st.store_id NULLS LAST, is_manager DESC, st.full_name
            """
        ).format(where=where),
        params,
    )
    return cur.fetchall()


def list_categories(cur):
    # Self-join on the recursive relationship: each category next to its parent's name.
    cur.execute(
        """
        SELECT c.category_id, c.name, c.parent_id, p.name AS parent_name
        FROM category c
        LEFT JOIN category p ON p.category_id = c.parent_id
        ORDER BY COALESCE(p.name, c.name), c.parent_id NULLS FIRST, c.name
        """
    )
    return cur.fetchall()


def list_brands(cur):
    cur.execute("SELECT brand_id, name FROM brand ORDER BY name")
    return cur.fetchall()

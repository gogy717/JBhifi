"""Catalogue: products and their specs."""
from psycopg2 import sql

from app.auth import require_catalogue_writer
from app.errors import ApiError, NotFound
from app.services import promotions
from app.services.filters import product_conditions, where
from app.services.reference import store_exists

# The columns of ProductSummary. The price comes from the view, so it includes any running promotion.
# {store_quantity} is one of the two fragments below: null when no store was asked about, otherwise that
# store's quantity (0 when the product has no inventory row there).
SUMMARY_SELECT = sql.SQL(
    """
    SELECT p.product_id, p.sku, p.name, p.brand_id, b.name AS brand, p.category_id, c.name AS category,
           p.base_price, cp.current_price, cp.promotion_id IS NOT NULL AS on_sale, p.is_active,
           COALESCE((SELECT sum(i.quantity) FROM inventory i WHERE i.product_id = p.product_id), 0)
               AS total_stock,
           {store_quantity} AS store_quantity
    FROM product p
    JOIN brand b                    ON b.brand_id = p.brand_id
    JOIN category c                 ON c.category_id = p.category_id
    JOIN v_product_current_price cp ON cp.product_id = p.product_id
    """
)
NO_STORE_QUANTITY = sql.SQL("NULL::int")
ONE_STORE_QUANTITY = sql.SQL(
    "COALESCE((SELECT i.quantity FROM inventory i WHERE i.product_id = p.product_id AND i.store_id = %s), 0)"
)

# The columns a PATCH may change. Only these names can reach the dynamic SET clause below.
UPDATABLE_COLUMNS = ("name", "brand_id", "category_id", "base_price", "is_active")


def list_products(cur, q=None, category_id=None, brand_id=None, include_inactive=False,
                  min_price=None, max_price=None, store_id=None):
    """The catalogue, filtered (R1). Prices are compared with the price a product sells for now, promotion
    included (R2), and both bounds count. A store_id adds that store's quantity to each product (R3); it
    doesn't filter the list."""
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError(422, "invalid_price_range", "The lowest price is above the highest price.",
                       {"min_price": str(min_price), "max_price": str(max_price)})
    if store_id is not None and not store_exists(cur, store_id):
        raise NotFound("Store", store_id)

    conditions, params = product_conditions(q, category_id, brand_id)
    if not include_inactive:
        conditions.append(sql.SQL("p.is_active"))
    if min_price is not None:
        conditions.append(sql.SQL("cp.current_price >= %s"))
        params.append(min_price)
    if max_price is not None:
        conditions.append(sql.SQL("cp.current_price <= %s"))
        params.append(max_price)

    if store_id is None:
        select = SUMMARY_SELECT.format(store_quantity=NO_STORE_QUANTITY)
    else:
        # The store's %s is in the SELECT list, ahead of every condition's, so its value goes first.
        select = SUMMARY_SELECT.format(store_quantity=ONE_STORE_QUANTITY)
        params = [store_id, *params]
    cur.execute(select + where(conditions) + sql.SQL(" ORDER BY c.name, b.name, p.name"), params)
    return cur.fetchall()


def get_product(cur, product_id: int):
    cur.execute(SUMMARY_SELECT.format(store_quantity=NO_STORE_QUANTITY) + sql.SQL("WHERE p.product_id = %s"),
                (product_id,))
    product = cur.fetchone()
    if product is None:
        raise NotFound("Product", product_id)
    product["specs"] = _specs(cur, product_id)
    cur.execute(
        """
        SELECT s.store_id, s.name AS store_name, s.store_type, s.state, COALESCE(i.quantity, 0) AS quantity
        FROM store s
        LEFT JOIN inventory i ON i.store_id = s.store_id AND i.product_id = %s
        ORDER BY s.store_id
        """,
        (product_id,),
    )
    product["stock"] = cur.fetchall()
    product["promotions"] = promotions.list_promotions(cur, product_id=product_id)
    return product


def create_product(cur, actor, new):
    require_catalogue_writer(actor)
    cur.execute(
        """
        INSERT INTO product (sku, name, brand_id, category_id, base_price)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING product_id
        """,
        (new.sku, new.name, new.brand_id, new.category_id, new.base_price),
    )
    return get_product(cur, cur.fetchone()["product_id"])


def update_product(cur, actor, product_id: int, changes: dict):
    require_catalogue_writer(actor)
    changes ={column: value for column, value in changes.items() if column in UPDATABLE_COLUMNS}
    if changes:
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(column)) for column in changes
        )
        cur.execute(
            sql.SQL("UPDATE product SET {} WHERE product_id = %s").format(assignments),
            (*changes.values(), product_id),
        )
        if cur.rowcount == 0:
            raise NotFound("Product", product_id)
    return get_product(cur, product_id)


def replace_specs(cur, actor, product_id: int, specs) -> list:
    """Replace all of a product's specs at once; other transactions see the old set or the new one."""
    require_catalogue_writer(actor)
    # Lock the product so two concurrent replacements run one after the other. Without it, the second
    # DELETE wouldn't see the rows the first one inserted, and the two sets would collide.
    cur.execute("SELECT 1 FROM product WHERE product_id = %s FOR UPDATE", (product_id,))
    if cur.fetchone() is None:
        raise NotFound("Product", product_id)
    cur.execute("DELETE FROM product_spec WHERE product_id = %s", (product_id,))
    for spec in specs:
        cur.execute(
            "INSERT INTO product_spec (product_id, spec_name, spec_value) VALUES (%s, %s, %s)",
            (product_id, spec.spec_name, spec.spec_value),
        )
    return _specs(cur, product_id)


def _specs(cur, product_id: int) -> list:
    cur.execute(
        "SELECT spec_name, spec_value FROM product_spec WHERE product_id = %s ORDER BY spec_name",
        (product_id,),
    )
    return cur.fetchall()

"""The store report (R9: low stock, sales by category, return rate), plan §6 #4–#6, and who may read it.

Figure tests build their own store, category, products, orders and returns inside the test's transaction
(tests/reports_support.py) and run build_store_report on the same cursor, so every figure is exact and nothing is
committed. The concurrency tests at the end commit, on products of their own.
"""
from decimal import Decimal

from app.services.reports import build_store_report
from tests.reports_support import a_category, a_product, a_sale, a_store, cancel, collect


def report(cur, store_id: int, days: int = 30) -> dict:
    return build_store_report(cur, store_id, days)


def low_stock(cur, store_id: int, days: int = 30) -> dict:
    """The store's low-stock rows by product id, with only the columns these tests check."""
    return {row["product_id"]: (row["quantity"], row["sold_30d"], row["days_of_cover"])
            for row in report(cur, store_id, days)["low_stock"]}


def test_a_sale_is_a_paid_order_that_is_not_cancelled(cur):
    store_id, _ = a_store(cur)
    product_id = a_product(cur, a_category(cur), "25.00")
    paid = a_sale(cur, store_id, [(product_id, 3)])
    collected = a_sale(cur, store_id, [(product_id, 1)])
    collect(cur, collected)
    cancel(cur, a_sale(cur, store_id, [(product_id, 2)]))
    a_sale(cur, store_id, [(product_id, 4)], paid=False)              # still placed: not paid yet

    cur.execute(
        """
        SELECT order_id, line_no, store_id, product_id, quantity, unit_price, line_total
        FROM v_sale_line WHERE store_id = %s ORDER BY order_id
        """,
        (store_id,),
    )
    assert cur.fetchall() == [
        {"order_id": paid, "line_no": 1, "store_id": store_id, "product_id": product_id, "quantity": 3,
         "unit_price": Decimal("25.00"), "line_total": Decimal("75.00")},
        {"order_id": collected, "line_no": 1, "store_id": store_id, "product_id": product_id, "quantity": 1,
         "unit_price": Decimal("25.00"), "line_total": Decimal("25.00")},
    ]


# ---------------------------------------------------------------- low stock (plan §6 #4)

def test_low_stock_lists_what_is_down_to_three(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    three = a_product(cur, category_id, stock=3, store_id=store_id)
    a_product(cur, category_id, stock=4, store_id=store_id)                    # 4 left, not selling: fine
    assert low_stock(cur, store_id) == {three: (3, 0, None)}       # nothing sold: no days of cover to work out


def test_low_stock_lists_what_runs_out_within_14_days_at_the_last_30_days_rate(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    ten_days = a_product(cur, category_id, stock=10, store_id=store_id)        # 30 sold in 30 days: 1 a day
    fourteen_days = a_product(cur, category_id, stock=14, store_id=store_id)   # exactly 14 days: not yet low
    a_sale(cur, store_id, [(ten_days, 20)], days_ago=29)
    a_sale(cur, store_id, [(ten_days, 10), (fourteen_days, 30)])
    assert low_stock(cur, store_id) == {ten_days: (10, 30, Decimal("10.0"))}


def test_low_stock_sales_rate_uses_the_last_30_days_whatever_the_report_window(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    old_seller = a_product(cur, category_id, stock=10, store_id=store_id)
    recent_seller = a_product(cur, category_id, stock=10, store_id=store_id)
    a_sale(cur, store_id, [(old_seller, 30)], days_ago=31)                     # before the 30 days
    a_sale(cur, store_id, [(recent_seller, 30)], days_ago=29)
    assert low_stock(cur, store_id, days=90) == {recent_seller: (10, 30, Decimal("10.0"))}
    assert low_stock(cur, store_id, days=7) == {recent_seller: (10, 30, Decimal("10.0"))}


def test_low_stock_counts_only_sales_at_this_store_that_are_not_cancelled(cur):
    store_id, _ = a_store(cur)
    other_store, _ = a_store(cur)
    product_id = a_product(cur, a_category(cur), stock=10, store_id=store_id)
    a_sale(cur, other_store, [(product_id, 30)])
    cancel(cur, a_sale(cur, store_id, [(product_id, 30)]))
    assert low_stock(cur, store_id) == {}


def test_low_stock_skips_products_the_store_does_not_stock_and_retired_products(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    a_product(cur, category_id)                                                 # no inventory row here
    a_product(cur, category_id, stock=0, store_id=store_id, active=False)       # retired: not reordered
    assert low_stock(cur, store_id) == {}


def test_a_low_stock_row_names_the_product_and_its_category(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    product_id = a_product(cur, category_id, stock=1, store_id=store_id)
    cur.execute("SELECT p.sku, p.name, c.name AS category FROM product p JOIN category c USING (category_id) "
                "WHERE p.product_id = %s", (product_id,))
    expected = cur.fetchone()
    [row] = report(cur, store_id)["low_stock"]
    assert row == {"product_id": product_id, "sku": expected["sku"], "name": expected["name"],
                   "category": expected["category"], "quantity": 1, "sold_30d": 0, "days_of_cover": None}

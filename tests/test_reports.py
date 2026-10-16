"""The store report (R9: low stock, sales by category, return rate), plan §6 #4–#6, and who may read it.

Figure tests build their own store, category, products, orders and returns inside the test's transaction
(tests/reports_support.py) and run build_store_report on the same cursor, so every figure is exact and nothing is
committed. The concurrency tests at the end commit, on products of their own.
"""
from decimal import Decimal

from tests.reports_support import a_category, a_product, a_sale, a_store, cancel, collect


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

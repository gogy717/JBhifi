"""The store report (R9: low stock, sales by category, return rate), plan §6 #4–#6, and who may read it.

Figure tests build their own store, category, products, orders and returns inside the test's transaction
(tests/reports_support.py) and run build_store_report on the same cursor, so every figure is exact and nothing is
committed. The concurrency tests at the end commit, on products of their own.
"""
from decimal import Decimal

from app.services.reports import build_store_report
from tests.reports_support import a_category, a_product, a_return, a_sale, a_store, cancel, collect


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


# ---------------------------------------------------------------- sales by category

def category_sales(cur, store_id: int, days: int = 30) -> dict:
    return {row["category_id"]: row for row in report(cur, store_id, days)["sales_by_category"]}


def test_sales_by_category_adds_up_the_sales_in_the_window(cur):
    store_id, _ = a_store(cur)
    other_store, _ = a_store(cur)
    category_id = a_category(cur)
    speaker = a_product(cur, category_id, "25.00")
    cable = a_product(cur, category_id, "10.00")
    a_sale(cur, store_id, [(speaker, 2), (cable, 1)])                 # 60.00
    a_sale(cur, store_id, [(speaker, 1)], days_ago=29)                # 25.00
    a_sale(cur, store_id, [(cable, 3)], days_ago=31)                  # before the window
    a_sale(cur, other_store, [(cable, 5)])                            # another store's sale
    cancel(cur, a_sale(cur, store_id, [(speaker, 4)]))                # not a sale
    row = category_sales(cur, store_id)[category_id]
    assert (row["orders"], row["units"], row["revenue"]) == (2, 4, Decimal("85.00"))
    assert row["parent_category"] == "Audio"


def test_sales_by_category_follows_the_report_window(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    speaker = a_product(cur, category_id, "25.00")
    a_sale(cur, store_id, [(speaker, 1)], days_ago=5)
    a_sale(cur, store_id, [(speaker, 2)], days_ago=60)
    assert category_sales(cur, store_id, days=7)[category_id]["revenue"] == Decimal("25.00")
    assert category_sales(cur, store_id, days=90)[category_id]["revenue"] == Decimal("75.00")


def test_a_category_with_no_sales_shows_zero(cur):
    store_id, _ = a_store(cur)
    cur.execute("SELECT category_id FROM category WHERE name = 'Laptops'")
    laptops_id = cur.fetchone()["category_id"]
    laptops = category_sales(cur, store_id)[laptops_id]
    assert laptops == {"category_id": laptops_id, "category": "Laptops",
                       "parent_category": "Computers & Tablets", "orders": 0, "units": 0,
                       "revenue": Decimal("0.00")}
    assert str(laptops["revenue"]) == "0.00"


def test_an_order_in_two_categories_counts_once_in_the_total(cur):
    store_id, _ = a_store(cur)
    first, second = a_category(cur), a_category(cur)
    a_sale(cur, store_id, [(a_product(cur, first, "25.00"), 1), (a_product(cur, second, "10.00"), 2)])
    sales = report(cur, store_id)
    rows = {row["category_id"]: row for row in sales["sales_by_category"]}
    assert (rows[first]["orders"], rows[second]["orders"]) == (1, 1)
    assert sales["sales_total"] == {"orders": 1, "units": 3, "revenue": Decimal("45.00")}


# ---------------------------------------------------------------- return rate (plan §6 #6)

def rates(cur, store_id: int, days: int = 30) -> tuple[dict, dict]:
    """(by category id, by product id) → (sold, returned, rate)."""
    sections = report(cur, store_id, days)
    by_category = {row["category_id"]: (row["units_sold"], row["units_returned"], row["return_rate"])
                   for row in sections["return_rate_by_category"]}
    by_product = {row["product_id"]: (row["units_sold"], row["units_returned"], row["return_rate"])
                  for row in sections["return_rate_by_product"]}
    return by_category, by_product


def collected_sale(cur, store_id: int, items, **options) -> int:
    order_id = a_sale(cur, store_id, items, **options)
    collect(cur, order_id)
    return order_id


def test_return_rate_is_a_fraction_not_integer_division(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    speaker = a_product(cur, category_id)
    a_return(cur, collected_sale(cur, store_id, [(speaker, 4)]), [(1, 1)])
    by_category, by_product = rates(cur, store_id)
    assert by_category[category_id] == (4, 1, Decimal("0.2500"))
    assert by_product[speaker] == (4, 1, Decimal("0.2500"))


def test_return_rate_counts_a_line_with_two_partial_returns_once(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    speaker = a_product(cur, category_id)
    order_id = collected_sale(cur, store_id, [(speaker, 4)])
    a_return(cur, order_id, [(1, 1)])
    a_return(cur, order_id, [(1, 1)])
    by_category, by_product = rates(cur, store_id)
    assert by_category[category_id] == (4, 2, Decimal("0.5000"))      # joined before summing: 8 sold
    assert by_product[speaker] == (4, 2, Decimal("0.5000"))


def test_return_rate_ignores_rejected_returns_without_dropping_unreturned_sales(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    speaker = a_product(cur, category_id)
    a_return(cur, collected_sale(cur, store_id, [(speaker, 2)]), [(1, 1)], status="rejected")
    collected_sale(cur, store_id, [(speaker, 2)])                     # never returned
    a_return(cur, collected_sale(cur, store_id, [(speaker, 1)]), [(1, 1)], status="received")
    by_category, by_product = rates(cur, store_id)
    # Filtering `status <> 'rejected'` in the outer WHERE would leave only the received line: 1 sold, 1 back.
    assert by_category[category_id] == (5, 1, Decimal("0.2000"))
    assert by_product[speaker] == (5, 1, Decimal("0.2000"))


def test_return_rate_is_zero_when_nothing_came_back_and_null_when_nothing_sold(cur):
    store_id, _ = a_store(cur)
    sold, unsold = a_category(cur), a_category(cur)
    speaker = a_product(cur, sold)
    a_product(cur, unsold)
    collected_sale(cur, store_id, [(speaker, 3)])
    by_category, by_product = rates(cur, store_id)
    assert by_category[sold] == (3, 0, Decimal("0.0000"))
    assert by_category[unsold] == (0, 0, None)
    assert set(by_product) == {speaker}                               # only products sold in the window


def test_return_rate_is_over_the_units_sold_in_the_window(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    speaker = a_product(cur, category_id)
    a_return(cur, collected_sale(cur, store_id, [(speaker, 2)], days_ago=40), [(1, 2)])  # sold before the window
    a_return(cur, collected_sale(cur, store_id, [(speaker, 4)]), [(1, 1)])
    assert rates(cur, store_id)[0][category_id] == (4, 1, Decimal("0.2500"))
    assert rates(cur, store_id, days=90)[0][category_id] == (6, 3, Decimal("0.5000"))


def test_a_return_counts_for_the_store_that_sold_the_item_not_the_one_that_received_it(cur):
    store_id, _ = a_store(cur)
    other_store, other_manager = a_store(cur)
    category_id = a_category(cur)
    speaker = a_product(cur, category_id)
    order_id = collected_sale(cur, store_id, [(speaker, 2)])
    a_return(cur, order_id, [(1, 1)], status="received", at_store=(other_store, other_manager))
    assert rates(cur, store_id)[1][speaker] == (2, 1, Decimal("0.5000"))
    assert rates(cur, other_store)[0][category_id] == (0, 0, None)


def test_products_are_listed_by_return_rate(cur):
    store_id, _ = a_store(cur)
    category_id = a_category(cur)
    never, half, all_back = (a_product(cur, category_id) for _ in range(3))
    collected_sale(cur, store_id, [(never, 2)])
    a_return(cur, collected_sale(cur, store_id, [(half, 2)]), [(1, 1)])
    a_return(cur, collected_sale(cur, store_id, [(all_back, 1)]), [(1, 1)])
    assert list(rates(cur, store_id)[1]) == [all_back, half, never]

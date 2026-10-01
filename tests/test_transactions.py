"""Stock adjustment as a transaction (BR03, BR18): all-or-nothing, and safe when requests race.

Each "request" here is what the API does: its own connection, one transaction, commit or roll back.
These tests commit, so each one works on a product it creates for itself.
"""
import psycopg2
import pytest

from app.services.inventory import adjust_stock
from tests.support import connect, run_at_once, unique_sku

SYDNEY_CBD = 1
AIDEN = 14          # works at Sydney CBD
ISLA = 16           # works at Bondi Junction


@pytest.fixture
def fresh_stock():
    """fresh_stock(quantity) → id of a new product holding `quantity` units at Sydney CBD (committed)."""
    def make(quantity: int) -> int:
        conn = connect()
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO product (sku, name, brand_id, category_id, base_price)
                SELECT %s, 'Transaction test item', b.brand_id, c.category_id, 10.00
                FROM brand b, category c
                WHERE b.name = 'JBL' AND c.name = 'Speakers'
                RETURNING product_id
                """,
                (unique_sku(),),
            )
            product_id = cur.fetchone()["product_id"]
            cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                        (SYDNEY_CBD, product_id, quantity))
        conn.close()
        return product_id
    return make


def request_adjustment(product_id, staff_id, delta, reason):
    """One API request: a transaction that commits if adjust_stock succeeds, and rolls back if it raises."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            return adjust_stock(cur, SYDNEY_CBD, product_id, staff_id, delta, reason, None)
    finally:
        conn.close()


def stock_and_log(product_id):
    """(quantity at Sydney CBD, number of logged adjustments), as committed."""
    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
                    (SYDNEY_CBD, product_id))
        quantity = cur.fetchone()["quantity"]
        cur.execute("SELECT count(*) AS n FROM stock_adjustment WHERE product_id = %s", (product_id,))
        logged = cur.fetchone()["n"]
    conn.close()
    return quantity, logged


def test_a_rejected_log_row_rolls_back_the_stock_change(fresh_stock):
    item = fresh_stock(5)
    with pytest.raises(psycopg2.errors.ForeignKeyViolation) as caught:
        request_adjustment(item, ISLA, 3, "received")
    assert caught.value.diag.constraint_name == "br18_adjustment_staff_at_store"
    # The UPDATE had already added 3 when the INSERT into the log failed; the rollback undid both.
    assert stock_and_log(item) == (5, 0)


def test_cannot_remove_more_than_is_on_hand(fresh_stock):
    item = fresh_stock(2)
    with pytest.raises(psycopg2.errors.CheckViolation) as caught:
        request_adjustment(item, AIDEN, -3, "damaged")
    assert caught.value.diag.constraint_name == "br03_inventory_qty_nonneg"
    assert stock_and_log(item) == (2, 0)


def test_concurrent_adjustments_lose_no_update(fresh_stock):
    item = fresh_stock(5)
    results = run_at_once(10, lambda: request_adjustment(item, AIDEN, 1, "received"))
    assert all(isinstance(result, dict) for result in results), results
    # Each transaction queued on the row lock and added 1 to the previous one's committed result,
    # so between them they saw every quantity from 6 to 15 exactly once.
    assert sorted(result["quantity_after"] for result in results) == list(range(6, 16))
    assert stock_and_log(item) == (15, 10)


def test_concurrent_removals_never_oversell(fresh_stock):
    item = fresh_stock(3)
    results = run_at_once(8, lambda: request_adjustment(item, AIDEN, -1, "damaged"))
    succeeded = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, psycopg2.errors.CheckViolation)]
    assert (len(succeeded), len(refused)) == (3, 5), results
    assert {error.diag.constraint_name for error in refused} == {"br03_inventory_qty_nonneg"}
    assert stock_and_log(item) == (0, 3)

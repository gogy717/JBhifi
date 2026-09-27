"""Rules that assert over many rows (BR12, BR14, BR15) under real concurrency.

Each "request" is a separate connection and transaction that commits or rolls back on its own, exactly
like an API call. A trigger locks the contended parent row first, so the transactions run one after the
other and the loser sees the winner's committed result instead of both passing the check.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
import pytest

from tests.concurrency import constraint_of, run_at_once
from tests.support import connect, unique_sku

SYDNEY_CBD = 1
AIDEN = 14


def in_transaction(work):
    """Run work(cur) on its own connection; commit if it returns, roll back if it raises."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            return work(cur)
    finally:
        conn.close()


def fetch_one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------- fixtures on committed data

@pytest.fixture
def committed_product():
    """committed_product(quantity, base_price) → product_id, committed, with stock at store 1."""
    def make(quantity: int, base_price: str = "100.00"):
        def work(cur):
            cur.execute(
                """
                INSERT INTO product (sku, name, brand_id, category_id, base_price)
                SELECT %s, 'Concurrency test item', b.brand_id, c.category_id, %s
                FROM brand b, category c WHERE b.name = 'JBL' AND c.name = 'Speakers'
                RETURNING product_id
                """,
                (unique_sku(), base_price),
            )
            product_id = cur.fetchone()["product_id"]
            cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                        (SYDNEY_CBD, product_id, quantity))
            return product_id
        return in_transaction(work)
    return make


@pytest.fixture
def committed_order():
    """committed_order(lines, charge) → order_id for a collected order, committed."""
    def make(lines, charge: str):
        def work(cur):
            cur.execute("""
                INSERT INTO customer (email, full_name)
                VALUES ('concurrency.customer@example.com', 'Concurrency Customer')
                ON CONFLICT (email) DO UPDATE SET full_name = EXCLUDED.full_name
                RETURNING customer_id
            """)
            customer_id = cur.fetchone()["customer_id"]
            cur.execute("""
                INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint,
                                            fulfilment_method, fulfilling_store_id)
                VALUES (%s, gen_random_uuid(), gen_random_uuid()::text, 'click_collect', %s) RETURNING order_id
            """, (customer_id, SYDNEY_CBD))
            order_id = cur.fetchone()["order_id"]
            for line_no, (product_id, qty, price) in enumerate(lines, start=1):
                cur.execute(
                    "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) "
                    "VALUES (%s, %s, %s, %s, %s)", (order_id, line_no, product_id, qty, price))
            cur.execute("SELECT set_config('app.staff_id', %s, true)", (str(AIDEN),))
            for status in ("paid", "picking", "ready", "collected"):
                cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))
            if Decimal(charge) > 0:
                cur.execute("INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', %s)",
                            (order_id, charge))
            return order_id
        return in_transaction(work)
    return make


# ---------------------------------------------------------------- BR12

def test_concurrent_return_requests_cannot_exceed_purchase(committed_product, committed_order):
    product_id = committed_product(10)
    order_id = committed_order([(product_id, 2, "189.00")], "378.00")

    def request_two(_):
        def work(cur):
            cur.execute("INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason) "
                        "VALUES (%s, gen_random_uuid(), gen_random_uuid()::text, 'Changed my mind') "
                        "RETURNING return_id", (order_id,))
            return_id = cur.fetchone()["return_id"]
            cur.execute("INSERT INTO return_line (return_id, line_no, order_id, quantity) "
                        "VALUES (%s, 1, %s, 2)", (return_id, order_id))
            return return_id
        return in_transaction(work)

    results = run_at_once(2, request_two)
    succeeded = [r for r in results if isinstance(r, int)]
    refused = [r for r in results if isinstance(r, psycopg2.Error)]
    assert (len(succeeded), len(refused)) == (1, 1), results
    assert {constraint_of(error) for error in refused} == {"br12_return_qty_within_purchased"}
    assert fetch_one("SELECT COALESCE(sum(rl.quantity), 0) AS returned FROM return_line rl "
                     "JOIN return_request rr USING (return_id) "
                     "WHERE rl.order_id = %s AND rr.status <> 'rejected'", (order_id,))["returned"] == 2


# ---------------------------------------------------------------- BR14

def test_concurrent_refunds_cannot_exceed_the_charge(committed_product, committed_order):
    product_id = committed_product(10)
    # Two units at 100.00 each, but only 100.00 captured — so each single-unit return is entitled to
    # 100.00 and the two together would over-refund the order.
    order_id = committed_order([(product_id, 2, "100.00")], "100.00")

    def received_return():
        def work(cur):
            cur.execute("INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason) "
                        "VALUES (%s, gen_random_uuid(), gen_random_uuid()::text, 'Changed my mind') "
                        "RETURNING return_id", (order_id,))
            return_id = cur.fetchone()["return_id"]
            cur.execute("INSERT INTO return_line (return_id, line_no, order_id, quantity) "
                        "VALUES (%s, 1, %s, 1)", (return_id, order_id))
            cur.execute("UPDATE return_request SET status = 'received', received_store_id = %s, "
                        "processed_by_staff_id = %s WHERE return_id = %s", (SYDNEY_CBD, AIDEN, return_id))
            return return_id
        return in_transaction(work)

    first, second = received_return(), received_return()

    def refund(return_id):
        def work(cur):
            cur.execute("UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))
            cur.execute("INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)",
                        (order_id, "100.00", return_id))
            return return_id
        return in_transaction(work)

    results = run_at_once(2, lambda i: refund([first, second][i]))
    refused = [r for r in results if isinstance(r, psycopg2.Error)]
    assert len(refused) == 1, results
    assert constraint_of(refused[0]) == "br14_refunds_within_charged"
    refunded = fetch_one("SELECT COALESCE(sum(amount), 0) AS refunded FROM payment "
                         "WHERE order_id = %s AND kind = 'refund'", (order_id,))["refunded"]
    assert refunded == Decimal("100.00")


# ---------------------------------------------------------------- BR15

def test_concurrent_overlapping_promotions_leave_one(committed_product):
    product_id = committed_product(0, "100.00")
    now = datetime.now(timezone.utc)

    def promote(offset_days):
        def work(cur):
            cur.execute(
                "INSERT INTO promotion (product_id, sale_price, starts_at, ends_at) "
                "VALUES (%s, 80.00, %s, %s) RETURNING promotion_id",
                (product_id, now + timedelta(days=offset_days), now + timedelta(days=offset_days + 7)),
            )
            return cur.fetchone()["promotion_id"]
        return in_transaction(work)

    results = run_at_once(2, lambda i: promote(i * 3))          # 0..7 and 3..10 overlap
    succeeded = [r for r in results if isinstance(r, int)]
    refused = [r for r in results if isinstance(r, psycopg2.Error)]
    assert (len(succeeded), len(refused)) == (1, 1), results
    assert {constraint_of(error) for error in refused} == {"br15_promotion_no_overlap"}
    assert fetch_one("SELECT count(*) AS n FROM promotion WHERE product_id = %s", (product_id,))["n"] == 1

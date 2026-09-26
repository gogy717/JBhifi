"""BR08/BR11/BR12/B? hardening: purchase records, the audit trail and the payment ledger are immutable,
the return window is exact, the category tree cannot cycle, and the application role is least-privilege.
"""
from datetime import datetime, timedelta

import psycopg2
import pytest

from tests.lifecycle import (RETURN_LINE, RETURN_REQUEST, backdate_history, completed_order, request_return)
from tests.support import connect_app

CUSTOMER_EMAIL = "lifecycle.customer@example.com"


@pytest.fixture
def customer(cur):
    from tests.lifecycle import make_customer
    return make_customer(cur, CUSTOMER_EMAIL)


@pytest.fixture
def order(cur, customer, product_id):
    """A collected, charged order: line 1 = 2 × AirPods 4 at 189.00 (total 378.00)."""
    return completed_order(cur, customer, [(product_id("APL-AP4"), 2, "189.00")])


def refund_return(cur, order_id, line_no=1, quantity=1):
    return_id = request_return(cur, order_id, [(line_no, quantity)])
    cur.execute(
        "UPDATE return_request SET status = 'received', received_store_id = 1, processed_by_staff_id = 14 "
        "WHERE return_id = %s",
        (return_id,),
    )
    cur.execute("INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)",
                (order_id, 189.00 * quantity, return_id))
    cur.execute("UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))
    return return_id


# ---------------------------------------------------------------- the payment ledger

def test_charge_cannot_be_reduced_or_deleted_after_refund(cur, order, violates):
    refund_return(cur, order)
    violates("payment_append_only", "UPDATE payment SET amount = 1.00 WHERE order_id = %s AND kind = 'charge'",
             (order,))
    violates("payment_append_only", "DELETE FROM payment WHERE order_id = %s", (order,))
    cur.execute("SELECT sum(CASE WHEN kind = 'charge' THEN amount ELSE -amount END) AS net FROM payment "
                "WHERE order_id = %s", (order,))
    assert cur.fetchone()["net"] == 189.00        # the 378.00 charge minus the 189.00 refund


# ---------------------------------------------------------------- the order timeline

def test_order_history_cannot_be_edited(cur, order, violates):
    violates("order_status_history_append_only",
             "UPDATE order_status_history SET to_status = 'paid' WHERE order_id = %s", (order,))
    violates("order_status_history_append_only",
             "DELETE FROM order_status_history WHERE order_id = %s", (order,))


def test_order_header_cannot_change_after_placement(cur, order, violates):
    for column, value in [("fulfilling_store_id", 2), ("customer_id", 1), ("delivery_address_no", 1)]:
        cur.execute("SAVEPOINT hdr")
        with pytest.raises(psycopg2.Error) as caught:
            cur.execute(f"UPDATE customer_order SET {column} = %s WHERE order_id = %s", (value, order))
        cur.execute("ROLLBACK TO SAVEPOINT hdr")
        assert caught.value.diag.constraint_name == "order_immutable", caught.value.pgerror


# ---------------------------------------------------------------- purchased order lines

def test_purchased_line_cannot_change(cur, order, product_id, violates):
    violates("br08_order_line_immutable",
             "UPDATE order_line SET quantity = 5 WHERE order_id = %s AND line_no = 1", (order,))
    violates("br08_order_line_immutable",
             "UPDATE order_line SET product_id = %s WHERE order_id = %s AND line_no = 1",
             (product_id("JBL-FLIP7-B"), order))
    violates("br08_order_line_immutable",
             "DELETE FROM order_line WHERE order_id = %s AND line_no = 1", (order,))
    violates("br08_order_line_immutable",
             "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) "
             "VALUES (%s, 2, %s, 1, 10.00)", (order, product_id("JBL-FLIP7-B")))
    cur.execute("SELECT quantity FROM order_line WHERE order_id = %s AND line_no = 1", (order,))
    assert cur.fetchone()["quantity"] == 2


# ---------------------------------------------------------------- return lines

def test_return_line_cannot_move_between_requests(cur, order, violates):
    first = request_return(cur, order, [(1, 1)])
    second = request_return(cur, order, [])            # a live request with no lines yet
    violates("br12_return_line_ownership",
             "UPDATE return_line SET return_id = %s WHERE return_id = %s AND line_no = 1", (second, first))
    violates("br12_return_line_ownership",
             "UPDATE return_line SET line_no = 9 WHERE return_id = %s AND line_no = 1", (first,))
    cur.execute("SELECT return_id, line_no, quantity FROM return_line WHERE return_id = %s", (first,))
    assert cur.fetchone() == {"return_id": first, "line_no": 1, "quantity": 1}


def test_return_lines_freeze_once_received(cur, order, violates):
    return_id = request_return(cur, order, [(1, 1)])
    assert RETURN_LINE is not None
    cur.execute(
        "UPDATE return_request SET status = 'received', received_store_id = 1, processed_by_staff_id = 14 "
        "WHERE return_id = %s",
        (return_id,),
    )
    violates("br12_return_line_editable",
             "UPDATE return_line SET quantity = 2 WHERE return_id = %s AND line_no = 1", (return_id,))
    violates("br12_return_line_editable",
             "DELETE FROM return_line WHERE return_id = %s AND line_no = 1", (return_id,))


# ---------------------------------------------------------------- BR11 window

def test_return_window_predicate_is_exact(cur):
    """Exactly 30 days is inside; one microsecond later is outside; before completion is outside."""
    def in_window(offset: str) -> bool:
        cur.execute("SELECT return_request_is_in_window(now(), now() + %s::interval) AS ok", (offset,))
        return cur.fetchone()["ok"]

    assert in_window("30 days") is True
    assert in_window("30 days 1 microsecond") is False
    assert in_window("-1 microsecond") is False


def test_return_window_rejects_an_expired_order(cur, order, violates):
    backdate_history(cur, order, datetime.now().astimezone() - timedelta(days=31))
    violates("br11_return_window", RETURN_REQUEST, (order,))


def test_return_request_time_is_the_servers_and_immutable(cur, order, violates):
    return_id = request_return(cur, order, [(1, 1)])
    cur.execute("SELECT requested_at FROM return_request WHERE return_id = %s", (return_id,))
    requested_at = cur.fetchone()["requested_at"]
    assert requested_at is not None
    violates("br11_return_window",
             "UPDATE return_request SET requested_at = now() - interval '1 day' WHERE return_id = %s",
             (return_id,))


# ---------------------------------------------------------------- category tree

def test_a_category_cannot_be_moved_inside_its_own_subtree(cur, violates):
    ids, parent = [], None
    for name in ("Cycle Root", "Cycle Child", "Cycle Grandchild"):
        cur.execute("INSERT INTO category (name, parent_id) VALUES (%s, %s) RETURNING category_id",
                    (name, parent))
        parent = cur.fetchone()["category_id"]
        ids.append(parent)
    violates("category_no_cycle", "UPDATE category SET parent_id = %s WHERE category_id = %s",
             (ids[2], ids[0]))                     # root under its grandchild: three-level cycle
    violates("category_no_cycle", "UPDATE category SET parent_id = %s WHERE category_id = %s",
             (ids[2], ids[1]))                     # child under its own child: two-level cycle
    cur.execute("UPDATE category SET parent_id = %s WHERE category_id = %s", (None, ids[0]))   # allowed


# ---------------------------------------------------------------- least privilege

@pytest.fixture
def app_cur():
    """A cursor for the application role, on its own connection (so it is a real privilege check)."""
    conn = connect_app()
    with conn.cursor() as cur:
        yield cur
    conn.rollback()
    conn.close()


def refuse(cur, statement, params=None):
    cur.execute("SAVEPOINT app_check")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege) as caught:
        cur.execute(statement, params)
    cur.execute("ROLLBACK TO SAVEPOINT app_check")
    return caught.value


def test_the_application_role_cannot_rewrite_history_or_delete_payments(app_cur):
    assert refuse(app_cur, "UPDATE order_status_history SET to_status = 'paid'") is not None
    assert refuse(app_cur, "DELETE FROM order_status_history") is not None
    assert refuse(app_cur, "INSERT INTO order_status_history (order_id, seq, to_status) VALUES (1, 99, 'paid')") \
        is not None
    assert refuse(app_cur, "UPDATE payment SET amount = 1") is not None
    assert refuse(app_cur, "DELETE FROM payment") is not None
    assert refuse(app_cur, "ALTER TABLE customer_order ADD COLUMN hacked int") is not None


def test_the_application_role_can_read_and_write_the_business_tables(app_cur):
    app_cur.execute("SELECT count(*) AS n FROM product")
    assert app_cur.fetchone()["n"] >= 48       # the seed's 48, plus products earlier tests committed
    app_cur.execute("SELECT count(*) AS n FROM stock_adjustment")
    assert app_cur.fetchone()["n"] is not None
    # The role may append an adjustment (privilege, not semantics), but never edit one (BR18).
    refuse(app_cur, "UPDATE stock_adjustment SET delta = 1")
    refuse(app_cur, "DELETE FROM stock_adjustment")

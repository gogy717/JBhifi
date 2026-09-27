"""T03: idempotency columns, the cancellation source, the return audit trail, and the deferred
completeness checks that stop a half-finished financial state from committing.

The commit-time cases run on their own connection: the transaction is built normally and then committed,
so a rule that only fires at COMMIT is observed exactly as the API would see it.
"""
import uuid

import psycopg2
import pytest

from tests.support import connect


def attempt_commit(work):
    """Build work(cur) on its own connection and commit. Return the error, or None on success."""
    conn = connect()
    try:
        with conn:
            with conn.cursor() as cur:
                work(cur)
        return None
    except psycopg2.Error as error:
        return error
    finally:
        conn.close()


def constraint_name(error) -> str | None:
    return None if error is None else error.diag.constraint_name


def new_customer(cur, email=None) -> int:
    cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Schema Test') RETURNING customer_id",
                (email or f"schema.{uuid.uuid4().hex[:8]}@example.com",))
    return cur.fetchone()["customer_id"]


def sku_id(cur, sku) -> int:
    cur.execute("SELECT product_id FROM product WHERE sku = %s", (sku,))
    return cur.fetchone()["product_id"]


def new_order(cur, lines, charge=None, *, statuses=(), method="click_collect", store_id=1, staff_id=14):
    """A customer_order with lines = [(product_id, quantity, unit_price)]; optionally charged/advanced."""
    customer_id = new_customer(cur)
    key = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint, fulfilment_method, "
        "fulfilling_store_id) VALUES (%s, %s, %s, %s, %s) RETURNING order_id",
        (customer_id, key, f"fingerprint:{key}", method, store_id),
    )
    order_id = cur.fetchone()["order_id"]
    for line_no, (product_id, quantity, unit_price) in enumerate(lines, start=1):
        cur.execute("INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) "
                    "VALUES (%s, %s, %s, %s, %s)", (order_id, line_no, product_id, quantity, unit_price))
    if charge is not None:
        cur.execute("INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', %s)", (order_id, charge))
    if statuses:
        cur.execute("SELECT set_config('app.staff_id', %s, true)", (str(staff_id),))
        for status in statuses:
            cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))
    return order_id, customer_id


def new_return(cur, order_id, lines, key=None):
    key = str(key or uuid.uuid4())
    cur.execute("INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason) "
                "VALUES (%s, %s, %s, 'Changed my mind') RETURNING return_id",
                (order_id, key, f"fingerprint:{key}"))
    return_id = cur.fetchone()["return_id"]
    for line_no, quantity in lines:
        cur.execute("INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, %s, %s, %s)",
                    (return_id, line_no, order_id, quantity))
    return return_id


def receive(cur, return_id, store_id=1, staff_id=14):
    cur.execute("UPDATE return_request SET status = 'received', received_store_id = %s, "
                "processed_by_staff_id = %s WHERE return_id = %s", (store_id, staff_id, return_id))


def act_as(cur, staff_id):
    """Model who the next write is: '' is the customer or the system, a number is that staff member."""
    cur.execute("SELECT set_config('app.staff_id', %s, true)", ("" if staff_id is None else str(staff_id),))


def collected_order(cur, quantity=2, price="189.00", charge="378.00"):
    return new_order(cur, [(sku_id(cur, "APL-AP4"), quantity, price)], charge,
                     statuses=("paid", "picking", "ready", "collected"))


# ---------------------------------------------------------------- idempotency keys

def test_return_request_key_is_unique_per_order(cur, violates):
    order_id, _ = collected_order(cur)
    other_order, _ = collected_order(cur)
    key = str(uuid.uuid4())
    new_return(cur, order_id, [(1, 1)], key=key)
    insert = ("INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason) "
              "VALUES (%s, %s, 'same-request', 'Changed my mind')")
    violates("return_idempotency_unique", insert, (order_id, key))
    # The same key on a different order is a different request, so it is allowed.
    new_return(cur, other_order, [], key=key)


# ---------------------------------------------------------------- refund sources

def test_refund_requires_exactly_one_source(cur, violates):
    order_id, _ = collected_order(cur)
    return_id = new_return(cur, order_id, [(1, 1)])
    receive(cur, return_id)
    cur.execute("INSERT INTO order_cancellation (order_id, reason) "
                "SELECT order_id, 'fixture' FROM customer_order WHERE order_id = %s RETURNING cancellation_id",
                (order_id,))
    cancellation_id = cur.fetchone()["cancellation_id"]
    insert = "INSERT INTO payment (order_id, kind, amount, return_id, cancellation_id) VALUES (%s,'refund',%s,%s,%s)"
    violates("br14_refund_has_source", insert, (order_id, "189.00", None, None))
    violates("br14_refund_has_source", insert, (order_id, "189.00", return_id, cancellation_id))


def test_a_refund_must_match_its_return(cur, violates):
    order_id, _ = collected_order(cur)
    return_id = new_return(cur, order_id, [(1, 1)])
    receive(cur, return_id)
    insert = "INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)"
    violates("br14_refund_matches_source", insert, (order_id, "100.00", return_id))   # one AirPods = 189.00
    cur.execute(insert, (order_id, "189.00", return_id))                             # exact price is accepted


# ---------------------------------------------------------------- cancellation refunds

def test_cancellation_refund_matches_order(cur, violates):
    order_id, _ = new_order(cur, [(sku_id(cur, "APL-AP4"), 1, "189.00")], "189.00")
    cur.execute("INSERT INTO order_cancellation (order_id, reason) VALUES (%s, 'Customer changed their mind') "
                "RETURNING cancellation_id", (order_id,))
    cancellation_id = cur.fetchone()["cancellation_id"]
    cur.execute("SELECT set_config('app.staff_id', '14', true)")
    cur.execute("UPDATE customer_order SET status = 'cancelled' WHERE order_id = %s", (order_id,))
    insert = "INSERT INTO payment (order_id, kind, amount, cancellation_id) VALUES (%s, 'refund', %s, %s)"
    violates("br14_refund_matches_source", insert, (order_id, "100.00", cancellation_id))
    cur.execute(insert, (order_id, "189.00", cancellation_id))
    cur.execute("SELECT sum(CASE WHEN kind='charge' THEN amount ELSE -amount END) AS net "
                "FROM payment WHERE order_id = %s", (order_id,))
    assert cur.fetchone()["net"] == 0            # fully refunded


def test_refund_once_per_cancellation(cur, violates):
    order_id, _ = new_order(cur, [(sku_id(cur, "APL-AP4"), 1, "189.00")], "189.00")
    cur.execute("INSERT INTO order_cancellation (order_id, reason) VALUES (%s, 'Customer changed their mind') "
                "RETURNING cancellation_id", (order_id,))
    cancellation_id = cur.fetchone()["cancellation_id"]
    cur.execute("SELECT set_config('app.staff_id', '14', true)")
    cur.execute("UPDATE customer_order SET status = 'cancelled' WHERE order_id = %s", (order_id,))
    insert = "INSERT INTO payment (order_id, kind, amount, cancellation_id) VALUES (%s, 'refund', %s, %s)"
    cur.execute(insert, (order_id, "189.00", cancellation_id))
    # A second charge lifts the ceiling so the unique-per-cancellation rule is the one reported.
    cur.execute("INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', '189.00')", (order_id,))
    violates("br14_refund_once_per_cancellation", insert, (order_id, "189.00", cancellation_id))


# ---------------------------------------------------------------- return audit trail

def test_return_status_history_records_every_change_with_its_actor(cur, violates):
    order_id, _ = collected_order(cur)
    act_as(cur, None)                          # the customer requests the return
    return_id = new_return(cur, order_id, [(1, 1)])
    act_as(cur, 14)                            # staff at the receiving store
    receive(cur, return_id)
    act_as(cur, 14)
    cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (return_id,))
    cur.execute("SELECT from_status, to_status, changed_by_staff_id FROM return_status_history "
                "WHERE return_id = %s ORDER BY seq", (return_id,))
    assert [tuple(row.values()) for row in cur.fetchall()] == [
        (None, "requested", None),
        ("requested", "received", 14),
        ("received", "rejected", 14),
    ]


def test_return_status_history_is_append_only(cur, violates):
    order_id, _ = collected_order(cur)
    return_id = new_return(cur, order_id, [(1, 1)])
    violates("return_status_history_append_only",
             "UPDATE return_status_history SET to_status = 'refunded' WHERE return_id = %s", (return_id,))
    violates("return_status_history_append_only",
             "DELETE FROM return_status_history WHERE return_id = %s", (return_id,))


def test_a_terminal_retry_adds_no_history(cur):
    order_id, _ = collected_order(cur)
    return_id = new_return(cur, order_id, [(1, 1)])
    receive(cur, return_id)
    cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (return_id,))
    cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (return_id,))
    cur.execute("SELECT count(*) AS n FROM return_status_history WHERE return_id = %s", (return_id,))
    assert cur.fetchone()["n"] == 3            # requested, received, rejected — the repeat added nothing


# ---------------------------------------------------------------- deferred completeness (COMMIT)

def test_a_refunded_return_without_its_refund_cannot_commit():
    def work(cur):
        order_id, _ = collected_order(cur)
        return_id = new_return(cur, order_id, [(1, 1)])
        receive(cur, return_id)
        cur.execute("UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))

    assert constraint_name(attempt_commit(work)) == "br14_source_complete"


def test_a_refund_for_a_return_that_never_completed_cannot_commit():
    def work(cur):
        order_id, _ = collected_order(cur)
        return_id = new_return(cur, order_id, [(1, 1)])
        receive(cur, return_id)
        cur.execute("INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)",
                    (order_id, "189.00", return_id))       # return is still 'received', not 'refunded'

    assert constraint_name(attempt_commit(work)) == "br14_source_complete"


def test_a_zero_value_refunded_return_needs_no_payment():
    def work(cur):
        order_id, _ = collected_order(cur, quantity=1, price="0.00", charge=None)   # nothing was charged
        return_id = new_return(cur, order_id, [(1, 1)])
        receive(cur, return_id)
        cur.execute("UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))

    assert attempt_commit(work) is None            # no charge, no refund, but the return still completes


def test_a_cancelled_order_needs_its_cancellation_record():
    def work(cur):
        order_id, _ = new_order(cur, [(sku_id(cur, "APL-AP4"), 1, "189.00")], "189.00")
        cur.execute("SELECT set_config('app.staff_id', '14', true)")
        cur.execute("UPDATE customer_order SET status = 'cancelled' WHERE order_id = %s", (order_id,))

    assert constraint_name(attempt_commit(work)) == "br14_source_complete"


def test_a_cancelled_order_needs_its_refund():
    def work(cur):
        order_id, _ = new_order(cur, [(sku_id(cur, "APL-AP4"), 1, "189.00")], "189.00")
        cur.execute("INSERT INTO order_cancellation (order_id, reason) VALUES (%s, 'Changed their mind')",
                    (order_id,))
        cur.execute("SELECT set_config('app.staff_id', '14', true)")
        cur.execute("UPDATE customer_order SET status = 'cancelled' WHERE order_id = %s", (order_id,))

    assert constraint_name(attempt_commit(work)) == "br14_source_complete"


def test_a_complete_cancellation_commits():
    def work(cur):
        order_id, _ = new_order(cur, [(sku_id(cur, "APL-AP4"), 1, "189.00")], "189.00")
        cur.execute("INSERT INTO order_cancellation (order_id, reason, cancelled_by_staff_id) "
                    "VALUES (%s, 'Changed their mind', 14) RETURNING cancellation_id", (order_id,))
        cancellation_id = cur.fetchone()["cancellation_id"]
        cur.execute("SELECT set_config('app.staff_id', '14', true)")
        cur.execute("UPDATE customer_order SET status = 'cancelled' WHERE order_id = %s", (order_id,))
        cur.execute("INSERT INTO payment (order_id, kind, amount, cancellation_id) "
                    "VALUES (%s, 'refund', '189.00', %s)", (order_id, cancellation_id))

    assert attempt_commit(work) is None

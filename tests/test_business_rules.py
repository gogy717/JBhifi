"""One test (or more) per business rule in plan §3: break the rule, and assert which named constraint
stopped it. Those names are the error codes the API returns, so this file doubles as the
rule → mechanism table for the report appendix.
"""
import uuid
from datetime import datetime, timezone

import pytest
from psycopg2 import sql

# ---------------------------------------------------------------- helpers


def make_customer(cur, email: str, with_address: bool = True) -> int:
    cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Test Customer') RETURNING customer_id",
                (email,))
    customer_id = cur.fetchone()["customer_id"]
    if with_address:
        cur.execute(
            """
            INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
            VALUES (%s, 1, '1 George St', 'Sydney', 'NSW', '2000')
            """,
            (customer_id,),
        )
    return customer_id


def place_order(cur, customer_id, lines, method="click_collect", store_id=1, address_no=None) -> int:
    """Insert an order and its lines; lines = [(product_id, quantity, unit_price), ...]."""
    cur.execute(
        """
        INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id,
                                    delivery_address_no)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING order_id
        """,
        (customer_id, str(uuid.uuid4()), method, store_id, address_no),
    )
    order_id = cur.fetchone()["order_id"]
    for line_no, (product_id, quantity, unit_price) in enumerate(lines, start=1):
        cur.execute(
            "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s, %s)",
            (order_id, line_no, product_id, quantity, unit_price),
        )
    return order_id


def advance(cur, order_id, *statuses, staff_id=None):
    """Move an order through the statuses in turn, acting as staff_id (None = the customer or system)."""
    cur.execute("SELECT set_config('app.staff_id', %s, true)", ("" if staff_id is None else str(staff_id),))
    for status in statuses:
        cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))


def pay(cur, order_id):
    """Charge the order its total, then move it to paid, as checkout does (BR20). Nothing due: no charge row."""
    cur.execute(
        """
        INSERT INTO payment (order_id, kind, amount)
        SELECT order_id, 'charge', total FROM v_order_total WHERE order_id = %s AND total > 0
        """,
        (order_id,),
    )
    advance(cur, order_id, "paid")


RETURN_REQUEST = """
    INSERT INTO return_request (order_id, idempotency_key, reason, requested_at)
    VALUES (%s, gen_random_uuid(), 'Changed my mind', now() + %s * interval '1 day')
    RETURNING return_id
"""
RETURN_LINE = "INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, %s, %s, %s)"


def request_return(cur, order_id, lines, days_from_now=0) -> int:
    """A return of lines = [(line_no, quantity), ...]."""
    cur.execute(RETURN_REQUEST, (order_id, days_from_now))
    return_id = cur.fetchone()["return_id"]
    for line_no, quantity in lines:
        cur.execute(RETURN_LINE, (return_id, line_no, order_id, quantity))
    return return_id


def receive(cur, return_id, store_id=1, staff_id=14):
    """Take a requested return in at a store, as the receive action does."""
    cur.execute("""UPDATE return_request
                   SET status = 'received', received_store_id = %s, processed_by_staff_id = %s, received_at = now()
                   WHERE return_id = %s""", (store_id, staff_id, return_id))


def reject(cur, return_id, staff_id=14, reason="Water damage"):
    """Refuse a received return, as the reject action does."""
    cur.execute("""UPDATE return_request
                   SET status = 'rejected', rejection_reason = %s, resolved_by_staff_id = %s, resolved_at = now()
                   WHERE return_id = %s""", (reason, staff_id, return_id))


@pytest.fixture
def customer(cur):
    """A customer with one address, address_no 1."""
    return make_customer(cur, "test.customer@example.com")


@pytest.fixture
def collected_order(cur, customer, product_id):
    """A paid ($527.95) C&C order at store 1, collected just now: line 1 = 2 × AirPods 4, line 2 = 1 × Flip 7."""
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 2, "189.00"),
                                           (product_id("JBL-FLIP7-B"), 1, "149.95")])
    pay(cur, order_id)
    advance(cur, order_id, "picking", "ready", "collected", staff_id=14)
    return order_id


# ---------------------------------------------------------------- BR01–BR05: customers, money, stock, staff

def test_br01_email_is_well_formed(violates):
    insert = "INSERT INTO customer (email, full_name) VALUES (%s, 'X')"
    violates("br01_email_format", insert, ("not-an-email",))
    violates("br01_email_format", insert, ("Mixed.Case@example.com",))     # stored lower-case


def test_br01_email_is_unique(cur, violates):
    insert = "INSERT INTO customer (email, full_name) VALUES ('dup@example.com', 'X')"
    cur.execute(insert)
    violates("br01_customer_email_unique", insert)


def test_br02_money_is_never_negative(violates):
    violates("br02_money_nonneg", "UPDATE product SET base_price = -1 WHERE sku = 'LEN-TABM11-128'")


def test_br03_stock_never_goes_negative(product_id, violates):
    violates("br03_inventory_qty_nonneg",
             "UPDATE inventory SET quantity = -1 WHERE store_id = 1 AND product_id = %s", (product_id("APL-AP4"),))


def test_br04_manager_works_at_the_store(cur, violates):
    # Staff 14 works at store 1. The FK is DEFERRED, so the UPDATE itself is accepted...
    cur.execute("UPDATE store SET manager_id = 14 WHERE store_id = 2")
    # ...and fails when the constraint is checked: at COMMIT, or right now if we ask for it.
    violates("br04_store_manager_works_here", "SET CONSTRAINTS br04_store_manager_works_here IMMEDIATE")


def test_br04_a_new_store_and_its_manager_in_one_transaction(cur):
    cur.execute("""INSERT INTO store (store_id, name, store_type, suburb, state, manager_id)
                   VALUES (100, 'Newtown', 'retail', 'Newtown', 'NSW', 1000)""")   # manager doesn't exist yet
    cur.execute("""INSERT INTO staff (staff_id, store_id, staff_type, full_name, email)
                   VALUES (1000, 100, 'store', 'New Manager', 'new.manager@jbhifi.example')""")
    cur.execute("SET CONSTRAINTS br04_store_manager_works_here IMMEDIATE")        # now it does: no error


def test_br05_store_staff_have_a_store_and_support_staff_do_not(violates):
    insert = "INSERT INTO staff (store_id, staff_type, full_name, email) VALUES (%s, %s, 'X', %s)"
    violates("br05_staff_store_matches_type", insert, (1, "support", "x1@jbhifi.example"))
    violates("br05_staff_store_matches_type", insert, (None, "store", "x2@jbhifi.example"))


# ---------------------------------------------------------------- BR06–BR10: orders

ORDER = """
    INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id,
                                delivery_address_no)
    VALUES (%s, gen_random_uuid(), %s, %s, %s)
"""


def test_br06_delivery_has_an_address_and_collect_does_not(customer, violates):
    violates("br06_order_address_matches_method", ORDER, (customer, "delivery", 13, None))
    violates("br06_order_address_matches_method", ORDER, (customer, "click_collect", 1, 1))


def test_br06_collect_only_at_a_retail_store(customer, violates):
    violates("br06_collect_at_retail_store", ORDER, (customer, "click_collect", 13, None))   # 13 = warehouse


def test_br06_a_store_with_collect_orders_stays_retail(cur, customer, product_id, violates):
    airpods = product_id("APL-AP4")
    place_order(cur, customer, [(airpods, 1, "189.00")], store_id=2)        # Click & Collect at Bondi Junction
    violates("br06_collect_at_retail_store", "UPDATE store SET store_type = 'warehouse' WHERE store_id = 2")
    # A store whose orders are all deliveries may become a warehouse. That store is made here (as in the BR04
    # test): other test files commit Click & Collect orders at the seeded stores.
    cur.execute("""INSERT INTO store (store_id, name, store_type, suburb, state, manager_id)
                   VALUES (100, 'Newtown', 'retail', 'Newtown', 'NSW', 1000)""")
    cur.execute("""INSERT INTO staff (staff_id, store_id, staff_type, full_name, email)
                   VALUES (1000, 100, 'store', 'New Manager', 'new.manager@jbhifi.example')""")
    place_order(cur, customer, [(airpods, 1, "189.00")], method="delivery", store_id=100, address_no=1)
    cur.execute("UPDATE store SET store_type = 'warehouse' WHERE store_id = 100")         # allowed


def test_br07_line_quantity_is_positive_and_a_product_appears_once(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    line = "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) VALUES (%s, 2, %s, %s, 10)"
    violates("br07_order_line_qty_positive", line, (order_id, product_id("JBL-FLIP7-B"), 0))
    violates("br07_order_line_product_once", line, (order_id, product_id("APL-AP4"), 1))


def test_br07_a_retired_product_cannot_be_ordered(cur, customer, product_id, violates):
    airpods, flip = product_id("APL-AP4"), product_id("JBL-FLIP7-B")
    order_id = place_order(cur, customer, [(flip, 1, "149.95")])
    cur.execute("UPDATE product SET is_active = FALSE WHERE product_id = %s", (airpods,))   # retired, still on file
    line = "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) VALUES (%s, 2, %s, 1, 189.00)"
    violates("br07_product_on_sale", line, (order_id, airpods))
    violates("order_line_product_fk", line, (order_id, 999999))         # no such product: the foreign key says so


def test_br07_an_order_without_lines_fails_at_commit(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [])            # accepted for now: an order's lines come after it...
    # ...so the check waits for COMMIT, or runs now if we ask for it — by name, never ALL (which would also run
    # every other deferred check).
    violates("br07_order_has_lines", "SET CONSTRAINTS br07_order_has_lines IMMEDIATE")
    cur.execute("""INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price)
                   VALUES (%s, 1, %s, 1, 189.00)""", (order_id, product_id("APL-AP4")))
    cur.execute("SET CONSTRAINTS br07_order_has_lines IMMEDIATE")         # now it has a line: no error


def test_br08_unit_price_never_changes(collected_order, violates):
    violates("br08_unit_price_immutable",
             "UPDATE order_line SET unit_price = 1.00 WHERE order_id = %s AND line_no = 1", (collected_order,))


def test_br08_lines_are_added_only_while_the_order_is_placed(cur, customer, product_id, violates):
    airpods, flip, headphones = product_id("APL-AP4"), product_id("JBL-FLIP7-B"), product_id("SONY-WH1000XM5-B")
    order_id = place_order(cur, customer, [(airpods, 2, "189.00")])
    line = "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) VALUES (%s, %s, %s, 1, %s)"
    # A written line is never changed or deleted, not even while its order is still placed...
    violates("br08_order_line_immutable",
             "UPDATE order_line SET quantity = 1 WHERE order_id = %s AND line_no = 1", (order_id,))
    violates("br08_order_line_immutable",
             "UPDATE order_line SET product_id = %s WHERE order_id = %s AND line_no = 1", (flip, order_id))
    violates("br08_unit_price_immutable",          # a price change is named as such, whatever else changes
             "UPDATE order_line SET unit_price = 1.00, quantity = 1 WHERE order_id = %s AND line_no = 1", (order_id,))
    violates("br08_order_line_immutable", "DELETE FROM order_line WHERE order_id = %s", (order_id,))
    # Row triggers don't fire on TRUNCATE. (Without CASCADE it is refused anyway: return_line refers to order_line.)
    violates("br08_order_line_immutable", "TRUNCATE order_line CASCADE")
    # ...and lines are added while the order is placed, and only then.
    cur.execute(line, (order_id, 2, flip, "149.95"))
    pay(cur, order_id)
    violates("br08_order_line_immutable", line, (order_id, 3, headphones, "399.00"))
    violates("order_line_order_fk", line, (-1, 1, flip, "149.95"))       # no such order: the foreign key says so


def test_br09_new_orders_start_as_placed(customer, violates):
    violates("br09_order_status_transition",
             """INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id, status)
                VALUES (%s, gen_random_uuid(), 'click_collect', 1, 'paid')""", (customer,))


def test_br09_status_moves_only_along_allowed_transitions(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    update = "UPDATE customer_order SET status = %s WHERE order_id = %s"
    violates("br09_order_status_transition", update, ("collected", order_id))   # skips paid → picking → ready
    pay(cur, order_id)
    advance(cur, order_id, "picking")
    violates("br09_order_status_transition", update, ("shipped", order_id))     # delivery-only status


def test_br09_every_status_change_is_logged_with_who_made_it(cur, collected_order):
    cur.execute("""SELECT from_status, to_status, changed_by_staff_id FROM order_status_history
                   WHERE order_id = %s ORDER BY seq""", (collected_order,))
    assert [tuple(row.values()) for row in cur.fetchall()] == [
        (None, "placed", None),
        ("placed", "paid", None),
        ("paid", "picking", 14),
        ("picking", "ready", 14),
        ("ready", "collected", 14),
    ]


def test_br09_a_service_can_name_when_a_change_happened(cur, customer, product_id):
    # As app.staff_id names who made a change, app.changed_at names when (the seed replays six months this way).
    # Unset or empty, the log uses the transaction's now(), as before.
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    cur.execute("SELECT set_config('app.changed_at', '2026-01-02 03:04:05+00', true)")
    pay(cur, order_id)
    advance(cur, order_id, "picking", staff_id=14)
    cur.execute("SELECT set_config('app.changed_at', '', true)")
    advance(cur, order_id, "ready", staff_id=14)
    cur.execute("""SELECT to_status, changed_at = '2026-01-02 03:04:05+00' AS named, changed_at = now() AS now
                   FROM order_status_history WHERE order_id = %s ORDER BY seq""", (order_id,))
    assert [tuple(row.values()) for row in cur.fetchall()] == [
        ("placed", False, True),            # inserted before the setting was made
        ("paid", True, False),
        ("picking", True, False),
        ("ready", False, True),
    ]


def test_br09_the_order_header_never_changes(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])    # Click & Collect at store 1
    other = make_customer(cur, "other.customer@example.com", with_address=False)
    for column, value in [("order_id", 999999),
                          ("customer_id", other),
                          ("idempotency_key", str(uuid.uuid4())),
                          ("fulfilment_method", "delivery"),
                          ("fulfilling_store_id", 2),     # retail, so BR06 (whose trigger fires first) agrees
                          ("delivery_address_no", 1),
                          ("placed_at", datetime(2026, 1, 1, tzinfo=timezone.utc))]:
        update = sql.SQL("UPDATE customer_order SET {} = %s WHERE order_id = %s").format(sql.Identifier(column))
        violates("br09_order_header_immutable", update, (value, order_id))
    pay(cur, order_id)                                    # the status is the one thing that moves


def test_br09_history_is_append_only(collected_order, violates):
    violates("br09_history_append_only",
             "UPDATE order_status_history SET changed_by_staff_id = NULL WHERE order_id = %s", (collected_order,))
    violates("br09_history_append_only", "DELETE FROM order_status_history WHERE order_id = %s", (collected_order,))
    violates("br09_history_append_only", "TRUNCATE order_status_history")     # row triggers don't fire on TRUNCATE


HISTORY = "INSERT INTO order_status_history (order_id, seq, from_status, to_status) VALUES (%s, %s, %s, %s)"


def test_br09_only_the_status_log_writes_history(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    # A well-formed row, written directly: refused, so the timeline can't disagree with the order's status.
    violates("br09_history_written_by_trigger", HISTORY, (order_id, 2, "placed", "paid"))
    pay(cur, order_id)                                   # the status change writes row 2 itself
    cur.execute("SELECT seq, from_status, to_status FROM order_status_history WHERE order_id = %s ORDER BY seq",
                (order_id,))
    assert [tuple(row.values()) for row in cur.fetchall()] == [(1, None, "placed"), (2, "placed", "paid")]


def test_br09_history_rows_are_well_formed(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])     # row 1: NULL → placed
    # br09_history_written_by_trigger refuses a direct INSERT before any CHECK is reached, so it is switched off
    # for this transaction only (ALTER TABLE is transactional: the test's rollback would restore it too).
    cur.execute("ALTER TABLE order_status_history DISABLE TRIGGER br09_history_written_by_trigger")
    violates("br09_history_first_row_is_creation", HISTORY, (order_id, 2, None, "paid"))       # later rows have a from
    violates("br09_history_first_row_is_creation", HISTORY, (order_id, 1, "placed", "paid"))   # row 1 has none
    violates("br09_history_status_changes", HISTORY, (order_id, 2, "placed", "placed"))         # not a change
    cur.execute(HISTORY, (order_id, 2, "placed", "paid"))                                       # well formed: accepted
    cur.execute("ALTER TABLE order_status_history ENABLE TRIGGER br09_history_written_by_trigger")
    violates("br09_history_written_by_trigger", HISTORY, (order_id, 3, "paid", "picking"))      # and the guard is back


def test_br10_one_order_per_idempotency_key(cur, customer, violates):
    insert = """INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id)
                VALUES (%s, '0b6f1d4e-5c3a-4a8e-9f2b-7d1e3c5a9b0f', 'click_collect', 1)"""
    cur.execute(insert, (customer,))
    violates("br10_order_idempotency_unique", insert, (customer,))


# ---------------------------------------------------------------- BR11–BR14: returns and refunds

def test_br11_only_completed_orders_can_be_returned(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    pay(cur, order_id)
    violates("br11_return_window", RETURN_REQUEST, (order_id, 0))


def test_br11_returns_within_30_days_of_completion(cur, collected_order, violates):
    cur.execute(RETURN_REQUEST, (collected_order, 30))                # day 30 is still inside the window
    violates("br11_return_window", RETURN_REQUEST, (collected_order, 31))


def test_br12_cannot_return_more_than_was_bought(cur, collected_order, violates):
    request_return(cur, collected_order, [(1, 1)])                    # 1 of the 2 AirPods
    second = request_return(cur, collected_order, [])
    violates("br12_return_qty_within_purchased", RETURN_LINE, (second, 1, collected_order, 2))   # 1 + 2 > 2
    cur.execute(RETURN_LINE, (second, 1, collected_order, 1))                                    # 1 + 1 = 2


def test_br12_rejected_returns_do_not_count(cur, collected_order):
    first = request_return(cur, collected_order, [(1, 2)])
    receive(cur, first)
    reject(cur, first)
    request_return(cur, collected_order, [(1, 2)])                    # allowed: the rejected one doesn't count


def test_br12_a_rejected_return_cannot_be_reopened(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])
    receive(cur, return_id)
    reject(cur, return_id)
    violates("return_status_transition",
             "UPDATE return_request SET status = 'requested' WHERE return_id = %s", (return_id,))


def test_br13_return_lines_come_from_the_returned_order(cur, customer, collected_order, product_id, violates):
    other_order = place_order(cur, customer, [(product_id("SONY-WH1000XM5-B"), 1, "399.00")])
    return_id = request_return(cur, collected_order, [])
    violates("br13_return_line_same_order", RETURN_LINE, (return_id, 1, other_order, 1))


def test_br14_refunds(cur, customer, collected_order, product_id, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])                 # worth 189.00
    receive(cur, return_id)
    payment = "INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, %s, %s, %s)"
    # A refund without a return is a cancellation refund, and a collected order can't be cancelled.
    violates("br14_refund_without_return_is_cancellation", payment, (collected_order, "refund", "189.00", None))
    # A charge that names a return. BR20 refuses any charge to the collected order first, so this is shown on
    # an order that is still placed; CHECKs run before foreign keys, so another order's return_id is fine here.
    placed = place_order(cur, customer, [(product_id("SONY-WH1000XM5-B"), 1, "399.00")])
    violates("br14_charge_has_no_return", payment, (placed, "charge", "1.00", return_id))
    violates("br14_refund_matches_return", payment, (collected_order, "refund", "600.00", return_id))
    # Refunds within what was charged is the second line of defence: while every refund equals its return's
    # value and BR12 caps what is returned, it can't be reached. Switched off, the first line no longer hides it
    # (ALTER TABLE is transactional: it is undone with the rest of the test).
    cur.execute("ALTER TABLE payment DISABLE TRIGGER br14_refund_matches_return")
    violates("br14_refunds_within_charged", payment, (collected_order, "refund", "600.00", return_id))
    cur.execute("ALTER TABLE payment ENABLE TRIGGER br14_refund_matches_return")
    cur.execute(payment, (collected_order, "refund", "189.00", return_id))
    violates("br14_refund_once_per_return", payment, (collected_order, "refund", "189.00", return_id))


def test_br14_payments_are_append_only(collected_order, violates):
    violates("br14_payment_append_only", "UPDATE payment SET amount = 1.00 WHERE order_id = %s", (collected_order,))
    violates("br14_payment_append_only", "DELETE FROM payment WHERE order_id = %s", (collected_order,))
    violates("br14_payment_append_only", "TRUNCATE payment")                  # row triggers don't fire on TRUNCATE


# ---------------------------------------------------------------- BR15–BR17: promotions, addresses

PROMOTION = """
    INSERT INTO promotion (product_id, sale_price, starts_at, ends_at)
    VALUES (%s, %s, now() + %s * interval '1 day', now() + %s * interval '1 day')
"""


def test_br15_sale_price_is_below_the_base_price(product_id, violates):
    violates("br15_promotion_below_base_price", PROMOTION, (product_id("LEN-TABM11-128"), "349.00", 1, 5))


def test_br15_promotions_for_a_product_never_overlap(cur, product_id, violates):
    headphones = product_id("SONY-WH1000XM5-B")      # seeded: a promotion running until ~30 days from now
    violates("br15_promotion_no_overlap", PROMOTION, (headphones, "379.00", 29, 40))
    cur.execute("SELECT ends_at FROM promotion WHERE product_id = %s AND starts_at <= now() AND now() < ends_at",
                (headphones,))
    ends_at = cur.fetchone()["ends_at"]
    # Periods are half-open [starts_at, ends_at), so the next one may start the moment this one ends.
    cur.execute("""INSERT INTO promotion (product_id, sale_price, starts_at, ends_at)
                   VALUES (%s, 379.00, %s, %s + interval '7 days')""", (headphones, ends_at, ends_at))


def test_br15_base_price_stays_above_current_promotions(product_id, violates):
    violates("br15_promotion_below_base_price",
             "UPDATE product SET base_price = 399.00 WHERE product_id = %s", (product_id("SONY-WH1000XM5-B"),))


def test_br16_addresses_are_immutable(cur, customer, violates):
    violates("br16_address_immutable",
             "UPDATE customer_address SET line1 = '2 George St' WHERE customer_id = %s", (customer,))
    cur.execute("UPDATE customer_address SET is_active = FALSE WHERE customer_id = %s", (customer,))  # allowed


def test_br17_delivery_address_belongs_to_the_customer(cur, customer, violates):
    other = make_customer(cur, "other.customer@example.com", with_address=False)
    # Address 1 exists — but it is `customer`'s, not `other`'s.
    violates("br17_order_address_is_customers", ORDER, (other, "delivery", 13, 1))


def test_br17_a_retired_address_cannot_be_ordered_to(cur, customer, violates):
    cur.execute("UPDATE customer_address SET is_active = FALSE WHERE customer_id = %s AND address_no = 1", (customer,))
    violates("br17_order_address_active", ORDER, (customer, "delivery", 13, 1))
    violates("br17_order_address_is_customers", ORDER, (customer, "delivery", 13, 2))    # no address 2: the FK says so
    cur.execute("""INSERT INTO customer_address (customer_id, address_no, line1, suburb, state, postcode)
                   VALUES (%s, 2, '2 George St', 'Sydney', 'NSW', '2000')""", (customer,))
    cur.execute(ORDER, (customer, "delivery", 13, 2))                                    # a current address: allowed


# ---------------------------------------------------------------- BR18: stock adjustments

ADJUSTMENT = """
    INSERT INTO stock_adjustment (store_id, product_id, staff_id, delta, reason, quantity_after)
    VALUES (1, %s, %s, %s, %s, 0)
"""


def test_br18_only_staff_of_that_store_adjust_its_stock(product_id, violates):
    airpods = product_id("APL-AP4")
    violates("br18_adjustment_staff_at_store", ADJUSTMENT, (airpods, 16, 1, "received"))   # works at store 2
    violates("br18_adjustment_staff_at_store", ADJUSTMENT, (airpods, 40, 1, "received"))   # support staff


def test_br18_change_matches_its_reason(product_id, violates):
    airpods = product_id("APL-AP4")
    for delta, reason in [(-1, "received"), (1, "damaged"), (0, "stocktake"), (1, "gift")]:
        violates("br18_adjustment_delta_matches_reason", ADJUSTMENT, (airpods, 14, delta, reason))


def test_br18_the_log_is_append_only(cur, product_id, violates):
    cur.execute(ADJUSTMENT + " RETURNING adjustment_id", (product_id("APL-AP4"), 14, 1, "received"))
    adjustment_id = cur.fetchone()["adjustment_id"]
    violates("br18_adjustment_append_only",
             "UPDATE stock_adjustment SET delta = 2 WHERE adjustment_id = %s", (adjustment_id,))
    violates("br18_adjustment_append_only", "DELETE FROM stock_adjustment WHERE adjustment_id = %s", (adjustment_id,))
    violates("br18_adjustment_append_only", "TRUNCATE stock_adjustment")     # row triggers don't fire on TRUNCATE


# ---------------------------------------------------------------- BR19: sign-in identities

ACCOUNT = "INSERT INTO user_account (auth_subject, customer_id, staff_id) VALUES (%s, %s, %s)"


def test_br19_an_identity_is_a_customer_or_a_staff_member(customer, violates):
    violates("br19_account_customer_xor_staff", ACCOUNT, ("user_both", customer, 14))
    violates("br19_account_customer_xor_staff", ACCOUNT, ("user_neither", None, None))


def test_br19_one_identity_per_person(cur, customer, violates):
    cur.execute(ACCOUNT, ("user_first_customer", customer, None))
    violates("br19_account_one_customer", ACCOUNT, ("user_second_customer", customer, None))
    cur.execute(ACCOUNT, ("user_first_staff", None, 41))            # Omar Haddad, support
    violates("br19_account_one_staff", ACCOUNT, ("user_second_staff", None, 41))


# ---------------------------------------------------------------- BR20: paid in full

CHARGE = "INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', %s)"
PAY = "UPDATE customer_order SET status = 'paid' WHERE order_id = %s"


def test_br20_an_order_is_paid_only_when_its_charge_equals_the_total(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 2, "189.00"),
                                           (product_id("JBL-FLIP7-B"), 1, "149.95")])     # total 527.95
    violates("br20_paid_in_full", PAY, (order_id,))                       # nothing charged
    for wrong in ("378.00", "600.00"):                                    # one line short; too much
        cur.execute("SAVEPOINT wrong_charge")
        cur.execute(CHARGE, (order_id, wrong))
        violates("br20_paid_in_full", PAY, (order_id,))
        cur.execute("ROLLBACK TO SAVEPOINT wrong_charge")
    cur.execute(CHARGE, (order_id, "527.95"))
    cur.execute(PAY, (order_id,))
    cur.execute("SELECT status FROM customer_order WHERE order_id = %s", (order_id,))
    assert cur.fetchone()["status"] == "paid"


def test_br20_an_order_without_lines_cannot_be_paid(cur, customer, violates):
    order_id = place_order(cur, customer, [])          # 0.00 due and 0.00 charged, but nothing was bought
    violates("br20_paid_in_full", PAY, (order_id,))


def test_br20_a_zero_total_order_is_paid_without_a_charge(cur, customer, product_id):
    # A line may cost 0.00 (money_aud allows it) but a charge may not (payment_amount_positive), so when nothing
    # is due, "charged in full" means no charge at all.
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "0.00")])
    cur.execute(PAY, (order_id,))
    cur.execute("SELECT status FROM customer_order WHERE order_id = %s", (order_id,))
    assert cur.fetchone()["status"] == "paid"


def test_br20_a_charge_is_taken_only_while_the_order_is_placed(cur, customer, product_id, violates):
    paid = place_order(cur, customer, [(product_id("APL-AP4"), 1, "0.00")])
    cur.execute(PAY, (paid,))                  # paid with no charge row, so a new charge can't be a second one
    violates("br20_charge_while_placed", CHARGE, (paid, "1.00"))
    cancelled = place_order(cur, customer, [(product_id("JBL-FLIP7-B"), 1, "149.95")])
    advance(cur, cancelled, "cancelled")
    violates("br20_charge_while_placed", CHARGE, (cancelled, "149.95"))
    violates("payment_order_fk", CHARGE, (-1, "1.00"))                    # no such order: the foreign key says so


def test_br20_at_most_one_charge_per_order(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    cur.execute(CHARGE, (order_id, "189.00"))
    violates("br20_one_charge_per_order", CHARGE, (order_id, "189.00"))   # still placed: only the index stops it


# ---------------------------------------------------------------- BR14 and BR21: cancelling an order (T4)

REFUND = "INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'refund', %s)"    # no return_id
CANCEL = "UPDATE customer_order SET status = 'cancelled' WHERE order_id = %s"


def test_br14_a_refund_without_a_return_is_only_for_cancelling(cur, customer, collected_order, product_id,
                                                               violates):
    paid = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    pay(cur, paid)
    cur.execute(REFUND, (paid, "189.00"))           # paid can still move to cancelled, so this is its refund
    cur.execute(CANCEL, (paid,))
    violates("br14_refund_without_return_is_cancellation", REFUND, (paid, "1.00"))   # already cancelled
    violates("br14_refund_without_return_is_cancellation", REFUND, (collected_order, "1.00"))   # completed
    picking = place_order(cur, customer, [(product_id("JBL-FLIP7-B"), 1, "149.95")])
    pay(cur, picking)
    advance(cur, picking, "picking", staff_id=14)
    violates("br14_refund_without_return_is_cancellation", REFUND, (picking, "1.00"))   # picking can't cancel


def test_br21_an_order_is_cancelled_only_when_fully_refunded(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    pay(cur, order_id)
    violates("br21_cancelled_order_refunded", CANCEL, (order_id,))          # 189.00 still held
    cur.execute(REFUND, (order_id, "188.99"))
    violates("br21_cancelled_order_refunded", CANCEL, (order_id,))          # 0.01 still held
    cur.execute(REFUND, (order_id, "0.01"))
    cur.execute(CANCEL, (order_id,))
    cur.execute("SELECT status FROM customer_order WHERE order_id = %s", (order_id,))
    assert cur.fetchone()["status"] == "cancelled"

    free = place_order(cur, customer, [(product_id("JBL-FLIP7-B"), 1, "0.00")])
    pay(cur, free)                                  # nothing charged, so nothing to give back
    cur.execute(CANCEL, (free,))
    cur.execute("SELECT status FROM customer_order WHERE order_id = %s", (free,))
    assert cur.fetchone()["status"] == "cancelled"


# ---------------------------------------------------------------- views

def test_current_price_includes_the_running_promotion(cur):
    cur.execute("""SELECT p.sku, v.current_price FROM v_product_current_price v JOIN product p USING (product_id)
                   WHERE p.sku IN ('SONY-WH1000XM5-B', 'LEN-TABM11-128', 'SONY-PS5-SLIM-DISC') ORDER BY p.sku""")
    assert [(row["sku"], str(row["current_price"])) for row in cur.fetchall()] == [
        ("LEN-TABM11-128", "349.00"),        # no promotion
        ("SONY-PS5-SLIM-DISC", "799.95"),    # promotion not started yet
        ("SONY-WH1000XM5-B", "399.00"),      # running promotion (an older, ended one is ignored)
    ]


def test_order_summary_has_the_total_store_and_last_update(cur, customer, product_id):
    # now() is fixed for a whole transaction, so every history row here would get the same changed_at and
    # the newest change couldn't be told from the first. app.changed_at names later times for the later moves,
    # as the seed does (BR09's log writes changed_at itself, so a column default would no longer apply).
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 2, "189.00"),
                                           (product_id("JBL-FLIP7-B"), 1, "149.95")])
    cur.execute("SELECT set_config('app.changed_at', (now() + interval '1 hour')::text, true)")
    pay(cur, order_id)
    cur.execute("SELECT set_config('app.changed_at', (now() + interval '2 hours')::text, true)")
    advance(cur, order_id, "picking", "ready", "collected", staff_id=14)

    cur.execute("SELECT * FROM v_order_summary WHERE order_id = %s", (order_id,))
    rows = cur.fetchall()
    assert len(rows) == 1                      # its 2 lines and 5 history rows don't multiply the order
    summary = rows[0]
    assert list(summary) == ["order_id", "customer_id", "placed_at", "status", "fulfilment_method",
                             "fulfilling_store_id", "fulfilling_store_name", "total", "line_count",
                             "last_updated_at"]
    assert (summary["customer_id"], summary["status"], summary["fulfilment_method"], summary["fulfilling_store_id"],
            summary["fulfilling_store_name"], str(summary["total"]), summary["line_count"]) \
        == (customer, "collected", "click_collect", 1, "Sydney CBD", "527.95", 2)
    cur.execute("SELECT changed_at FROM order_status_history WHERE order_id = %s ORDER BY seq", (order_id,))
    first, *_, newest = [row["changed_at"] for row in cur.fetchall()]
    assert summary["last_updated_at"] == newest > first


def test_order_payment_balances_charges_and_refunds_without_fan_out(cur, customer, collected_order, product_id):
    def payment_of(order_id):
        cur.execute("SELECT charged, refunded, balance FROM v_order_payment WHERE order_id = %s", (order_id,))
        return [tuple(str(value) for value in row.values()) for row in cur.fetchall()]

    # collected_order: two lines, one charge of 527.95. Nothing refunded yet reads 0.00, not 0.
    assert payment_of(collected_order) == [("527.95", "0.00", "527.95")]
    # Refund one AirPods (line 1) and the Flip 7 (line 2), each on its own received return.
    for line_no, amount in [(1, "189.00"), (2, "149.95")]:
        return_id = request_return(cur, collected_order, [(line_no, 1)])
        receive(cur, return_id)
        cur.execute("INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)",
                    (collected_order, amount, return_id))
    # Summed per order before any join, so the two lines don't double the three payments (joining the lines
    # first would report 1055.90 charged and 677.90 refunded).
    assert payment_of(collected_order) == [("527.95", "338.95", "189.00")]
    # An order with no payments yet still has its one row.
    unpaid = place_order(cur, customer, [(product_id("SONY-WH1000XM5-B"), 1, "399.00")])
    assert payment_of(unpaid) == [("0.00", "0.00", "0.00")]
    cur.execute("SELECT (SELECT count(*) FROM v_order_payment) = (SELECT count(*) FROM customer_order) AS one_each")
    assert cur.fetchone()["one_each"]


def test_order_timeline_names_the_staff_in_seq_order(cur, collected_order):
    cur.execute("SELECT * FROM v_order_timeline WHERE order_id = %s ORDER BY seq", (collected_order,))
    rows = cur.fetchall()
    assert list(rows[0]) == ["order_id", "seq", "from_status", "to_status", "changed_at",
                             "changed_by_staff_id", "changed_by_name"]
    # The customer's own moves have no staff member and are still listed (LEFT JOIN): all five rows.
    assert [(r["seq"], r["from_status"], r["to_status"], r["changed_by_staff_id"], r["changed_by_name"])
            for r in rows] == [
        (1, None, "placed", None, None),
        (2, "placed", "paid", None, None),
        (3, "paid", "picking", 14, "Aiden Chen"),
        (4, "picking", "ready", 14, "Aiden Chen"),
        (5, "ready", "collected", 14, "Aiden Chen"),
    ]


# Status and history must agree (BR09, R11). Each query lists the orders that break one condition, over
# every order in the database, including those other test files committed. NOT EXISTS and max(seq) only:
# no window functions.
HISTORY_CHECKS = {
    "status is the newest row's to_status": """
        SELECT o.order_id
        FROM customer_order o
        WHERE NOT EXISTS (
            SELECT 1
            FROM order_status_history h
            WHERE h.order_id = o.order_id
              AND h.to_status = o.status
              AND h.seq = (SELECT max(h2.seq) FROM order_status_history h2 WHERE h2.order_id = o.order_id))
    """,
    "each row starts where the one before ended": """
        SELECT h.order_id
        FROM order_status_history h
        WHERE h.seq > 1
          AND NOT EXISTS (
              SELECT 1
              FROM order_status_history prev
              WHERE prev.order_id = h.order_id
                AND prev.to_status = h.from_status
                AND prev.seq = (SELECT max(p2.seq) FROM order_status_history p2
                                WHERE p2.order_id = h.order_id AND p2.seq < h.seq))
    """,
    "row 1 is NULL -> placed": """
        SELECT o.order_id
        FROM customer_order o
        WHERE NOT EXISTS (
            SELECT 1
            FROM order_status_history h
            WHERE h.order_id = o.order_id AND h.seq = 1 AND h.from_status IS NULL AND h.to_status = 'placed')
    """,
}


def history_breaks(cur) -> dict:
    """{condition: ids of the orders that break it}."""
    found = {}
    for condition, query in HISTORY_CHECKS.items():
        cur.execute(query)
        found[condition] = sorted(row["order_id"] for row in cur.fetchall())
    return found


def test_every_orders_status_is_its_latest_history_entry(cur, customer, collected_order, product_id):
    place_order(cur, customer, [(product_id("SONY-WH1000XM5-B"), 1, "399.00")])           # stays placed
    paid = place_order(cur, customer, [(product_id("JBL-T770NC-B"), 1, "179.95")])
    pay(cur, paid)
    cancelled = place_order(cur, customer, [(product_id("LEN-TABM11-128"), 1, "349.00")])
    advance(cur, cancelled, "cancelled")
    assert history_breaks(cur) == {condition: [] for condition in HISTORY_CHECKS}

    # The checks can fail: forge a sixth row for collected_order that neither matches its status nor starts
    # where row 5 ended. Only BR09's log trigger may write history, so that guard is switched off first
    # (ALTER TABLE is transactional: it is undone with the rest of the test).
    cur.execute("ALTER TABLE order_status_history DISABLE TRIGGER br09_history_written_by_trigger")
    cur.execute("""INSERT INTO order_status_history (order_id, seq, from_status, to_status)
                   VALUES (%s, 6, 'ready', 'cancelled')""", (collected_order,))
    assert history_breaks(cur) == {"status is the newest row's to_status": [collected_order],
                                   "each row starts where the one before ended": [collected_order],
                                   "row 1 is NULL -> placed": []}


# ---------------------------------------------------------------- SP3: returns (BR10, BR14 and BR22 widened or new)

def test_br10_a_return_key_is_used_once_per_order(cur, customer, collected_order, product_id, violates):
    key = str(uuid.uuid4())
    insert = "INSERT INTO return_request (order_id, idempotency_key, reason) VALUES (%s, %s, 'Too big')"
    cur.execute(insert, (collected_order, key))
    violates("br10_return_idempotency_unique", insert, (collected_order, key))
    other = place_order(cur, customer, [(product_id("SONY-WH1000XM5-B"), 1, "399.00")])
    pay(cur, other)
    advance(cur, other, "picking", "ready", "collected", staff_id=14)
    cur.execute(insert, (other, key))                                  # the key is scoped to its order


def test_br14_a_refund_equals_the_value_of_its_return(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])          # one AirPods, bought at 189.00
    receive(cur, return_id)
    payment = "INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)"
    violates("br14_refund_matches_return", payment, (collected_order, "100.00", return_id))
    violates("br14_refund_matches_return", payment, (collected_order, "189.01", return_id))
    cur.execute(payment, (collected_order, "189.00", return_id))


def test_br22_returns_are_received_at_a_retail_store(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])
    receive_at = """UPDATE return_request
                    SET status = 'received', received_store_id = %s, processed_by_staff_id = %s, received_at = now()
                    WHERE return_id = %s"""
    violates("br22_return_received_at_retail_store", receive_at, (13, 13, return_id))   # Eastern Creek DC
    cur.execute(receive_at, (2, 16, return_id))                         # any retail store, not only store 1


def test_a_return_is_rejected_only_after_it_is_received(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])
    reject_unseen = """UPDATE return_request
                       SET status = 'rejected', rejection_reason = 'Unseen', resolved_by_staff_id = 14,
                           resolved_at = now()
                       WHERE return_id = %s"""
    violates("return_status_transition", reject_unseen, (return_id,))
    # The CHECK holds the same line on its own: with the transition trigger off, a rejected return still
    # needs a receiving store and receiver.
    cur.execute("ALTER TABLE return_request DISABLE TRIGGER return_status_transition")
    violates("return_request_receipt_recorded", reject_unseen, (return_id,))
    cur.execute("ALTER TABLE return_request ENABLE TRIGGER return_status_transition")
    receive(cur, return_id)
    reject(cur, return_id)


def test_return_receipt_and_resolution_are_recorded_together(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])
    violates("return_request_received_at_recorded",
             """UPDATE return_request SET status = 'received', received_store_id = 1, processed_by_staff_id = 14
                WHERE return_id = %s""", (return_id,))
    receive(cur, return_id)
    violates("return_request_resolution_recorded",
             "UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))
    violates("return_request_resolution_recorded",
             "UPDATE return_request SET resolved_by_staff_id = 14 WHERE return_id = %s", (return_id,))
    violates("return_request_resolver_at_store", """UPDATE return_request
                SET status = 'rejected', rejection_reason = 'Scratched', resolved_by_staff_id = 16,
                    resolved_at = now()
                WHERE return_id = %s""", (return_id,))      # staff 16 works at store 2, not the receiving store 1
    reject(cur, return_id, staff_id=15)                     # another staff member of the receiving store


def test_only_a_rejected_return_has_a_reason(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])
    receive(cur, return_id)
    violates("return_request_rejection_has_reason",
             "UPDATE return_request SET rejection_reason = 'Scratched' WHERE return_id = %s", (return_id,))
    reject_with = """UPDATE return_request
                     SET status = 'rejected', rejection_reason = %s, resolved_by_staff_id = 14, resolved_at = now()
                     WHERE return_id = %s"""
    violates("return_request_rejection_has_reason", reject_with, (None, return_id))
    violates("return_request_rejection_has_reason", reject_with, ("   ", return_id))
    cur.execute(reject_with, ("Scratched", return_id))


def test_return_value_is_the_purchase_price_of_what_came_back(cur, collected_order):
    whole = request_return(cur, collected_order, [(1, 2), (2, 1)])     # 2 x 189.00 + 1 x 149.95
    receive(cur, whole)
    reject(cur, whole)                                                 # so its units can be asked for again
    part = request_return(cur, collected_order, [(1, 1)])
    cur.execute("SELECT return_id, order_id, quantity, value FROM v_return_value WHERE return_id IN (%s, %s)"
                " ORDER BY return_id", (whole, part))
    assert [(row["quantity"], str(row["value"])) for row in cur.fetchall()] == [(3, "527.95"), (1, "189.00")]


def test_a_return_without_lines_is_worth_nothing(cur, collected_order):
    # Claimed in this transaction, no lines yet: still one row in the view, so the BR14 trigger compares a
    # refund with 0.00, never with NULL.
    return_id = request_return(cur, collected_order, [])
    cur.execute("SELECT quantity, value FROM v_return_value WHERE return_id = %s", (return_id,))
    assert [(row["quantity"], str(row["value"])) for row in cur.fetchall()] == [(0, "0.00")]


def test_br14_a_returns_lines_never_change(cur, collected_order, violates):
    # A refund equals its return's value (br14_refund_matches_return) when it is paid; the lines it was worked out
    # from must stay as they were, or the two could part afterwards. Returning more is BR12's to refuse first.
    return_id = request_return(cur, collected_order, [(1, 1)])
    violates("br14_return_line_immutable",
             "UPDATE return_line SET quantity = 1 WHERE return_id = %s", (return_id,))
    violates("br14_return_line_immutable", "DELETE FROM return_line WHERE return_id = %s", (return_id,))
    violates("br14_return_line_immutable", "TRUNCATE return_line")          # row triggers don't fire on TRUNCATE
    violates("br14_return_line_immutable", "DELETE FROM return_request WHERE return_id = %s", (return_id,))

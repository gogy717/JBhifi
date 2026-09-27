"""One test (or more) per business rule in plan §3: break the rule, and assert which named constraint
stopped it. Those names are the error codes the API returns, so this file doubles as the
rule → mechanism table for the report appendix.
"""
import pytest

# ---------------------------------------------------------------- helpers
# Building a valid history is shared with the lifecycle tests, so there is exactly one way to create an
# order, advance it and request a return.
from tests.lifecycle import (RETURN_LINE, RETURN_REQUEST, advance, make_customer, place_order,
                             request_return, return_request_args)


@pytest.fixture
def customer(cur):
    """A customer with one address, address_no 1."""
    return make_customer(cur, "test.customer@example.com")


@pytest.fixture
def collected_order(cur, customer, product_id):
    """A paid ($527.95) C&C order at store 1, collected just now: line 1 = 2 × AirPods 4, line 2 = 1 × Flip 7."""
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 2, "189.00"),
                                           (product_id("JBL-FLIP7-B"), 1, "149.95")])
    advance(cur, order_id, "paid")
    cur.execute("INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', 527.95)", (order_id,))
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
    INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint, fulfilment_method,
                                fulfilling_store_id, delivery_address_no)
    VALUES (%s, gen_random_uuid(), gen_random_uuid()::text, %s, %s, %s)
"""


def test_br06_delivery_has_an_address_and_collect_does_not(customer, violates):
    violates("br06_order_address_matches_method", ORDER, (customer, "delivery", 13, None))
    violates("br06_order_address_matches_method", ORDER, (customer, "click_collect", 1, 1))


def test_br06_collect_only_at_a_retail_store(customer, violates):
    violates("br06_collect_at_retail_store", ORDER, (customer, "click_collect", 13, None))   # 13 = warehouse


def test_br07_line_quantity_is_positive_and_a_product_appears_once(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    line = "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) VALUES (%s, 2, %s, %s, 10)"
    violates("br07_order_line_qty_positive", line, (order_id, product_id("JBL-FLIP7-B"), 0))
    violates("br07_order_line_product_once", line, (order_id, product_id("APL-AP4"), 1))


def test_br08_unit_price_never_changes(collected_order, violates):
    violates("br08_unit_price_immutable",
             "UPDATE order_line SET unit_price = 1.00 WHERE order_id = %s AND line_no = 1", (collected_order,))


def test_br09_new_orders_start_as_placed(customer, violates):
    violates("br09_order_status_transition",
             """INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint,
                                            fulfilment_method, fulfilling_store_id, status)
                VALUES (%s, gen_random_uuid(), gen_random_uuid()::text, 'click_collect', 1, 'paid')""",
             (customer,))


def test_br09_status_moves_only_along_allowed_transitions(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    update = "UPDATE customer_order SET status = %s WHERE order_id = %s"
    violates("br09_order_status_transition", update, ("collected", order_id))   # skips paid → picking → ready
    advance(cur, order_id, "paid", "picking")
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


def test_br10_one_order_per_idempotency_key(cur, customer, violates):
    insert = """INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint,
                                            fulfilment_method, fulfilling_store_id)
                VALUES (%s, '0b6f1d4e-5c3a-4a8e-9f2b-7d1e3c5a9b0f', 'same-request', 'click_collect', 1)"""
    cur.execute(insert, (customer,))
    violates("br10_order_idempotency_unique", insert, (customer,))


# ---------------------------------------------------------------- BR11–BR14: returns and refunds

def test_br11_only_completed_orders_can_be_returned(cur, customer, product_id, violates):
    order_id = place_order(cur, customer, [(product_id("APL-AP4"), 1, "189.00")])
    advance(cur, order_id, "paid")
    violates("br11_return_window", RETURN_REQUEST, return_request_args(order_id))


def test_br11_a_just_completed_order_can_be_returned(cur, collected_order):
    # The exact 30-day boundary is covered by test_lifecycle_rules.py through the SQL predicate.
    cur.execute(RETURN_REQUEST, return_request_args(collected_order))
    assert cur.fetchone()["return_id"] is not None


def test_br12_cannot_return_more_than_was_bought(cur, collected_order, violates):
    request_return(cur, collected_order, [(1, 1)])                    # 1 of the 2 AirPods
    second = request_return(cur, collected_order, [])
    violates("br12_return_qty_within_purchased", RETURN_LINE, (second, 1, collected_order, 2))   # 1 + 2 > 2
    cur.execute(RETURN_LINE, (second, 1, collected_order, 1))                                    # 1 + 1 = 2


def test_br12_rejected_returns_do_not_count(cur, collected_order):
    first = request_return(cur, collected_order, [(1, 2)])
    cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (first,))
    request_return(cur, collected_order, [(1, 2)])                    # allowed: the rejected one doesn't count


def test_br12_a_rejected_return_cannot_be_reopened(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])
    cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (return_id,))
    violates("return_status_transition",
             "UPDATE return_request SET status = 'requested' WHERE return_id = %s", (return_id,))


def test_br13_return_lines_come_from_the_returned_order(cur, customer, collected_order, product_id, violates):
    other_order = place_order(cur, customer, [(product_id("SONY-WH1000XM5-B"), 1, "399.00")])
    return_id = request_return(cur, collected_order, [])
    violates("br13_return_line_same_order", RETURN_LINE, (return_id, 1, other_order, 1))


def test_br14_refunds(cur, collected_order, violates):
    return_id = request_return(cur, collected_order, [(1, 1)])
    cur.execute("""UPDATE return_request SET status = 'received', received_store_id = 1, processed_by_staff_id = 14
                   WHERE return_id = %s""", (return_id,))
    payment = "INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, %s, %s, %s)"
    violates("br14_refund_has_source", payment, (collected_order, "refund", "189.00", None))
    violates("br14_refund_has_source", payment, (collected_order, "charge", "1.00", return_id))
    violates("br14_refunds_within_charged", payment, (collected_order, "refund", "600.00", return_id))
    cur.execute(payment, (collected_order, "refund", "189.00", return_id))
    violates("br14_refund_once_per_return", payment, (collected_order, "refund", "10.00", return_id))


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


# ---------------------------------------------------------------- views

def test_current_price_includes_the_running_promotion(cur):
    cur.execute("""SELECT p.sku, v.current_price FROM v_product_current_price v JOIN product p USING (product_id)
                   WHERE p.sku IN ('SONY-WH1000XM5-B', 'LEN-TABM11-128', 'SONY-PS5-SLIM-DISC') ORDER BY p.sku""")
    assert [(row["sku"], str(row["current_price"])) for row in cur.fetchall()] == [
        ("LEN-TABM11-128", "349.00"),        # no promotion
        ("SONY-PS5-SLIM-DISC", "799.95"),    # promotion not started yet
        ("SONY-WH1000XM5-B", "399.00"),      # running promotion (an older, ended one is ignored)
    ]

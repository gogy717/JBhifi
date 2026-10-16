"""The seed's pg_temp helpers (scripts/seed_helpers.sql): each one replays what its service does — T1 checkout, a
status move, T4 cancel, T3 stock received — at a named time, through every rule.

They run inside the test's own transaction (the `cur` fixture), so the helpers and everything they write are rolled
back afterwards. Explicit order ids start at 900001, far from the ids that committed tests take from the sequence.
"""
from decimal import Decimal
from pathlib import Path

import pytest

HELPERS = Path(__file__).resolve().parent.parent / "scripts" / "seed_helpers.sql"
AIDEN, ZARA, ISLA = 14, 15, 16          # Aiden and Zara work at Sydney CBD (store 1); Isla at Bondi Junction


@pytest.fixture
def seed(cur):
    """The test's cursor with the helpers loaded, in the seed's time zone (the anchor is Sydney midnight)."""
    cur.execute("SET LOCAL timezone = 'Australia/Sydney'")
    cur.execute(HELPERS.read_text())
    return cur


def one(cur, query, params=()):
    cur.execute(query, params)
    return cur.fetchone()


def at(seed, days, minutes):
    return one(seed, "SELECT pg_temp.seed_at(%s, %s) AS t", (days, minutes))["t"]


def a_customer(seed, email="seed.helper@example.com", *, days=30):
    seed.execute("""SELECT pg_temp.seed_customer(%s, 'Seed Helper', NULL, pg_temp.seed_at(%s, 600),
                                                 '1 Test St', 'Sydney', 'NSW', '2000')""", (email, days))
    return email


def placed(seed, order_id, email, *, days, minutes=600, method="click_collect", store=1, address=None):
    seed.execute("SELECT pg_temp.seed_order(%s, %s, gen_random_uuid(), %s, %s, %s, pg_temp.seed_at(%s, %s))",
                 (order_id, email, method, store, address, days, minutes))


def checkout(seed, order_id, email, *, days, minutes=600, lines=(("APL-AP4", 1),), **header):
    """seed_order, its lines (numbered as listed), then seed_pay: one order checked out at that time."""
    placed(seed, order_id, email, days=days, minutes=minutes, **header)
    for line_no, (sku, quantity) in enumerate(lines, start=1):
        seed.execute("SELECT pg_temp.seed_line(%s, %s, %s, %s)", (order_id, line_no, sku, quantity))
    seed.execute("SELECT pg_temp.seed_pay(%s)", (order_id,))


def stock(seed, store_id, sku):
    return one(seed, """SELECT i.quantity FROM inventory i JOIN product p USING (product_id)
                        WHERE i.store_id = %s AND p.sku = %s""", (store_id, sku))["quantity"]


def history(seed, order_id):
    seed.execute("""SELECT from_status, to_status, changed_by_staff_id, changed_at FROM order_status_history
                    WHERE order_id = %s ORDER BY seq""", (order_id,))
    return [tuple(row.values()) for row in seed.fetchall()]


def payments(seed, order_id):
    seed.execute("SELECT kind, amount, created_at FROM payment WHERE order_id = %s ORDER BY payment_id", (order_id,))
    return [tuple(row.values()) for row in seed.fetchall()]


def test_seed_at_is_local_time_before_the_anchor(seed):
    t = at(seed, 20, 615)
    row = one(seed, """SELECT %s::timestamptz < date_trunc('day', now()) AS before_anchor,
                              to_char(%s::timestamptz, 'HH24:MI') AS clock""", (t, t))
    assert (row["before_anchor"], row["clock"]) == (True, "10:15")      # 20 days before Sydney midnight, 10:15


def test_a_seeded_checkout_is_paid_at_its_time_through_the_rules(seed):
    email = a_customer(seed, days=30)
    before = stock(seed, 1, "JBL-FLIP7-B")
    checkout(seed, 900001, email, days=20, minutes=615, lines=[("JBL-FLIP7-B", 2)])
    t = at(seed, 20, 615)

    assert one(seed, "SELECT created_at FROM customer WHERE email = %s", (email,))["created_at"] == at(seed, 30, 600)
    order = one(seed, "SELECT status, placed_at FROM customer_order WHERE order_id = 900001")
    assert (order["status"], order["placed_at"]) == ("paid", t)
    assert history(seed, 900001) == [(None, "placed", None, t), ("placed", "paid", None, t)]
    base = one(seed, "SELECT base_price FROM product WHERE sku = 'JBL-FLIP7-B'")["base_price"]
    assert payments(seed, 900001) == [("charge", 2 * base, t)]          # one charge of the total, at placed_at
    assert stock(seed, 1, "JBL-FLIP7-B") == before - 2


def test_a_line_is_priced_by_the_promotion_running_when_it_was_placed(seed):
    # The reference seed's promotions are relative to its build date: this headset was 449.00 from 60 to 30 days
    # ago, and is 399.00 from 7 days ago.
    email = a_customer(seed, days=90)
    for order_id, days in ((900002, 45), (900003, 20), (900004, 3)):
        checkout(seed, order_id, email, days=days, lines=[("SONY-WH1000XM5-B", 1)])
    base = one(seed, "SELECT base_price FROM product WHERE sku = 'SONY-WH1000XM5-B'")["base_price"]
    seed.execute("""SELECT o.order_id, l.unit_price FROM order_line l JOIN customer_order o USING (order_id)
                    WHERE o.order_id IN (900002, 900003, 900004) ORDER BY o.order_id""")
    assert [row["unit_price"] for row in seed.fetchall()] == [Decimal("449.00"), base, Decimal("399.00")]


def test_seeded_moves_and_a_cancel_follow_the_rules(seed):
    email = a_customer(seed)
    before = stock(seed, 1, "APL-AP4")
    checkout(seed, 900005, email, days=10)
    seed.execute("SELECT pg_temp.seed_move(900005, 'picking', pg_temp.seed_at(10, 700), %s)", (AIDEN,))
    seed.execute("SELECT pg_temp.seed_move(900005, 'ready', pg_temp.seed_at(10, 800), %s)", (ZARA,))
    seed.execute("SELECT pg_temp.seed_cancel(900005, pg_temp.seed_at(2, 600), %s)", (AIDEN,))   # not collected

    assert [row[:3] for row in history(seed, 900005)][2:] == [
        ("paid", "picking", AIDEN), ("picking", "ready", ZARA), ("ready", "cancelled", AIDEN)]
    assert [row[3] for row in history(seed, 900005)][2:] == [at(seed, 10, 700), at(seed, 10, 800), at(seed, 2, 600)]
    charge, refund = payments(seed, 900005)
    assert (refund[0], refund[1], refund[2]) == ("refund", charge[1], at(seed, 2, 600))
    assert stock(seed, 1, "APL-AP4") == before                          # back on the shelf

    checkout(seed, 900006, email, days=4)
    seed.execute("SELECT pg_temp.seed_cancel(900006, pg_temp.seed_at(4, 700), NULL)")   # the customer's own
    assert history(seed, 900006)[-1][:3] == ("paid", "cancelled", None)
    assert one(seed, "SELECT balance FROM v_order_payment WHERE order_id = 900006")["balance"] == 0


def test_a_seeded_delivery_is_logged_like_t3(seed):
    before = stock(seed, 1, "APL-AP4")
    seed.execute("SELECT pg_temp.seed_receive(1, 'APL-AP4', 8, %s, pg_temp.seed_at(5, 540))", (AIDEN,))
    assert stock(seed, 1, "APL-AP4") == before + 8
    row = one(seed, """SELECT a.staff_id, a.delta, a.reason, a.quantity_after, a.adjusted_at
                       FROM stock_adjustment a JOIN product p USING (product_id)
                       WHERE a.store_id = 1 AND p.sku = 'APL-AP4' ORDER BY a.adjustment_id DESC LIMIT 1""")
    assert tuple(row.values()) == (AIDEN, 8, "received", before + 8, at(seed, 5, 540))


def test_the_seed_cannot_break_a_rule(seed, violates):
    email = a_customer(seed)
    checkout(seed, 900007, email, days=10)
    violates("br09_order_status_transition", "SELECT pg_temp.seed_move(900007, 'collected', pg_temp.seed_at(9, 0), 14)")
    placed(seed, 900008, email, days=9)
    violates("br03_inventory_qty_nonneg", "SELECT pg_temp.seed_line(900008, 1, 'APL-AP4', 100000)")
    violates("br18_adjustment_staff_at_store",
             "SELECT pg_temp.seed_receive(1, 'APL-AP4', 5, %s, pg_temp.seed_at(9, 0))", (ISLA,))
    seed.execute("SELECT pg_temp.seed_address(%s, 2, '2 New St', 'Newtown', 'NSW', '2042')", (email,))
    seed.execute("SELECT pg_temp.seed_retire_address(%s, 1)", (email,))
    violates("br17_order_address_active",
             """SELECT pg_temp.seed_order(900009, %s, gen_random_uuid(), 'delivery', 13, 1,
                                          pg_temp.seed_at(8, 0))""", (email,))

"""The generated seed (sql/20_seed_generated.sql), loaded into a database of its own: <POSTGRES_TEST_DB>_seed.

Loading it is already the main evidence: every one of its ~1,500 orders went through every rule (BR03, BR06–BR10,
BR14, BR16–BR18, BR20, BR21), with no trigger disabled. These tests then check what no single rule sees: the
history checks over every order, money against status, the timeline itself, and that the stock adds up (spec §5).
A delivery's address being current when it was placed is BR17's to refuse while loading: customer_address keeps
no retirement time to check afterwards.

scripts/generate_seed.py uses the same database: don't run the two at the same time.
"""
import pytest

from scripts import generate_seed as gen
from tests.seed_support import ANCHORS, TIMELINE_CHECKS
from tests.test_business_rules import HISTORY_CHECKS, history_breaks


@pytest.fixture(scope="module")
def seeded(seeded_db):
    """The seeded database, loaded once per test run (conftest.py, tests/seed_support.py). Yields (cursor, opening
    stock, regenerated text, seconds to load, {anchor: timeline breaks})."""
    return seeded_db


def rows(cur, query, params=()):
    cur.execute(query, params)
    return cur.fetchall()


def test_the_committed_file_is_what_the_generator_writes(seeded):
    _, _, regenerated, loaded_in, _ = seeded
    print(f"\nseed loaded in {loaded_in:.1f} s")
    assert gen.SEED_FILE.read_text(encoding="utf-8") == regenerated, "run: python scripts/generate_seed.py"


def test_the_checks_are_planned_on_the_loaded_rows(seeded):
    """The replays above insert and roll back thousands of rows, so autovacuum may ANALYZE these tables while they
    are empty; planned on those statistics (0 rows), the checks below take minutes instead of milliseconds."""
    assert rows(seeded[0], "SELECT reltuples FROM pg_class WHERE relname = 'customer_order'") \
        == [{"reltuples": gen.ORDERS}]


def test_the_history_checks_find_nothing(seeded):
    cur = seeded[0]
    assert history_breaks(cur) == {condition: [] for condition in HISTORY_CHECKS}


def test_money_matches_every_orders_status(seeded):
    cur = seeded[0]
    assert rows(cur, "SELECT order_id FROM customer_order WHERE status = 'placed'") == []   # T1 always pays
    # An order that wasn't cancelled was charged its total and refunded exactly its refunded returns' worth.
    assert rows(cur, """SELECT o.order_id FROM customer_order o
                        JOIN v_order_total t USING (order_id) JOIN v_order_payment p USING (order_id)
                        LEFT JOIN (SELECT r.order_id, sum(v.value) AS value
                                   FROM return_request r JOIN v_return_value v USING (return_id)
                                   WHERE r.status = 'refunded' GROUP BY r.order_id) back USING (order_id)
                        WHERE o.status <> 'cancelled'
                          AND (p.charged <> t.total OR p.refunded <> COALESCE(back.value, 0))""") == []
    assert rows(cur, """SELECT order_id FROM customer_order JOIN v_order_payment USING (order_id)
                        WHERE status = 'cancelled' AND balance <> 0""") == []


def test_every_orders_timeline_runs_forward_from_its_placing(seeded):
    cur = seeded[0]
    assert rows(cur, """SELECT h.order_id FROM order_status_history h JOIN customer_order o USING (order_id)
                        WHERE h.seq = 1 AND h.changed_at <> o.placed_at""") == []
    assert rows(cur, """SELECT h.order_id FROM order_status_history h
                        JOIN order_status_history next ON next.order_id = h.order_id AND next.seq = h.seq + 1
                        WHERE next.changed_at < h.changed_at""") == []
    assert rows(cur, """SELECT p.order_id FROM payment p JOIN customer_order o USING (order_id)
                        WHERE p.kind = 'charge' AND p.created_at <> o.placed_at""") == []
    assert rows(cur, """SELECT c.customer_id FROM customer c JOIN customer_order o USING (customer_id)
                        GROUP BY c.customer_id, c.created_at HAVING c.created_at >= min(o.placed_at)""") == []


def test_nothing_is_dated_after_now(seeded):
    cur = seeded[0]
    latest = rows(cur, """SELECT greatest((SELECT max(created_at) FROM customer), (SELECT max(placed_at) FROM customer_order),
                                         (SELECT max(changed_at) FROM order_status_history),
                                         (SELECT max(created_at) FROM payment),
                                         (SELECT max(adjusted_at) FROM stock_adjustment),
                                         (SELECT max(greatest(requested_at, received_at, resolved_at))
                                          FROM return_request)) < now() AS past""")
    assert latest == [{"past": True}]


def test_the_stock_adds_up(seeded):
    cur, opening = seeded[0], seeded[1]
    received = {(r["store_id"], r["product_id"]): r["n"] for r in rows(cur, """
        SELECT store_id, product_id, sum(delta) AS n FROM stock_adjustment GROUP BY store_id, product_id""")}
    sold = {(r["store_id"], r["product_id"]): r["n"] for r in rows(cur, """
        SELECT o.fulfilling_store_id AS store_id, l.product_id, sum(l.quantity) AS n
        FROM order_line l JOIN customer_order o USING (order_id)
        WHERE o.status <> 'cancelled' GROUP BY 1, 2""")}
    returned = {(r["store_id"], r["product_id"]): r["n"] for r in rows(cur, """
        SELECT r.received_store_id AS store_id, ol.product_id, sum(rl.quantity) AS n
        FROM return_request r JOIN return_line rl USING (return_id)
        JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no
        WHERE r.status = 'refunded' GROUP BY 1, 2""")}            # T2 restocks where the return came in
    now = {(r["store_id"], r["product_id"]): r["quantity"] for r in rows(cur, "SELECT * FROM inventory")}
    expected = {key: quantity + received.get(key, 0) - sold.get(key, 0) + returned.get(key, 0)
                for key, quantity in opening.items()}
    assert now == expected
    assert received and min(now.values()) == 0                     # deliveries were needed; some shelves are empty


def test_the_scripted_scenarios_are_there(seeded):
    cur = seeded[0]
    alice = rows(cur, """SELECT o.fulfilment_method AS method, o.status,
                                (date_trunc('day', now() AT TIME ZONE 'Australia/Sydney')::date
                                 - (o.placed_at AT TIME ZONE 'Australia/Sydney')::date) AS days
                         FROM customer_order o JOIN customer c USING (customer_id)
                         WHERE c.email = %s""", (gen.ALICE,))
    assert {("delivery", "delivered", 45), ("click_collect", "collected", 7), ("click_collect", "ready", 2),
            ("click_collect", "paid", 1)} <= {(r["method"], r["status"], r["days"]) for r in alice}
    assert rows(cur, "SELECT customer_id FROM customer WHERE email = %s", (gen.ALICE,)) == [{"customer_id": 1}]
    queue = [r["status"] for r in rows(cur, """SELECT status FROM customer_order
                                              WHERE fulfilling_store_id = 1 AND placed_at > now() - interval '3 days'""")]
    assert queue.count("paid") >= 4 and queue.count("picking") >= 3
    for email, status in ((gen.BEN, "cancelled"), (gen.MEI, "shipped")):
        assert status in [r["status"] for r in rows(cur, """SELECT status FROM customer_order
                                                            JOIN customer USING (customer_id) WHERE email = %s""",
                                                    (email,))]


def test_the_seed_has_the_planned_size(seeded):
    cur = seeded[0]
    counts = rows(cur, """SELECT (SELECT count(*) FROM customer) AS customers,
                                 (SELECT count(*) FROM customer_order) AS orders,
                                 (SELECT count(*) FROM customer_order WHERE status = 'cancelled') AS cancelled,
                                 (SELECT count(*) FROM customer_address WHERE NOT is_active) AS retired""")[0]
    assert (counts["customers"], counts["orders"]) == (gen.CUSTOMERS + 4, gen.ORDERS)
    assert 0.02 <= counts["cancelled"] / counts["orders"] <= 0.07
    assert counts["retired"] > 10
    # The API's next order and customer don't collide with seeded ids.
    assert rows(cur, "SELECT last_value FROM customer_order_order_id_seq") == [{"last_value": gen.ORDERS}]



@pytest.mark.parametrize("anchor", ANCHORS)
def test_the_timeline_holds_on_whatever_day_it_is_loaded(seeded, anchor):
    assert seeded[4][anchor] == {check: [] for check in TIMELINE_CHECKS}



def test_returns_are_in_every_state_and_refunded_at_what_they_are_worth(seeded):
    cur = seeded[0]
    states = {r["status"]: r["n"] for r in rows(cur, "SELECT status, count(*) AS n FROM return_request GROUP BY 1")}
    assert set(states) == {"requested", "received", "refunded", "rejected"}
    completed = rows(cur, "SELECT count(*) AS n FROM customer_order WHERE status IN ('delivered', 'collected')")[0]["n"]
    assert 0.03 <= sum(states.values()) / completed <= 0.10
    # A refunded return has exactly one refund, of its value, made when it was resolved; no other return has any.
    assert rows(cur, """SELECT r.return_id FROM return_request r JOIN v_return_value v USING (return_id)
                        LEFT JOIN payment p ON p.return_id = r.return_id
                        WHERE (r.status = 'refunded' AND v.value > 0)
                                  <> (p.payment_id IS NOT NULL AND p.amount = v.value AND p.created_at = r.resolved_at)
                        """) == []
    partial = rows(cur, """SELECT count(*) AS n FROM v_return_value v JOIN customer_order o USING (order_id)
                           JOIN (SELECT order_id, sum(quantity) AS bought FROM order_line GROUP BY 1) b USING (order_id)
                           WHERE v.quantity < b.bought""")[0]["n"]
    assert partial >= 3


def test_sydney_cbd_has_returns_for_its_reports(seeded):
    """SP4's return rate counts non-rejected returns of the store's sales placed in the last 30 or 90 days."""
    cur = seeded[0]
    for days, least in ((30, 2), (90, 4)):
        found = rows(cur, """SELECT count(DISTINCT r.return_id) AS n
                             FROM return_request r JOIN v_sale_line s ON s.order_id = r.order_id
                             WHERE s.store_id = 1 AND r.status <> 'rejected' AND s.placed_at > now() - %s * interval '1 day'
                          """, (days,))[0]["n"]
        assert found >= least, (days, found)


def test_the_scripted_returns_are_there(seeded):
    cur = seeded[0]
    alice = rows(cur, """SELECT r.status, r.reason FROM return_request r JOIN customer_order o USING (order_id)
                         JOIN customer c USING (customer_id) WHERE c.email = %s""", (gen.ALICE,))
    assert {"status": "requested", "reason": "Changed my mind"} in [dict(r) for r in alice]
    waiting = rows(cur, """SELECT return_id FROM return_request
                           WHERE status = 'received' AND received_store_id = 1 AND processed_by_staff_id = 14""")
    assert waiting
    # The API's next return doesn't collide with seeded ids either.
    assert rows(cur, "SELECT last_value = (SELECT max(return_id) FROM return_request) AS ok FROM return_request_return_id_seq") \
        == [{"ok": True}]

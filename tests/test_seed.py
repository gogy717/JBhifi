"""The generated seed (sql/20_seed_generated.sql), loaded into a database of its own: <POSTGRES_TEST_DB>_seed.

Loading it is already the main evidence: every one of its ~1,500 orders went through every rule (BR03, BR06–BR10,
BR14, BR16–BR18, BR20, BR21), with no trigger disabled. These tests then check what no single rule sees: the
history checks over every order, money against status, the timeline itself, and that the stock adds up (spec §5).
A delivery's address being current when it was placed is BR17's to refuse while loading: customer_address keeps
no retirement time to check afterwards.

scripts/generate_seed.py uses the same database: don't run the two at the same time.
"""
import time

import pytest

from scripts import generate_seed as gen
from tests.test_business_rules import HISTORY_CHECKS, history_breaks


@pytest.fixture(scope="module")
def seeded():
    """Build the database from the hand-written files, note the stock and what the generator would write now,
    then load the committed seed file. Yields (cursor, opening stock, regenerated text, seconds to load)."""
    dbname = gen.seed_database()
    gen.build_reference_database(dbname)
    conn = gen.connect(dbname)
    conn.autocommit = True                              # the file has its own BEGIN … COMMIT
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT store_id, product_id, quantity FROM inventory")
            opening = {(row["store_id"], row["product_id"]): row["quantity"] for row in cur.fetchall()}
            regenerated = gen.render(gen.plan(gen.read_reference(cur)))
            started = time.monotonic()
            cur.execute(gen.SEED_FILE.read_text())
            loaded_in = time.monotonic() - started
            yield cur, opening, regenerated, loaded_in
    finally:
        conn.close()


def rows(cur, query, params=()):
    cur.execute(query, params)
    return cur.fetchall()


def test_the_committed_file_is_what_the_generator_writes(seeded):
    _, _, regenerated, loaded_in = seeded
    print(f"\nseed loaded in {loaded_in:.1f} s")
    assert gen.SEED_FILE.read_text() == regenerated, "run: python scripts/generate_seed.py"


def test_the_history_checks_find_nothing(seeded):
    cur = seeded[0]
    assert history_breaks(cur) == {condition: [] for condition in HISTORY_CHECKS}


def test_money_matches_every_orders_status(seeded):
    cur = seeded[0]
    assert rows(cur, "SELECT order_id FROM customer_order WHERE status = 'placed'") == []   # T1 always pays
    assert rows(cur, """SELECT o.order_id FROM customer_order o
                        JOIN v_order_total t USING (order_id) JOIN v_order_payment p USING (order_id)
                        WHERE o.status <> 'cancelled' AND (p.charged <> t.total OR p.refunded <> 0)""") == []
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
                                         (SELECT max(adjusted_at) FROM stock_adjustment)) < now() AS past""")
    assert latest == [{"past": True}]


def test_the_stock_adds_up(seeded):
    cur, opening = seeded[0], seeded[1]
    received = {(r["store_id"], r["product_id"]): r["n"] for r in rows(cur, """
        SELECT store_id, product_id, sum(delta) AS n FROM stock_adjustment GROUP BY store_id, product_id""")}
    sold = {(r["store_id"], r["product_id"]): r["n"] for r in rows(cur, """
        SELECT o.fulfilling_store_id AS store_id, l.product_id, sum(l.quantity) AS n
        FROM order_line l JOIN customer_order o USING (order_id)
        WHERE o.status <> 'cancelled' GROUP BY 1, 2""")}
    now = {(r["store_id"], r["product_id"]): r["quantity"] for r in rows(cur, "SELECT * FROM inventory")}
    expected = {key: quantity + received.get(key, 0) - sold.get(key, 0) for key, quantity in opening.items()}
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

"""Loading the generated seed (sql/20_seed_generated.sql) into its own database, <POSTGRES_TEST_DB>_seed, for the
tests that need realistic data: tests/test_seed.py checks the data itself, tests/test_indexes.py the query plans on
it. conftest.py loads it once per test run (the seeded_db fixture).

scripts/generate_seed.py uses the same database: don't run the two at the same time.
"""
import time

from scripts import generate_seed as gen


# Load dates the timeline must survive: the days after daylight saving starts (4 Oct 2026) and ends (4 Apr 2027),
# the submission weekend, and a day that once put a collection before its ready.
ANCHORS = ["2026-10-05", "2026-10-25", "2026-11-09", "2027-04-05"]

# What must hold whatever day the file is loaded: each a query returning the rows that break it.
TIMELINE_CHECKS = {
    "history runs forward": """
        SELECT h.order_id FROM order_status_history h
        JOIN order_status_history next ON next.order_id = h.order_id AND next.seq = h.seq + 1
        WHERE next.changed_at < h.changed_at""",
    "orders are placed 08:00-21:59": """
        SELECT order_id FROM customer_order WHERE extract(hour FROM placed_at) NOT BETWEEN 8 AND 21""",
    "staff move orders 09:00-20:59": """
        SELECT order_id FROM order_status_history
        WHERE changed_by_staff_id IS NOT NULL AND extract(hour FROM changed_at) NOT BETWEEN 9 AND 20""",
    "everything is before the anchor": """
        SELECT order_id FROM order_status_history WHERE changed_at >= current_setting('seed.anchor')::date""",
    "returns run forward": """
        SELECT order_id FROM return_request
        WHERE received_at <= requested_at OR resolved_at <= received_at
           OR greatest(requested_at, received_at, resolved_at) >= current_setting('seed.anchor')::date""",
    "staff take returns in 09:00-20:59": """
        SELECT order_id FROM return_request
        WHERE extract(hour FROM received_at) NOT BETWEEN 9 AND 20 OR extract(hour FROM resolved_at) NOT BETWEEN 9 AND 20""",
}


def timeline_breaks(cur, text: str, anchor: str) -> dict:
    """Load the seed as if on `anchor`, inside a transaction that is rolled back (the file's own BEGIN and COMMIT
    are left out, so the deferred BR07 check doesn't run; the real load covers it), and run TIMELINE_CHECKS."""
    cur.execute("BEGIN")
    try:
        cur.execute("SET LOCAL timezone = 'Australia/Sydney'")
        cur.execute("SELECT set_config('seed.anchor', %s, true)", (anchor,))
        cur.execute(text.replace("\nBEGIN;\n", "\n", 1).replace("\nCOMMIT;\n", "\n", 1))
        cur.execute("ANALYZE")             # statistics of the rows just loaded (rolled back with them), not stale ones
        found = {}
        for check, query in TIMELINE_CHECKS.items():
            cur.execute(query)
            found[check] = [row["order_id"] for row in cur.fetchall()][:5]
        return found
    finally:
        cur.execute("ROLLBACK")


def load_seed():
    """Build the database from the hand-written files; note the stock and what the generator would write now; replay
    the committed file as of each of ANCHORS (rolled back); then load it for real. Yields (cursor, opening stock,
    regenerated text, seconds to load, {anchor: timeline breaks})."""
    dbname = gen.seed_database()
    gen.build_reference_database(dbname)
    conn = gen.connect(dbname)
    conn.autocommit = True                              # the file has its own BEGIN … COMMIT
    text = gen.SEED_FILE.read_text(encoding="utf-8")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT store_id, product_id, quantity FROM inventory")
            opening = {(row["store_id"], row["product_id"]): row["quantity"] for row in cur.fetchall()}
            regenerated = gen.render(gen.plan(gen.read_reference(cur)))
            anchored = {anchor: timeline_breaks(cur, text, anchor) for anchor in ANCHORS}
            started = time.monotonic()
            cur.execute(text)
            loaded_in = time.monotonic() - started
            # The replays inserted and rolled back thousands of rows, which can make autovacuum ANALYZE these tables
            # while they are empty; fresh statistics keep the checks' plans fit for 1,500 orders.
            cur.execute("ANALYZE")
            yield cur, opening, regenerated, loaded_in, anchored
    finally:
        conn.close()

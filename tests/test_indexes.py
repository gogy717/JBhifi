"""The indexes in sql/05_indexes.sql (optional, beyond Week 10 — Weeks 11–12, plan T-8; docs/indexes-explain.md):
they exist as defined, and the planner can use each one for the SQL its service really sends.

How "can use" is tested. The test database doesn't load the generated seed, so its tables are tiny and the
planner rightly prefers sequential scans: asserting that a plain EXPLAIN uses an index would fail for the right
reason. So each check turns sequential scans off for its own transaction (SET LOCAL enable_seqscan = off). That
doesn't pick an index for the planner — it only removes the sequential-scan option — and the check then asks for
more than the index's name: the query's filter column has to be one of the index's search conditions ("Index
Cond"), not a filter applied afterwards. An index on the wrong column, or a service that stops filtering that way,
fails. The column order is pinned by the definition check alone: tried with (placed_at, fulfilling_store_id), the
planner searched that index on both columns too, so no plan check here can tell the two orders apart
(docs/indexes-explain.md says why the store comes first). Whether the planner chooses the index by itself on
realistic data is shown in
docs/indexes-explain.md, on the seeded dev database. Rejected: loading thousands of rows here (slow, and dependent
on their distribution), and reading pg_stat_user_indexes.idx_scan after the query (statistics are flushed
asynchronously, so the count can lag).

The SQL is captured from the services themselves by a cursor that records what it executes.
"""
from psycopg2.extras import RealDictCursor

from app.auth import Actor
from app.services import fulfilment, orders, reports

SUPPORT = Actor("staff", 40, "Nora Fitzgerald", staff_type="support")
SYDNEY_CBD = 1
# The store checks ask about Robina, a retail store almost no other test orders from. An index is for a selective
# filter: most of the orders other tests commit are at Sydney CBD, and for a store holding nearly every order the
# planner is right to estimate a full read of the primary key index as cheaper (seen in a full run).
ROBINA = 12


class Recording(RealDictCursor):
    """A cursor that keeps every statement it runs, with its parameters filled in."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.statements = []

    def execute(self, query, params=None):
        self.statements.append(self.mogrify(query, params).decode())
        return super().execute(query, params)


def sent_by(db, work, marker: str) -> str:
    """The one statement that work(cur) sends containing marker (compared with runs of spaces made single)."""
    with db.cursor(cursor_factory=Recording) as cur:
        work(cur)
        found = [statement for statement in cur.statements if marker in " ".join(statement.split())]
    assert len(found) == 1, found
    return found[0]


def index_conditions(cur, statement: str) -> dict[str, list[str]]:
    """Every index the plan for statement uses, with its search conditions ("Index Cond"), with sequential scans
    off for this transaction only."""
    cur.execute("SET LOCAL enable_seqscan = off")
    cur.execute("EXPLAIN (FORMAT JSON) " + statement)
    found, nodes = {}, [cur.fetchone()["QUERY PLAN"][0]["Plan"]]
    while nodes:
        node = nodes.pop()
        if "Index Name" in node:
            found.setdefault(node["Index Name"], []).append(node.get("Index Cond", ""))
        nodes.extend(node.get("Plans", []))
    return found


def searches_by(cur, statement: str, index: str, column: str) -> bool:
    """Does the plan look rows up through index by column (an Index Cond on it), rather than filter afterwards?
    On failure, the message lists the indexes the plan did use."""
    used = index_conditions(cur, statement)
    assert any(column in condition for condition in used.get(index, [])), used
    return True


def an_order(cur) -> int:
    """A Click & Collect order with one line, inside the test's transaction (rolled back afterwards)."""
    cur.execute("INSERT INTO customer (email, full_name) VALUES ('index.test@example.com', 'Index Test') "
                "RETURNING customer_id")
    customer_id = cur.fetchone()["customer_id"]
    cur.execute("""INSERT INTO customer_order (customer_id, idempotency_key, fulfilment_method, fulfilling_store_id)
                   VALUES (%s, gen_random_uuid(), 'click_collect', %s) RETURNING order_id""", (customer_id, SYDNEY_CBD))
    order_id = cur.fetchone()["order_id"]
    cur.execute("""INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price)
                   SELECT %s, 1, product_id, 1, base_price FROM product WHERE sku = 'APL-AP4'""", (order_id,))
    return order_id


def test_the_indexes_exist_as_defined(cur):
    cur.execute("""SELECT indexname, indexdef FROM pg_indexes
                   WHERE indexname IN ('customer_order_store_placed_idx', 'payment_order_idx') ORDER BY indexname""")
    assert [(row["indexname"], row["indexdef"]) for row in cur.fetchall()] == [
        ("customer_order_store_placed_idx",
         "CREATE INDEX customer_order_store_placed_idx ON public.customer_order USING btree (fulfilling_store_id, placed_at)"),
        ("payment_order_idx", "CREATE INDEX payment_order_idx ON public.payment USING btree (order_id)"),
    ]


def test_the_store_queue_can_use_the_store_and_date_index(db, cur):
    statement = sent_by(db, lambda c: fulfilment.list_store_orders(c, SUPPORT, ROBINA, ["paid", "picking", "ready"]),
                        "FROM v_order_summary")
    assert searches_by(cur, statement, "customer_order_store_placed_idx", "fulfilling_store_id")


def test_the_store_report_can_use_the_store_and_date_index(db, cur):
    statement = sent_by(db, lambda c: reports.build_store_report(c, ROBINA, 30),
                        "count(DISTINCT order_id) AS orders")             # the sales total section
    assert searches_by(cur, statement, "customer_order_store_placed_idx", "fulfilling_store_id")


def test_an_orders_payments_can_use_the_payment_index(db, cur):
    order_id = an_order(cur)
    statement = sent_by(db, lambda c: orders.get_order(c, SUPPORT, order_id), "FROM v_order_payment")
    assert searches_by(cur, statement, "payment_order_idx", "order_id")

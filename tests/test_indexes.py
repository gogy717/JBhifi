"""The indexes in sql/05_indexes.sql (optional, beyond Week 10 — Weeks 11–12, plan T-8; docs/indexes-explain.md):
they exist as defined, and on realistic data the planner chooses each one, by itself, for the SQL its service
really sends.

The plan checks run on the generated seed (the seeded_db fixture: 1,500 orders, loaded once per test run and
ANALYZEd straight after). Its statistics are the same every run: the data is deterministic, and every table is
smaller than ANALYZE's default sample (30,000 rows), so each one is read whole. So the planner's choice is the
same every run too, and the checks need no hints. They ask for more than the index's name: the query's filter
column has to be the index's search condition ("Index Cond"), not a filter applied afterwards, so an index on the
wrong column, or a service that stops filtering that way, fails. The column order is pinned by the definition
check alone: tried with (placed_at, fulfilling_store_id), the planner searched that index on both columns too
(docs/indexes-explain.md says why the store comes first).

Not on the ordinary test database: it has no generated seed, and what the planner picks for its tiny tables
depends on statistics that autovacuum may or may not have refreshed by then, and on whatever rows earlier tests
committed — the store checks, run there, failed now and then (the plan read the whole primary key index instead).

The SQL is captured from the services themselves by a cursor that records what it executes.
"""
import pytest
from psycopg2.extras import RealDictCursor

from app.auth import Actor
from app.services import fulfilment, orders, reports

SUPPORT = Actor("staff", 40, "Nora Fitzgerald", staff_type="support")
STORE = 10              # a retail store, with 132 of the seed's orders: the store measured in docs/indexes-explain.md
ORDER = 700             # a seeded order with payments, also the one measured there


class Recording(RealDictCursor):
    """A cursor that keeps every statement it runs, with its parameters filled in."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.statements = []

    def execute(self, query, params=None):
        self.statements.append(self.mogrify(query, params).decode())
        return super().execute(query, params)


def sent_by(conn, work, marker: str) -> str:
    """The one statement that work(cur) sends containing marker (compared with runs of spaces made single)."""
    with conn.cursor(cursor_factory=Recording) as cur:
        work(cur)
        found = [statement for statement in cur.statements if marker in " ".join(statement.split())]
    assert len(found) == 1, found
    return found[0]


def index_conditions(cur, statement: str) -> dict[str, list[str]]:
    """Every index the plan for statement uses, with its search conditions ("Index Cond")."""
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


@pytest.fixture
def seed(seeded_db):
    """A cursor on the seeded database (autocommit: these checks only read)."""
    return seeded_db[0]


def test_the_indexes_exist_as_defined(cur):
    cur.execute("""SELECT indexname, indexdef FROM pg_indexes
                   WHERE indexname IN ('customer_order_store_placed_idx', 'payment_order_idx') ORDER BY indexname""")
    assert [(row["indexname"], row["indexdef"]) for row in cur.fetchall()] == [
        ("customer_order_store_placed_idx",
         "CREATE INDEX customer_order_store_placed_idx ON public.customer_order USING btree (fulfilling_store_id, placed_at)"),
        ("payment_order_idx", "CREATE INDEX payment_order_idx ON public.payment USING btree (order_id)"),
    ]


def test_the_planner_chooses_the_store_and_date_index_for_the_store_queue(seed):
    statement = sent_by(seed.connection, lambda c: fulfilment.list_store_orders(c, SUPPORT, STORE, ["paid", "picking", "ready"]),
                        "FROM v_order_summary")
    assert searches_by(seed, statement, "customer_order_store_placed_idx", "fulfilling_store_id")


def test_the_planner_chooses_the_store_and_date_index_for_the_store_report(seed):
    statement = sent_by(seed.connection, lambda c: reports.build_store_report(c, STORE, 30),
                        "count(DISTINCT order_id) AS orders")             # the sales total section
    assert searches_by(seed, statement, "customer_order_store_placed_idx", "fulfilling_store_id")


def test_the_planner_chooses_the_payment_index_for_an_orders_payments(seed):
    statement = sent_by(seed.connection, lambda c: orders.get_order(c, SUPPORT, ORDER), "FROM v_order_payment")
    assert searches_by(seed, statement, "payment_order_idx", "order_id")

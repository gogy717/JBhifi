"""Re-measure docs/indexes-explain.md: the hot queries' plans and timings on the dev database.

    .venv/bin/python scripts/explain_hot_queries.py              (plans and timings; reads only)
    .venv/bin/python scripts/explain_hot_queries.py --compare    (with and without sql/05_indexes.sql's indexes)

Connects only to POSTGRES_DB in .env, which should hold the generated seed (scripts/reset_db.py) and fresh
statistics: run ANALYZE once after loading it (psql: ANALYZE;), as the document's measurements were.

The SQL measured is what the services really send: each service function runs with a cursor that records its
statements, and each statement then runs under EXPLAIN (ANALYZE, BUFFERS) — the fastest of 7 runs, warm cache.
The queries only read; get_order's read takes its usual FOR SHARE lock while it runs.

--compare drops the two indexes inside a savepoint and restores them (ROLLBACK TO SAVEPOINT; the whole run ends in
ROLLBACK), alternating with and without on one connection, three rounds each: separate sessions drift by more than
most of the differences. Nothing is left changed, but while it runs it holds an exclusive lock on customer_order
and payment, so don't run it while you use the app.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                           # import the app's services, as the API does

import psycopg2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

from app.auth import Actor  # noqa: E402
from app.services import fulfilment, orders, reports, returns, support  # noqa: E402

SUPPORT = Actor("staff", 40, "Nora Fitzgerald", staff_type="support")
CUSTOMER, STORE, RETURNS_CUSTOMER, ORDER = 29, 10, 17, 700     # the seed's busiest customer, a retail store, …
INDEXES = ("customer_order_store_placed_idx", "payment_order_idx")
RUNS = 7

# Queries the services send, as (name, work(cur)); each of their statements is measured.
SERVICE_QUERIES = [
    ("Q1 my orders (GET /customers/{id}/orders)", lambda cur: orders.list_customer_orders(cur, SUPPORT, CUSTOMER)),
    ("Q2 store queue (GET /stores/{id}/orders?status=paid,picking,ready)",
     lambda cur: fulfilment.list_store_orders(cur, SUPPORT, STORE, ["paid", "picking", "ready"])),
    ("Q3 store report (GET /stores/{id}/report, 30 days)", lambda cur: reports.build_store_report(cur, STORE, 30)),
    ("Q4 a customer's returns (GET /customers/{id}/returns)",
     lambda cur: returns.list_customer_returns(cur, SUPPORT, RETURNS_CUSTOMER)),
    ("Q5 support history (GET /customers/{id}/history)", lambda cur: support.customer_history(cur, SUPPORT, CUSTOMER)),
]
# Queries inside triggers, copied from sql/02_rules.sql with the order's values filled in.
TRIGGER_QUERIES = [
    ("Q6 BR11 completion time", f"""
        SELECT max(h.changed_at) FROM customer_order o
        JOIN order_status_history h ON h.order_id = o.order_id AND h.to_status = o.status
        WHERE o.order_id = {ORDER} AND o.status IN ('delivered', 'collected')"""),
    ("Q7 BR14 refund cap: one order's payments", f"""
        SELECT COALESCE(sum(CASE WHEN kind = 'charge' THEN amount END), 0),
               COALESCE(sum(CASE WHEN kind = 'refund' THEN amount END), 0)
        FROM payment WHERE order_id = {ORDER} AND payment_id <> 0"""),
]


class Recording(RealDictCursor):
    """A cursor that keeps every statement it runs, with its parameters filled in."""
    statements: list = []

    def execute(self, query, params=None):
        Recording.statements.append(self.mogrify(query, params).decode())
        return super().execute(query, params)


def connect(cursor_factory=RealDictCursor):
    return psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
                            dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
                            password=os.environ["POSTGRES_PASSWORD"], cursor_factory=cursor_factory)


def sent_by(work) -> list[str]:
    """The statements work(cur) sends, without the existence checks and SETs around them."""
    conn = connect(Recording)
    try:
        with conn.cursor() as cur:
            Recording.statements = []
            work(cur)
            return [q for q in Recording.statements if not q.lstrip().upper().startswith(("SELECT 1 FROM", "SET "))]
    finally:
        conn.rollback()
        conn.close()


def fastest(cur, statement: str) -> tuple[float, str]:
    """(execution ms, plan) of the fastest of RUNS runs under EXPLAIN (ANALYZE, BUFFERS)."""
    best = None
    for _ in range(RUNS):
        cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + statement)
        lines = [row["QUERY PLAN"] for row in cur.fetchall()]
        ms = float(next(line for line in lines if line.startswith("Execution Time")).split()[2])
        if best is None or ms < best[0]:
            best = (ms, "\n".join(lines))
    return best


def compared(cur, statement: str) -> dict[str, tuple[float, str]]:
    """The fastest with and without the indexes, alternating three rounds on this connection."""
    runs = {"with": [], "without": []}
    for _ in range(3):
        runs["with"].append(fastest(cur, statement))
        cur.execute("SAVEPOINT without_indexes")
        for index in INDEXES:
            cur.execute(f"DROP INDEX {index}")          # one of the two fixed names above, never user input
        runs["without"].append(fastest(cur, statement))
        cur.execute("ROLLBACK TO SAVEPOINT without_indexes")
    return {way: min(results) for way, results in runs.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="EXPLAIN the hot queries on the dev database.")
    parser.add_argument("--compare", action="store_true", help="also measure without the two indexes (rolled back)")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    measured = [(name, sent_by(work)) for name, work in SERVICE_QUERIES]
    measured += [(name, [query]) for name, query in TRIGGER_QUERIES]
    measured.append(("Q8 GET /orders/{id}: v_order_payment",
                     [q for q in sent_by(lambda cur: orders.get_order(cur, SUPPORT, ORDER)) if "v_order_payment" in q]))

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database() AS db, version() AS version, "
                        "(SELECT count(*) FROM customer_order) AS orders")
            about = cur.fetchone()
            print(f"{about['db']}: {about['orders']} orders; {about['version'].split(' on ')[0]}")
            for name, statements in measured:
                print(f"\n######## {name}")
                for number, statement in enumerate(statements, start=1):
                    print(f"--- statement {number}: {' '.join(statement.split())[:160]}")
                    if args.compare:
                        result = compared(cur, statement)
                        for way in ("without", "with"):
                            ms, plan = result[way]
                            print(f"{way.upper()} indexes, fastest of {3 * RUNS}: {ms:.3f} ms\n{plan}")
                    else:
                        ms, plan = fastest(cur, statement)
                        print(f"fastest of {RUNS}: {ms:.3f} ms\n{plan}")
    finally:
        conn.rollback()                                 # --compare's dropped indexes were already restored
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

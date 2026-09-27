"""Reproducible demonstration data for the JB Hi-Fi prototype.

The reference seed (`sql/10_seed_reference.sql`) supplies stores, staff, the catalogue and four demo
customers. This script adds *scenario* rows on top of it: orders at every stage of both fulfilment paths,
returns in every state, a paid cancellation, a logged stock correction and a deliberately empty-store
checkout example, all positioned relative to one reference time so the demo is reproducible.

Two rules govern how the scenarios are built:

1. They are built with the same statements the application uses — real INSERTs and real status UPDATEs —
   so the triggers that enforce BR03, BR06–BR14 and BR18 run and a scenario cannot reach a state the
   application could not. Nothing is written straight into a status column.
2. Only *recorded times* are shifted afterwards, inside one maintenance transaction: the append-only
   guards on the history, payment and adjustment tables, the order immutability guard and BR11's
   request-time guard are suspended for the single UPDATE that ages a row, then restored before COMMIT.
   `SET CONSTRAINTS ALL IMMEDIATE` then re-checks the deferred BR14 rules, and `reconcile()` recomputes
   stock and money from the rows that were written.

The seeder refuses to run against the demo database named in `POSTGRES_DB` (`jbhifi`): like the pytest
fixtures, it only accepts a disposable name ending in `_demo` or `_test`.

    python scripts/seed_demo.py --database jbhifi_demo --seed 9120
    python scripts/seed_demo.py --database jbhifi_demo --reference-time 2026-09-26T09:00:00+10:00
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

load_dotenv()

ZERO = Decimal("0.00")
# Stable namespace for the deterministic idempotency keys: the same (seed, scenario) always produces the
# same key, so a second run is detected by BR10's own unique constraint rather than by a marker table.
KEY_NAMESPACE = uuid.UUID("6f8a1e6c-9120-4c4e-9f0e-1c2f5b9a7d31")
SQL_DIR = pathlib.Path(__file__).resolve().parent.parent / "sql"


class DemoSeedError(RuntimeError):
    """The seed cannot run: the wrong database, missing reference data, or an already-seeded database."""


@dataclass(frozen=True)
class Scenario:
    """One order to build, plus the returns taken from it."""
    customer_email: str
    fulfilment_method: str
    store_id: int
    address_no: int | None
    lines: tuple[tuple[str, int], ...]       # (SKU, quantity)
    paid_days_ago: int                        # how long before the reference time the order was placed
    delivery_days: int | None                 # days from placement to completion; None = not completed
    statuses: tuple[str, ...]                 # the statuses to advance through after `paid`
    staff_id: int                             # the staff member who moves the order
    completed_days_ago: int | None = None      # how long before the reference time it completed
    return_status: str | None = None           # requested / received / rejected / refunded
    return_lines: tuple[tuple[int, int], ...] = ()   # (line_no, quantity)
    received_store_id: int | None = None
    received_staff_id: int | None = None
    return_days_after_completion: int = 1


# Every scenario uses seeded reference data only. The store ids are the ones the reference seed pins:
# 1 Sydney CBD, 2 Bondi Junction, 5 Melbourne Central, 9 Brisbane City, 13 Eastern Creek DC (warehouse).
# Staff ids: 1/14/15 work at store 1, 2/16/17 at store 2, 5/22/23 at store 5, 9/30/31 at store 9 and
# 13/38/39 at the warehouse.
SCENARIOS: dict[str, Scenario] = {
    # A delivered home-delivery order with a partial refund already processed: the customer can see the
    # remaining quantity, the refund and the restocked item.
    "delivery_refunded_partial": Scenario(
        "alice.morgan@example.com", "delivery", 13, 1, (("APL-AP4", 3),), paid_days_ago=12,
        delivery_days=2, statuses=("picking", "shipped", "delivered"), staff_id=38,
        completed_days_ago=10, return_status="refunded", return_lines=((1, 1),),
        received_store_id=1, received_staff_id=1, return_days_after_completion=2,
    ),
    # A collected order with a request still waiting for staff: the admin queue can receive it.
    "collection_return_requested": Scenario(
        "ben.okafor@example.com", "click_collect", 5, None, (("JBL-FLIP7-B", 2),), paid_days_ago=6,
        delivery_days=3, statuses=("picking", "ready", "collected"), staff_id=22,
        completed_days_ago=3, return_status="requested", return_lines=((1, 1),),
        received_store_id=5, received_staff_id=22,
    ),
    # A return that has arrived at the store but has not been refunded yet.
    "delivery_return_received": Scenario(
        "tom.fraser@example.com", "delivery", 13, 1, (("MS-XBOXCTRL-B", 2),), paid_days_ago=14,
        delivery_days=6, statuses=("picking", "shipped", "delivered"), staff_id=38,
        completed_days_ago=8, return_status="received", return_lines=((1, 1),),
        received_store_id=1, received_staff_id=14, return_days_after_completion=2,
    ),
    # A return a store refused (damaged on arrival): rejected is final and no money moves.
    "delivery_return_rejected": Scenario(
        "alice.morgan@example.com", "delivery", 13, 1, (("SONY-DUALSENSE-W", 1),), paid_days_ago=20,
        delivery_days=5, statuses=("picking", "shipped", "delivered"), staff_id=38,
        completed_days_ago=15, return_status="rejected", return_lines=((1, 1),),
        received_store_id=1, received_staff_id=1, return_days_after_completion=3,
    ),
    # A multi-line collection with one line refunded in full and one line left: "multiple returns" on one
    # order, and the purchase-time price (not today's) is what was refunded.
    "collection_multiline_refunded": Scenario(
        "ben.okafor@example.com", "click_collect", 5, None,
        (("GAR-FR265", 1), ("JBL-T770NC-B", 1)), paid_days_ago=9, delivery_days=4,
        statuses=("picking", "ready", "collected"), staff_id=22, completed_days_ago=5,
        return_status="refunded", return_lines=((2, 1),), received_store_id=5, received_staff_id=23,
        return_days_after_completion=1,
    ),
    # A completed order older than 30 days: eligible for nothing, which is what the order page must say.
    "collection_expired_window": Scenario(
        "mei.zhou@example.com", "click_collect", 9, None, (("SONOS-BEAM2", 1),), paid_days_ago=50,
        delivery_days=5, statuses=("picking", "ready", "collected"), staff_id=30,
        completed_days_ago=45, return_days_after_completion=0,
    ),
    # Orders still in flight, for the staff queues.
    "delivery_picking": Scenario(
        "alice.morgan@example.com", "delivery", 13, 1, (("HP-PAV15-I5", 1),), paid_days_ago=2,
        delivery_days=None, statuses=("picking",), staff_id=38,
    ),
    "collection_ready": Scenario(
        "tom.fraser@example.com", "click_collect", 1, None, (("NIN-SW2-PROCTRL", 1),), paid_days_ago=3,
        delivery_days=None, statuses=("picking", "ready"), staff_id=14,
    ),
    "collection_fresh_paid": Scenario(
        "alice.morgan@example.com", "click_collect", 1, None, (("APL-APP3", 1),), paid_days_ago=0,
        delivery_days=None, statuses=(), staff_id=14,
    ),
    # A paid delivery cancelled before it shipped: stock returns to the warehouse and the charge is
    # refunded against the cancellation record, not against a fabricated merchandise return. Delivery
    # orders may only be cancelled while they are placed or paid, so this one has not started picking.
    "delivery_cancelled": Scenario(
        "mei.zhou@example.com", "delivery", 13, 1, (("SAM-TABS10FE-128", 1),), paid_days_ago=4,
        delivery_days=1, statuses=(), staff_id=38, completed_days_ago=3,
    ),
}


def scenario_key(seed: int, name: str) -> uuid.UUID:
    """The deterministic idempotency key for one scenario, so a repeat run cannot duplicate it."""
    return uuid.uuid5(KEY_NAMESPACE, f"jbhifi-demo:{seed}:{name}")


# ---------------------------------------------------------------- database guard

def assert_disposable_database(dbname: str, demo_db: str | None = None) -> None:
    """Refuse a database that might hold data worth keeping.

    The pytest fixtures use the same rule (`tests/support.assert_is_test_database`): the name must end in
    `_demo` or `_test`, and it must not be the database the API points at.
    """
    demo_db = demo_db or os.environ.get("POSTGRES_DB", "jbhifi")
    if dbname == demo_db:
        raise DemoSeedError(
            f"refusing to seed {dbname!r}: that is the demo database the API uses "
            f"(POSTGRES_DB). Create a separate database whose name ends in _demo or _test."
        )
    if not dbname.endswith(("_demo", "_test")):
        raise DemoSeedError(
            f"refusing to seed {dbname!r}: the demo seed only writes to a disposable database whose "
            f"name ends in _demo or _test (use --database)."
        )


# ---------------------------------------------------------------- seeding

def seed_demo(cur, reference_time: datetime | None = None, seed: int = 9120) -> dict:
    """Build every scenario on `cur` and return a summary.

    The caller owns the transaction: `seed_demo` never commits. Times are relative to `reference_time`
    (default: now, in the local time zone) so a demo can be rebuilt exactly.
    """
    reference_time = _aware(reference_time or datetime.now(timezone.utc))
    cur.execute("SET LOCAL timezone = 'Australia/Sydney'")

    _check_reference_data(cur)
    already = _already_seeded(cur, seed)
    if already:
        raise DemoSeedError(
            "this database already contains the demo scenarios "
            f"({', '.join(sorted(already))}). Rebuild the database (docker compose down -v && "
            "docker compose up -d) before seeding again."
        )

    stock_before = _inventory_snapshot(cur)
    summary = {
        "created": True,
        "seed": seed,
        "reference_time": reference_time.isoformat(),
        "scenario_order_ids": {},
        "scenario_return_ids": {},
        "scenario_cancellation_ids": {},
        "scenario_adjustment_ids": {},
        "reconciliation": {},
    }
    built: list[dict] = []

    for name, scenario in SCENARIOS.items():
        built.append(_build_order(cur, summary, name, scenario, reference_time, seed))

    summary["scenario_adjustment_ids"]["empty_stock_at_sydney_cbd"] = _empty_store_stock(
        cur, "LG-43UT8050", 1, summary
    )

    # Flush the deferred BR14 checks before touching the guards: PostgreSQL refuses ALTER TABLE while a
    # deferred constraint event is still pending, and the data is complete at this point.
    cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with suspension(cur, TIMESTAMP_GUARDS):
        for record in built:
            _shift_times(cur, record, reference_time, seed)
        # The stocktake that emptied the demo store is a week old, not "now" (BR18's log is append-only,
        # which is why its guard is in the suspension list).
        cur.execute("UPDATE stock_adjustment SET adjusted_at = %s WHERE note LIKE %s",
                    (reference_time - timedelta(days=7), "demo%"))

    cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
    summary["reconciliation"] = _reconcile(cur, stock_before, built)
    return summary


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone()
    return value


def _check_reference_data(cur) -> None:
    cur.execute("SELECT count(*) AS n FROM product")
    if cur.fetchone()["n"] == 0:
        raise DemoSeedError("the catalogue is empty: load `sql/*.sql` before seeding demo scenarios")
    cur.execute("SELECT count(*) AS n FROM customer")
    if cur.fetchone()["n"] == 0:
        raise DemoSeedError("there are no demo customers: load `sql/10_seed_reference.sql` first")


def _already_seeded(cur, seed: int) -> set[str]:
    """Scenario names whose deterministic order already exists (BR10's unique key finds them)."""
    found: set[str] = set()
    for name, scenario in SCENARIOS.items():
        cur.execute(
            "SELECT 1 FROM customer_order o JOIN customer c ON c.customer_id = o.customer_id "
            "WHERE c.email = %s AND o.idempotency_key = %s",
            (scenario.customer_email, str(scenario_key(seed, name))),
        )
        if cur.fetchone() is not None:
            found.add(name)
    return found


def _build_order(cur, summary: dict, name: str, scenario: Scenario, reference_time: datetime, seed: int) -> dict:
    customer_id, address_no = _customer(cur, scenario)
    lines = _resolve_lines(cur, scenario)
    placed_at = reference_time - timedelta(days=scenario.paid_days_ago)
    key = scenario_key(seed, name)

    cur.execute(
        """
        INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint, fulfilment_method,
                                    fulfilling_store_id, delivery_address_no, placed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING order_id
        """,
        (customer_id, str(key), f"demo:{seed}:{name}", scenario.fulfilment_method, scenario.store_id,
         address_no if scenario.fulfilment_method == "delivery" else None, placed_at),
    )
    order_id = cur.fetchone()["order_id"]
    summary["scenario_order_ids"][name] = order_id

    total = ZERO
    for line_no, (product_id, sku, quantity, unit_price) in enumerate(lines, start=1):
        cur.execute(
            "INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) "
            "VALUES (%s, %s, %s, %s, %s)",
            (order_id, line_no, product_id, quantity, unit_price),
        )
        _take_stock(cur, scenario.store_id, product_id, sku, quantity, summary, name)
        total += unit_price * quantity

    if total > 0:
        cur.execute("INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'charge', %s)",
                    (order_id, total))

    _advance(cur, order_id, ("paid",) + scenario.statuses, scenario.staff_id)

    record = {
        "name": name, "scenario": scenario, "order_id": order_id, "customer_id": customer_id,
        "placed_at": placed_at, "lines": lines, "total": total, "returns": [],
    }
    if scenario.return_status:
        record["returns"].append(_build_return(cur, summary, name, scenario, record, reference_time))
    if name == "delivery_cancelled":
        _cancel(cur, record, reference_time, summary)
    return record


def _customer(cur, scenario: Scenario) -> tuple[int, int | None]:
    cur.execute(
        "SELECT c.customer_id, a.address_no "
        "FROM customer c LEFT JOIN customer_address a "
        "  ON a.customer_id = c.customer_id AND a.is_active AND a.address_no = %s "
        "WHERE c.email = %s",
        (scenario.address_no, scenario.customer_email),
    )
    row = cur.fetchone()
    if row is None:
        raise DemoSeedError(f"demo customer {scenario.customer_email!r} is missing from the seed data")
    if scenario.fulfilment_method == "delivery" and row["address_no"] is None:
        raise DemoSeedError(
            f"customer {scenario.customer_email!r} has no active address {scenario.address_no}"
        )
    return row["customer_id"], row["address_no"]


def _resolve_lines(cur, scenario: Scenario) -> list[tuple[int, str, int, Decimal]]:
    resolved = []
    for sku, quantity in scenario.lines:
        cur.execute(
            "SELECT p.product_id, cp.current_price FROM product p "
            "JOIN v_product_current_price cp ON cp.product_id = p.product_id "
            "WHERE p.sku = %s AND p.is_active",
            (sku,),
        )
        row = cur.fetchone()
        if row is None:
            raise DemoSeedError(f"product {sku!r} is missing or retired in the reference data")
        resolved.append((row["product_id"], sku, quantity, Decimal(row["current_price"])))
    return resolved


def _take_stock(cur, store_id: int, product_id: int, sku: str, quantity: int, summary: dict, name: str) -> None:
    """Deduct the purchased quantity, topping the store up with a logged 'received' adjustment first."""
    cur.execute("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s FOR UPDATE",
                (store_id, product_id))
    row = cur.fetchone()
    available = row["quantity"] if row else 0
    if available < quantity:
        _adjust(cur, store_id, product_id, quantity - available, "received",
                f"demo stock for {name}", summary, f"{name}:received")
    cur.execute(
        "UPDATE inventory SET quantity = quantity - %s "
        "WHERE store_id = %s AND product_id = %s AND quantity >= %s",
        (quantity, store_id, product_id, quantity),
    )
    if cur.rowcount != 1:
        raise DemoSeedError(f"could not take {quantity} of {sku} from store {store_id}")


def _adjust(cur, store_id: int, product_id: int, delta: int, reason: str, note: str,
            summary: dict, key: str | None = None) -> int:
    """A manual stock change, written exactly as `app/services/inventory.py` writes it (BR18)."""
    staff = _staff_at(cur, store_id, manager=True)
    cur.execute(
        "UPDATE inventory SET quantity = quantity + %s WHERE store_id = %s AND product_id = %s "
        "RETURNING quantity",
        (delta, store_id, product_id),
    )
    after = cur.fetchone()["quantity"]
    cur.execute(
        "INSERT INTO stock_adjustment (store_id, product_id, staff_id, delta, reason, note, quantity_after) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING adjustment_id",
        (store_id, product_id, staff, delta, reason, note, after),
    )
    adjustment_id = cur.fetchone()["adjustment_id"]
    if key:
        summary["scenario_adjustment_ids"][key] = adjustment_id
    return adjustment_id


def _staff_at(cur, store_id: int, manager: bool = False) -> int:
    if manager:
        cur.execute("SELECT manager_id FROM store WHERE store_id = %s", (store_id,))
        return cur.fetchone()["manager_id"]
    cur.execute("SELECT staff_id FROM staff WHERE store_id = %s ORDER BY staff_id LIMIT 1", (store_id,))
    row = cur.fetchone()
    if row is None:
        raise DemoSeedError(f"store {store_id} has no staff")
    return row["staff_id"]


def _advance(cur, order_id: int, statuses: tuple[str, ...], staff_id: int) -> None:
    """Move the order through the same UPDATEs the application uses, so BR09 and its history run."""
    cur.execute("SELECT set_config('app.staff_id', %s, true)", (str(staff_id),))
    for status in statuses:
        if status == "paid":
            cur.execute("SELECT set_config('app.staff_id', '', true)")
        cur.execute("UPDATE customer_order SET status = %s WHERE order_id = %s", (status, order_id))
        if status == "paid":
            cur.execute("SELECT set_config('app.staff_id', %s, true)", (str(staff_id),))


def _build_return(cur, summary: dict, name: str, scenario: Scenario, record: dict,
                  reference_time: datetime) -> dict:
    completed_at = _completed_at(record, scenario, reference_time)
    key = uuid.uuid5(KEY_NAMESPACE, f"jbhifi-demo:{name}:return")
    cur.execute(
        "INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason) "
        "VALUES (%s, %s, %s, %s) RETURNING return_id",
        (record["order_id"], str(key), f"demo:{name}:return", _return_reason(scenario.return_status)),
    )
    return_id = cur.fetchone()["return_id"]
    summary["scenario_return_ids"][name] = return_id

    for line_no, quantity in scenario.return_lines:
        cur.execute(
            "INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, %s, %s, %s)",
            (return_id, line_no, record["order_id"], quantity),
        )

    result = {"return_id": return_id, "status": scenario.return_status, "requested_at": None,
              "refund_amount": ZERO, "expected_refund": ZERO, "received_store_id": None}

    if scenario.return_status != "requested":
        cur.execute(
            "UPDATE return_request SET status = 'received', received_store_id = %s, "
            "processed_by_staff_id = %s WHERE return_id = %s",
            (scenario.received_store_id, scenario.received_staff_id, return_id),
        )
        result["received_store_id"] = scenario.received_store_id

    if scenario.return_status == "refunded":
        cur.execute("SELECT return_expected_refund(%s) AS due", (return_id,))
        due = Decimal(cur.fetchone()["due"])
        result["expected_refund"] = due
        if due > 0:
            cur.execute("INSERT INTO payment (order_id, kind, amount, return_id) "
                        "VALUES (%s, 'refund', %s, %s)",
                        (record["order_id"], due, return_id))
        result["refund_amount"] = due
        for line_no, quantity in scenario.return_lines:
            product_id = record["lines"][line_no - 1][0]
            _restock(cur, scenario.received_store_id, product_id, quantity)
        cur.execute("UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))
    elif scenario.return_status == "rejected":
        cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (return_id,))

    result["requested_at"] = completed_at + timedelta(days=scenario.return_days_after_completion)
    return result


def _return_reason(status: str | None) -> str:
    return {
        "requested": "Changed my mind",
        "received": "Changed my mind",
        "refunded": "Wrong size or model",
        "rejected": "Reported as damaged on arrival",
    }.get(status, "Changed my mind")


def _restock(cur, store_id: int, product_id: int, quantity: int) -> None:
    """Add returned or cancelled stock back with a relative update, the way the services do."""
    cur.execute(
        "INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, 0) "
        "ON CONFLICT (store_id, product_id) DO NOTHING",
        (store_id, product_id),
    )
    cur.execute(
        "UPDATE inventory SET quantity = quantity + %s WHERE store_id = %s AND product_id = %s",
        (quantity, store_id, product_id),
    )


def _cancel(cur, record: dict, reference_time: datetime, summary: dict) -> None:
    scenario = record["scenario"]
    cancelled_at = reference_time - timedelta(days=scenario.completed_days_ago or 0)
    cur.execute("SELECT set_config('app.staff_id', %s, true)", (str(scenario.staff_id),))
    cur.execute(
        "INSERT INTO order_cancellation (order_id, reason, cancelled_by_staff_id) "
        "VALUES (%s, %s, %s) RETURNING cancellation_id",
        (record["order_id"], "Customer changed their mind before dispatch", scenario.staff_id),
    )
    cancellation_id = cur.fetchone()["cancellation_id"]
    cur.execute("SELECT order_captured_balance(%s, NULL) AS balance", (record["order_id"],))
    balance = Decimal(cur.fetchone()["balance"])
    if balance > 0:
        cur.execute("INSERT INTO payment (order_id, kind, amount, cancellation_id) "
                    "VALUES (%s, 'refund', %s, %s)",
                    (record["order_id"], balance, cancellation_id))
    for product_id, _sku, quantity, _price in record["lines"]:
        _restock(cur, scenario.store_id, product_id, quantity)
    cur.execute("UPDATE customer_order SET status = 'cancelled' WHERE order_id = %s", (record["order_id"],))
    record["cancelled_at"] = cancelled_at
    record["cancellation_id"] = cancellation_id
    record["refunded"] = balance
    summary["scenario_cancellation_ids"][record["name"]] = cancellation_id


def _empty_store_stock(cur, sku: str, store_id: int, summary: dict) -> int | None:
    """Leave one product with no stock at one store, so an out-of-stock checkout can be demonstrated."""
    cur.execute(
        "SELECT p.product_id, i.quantity FROM product p "
        "JOIN inventory i ON i.product_id = p.product_id AND i.store_id = %s "
        "WHERE p.sku = %s FOR UPDATE OF i",
        (store_id, sku),
    )
    row = cur.fetchone()
    if row is None:
        raise DemoSeedError(f"{sku} is not ranged at store {store_id}")
    if row["quantity"] == 0:
        return None
    return _adjust(cur, store_id, row["product_id"], -row["quantity"], "stocktake",
                   f"demo: {sku} counted out at store {store_id}", summary)


def _completed_at(record: dict, scenario: Scenario, reference_time: datetime) -> datetime:
    if scenario.completed_days_ago is None:
        raise DemoSeedError(f"scenario {record['name']!r} has a return but no completion time")
    return reference_time - timedelta(days=scenario.completed_days_ago)


# ---------------------------------------------------------------- maintenance times

# Only these guards are suspended, and only for the UPDATE that ages a row.
TIMESTAMP_GUARDS = (
    ("customer_order", "order_immutable"),
    ("order_status_history", "order_status_history_append_only"),
    ("return_status_history", "return_status_history_append_only"),
    ("payment", "payment_append_only"),
    ("order_cancellation", "order_cancellation_append_only"),
    ("stock_adjustment", "br18_adjustment_append_only"),
    ("return_request", "br11_return_window"),
)


@contextmanager
def suspension(cur, guards):
    """Disable the named triggers, then restore them — even if the UPDATEs raise.

    `ALTER TABLE … DISABLE TRIGGER` is transactional, so a rollback restores the guard anyway; the
    explicit re-enable keeps the invariant true for a caller that commits.
    """
    for table, trigger in guards:
        cur.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
            sql.Identifier(table), sql.Identifier(trigger)))
    try:
        yield
    finally:
        for table, trigger in reversed(guards):
            cur.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER {}").format(
                sql.Identifier(table), sql.Identifier(trigger)))


def _shift_times(cur, record: dict, reference_time: datetime, seed: int) -> None:
    """Age one scenario's rows to their recorded times (the only maintenance write in the seeder)."""
    scenario = record["scenario"]
    placed_at = record["placed_at"]
    completed_at = (_completed_at(record, scenario, reference_time)
                    if scenario.completed_days_ago is not None else None)
    statuses = ["placed", "paid", *scenario.statuses]

    cur.execute("UPDATE customer_order SET placed_at = %s WHERE order_id = %s",
                (placed_at, record["order_id"]))
    _spread_history(cur, "order_status_history", "order_id", record["order_id"], statuses,
                    placed_at, completed_at or reference_time)
    cur.execute("UPDATE payment SET created_at = %s WHERE order_id = %s AND cancellation_id IS NULL",
                (placed_at + timedelta(hours=1), record["order_id"]))

    if "cancelled_at" in record:
        cur.execute("UPDATE order_cancellation SET created_at = %s WHERE cancellation_id = %s",
                    (record["cancelled_at"], record["cancellation_id"]))
        cur.execute("UPDATE payment SET created_at = %s WHERE order_id = %s AND cancellation_id IS NOT NULL",
                    (record["cancelled_at"], record["order_id"]))

    for item in record["returns"]:
        cur.execute("UPDATE return_request SET requested_at = %s WHERE return_id = %s",
                    (item["requested_at"], item["return_id"]))
        _spread_history(cur, "return_status_history", "return_id", item["return_id"],
                        _return_statuses(item["status"]), item["requested_at"],
                        completed_at or reference_time)
        cur.execute("UPDATE payment SET created_at = %s WHERE return_id = %s",
                    (item["requested_at"] + timedelta(hours=2), item["return_id"]))

    if record["name"] == "collection_expired_window":
        pass                       # its whole history is already older than 30 days


def _return_statuses(status: str) -> list[str]:
    if status == "requested":
        return ["requested"]
    if status == "rejected":
        return ["requested", "rejected"]
    return ["requested", "received", "refunded"]


def _spread_history(cur, table: str, key: str, key_value: int, statuses: list[str],
                    start: datetime, end: datetime) -> None:
    """Give each history row a time between `start` and `end`, in sequence order."""
    rows = max(len(statuses), 1)
    step = (end - start) / rows if end > start else timedelta(0)
    for index, _status in enumerate(statuses, start=1):
        cur.execute(
            sql.SQL("UPDATE {} SET changed_at = %s WHERE {} = %s AND seq = %s").format(
                sql.Identifier(table), sql.Identifier(key)),
            (start + step * index, key_value, index),
        )


# ---------------------------------------------------------------- reconciliation

def _inventory_snapshot(cur) -> dict[tuple[int, int], int]:
    cur.execute("SELECT store_id, product_id, quantity FROM inventory")
    return {(row["store_id"], row["product_id"]): row["quantity"] for row in cur.fetchall()}


def _reconcile(cur, stock_before: dict[tuple[int, int], int], built: list[dict]) -> dict:
    """Recompute stock and money from the rows the seeder wrote, and report every disagreement."""
    moved: dict[tuple[int, int], int] = {}

    def add(store_id: int, product_id: int, delta: int) -> None:
        moved[(store_id, product_id)] = moved.get((store_id, product_id), 0) + delta

    for record in built:
        scenario = record["scenario"]
        for product_id, _sku, quantity, _price in record["lines"]:
            add(scenario.store_id, product_id, -quantity)
        if "cancelled_at" in record:
            for product_id, _sku, quantity, _price in record["lines"]:
                add(scenario.store_id, product_id, quantity)
        for item in record["returns"]:
            if item["status"] == "refunded":
                for line_no, quantity in record["scenario"].return_lines:
                    add(item["received_store_id"], record["lines"][line_no - 1][0], quantity)

    cur.execute(
        "SELECT store_id, product_id, delta FROM stock_adjustment "
        "WHERE note IS NOT NULL AND note LIKE 'demo%'"
    )
    for row in cur.fetchall():
        add(row["store_id"], row["product_id"], row["delta"])

    problems: list[str] = []
    for key, delta in sorted(moved.items()):
        cur.execute("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s", key)
        actual = cur.fetchone()["quantity"]
        expected = stock_before.get(key, 0) + delta
        if actual != expected:
            problems.append(f"inventory {key}: expected {expected}, found {actual}")

    for record in built:
        order_id = record["order_id"]
        cur.execute(
            "SELECT COALESCE(sum(CASE WHEN kind = 'charge' THEN amount END), 0) AS charged, "
            "       COALESCE(sum(CASE WHEN kind = 'refund' THEN amount END), 0) AS refunded "
            "FROM payment WHERE order_id = %s",
            (order_id,),
        )
        money = cur.fetchone()
        if Decimal(money["refunded"]) > Decimal(money["charged"]):
            problems.append(f"order {order_id}: refunded more than was charged")
        if Decimal(record["total"]) != Decimal(money["charged"]):
            problems.append(
                f"order {order_id}: the charge {money['charged']} does not match the sold lines "
                f"{record['total']}"
            )

    cur.execute(
        """
        SELECT rl.order_id, rl.line_no, sum(rl.quantity) AS returned, ol.quantity AS bought
        FROM return_line rl
        JOIN return_request rr ON rr.return_id = rl.return_id AND rr.status <> 'rejected'
        JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no
        GROUP BY rl.order_id, rl.line_no, ol.quantity
        HAVING sum(rl.quantity) > ol.quantity
        """
    )
    for row in cur.fetchall():
        problems.append(f"order {row['order_id']} line {row['line_no']}: returned more than was bought")

    if problems:
        raise DemoSeedError("the demo scenarios do not reconcile: " + "; ".join(problems))
    return {"stock_rows_checked": len(moved), "orders_checked": len(built), "problems": []}


# ---------------------------------------------------------------- command line

def connect(database: str):
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        dbname=database,
        user=os.environ.get("POSTGRES_USER", "jbhifi"),
        password=os.environ.get("POSTGRES_PASSWORD", "devpassword"),
        cursor_factory=RealDictCursor,
    )


def create_database(database: str, demo_db: str | None = None):
    """Drop and rebuild a disposable database from `sql/*.sql`, as Docker does on a fresh volume.

    The caller has already passed the name guard (`assert_disposable_database`); this is still an
    explicit `--create` command, never something a normal seed run does.
    """
    assert_disposable_database(database, demo_db)
    admin = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        dbname="postgres",
        user=os.environ.get("POSTGRES_USER", "jbhifi"),
        password=os.environ.get("POSTGRES_PASSWORD", "devpassword"),
    )
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    admin.close()

    conn = connect(database)
    conn.autocommit = True
    with conn.cursor() as cur:
        for path in sorted(SQL_DIR.glob("*.sql")):
            cur.execute(path.read_text())
    conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the reproducible demo scenarios.")
    parser.add_argument("--database", required=True,
                        help="a disposable database whose name ends in _demo or _test")
    parser.add_argument("--reference-time", default=None,
                        help="ISO-8601 time the demo is anchored to (default: now)")
    parser.add_argument("--seed", type=int, default=9120, help="scenario idempotency seed")
    parser.add_argument("--create", action="store_true",
                        help="drop and rebuild the target database from sql/*.sql before seeding")
    args = parser.parse_args(argv)

    try:
        assert_disposable_database(args.database)
        reference_time = _aware(datetime.fromisoformat(args.reference_time)) if args.reference_time else None
        if args.create:
            create_database(args.database)
        conn = connect(args.database)
    except (DemoSeedError, ValueError, psycopg2.Error) as error:
        print(f"seed_demo: {error}", file=sys.stderr)
        return 2

    try:
        with conn, conn.cursor() as cur:
            summary = seed_demo(cur, reference_time, args.seed)
    except (DemoSeedError, psycopg2.Error) as error:
        conn.close()
        print(f"seed_demo: {error}", file=sys.stderr)
        return 1
    conn.close()

    print(json.dumps(summary, indent=2, default=str))
    print(
        f"\nSeeded {len(summary['scenario_order_ids'])} orders into {args.database}.\n"
        f"Sign in as a demo customer and set a store in the storefront; the store admin "
        f"(/admin/orders, /admin/returns) sees the same rows.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

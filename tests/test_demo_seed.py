"""T17: the demo scenarios are reproducible, rule-consistent and reconcile with the ledger."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from scripts.seed_demo import DemoSeedError, assert_disposable_database, scenario_key, seed_demo


def seeded(cur):
    return seed_demo(cur, datetime.now(timezone.utc), seed=9120)


def test_seed_builds_every_scenario_and_reconciles(cur):
    summary = seeded(cur)

    assert summary["created"] is True
    assert summary["scenario_order_ids"].keys() == {
        "delivery_refunded_partial", "collection_return_requested", "delivery_return_received",
        "delivery_return_rejected", "collection_multiline_refunded", "collection_expired_window",
        "delivery_picking", "collection_ready", "collection_fresh_paid", "delivery_cancelled",
    }
    # Every order id is real, and every assertion the seeder made about stock and money passed.
    assert all(isinstance(order_id, int) for order_id in summary["scenario_order_ids"].values())
    assert summary["reconciliation"]["problems"] == []
    assert summary["reconciliation"]["orders_checked"] == len(summary["scenario_order_ids"])
    assert summary["scenario_return_ids"].keys() == {
        "collection_return_requested", "delivery_return_received", "delivery_return_rejected",
        "collection_multiline_refunded", "delivery_refunded_partial",
    }
    assert summary["scenario_cancellation_ids"].keys() == {"delivery_cancelled"}


def test_seed_covers_every_order_and_return_state(cur):
    summary = seeded(cur)

    def rows(query, params=()):
        cur.execute(query, params)
        return cur.fetchall()

    orders = summary["scenario_order_ids"]
    statuses = {name: rows("SELECT status FROM customer_order WHERE order_id = %s", (order_id,))[0]["status"]
                for name, order_id in orders.items()}
    assert statuses["delivery_refunded_partial"] == "delivered"
    assert statuses["collection_multiline_refunded"] == "collected"
    assert statuses["delivery_picking"] == "picking"
    assert statuses["collection_ready"] == "ready"
    assert statuses["collection_fresh_paid"] == "paid"
    assert statuses["delivery_cancelled"] == "cancelled"

    returns = summary["scenario_return_ids"]
    return_statuses = {
        name: rows("SELECT status FROM return_request WHERE return_id = %s", (return_id,))[0]["status"]
        for name, return_id in returns.items()
    }
    assert set(return_statuses.values()) == {"requested", "received", "refunded", "rejected"}
    for name, return_id in returns.items():
        history = rows("SELECT seq, to_status FROM return_status_history WHERE return_id = %s ORDER BY seq",
                       (return_id,))
        assert [row["seq"] for row in history] == list(range(1, len(history) + 1))


def test_seeded_return_is_partial_and_refunds_the_purchase_price(cur):
    summary = seeded(cur)
    order_id = summary["scenario_order_ids"]["delivery_refunded_partial"]
    return_id = summary["scenario_return_ids"]["delivery_refunded_partial"]

    cur.execute(
        "SELECT ol.unit_price, ol.quantity AS bought, rl.quantity AS returned "
        "FROM return_line rl JOIN order_line ol ON ol.order_id = rl.order_id AND ol.line_no = rl.line_no "
        "WHERE rl.return_id = %s",
        (return_id,),
    )
    line = cur.fetchone()
    assert line["returned"] < line["bought"], "the scenario is meant to show a partial return"

    cur.execute("SELECT amount FROM payment WHERE return_id = %s", (return_id,))
    refund = Decimal(cur.fetchone()["amount"])
    assert refund == Decimal(line["unit_price"]) * line["returned"]

    cur.execute("SELECT COALESCE(sum(amount), 0) AS charged FROM payment "
                "WHERE order_id = %s AND kind = 'charge'", (order_id,))
    assert refund <= Decimal(cur.fetchone()["charged"])


def test_expired_order_cannot_be_returned(cur, violates):
    summary = seeded(cur)
    order_id = summary["scenario_order_ids"]["collection_expired_window"]

    cur.execute(
        "SELECT max(changed_at) AS completed_at FROM order_status_history "
        "WHERE order_id = %s AND to_status = 'collected'",
        (order_id,),
    )
    completed_at = cur.fetchone()["completed_at"]
    assert completed_at < datetime.now(timezone.utc) - timedelta(days=30)

    violates(
        "br11_return_window",
        "INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason) "
        "VALUES (%s, gen_random_uuid(), 'too-late', 'Too late')",
        (order_id,),
    )


def test_cancellation_restocks_and_refunds_once(cur):
    summary = seeded(cur)
    order_id = summary["scenario_order_ids"]["delivery_cancelled"]
    cancellation_id = summary["scenario_cancellation_ids"]["delivery_cancelled"]

    cur.execute("SELECT kind, amount, return_id, cancellation_id FROM payment WHERE order_id = %s", (order_id,))
    payments = cur.fetchall()
    refunds = [row for row in payments if row["kind"] == "refund"]
    assert len(refunds) == 1
    assert refunds[0]["cancellation_id"] == cancellation_id
    assert refunds[0]["return_id"] is None, "a cancellation must not fabricate a merchandise return"
    charges = sum((Decimal(row["amount"]) for row in payments if row["kind"] == "charge"), Decimal("0.00"))
    assert Decimal(refunds[0]["amount"]) == charges

    cur.execute("SELECT count(*) AS n FROM order_status_history WHERE order_id = %s AND to_status = 'cancelled'",
                (order_id,))
    assert cur.fetchone()["n"] == 1


def test_manual_stock_changes_are_logged(cur):
    summary = seeded(cur)

    # At least the deliberate stocktake correction is logged (BR18); a short-stocked store would also
    # get a logged `received` top-up, which the reconciliation counts.
    cur.execute("SELECT count(*) AS n FROM stock_adjustment WHERE note LIKE 'demo%'")
    assert cur.fetchone()["n"] >= 1
    cur.execute("SELECT delta, reason, note FROM stock_adjustment WHERE note LIKE 'demo%'")
    logged = cur.fetchall()
    assert all(row["reason"] in ("received", "stocktake") for row in logged)
    assert any(row["reason"] == "stocktake" and row["delta"] < 0 for row in logged)
    cur.execute(
        "SELECT reason FROM stock_adjustment WHERE adjustment_id = %s",
        (summary["scenario_adjustment_ids"]["empty_stock_at_sydney_cbd"],),
    )
    assert cur.fetchone()["reason"] == "stocktake"

    # The empty-stock example really is empty, so a demo checkout of it must fail.
    cur.execute(
        "SELECT i.quantity FROM inventory i JOIN product p ON p.product_id = i.product_id "
        "WHERE p.sku = 'LG-43UT8050' AND i.store_id = 1"
    )
    assert cur.fetchone()["quantity"] == 0


def test_seeding_twice_is_refused(cur):
    seeded(cur)
    with pytest.raises(DemoSeedError, match="already contains the demo scenarios"):
        seed_demo(cur, datetime.now(timezone.utc), seed=9120)


def test_the_idempotency_key_is_stable_for_a_seed():
    assert scenario_key(9120, "delivery_picked") == scenario_key(9120, "delivery_picked")
    assert scenario_key(9120, "delivery_picked") != scenario_key(9121, "delivery_picked")
    assert scenario_key(9120, "a") != scenario_key(9120, "b")


def test_the_seeder_refuses_a_database_that_might_hold_real_data():
    assert_disposable_database("jbhifi_demo", demo_db="jbhifi")
    with pytest.raises(DemoSeedError):
        assert_disposable_database("jbhifi", demo_db="jbhifi")
    with pytest.raises(DemoSeedError):
        assert_disposable_database("production", demo_db="jbhifi")

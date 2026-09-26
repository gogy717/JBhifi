"""T16: the three reports. Every test builds its own committed rows with controlled timestamps and checks
a hand-calculated answer — including the Sydney date boundary and who may see which store.

The return fixtures need two timestamps the API generates for itself (`requested_at`, and the recorded
completion time). They are set with the same maintenance pattern `tests/lifecycle.py` uses: disable the one
guard, write the row, restore it, all inside the test's own transaction.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.lifecycle import advance
from tests.shop import AIDEN, BONDI, ISLA, SUPPORT, SYDNEY_CBD, committed, error_of, staff_client

API = "/api/v1/reports"

# Each test uses its own month, because every fixture commits: without that, one test's rows would show up
# in another test's totals. The months are a year back rather than recent, because other suites (and the
# demo seeder's tests) commit orders and returns "now"; 2025 cannot collide with any of them. They are
# still in the past, which is what BR11 needs: a return cannot be requested before the order was completed.
MARCH = {"from_date": "2025-03-01", "to_date": "2025-04-01"}
MARCH_15 = datetime(2025, 3, 15, tzinfo=timezone.utc)
APRIL = {"from_date": "2025-04-01", "to_date": "2025-05-01"}
APRIL_15 = datetime(2025, 4, 15, tzinfo=timezone.utc)
MAY = {"from_date": "2025-05-01", "to_date": "2025-06-01"}
MAY_15 = datetime(2025, 5, 15, tzinfo=timezone.utc)
JUNE = {"from_date": "2025-06-01", "to_date": "2025-07-01"}
JUNE_20 = datetime(2025, 6, 20, tzinfo=timezone.utc)
JULY = {"from_date": "2025-07-01", "to_date": "2025-08-01"}
AUGUST = {"from_date": "2025-08-01", "to_date": "2025-09-01"}
AUGUST_8 = datetime(2025, 8, 8, tzinfo=timezone.utc)
AUGUST_15 = datetime(2025, 8, 15, tzinfo=timezone.utc)
SEPTEMBER_20 = datetime(2025, 9, 20, tzinfo=timezone.utc)
JANUARY_8 = datetime(2025, 1, 8, tzinfo=timezone.utc)
FEBRUARY_1 = datetime(2025, 2, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------- fixtures on committed data

def a_customer_id(cur) -> int:
    cur.execute("INSERT INTO customer (email, full_name) VALUES (%s, 'Report Test') RETURNING customer_id",
                (f"report.{uuid.uuid4().hex[:8]}@example.com",))
    return cur.fetchone()["customer_id"]


def a_product_id(cur, price="100.00", active=True, stock=None, store_id=SYDNEY_CBD, name="Report item") -> int:
    cur.execute(
        """
        INSERT INTO product (sku, name, brand_id, category_id, base_price, is_active)
        SELECT %s, %s, b.brand_id, c.category_id, %s, %s
        FROM brand b, category c WHERE b.name = 'JBL' AND c.name = 'Speakers'
        RETURNING product_id
        """,
        (f"RPT-{uuid.uuid4().hex[:10].upper()}", name, price, active),
    )
    product_id = cur.fetchone()["product_id"]
    if stock is not None:
        cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (store_id, product_id, stock))
    return product_id


def an_order(cur, *, store_id=SYDNEY_CBD, lines=1, charge=None, at=MARCH_15) -> int:
    """A committed order placed and charged at `at`."""
    customer_id = a_customer_id(cur)
    cur.execute(
        "INSERT INTO customer_order (customer_id, idempotency_key, request_fingerprint, fulfilment_method, "
        "fulfilling_store_id, placed_at) VALUES (%s, gen_random_uuid(), 'report', 'click_collect', %s, %s) "
        "RETURNING order_id",
        (customer_id, store_id, at),
    )
    order_id = cur.fetchone()["order_id"]
    for line_no in range(1, lines + 1):
        cur.execute("INSERT INTO order_line (order_id, line_no, product_id, quantity, unit_price) "
                    "VALUES (%s, %s, %s, 1, 100.00)", (order_id, line_no, a_product_id(cur)))
    if charge is not None:
        cur.execute("INSERT INTO payment (order_id, kind, amount, created_at) VALUES (%s, 'charge', %s, %s)",
                    (order_id, charge, at))
    return order_id


def a_completed_order(cur, *, store_id=SYDNEY_CBD, charge="100.00", at=MARCH_15) -> int:
    """A charged order taken to `collected`, with its recorded completion time moved back to `at`."""
    order_id = an_order(cur, store_id=store_id, charge=charge, at=at)
    staff_id = {SYDNEY_CBD: 14, BONDI: 16}[store_id]
    advance(cur, order_id, "paid", "picking", "ready", "collected", staff_id=staff_id)
    _backdate_order(cur, order_id, at)
    return order_id


def _backdate_order(cur, order_id: int, at: datetime) -> None:
    """Age an order's recorded status times. Maintenance only: it needs table ownership."""
    cur.execute("ALTER TABLE order_status_history DISABLE TRIGGER order_status_history_append_only")
    try:
        cur.execute("UPDATE order_status_history SET changed_at = %s WHERE order_id = %s", (at, order_id))
    finally:
        cur.execute("ALTER TABLE order_status_history ENABLE TRIGGER order_status_history_append_only")


def a_return(cur, *, store_id=SYDNEY_CBD, requested_at=MARCH_15, status="requested",
             received_store_id=None, refund=None, refunded_at=None) -> int:
    """A return requested at `requested_at`, optionally received and/or refunded."""
    # The order is completed "now" so BR11's insert check passes, and its recorded times are aged after
    # the return exists — the same trick `scripts/seed_demo.py` uses for historical scenarios.
    order_id = a_completed_order(cur, store_id=store_id, at=requested_at)
    # A few minutes ago, not "now": the return's own request time is the transaction's timestamp, and the
    # completion has to be able to sit *before* it.
    _backdate_order(cur, order_id, datetime.now(timezone.utc) - timedelta(minutes=5))
    receiver = {SYDNEY_CBD: 14, BONDI: 16}.get(received_store_id)
    cur.execute(
        "INSERT INTO return_request (order_id, idempotency_key, request_fingerprint, reason, status, "
        "received_store_id, processed_by_staff_id) "
        "VALUES (%s, gen_random_uuid(), 'report', 'report test', 'requested', %s, %s) RETURNING return_id",
        (order_id, received_store_id, receiver),
    )
    return_id = cur.fetchone()["return_id"]
    cur.execute("INSERT INTO return_line (return_id, line_no, order_id, quantity) VALUES (%s, 1, %s, 1)",
                (return_id, order_id))
    # Move it along the statuses the database allows, rather than writing a state directly.
    if status in ("received", "refunded"):
        cur.execute("UPDATE return_request SET status = 'received' WHERE return_id = %s", (return_id,))
    if status == "refunded":
        cur.execute("UPDATE return_request SET status = 'refunded' WHERE return_id = %s", (return_id,))
    elif status == "rejected":
        cur.execute("UPDATE return_request SET status = 'rejected' WHERE return_id = %s", (return_id,))
    if refund is not None:
        cur.execute("INSERT INTO payment (order_id, kind, amount, return_id, created_at) "
                    "VALUES (%s, 'refund', %s, %s, %s)",
                    (order_id, refund, return_id, refunded_at or requested_at))
    # The request time is the server's (T02), so it is aged here the way the demo seeder ages history.
    # Flush the deferred completeness checks first: ALTER TABLE is refused while trigger events are queued.
    cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
    cur.execute("ALTER TABLE return_request DISABLE TRIGGER br11_return_window")
    try:
        cur.execute("UPDATE return_request SET requested_at = %s WHERE return_id = %s",
                    (requested_at, return_id))
    finally:
        cur.execute("ALTER TABLE return_request ENABLE TRIGGER br11_return_window")
    _backdate_order(cur, order_id, requested_at)      # completion and request agree, as they would in life
    return return_id


def fetch(client, path, params):
    response = client.get(f"{API}/{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def store_row(report, store_id):
    return next((row for row in report["rows"] if row["store_id"] == store_id), None)


# ---------------------------------------------------------------- sales

def test_sales_does_not_multiply_payments():
    """An order with three lines and one charge of 300.00 is 300.00 captured, not 900.00."""
    committed(lambda cur: an_order(cur, lines=3, charge="300.00"))
    report = fetch(staff_client(SUPPORT), "sales", {**MARCH, "store_id": SYDNEY_CBD})
    row = store_row(report, SYDNEY_CBD)
    assert row["captured_amount"] == "300.00"
    assert row["order_count"] == 1
    assert row["charged_orders"] == 1
    assert row["refund_count"] == 0


def test_only_that_stores_trade_is_reported():
    committed(lambda cur: an_order(cur, store_id=SYDNEY_CBD, charge="100.00", at=APRIL_15))
    committed(lambda cur: an_order(cur, store_id=BONDI, charge="250.00", at=APRIL_15))

    one_store = fetch(staff_client(AIDEN), "sales", {**APRIL, "store_id": SYDNEY_CBD})
    assert [(row["store_id"], row["captured_amount"]) for row in one_store["rows"]] \
        == [(SYDNEY_CBD, "100.00")]

    everything = fetch(staff_client(SUPPORT), "sales", APRIL)
    by_store = {row["store_id"]: row["captured_amount"] for row in everything["rows"]}
    assert by_store[SYDNEY_CBD] == "100.00"
    assert by_store[BONDI] == "250.00"
    assert everything["totals"]["captured_amount"] == "350.00"
    assert everything["totals"]["net_receipts"] == "350.00"


def test_refunds_use_their_own_event_date_and_net_off():
    """A May charge refunded in June: May shows the charge, June shows the refund."""
    committed(lambda cur: an_order(cur, charge="200.00", at=MAY_15))
    committed(lambda cur: a_return(cur, requested_at=MAY_15, status="refunded",
                                   received_store_id=SYDNEY_CBD, refund="100.00",
                                   refunded_at=JUNE_20))
    committed(lambda cur: cur.execute(
        "INSERT INTO payment (order_id, kind, amount, created_at) VALUES (%s, 'charge', '1.00', %s)",
        (an_order_id_for_a_charge(cur), FEBRUARY_1)))

    may = fetch(staff_client(SUPPORT), "sales", {**MAY, "store_id": SYDNEY_CBD})
    assert may["totals"]["captured_amount"] == "300.00"          # 200 + the 100 charge of the return's order
    assert may["totals"]["refunded_amount"] == "0.00"            # the refund happens in June
    assert may["totals"]["net_receipts"] == "300.00"

    june = fetch(staff_client(SUPPORT), "sales", {**JUNE, "store_id": SYDNEY_CBD})
    assert june["totals"]["captured_amount"] == "0.00"           # the February charge is outside both
    assert june["totals"]["refunded_amount"] == "100.00"         # the return's line at its sold price
    assert june["totals"]["net_receipts"] == "-100.00"
    assert june["totals"]["refund_count"] == 1


def an_order_id_for_a_charge(cur) -> int:
    """An order to hang a hand-dated payment on (its own charge is not needed)."""
    return an_order(cur, charge=None, at=FEBRUARY_1)


def test_an_impossible_period_is_refused():
    response = staff_client(SUPPORT).get(f"{API}/sales",
                                        params={"from_date": "2026-04-01", "to_date": "2026-03-01"})
    assert error_of(response) == (422, "invalid_date_range")


# ---------------------------------------------------------------- low stock

def test_low_stock_includes_products_with_no_inventory_row():
    never_stocked = committed(lambda cur: a_product_id(cur, stock=None, name="Never stocked"))
    stocked_low = committed(lambda cur: a_product_id(cur, stock=2, name="Two left"))
    stocked_plenty = committed(lambda cur: a_product_id(cur, stock=40, name="Plenty"))
    retired = committed(lambda cur: a_product_id(cur, stock=0, active=False, name="Retired"))

    report = fetch(staff_client(AIDEN), "low-stock", {"store_id": SYDNEY_CBD, "threshold": 3})
    by_id = {row["product_id"]: row for row in report["rows"]}

    assert by_id[never_stocked]["quantity"] == 0
    assert by_id[never_stocked]["has_inventory_row"] is False
    assert by_id[stocked_low]["quantity"] == 2
    assert by_id[stocked_low]["has_inventory_row"] is True
    assert stocked_plenty not in by_id
    assert retired not in by_id                              # a retired product is not sellable work
    assert report["store_name"] == "Sydney CBD" and report["threshold"] == 3


def test_low_stock_is_for_one_store_only():
    product = committed(lambda cur: a_product_id(cur, stock=1, store_id=BONDI))
    at_bondi = fetch(staff_client(ISLA), "low-stock", {"store_id": BONDI})
    assert product in {row["product_id"] for row in at_bondi["rows"]}
    at_cbd = fetch(staff_client(AIDEN), "low-stock", {"store_id": SYDNEY_CBD})
    assert product in {row["product_id"] for row in at_cbd["rows"]}   # never stocked there: 0, low
    assert all(row["quantity"] <= 3 for row in at_cbd["rows"])


# ---------------------------------------------------------------- returns

def test_return_report_cohort_is_the_request_date_not_the_refund_date():
    """A March request refunded in April belongs to the March cohort, with its refund attached."""
    inside = committed(lambda cur: a_return(cur, requested_at=AUGUST_8,
                                            status="refunded", received_store_id=BONDI,
                                            refund="100.00", refunded_at=SEPTEMBER_20))
    committed(lambda cur: a_return(cur, requested_at=JANUARY_8,
                                   status="received", received_store_id=SYDNEY_CBD))
    assert inside

    august = fetch(staff_client(SUPPORT), "returns", AUGUST)
    row = store_row(august, SYDNEY_CBD)
    assert row["requested_count"] == 1                 # the January request is not in this cohort
    assert row["refunded_count"] == 1
    assert row["refunded_amount"] == "100.00"          # joined on the request, not the refund's date
    assert row["receiving_stores"] == "Bondi Junction (1)"    # shown apart from the fulfilling store

    september = fetch(staff_client(SUPPORT), "returns",
                      {"from_date": "2025-09-01", "to_date": "2025-10-01"})
    assert september["totals"]["requested_count"] == 0  # a refund alone does not start a cohort row


def test_return_report_counts_every_status():
    for status in ("requested", "received", "refunded", "rejected"):
        committed(lambda cur, status=status: a_return(
            cur, store_id=BONDI, requested_at=AUGUST_15, status=status,
            received_store_id=BONDI if status in ("received", "refunded") else None,
            refund="100.00" if status == "refunded" else None))
    row = store_row(fetch(staff_client(SUPPORT), "returns", AUGUST), BONDI)
    assert (row["requested_count"], row["received_count"], row["refunded_count"], row["rejected_count"]) \
        == (4, 1, 1, 1)
    assert row["refunded_amount"] == "100.00"


# ---------------------------------------------------------------- boundaries and permissions

def test_the_window_is_sydney_midnight_inclusive_to_exclusive():
    # Sydney is UTC+10 in July, so local midnight is 14:00 UTC the day before. The last second of June and
    # the first second of August are outside the July report; the first and last seconds of July are in it.
    committed(lambda cur: an_order(cur, charge="10.00",
                                   at=datetime(2025, 6, 30, 13, 59, 59, tzinfo=timezone.utc)))
    committed(lambda cur: an_order(cur, charge="20.00",
                                   at=datetime(2025, 6, 30, 14, 0, 0, tzinfo=timezone.utc)))
    committed(lambda cur: an_order(cur, charge="30.00",
                                   at=datetime(2025, 7, 31, 13, 59, 59, tzinfo=timezone.utc)))
    committed(lambda cur: an_order(cur, charge="40.00",
                                   at=datetime(2025, 7, 31, 14, 0, 0, tzinfo=timezone.utc)))

    report = fetch(staff_client(SUPPORT), "sales", {**JULY, "store_id": SYDNEY_CBD})
    window = report["window"]
    assert window["from_date"] == "2025-07-01" and window["to_date"] == "2025-08-01"
    # Melbourne/Sydney standard time is UTC+10, so local midnight is 14:00 UTC the day before.
    assert datetime.fromisoformat(window["from_at"]) == datetime(2025, 6, 30, 14, 0, tzinfo=timezone.utc)
    assert datetime.fromisoformat(window["to_at"]) == datetime(2025, 7, 31, 14, 0, tzinfo=timezone.utc)
    assert Decimal(report["totals"]["captured_amount"]) == Decimal("50.00")   # 20 + 30, not 10 or 40


def test_reports_are_scoped_to_the_signed_in_store():
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get(f"{API}/sales").status_code == 401

    # Support may read everything, or one store; a store's staff only their own.
    assert staff_client(SUPPORT).get(f"{API}/sales", params=MARCH).status_code == 200
    assert staff_client(SUPPORT).get(f"{API}/sales", params={**MARCH, "store_id": BONDI}).status_code == 200
    assert staff_client(AIDEN).get(f"{API}/sales", params={**MARCH, "store_id": SYDNEY_CBD}).status_code == 200
    assert error_of(staff_client(AIDEN).get(f"{API}/sales", params={**MARCH, "store_id": BONDI})) \
        == (403, "other_store")
    assert error_of(staff_client(AIDEN).get(f"{API}/sales", params=MARCH)) == (403, "support_only")

    # Low stock is always one store: with none named it is the signed-in staff member's own.
    assert staff_client(AIDEN).get(f"{API}/low-stock", params={"threshold": 3}).status_code == 200
    assert error_of(staff_client(AIDEN).get(f"{API}/low-stock",
                                            params={"store_id": BONDI, "threshold": 3})) \
        == (403, "other_store")
    assert staff_client(SUPPORT).get(f"{API}/low-stock",
                                     params={"store_id": BONDI, "threshold": 3}).status_code == 200


def test_the_default_window_is_the_last_thirty_days():
    """With no dates, the reports cover the last 30 Sydney days including today.

    Other suites commit orders "now", so this checks the *change* the fixture makes rather than a total.
    """
    client = staff_client(SUPPORT)
    before = fetch(client, "sales", {"store_id": SYDNEY_CBD})
    committed(lambda cur: an_order(cur, charge="12.00", at=datetime.now(timezone.utc) - timedelta(days=2)))
    after = fetch(client, "sales", {"store_id": SYDNEY_CBD})
    window = after["window"]
    assert (datetime.fromisoformat(window["to_date"]) - datetime.fromisoformat(window["from_date"])).days == 30
    assert Decimal(after["totals"]["captured_amount"]) - Decimal(before["totals"]["captured_amount"]) \
        == Decimal("12.00")

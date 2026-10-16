"""Returns when transactions race, and when T2 fails part-way (spec §2, plan §5). Each "request" here is what
the API does: its own connection and one transaction, committed if the service returns and rolled back if it
raises, released at the same moment as the others (run_together). These tests commit, so each one makes its
own products, customer and order.
"""
import time
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth import Actor
from app.errors import ApiError
from app.main import app
from app.schemas.returns import ReturnCreate
from app.services import returns
from tests.auth_support import as_customer, as_staff
from tests.checkout_support import a_customer, a_product, committed, run_together
from tests.returns_support import completed_order, refunds_of, returns_of
from tests.support import connect

client = TestClient(app)
API = "/api/v1"
HOLD = 0.3              # seconds a racing transaction stays open after its work, so the two always overlap
AIDEN = Actor("staff", 14, "Aiden Chen", store_id=1, store_name="Sydney CBD", staff_type="store")
ZARA = Actor("staff", 15, "Zara Ahmed", store_id=1, store_name="Sydney CBD", staff_type="store")


def in_its_own_transaction(work, hold: float = HOLD):
    """Run work(cur) as one request would: its own connection and transaction, committed if it returns,
    rolled back if it raises. It stays open `hold` seconds after the work, so a racing request has to wait."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '10s'")   # a lock regression fails the test, never hangs it
            result = work(cur)
            time.sleep(hold)
            return result
    finally:
        conn.close()


def stock_of(store_id: int, product_id: int) -> int:
    return committed("SELECT quantity FROM inventory WHERE store_id = %s AND product_id = %s",
                     (store_id, product_id))[0]["quantity"]


def a_received_return(lines, *items) -> tuple[dict, int, list[dict]]:
    """A new customer's collected order of items = [(price, quantity, stock at Sydney CBD), ...], a return of
    lines = [(line_no, quantity), ...], received at Sydney CBD. Returns (return detail, customer id, products)."""
    products = [a_product(price, stock=stock) for price, _, stock in items]
    customer, email = a_customer()
    order_id = completed_order(email, [(product["sku"], quantity) for product, (_, quantity, _) in zip(products, items)])
    body = {"reason": "Faulty", "lines": [{"line_no": line_no, "quantity": quantity} for line_no, quantity in lines]}
    asked = client.post(f"{API}/orders/{order_id}/returns", json=body,
                        headers={**as_customer(email), "Idempotency-Key": str(uuid.uuid4())})
    assert asked.status_code == 201, asked.text
    received = client.post(f"{API}/returns/{asked.json()['return_id']}/receive", headers=as_staff(14))
    assert received.status_code == 200, received.text
    return received.json(), customer, products


def test_two_staff_refunding_one_return_refund_it_once():
    """Two staff members press Refund on the same return at once. The first locks the order, then the return;
    the second waits on the order lock, then finds the return refunded and stops — one refund, stock added once."""
    detail, _, (product,) = a_received_return([(1, 2)], ("189.00", 2, 3))
    results = run_together(lambda: in_its_own_transaction(lambda cur: returns.refund_return(cur, AIDEN, detail["return_id"])),
                           lambda: in_its_own_transaction(lambda cur: returns.refund_return(cur, ZARA, detail["return_id"])))
    refunded = [result for result in results if isinstance(result, dict)]
    refused = [result for result in results if isinstance(result, ApiError)]
    assert (len(refunded), len(refused)) == (1, 1), results
    assert (refused[0].status, refused[0].code, refused[0].detail) == (409, "return_status_transition",
                                                                      {"status": "refunded"})
    assert refunds_of(detail["return_id"]) == ["378.00"]
    assert stock_of(1, product["product_id"]) == 5


def test_the_refund_unique_key_is_the_backstop():
    """Skip T2's status check and insert the same refund twice at once: UNIQUE (return_id) on payment (BR14)
    still lets only one in. The return is worth less than half of what the order was charged (149.95 of
    527.95) on purpose: the second insert first waits in br14_refunds_within_charged for the order lock, and
    when it goes on, that trigger (which runs before the unique check) would refuse it if the two refunds
    together came to more than the charge — and the test would no longer be about the unique key."""
    detail, _, _ = a_received_return([(2, 1)], ("189.00", 2, 0), ("149.95", 1, 0))
    assert detail["value"] == "149.95"

    def refund_directly(cur):
        cur.execute("INSERT INTO payment (order_id, kind, amount, return_id) VALUES (%s, 'refund', %s, %s)",
                    (detail["order_id"], detail["value"], detail["return_id"]))
        return "refunded"

    results = run_together(lambda: in_its_own_transaction(refund_directly),
                           lambda: in_its_own_transaction(refund_directly))
    refused = [result for result in results if isinstance(result, psycopg2.Error)]
    assert (results.count("refunded"), len(refused)) == (1, 1), results
    assert refused[0].diag.constraint_name == "br14_refund_once_per_return"
    assert refunds_of(detail["return_id"]) == ["149.95"]


def test_a_failed_refund_rolls_back_everything(monkeypatch):
    """Plan §5's simulated failure for T2: the refund is written, then the payment provider fails. By then the
    stock is back on the shelf inside the transaction; the failure takes the stock and the payment back, the
    return stays received, and it can be refunded again."""
    detail, _, (product,) = a_received_return([(1, 1)], ("189.00", 2, 3))
    real_refund = returns._refund
    seen = {}

    def provider_down(cur, return_id):
        real_refund(cur, return_id)
        cur.execute("SELECT (SELECT quantity FROM inventory WHERE store_id = 1 AND product_id = %s) AS stock, "
                    "(SELECT count(*) FROM payment WHERE return_id = %s) AS refunds", (product["product_id"], return_id))
        seen.update(cur.fetchone())
        raise RuntimeError("payment provider unavailable")

    monkeypatch.setattr(returns, "_refund", provider_down)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        in_its_own_transaction(lambda cur: returns.refund_return(cur, AIDEN, detail["return_id"]), hold=0)
    assert (seen["stock"], seen["refunds"]) == (4, 1)                    # written, inside the transaction
    assert stock_of(1, product["product_id"]) == 3
    assert refunds_of(detail["return_id"]) == []
    assert client.get(f"{API}/returns/{detail['return_id']}", headers=as_staff(14)).json()["status"] == "received"

    monkeypatch.setattr(returns, "_refund", real_refund)
    in_its_own_transaction(lambda cur: returns.refund_return(cur, AIDEN, detail["return_id"]), hold=0)
    assert refunds_of(detail["return_id"]) == ["189.00"]
    assert stock_of(1, product["product_id"]) == 4


def test_a_failure_after_the_status_change_rolls_it_back_too(monkeypatch):
    """The last step of T2 is the move to refunded; failing right after it (here, in the final read) still
    takes the status, the refund and the stock back together."""
    detail, _, (product,) = a_received_return([(1, 1)], ("189.00", 2, 3))

    def read_fails(cur, actor, return_id):
        raise RuntimeError("lost the connection")

    monkeypatch.setattr(returns, "get_return", read_fails)
    with pytest.raises(RuntimeError, match="lost the connection"):
        in_its_own_transaction(lambda cur: returns.refund_return(cur, AIDEN, detail["return_id"]), hold=0)
    status = committed("SELECT status, resolved_at FROM return_request WHERE return_id = %s", (detail["return_id"],))
    assert [(row["status"], row["resolved_at"]) for row in status] == [("received", None)]
    assert refunds_of(detail["return_id"]) == []
    assert stock_of(1, product["product_id"]) == 3


def test_the_same_key_at_once_creates_one_return():
    """A double click: the same request, with the same key, twice at once. The second claim waits on the unique
    key (BR10) for the first transaction, then replays its return."""
    customer, email = a_customer()
    order_id = completed_order(email, [(a_product("189.00")["sku"], 2)])
    buyer = Actor("customer", customer, "Checkout Tester")
    body = ReturnCreate.model_validate({"reason": "Too big", "lines": [{"line_no": 1, "quantity": 1}]})
    key = uuid.uuid4()
    results = run_together(*[lambda: in_its_own_transaction(lambda cur: returns.request_return(cur, buyer, order_id,
                                                                                               key, body))] * 2)
    assert sorted(replayed for _, replayed in results) == [False, True], results
    assert results[0][0]["return_id"] == results[1][0]["return_id"]
    assert returns_of(order_id) == [results[0][0]["return_id"]]


def test_two_requests_for_the_last_units_of_a_line_have_one_winner():
    """Two different requests (two keys) for both units of line 1 at once. BR12's trigger locks the order line
    FOR UPDATE before it adds up what is already returned, so the second waits, then counts the first's units."""
    customer, email = a_customer()
    order_id = completed_order(email, [(a_product("189.00")["sku"], 2)])
    buyer = Actor("customer", customer, "Checkout Tester")
    body = ReturnCreate.model_validate({"reason": "Too big", "lines": [{"line_no": 1, "quantity": 2}]})
    results = run_together(*[lambda: in_its_own_transaction(lambda cur: returns.request_return(cur, buyer, order_id,
                                                                                               uuid.uuid4(), body))] * 2)
    refused = [result for result in results if isinstance(result, psycopg2.Error)]
    assert len(refused) == 1, results
    assert refused[0].diag.constraint_name == "br12_return_qty_within_purchased"
    assert len(returns_of(order_id)) == 1

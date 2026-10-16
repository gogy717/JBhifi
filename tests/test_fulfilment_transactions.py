"""Fulfilment and T4 under concurrency and failure (report §4).

Two requests at once on one order: both lock the order row FOR UPDATE first, so the second waits, then reads the
first one's committed status, finds it differs from the status its screen showed, and is told so (409
status_changed): exactly one of them acts. And a cancellation that fails part-way changes nothing: the restock,
the refund and the status change are one transaction.
"""
import time
from decimal import Decimal

from fastapi.testclient import TestClient

from app.auth import Actor
from app.errors import ApiError
from app.main import app
from app.schemas.fulfilment import CancelRequest, StatusMove
from app.services import fulfilment
from tests.auth_support import as_customer
from tests.checkout_support import SYDNEY_CBD, quantity_at, run_together
from tests.fulfilment_support import bought, history_of, payments_of, status_of
from tests.support import connect

AIDEN = Actor("staff", 14, "Aiden Chen", SYDNEY_CBD, "Sydney CBD", "store")
OLIVIA = Actor("staff", 1, "Olivia Nguyen", SYDNEY_CBD, "Sydney CBD", "store", runs_store=True)
HOLD = 0.3                      # seconds a request keeps its locks before it commits, so the other one meets them


def customer(order) -> Actor:
    return Actor("customer", order.customer_id, "Checkout Tester")


def request(work):
    """One request the way the API runs it: its own connection and transaction, committed if work(cur) returns
    and rolled back if it raises. It holds its locks for HOLD seconds before committing."""
    def run():
        conn = connect()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")   # a lock regression fails the test, never hangs it
                result = work(cur)
                time.sleep(HOLD)
                return result
        finally:
            conn.close()
    return run


def move(actor, order_id, from_status, to_status):
    return request(lambda cur: fulfilment.advance_order(cur, actor, order_id,
                                                         StatusMove(from_status=from_status, to_status=to_status)))


def cancel(actor, order_id, from_status):
    return request(lambda cur: fulfilment.cancel_order(cur, actor, order_id, CancelRequest(from_status=from_status)))


def one_winner(results) -> tuple[dict, ApiError]:
    """The two results of a race: exactly one order detail and one status_changed refusal."""
    won = [result for result in results if isinstance(result, dict)]
    lost = [result for result in results if isinstance(result, ApiError)]
    assert (len(won), len(lost)) == (1, 1), results
    assert lost[0].code == "status_changed"
    return won[0], lost[0]


def test_two_clerks_making_the_same_move_at_once_one_wins():
    order = bought()
    won, lost = one_winner(run_together(move(AIDEN, order.order_id, "paid", "picking"),
                                        move(OLIVIA, order.order_id, "paid", "picking")))
    assert lost.detail == {"status": "picking"}
    assert [to for _, to, _ in history_of(order.order_id)] == ["placed", "paid", "picking"]   # logged once
    assert history_of(order.order_id)[-1][2] == won["history"][-1]["changed_by_staff_id"]


def test_a_cancel_and_a_move_at_once_have_one_winner():
    order = bought(quantity=2, stock=5)
    won, _ = one_winner(run_together(cancel(customer(order), order.order_id, "paid"),
                                     move(AIDEN, order.order_id, "paid", "picking")))
    if won["status"] == "cancelled":
        assert (quantity_at(order.store_id, order.product_id), len(payments_of(order.order_id))) == (5, 2)
    else:
        assert won["status"] == "picking"
        assert (quantity_at(order.store_id, order.product_id), len(payments_of(order.order_id))) == (3, 1)
    assert status_of(order.order_id) == won["status"]


def test_the_customer_and_the_store_cancelling_at_once_refund_once():
    order = bought(quantity=2, stock=5)
    one_winner(run_together(cancel(customer(order), order.order_id, "paid"),
                            cancel(AIDEN, order.order_id, "paid")))
    assert payments_of(order.order_id) == [("charge", "200.00", None), ("refund", "200.00", None)]
    assert quantity_at(order.store_id, order.product_id) == 5          # back once, not twice
    assert [to for _, to, _ in history_of(order.order_id)].count("cancelled") == 1


# ---------------------------------------------------------------- failures roll back everything

api = TestClient(app, raise_server_exceptions=False)     # a failure is answered as the API answers it


def cancel_through_the_api(order):
    return api.post(f"/api/v1/orders/{order.order_id}/cancel", json={"from_status": "paid"},
                    headers=as_customer(order.email))


def assert_untouched(order):
    """Exactly as checkout left it: paid, one charge, two history rows, the stock still taken."""
    assert status_of(order.order_id) == "paid"
    assert payments_of(order.order_id) == [("charge", order.total, None)]
    assert len(history_of(order.order_id)) == 2
    assert quantity_at(order.store_id, order.product_id) == 3


def test_a_failed_refund_rolls_back_the_whole_cancellation(monkeypatch):
    order = bought(quantity=2, stock=5)

    def provider_down(cur, order_id):
        raise RuntimeError("the payment provider is down")
    monkeypatch.setattr(fulfilment, "_refund", provider_down)        # fails after the restock has run

    assert cancel_through_the_api(order).status_code == 500
    assert_untouched(order)


def test_a_short_refund_is_refused_by_br21_and_the_restock_rolls_back(monkeypatch):
    order = bought(quantity=2, stock=5)

    def one_cent_short(cur, order_id):
        cur.execute("INSERT INTO payment (order_id, kind, amount) VALUES (%s, 'refund', %s)",
                    (order_id, Decimal(order.total) - Decimal("0.01")))
    monkeypatch.setattr(fulfilment, "_refund", one_cent_short)

    response = cancel_through_the_api(order)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "br21_cancelled_order_refunded")
    assert_untouched(order)


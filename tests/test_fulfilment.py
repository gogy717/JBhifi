"""Moving orders along (R7, R11): POST /orders/{id}/status and the store queue GET /stores/{id}/orders.

Who may move an order (the fulfilling store's staff, and support), that BR09 decides which moves are legal, that
every move is logged with the staff member who made it, and that a screen showing an old status is told the
current one instead of moving the order (spec §3). Orders are placed by a real checkout (tests/fulfilment_support.py).
"""
from fastapi.testclient import TestClient

from app.main import app
from tests.auth_support import as_customer, as_staff
from tests.checkout_support import BONDI, SYDNEY_CBD
from tests.fulfilment_support import bought, history_of, status_of
from tests.orders_support import move

client = TestClient(app)
API = "/api/v1"
OLIVIA, AIDEN = 1, 14           # Sydney CBD (store 1): its manager, and a member of staff
ISLA = 16                       # Bondi Junction (store 2)
NORA = 40                       # support


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def move_to(order_id: int, from_status: str, to_status: str, headers: dict):
    return client.post(f"{API}/orders/{order_id}/status", json={"from_status": from_status, "to_status": to_status},
                       headers=headers)


def walk(order_id: int, statuses: list[str], staff_id: int) -> None:
    """Move the order through statuses in turn as staff_id, checking each answer."""
    current = status_of(order_id)
    for status in statuses:
        response = move_to(order_id, current, status, as_staff(staff_id))
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == status
        current = status


def test_a_collection_order_moves_paid_picking_ready_collected():
    order = bought()
    walk(order.order_id, ["picking", "ready", "collected"], AIDEN)
    assert history_of(order.order_id) == [
        (None, "placed", None),
        ("placed", "paid", None),             # the customer's own checkout
        ("paid", "picking", AIDEN),
        ("picking", "ready", AIDEN),
        ("ready", "collected", AIDEN),
    ]


def test_a_delivery_order_moves_paid_picking_shipped_delivered():
    order = bought(method="delivery")        # shipped from Sydney CBD, where it is stocked
    walk(order.order_id, ["picking", "shipped", "delivered"], OLIVIA)
    assert history_of(order.order_id)[2:] == [
        ("paid", "picking", OLIVIA),
        ("picking", "shipped", OLIVIA),
        ("shipped", "delivered", OLIVIA),
    ]


def test_support_moves_an_order_and_the_history_names_them():
    order = bought(store_id=BONDI)
    walk(order.order_id, ["picking"], NORA)
    assert history_of(order.order_id)[-1] == ("paid", "picking", NORA)


def test_the_answer_is_the_order_in_full():
    order = bought()
    detail = move_to(order.order_id, "paid", "picking", as_staff(AIDEN)).json()
    assert detail["allowed_next_statuses"] == ["ready"]           # picking can't be cancelled
    assert [entry["changed_by_name"] for entry in detail["history"]][-1] == "Aiden Chen"


def test_an_illegal_move_is_refused_by_br09():
    order = bought()
    assert error_of(move_to(order.order_id, "paid", "ready", as_staff(AIDEN))) == (409, "br09_order_status_transition")
    assert error_of(move_to(order.order_id, "paid", "shipped", as_staff(AIDEN))) == (409, "br09_order_status_transition")
    assert status_of(order.order_id) == "paid"
    assert len(history_of(order.order_id)) == 2                   # placed, paid: nothing logged


def test_paid_and_cancelled_are_not_moves():
    order = bought()
    for to_status in ("paid", "cancelled", "nowhere"):           # paid is checkout's; cancelling is T4
        assert error_of(move_to(order.order_id, "placed", to_status, as_staff(AIDEN))) == (422, "validation_error")


def test_another_stores_staff_and_customers_cannot_move_an_order():
    order = bought()
    assert error_of(move_to(order.order_id, "paid", "picking", as_staff(ISLA))) == (403, "other_store")
    assert error_of(move_to(order.order_id, "paid", "picking", as_customer(order.email))) == (403, "staff_only")
    assert error_of(move_to(order.order_id, "paid", "picking", {})) == (401, "not_signed_in")
    assert status_of(order.order_id) == "paid"


def test_a_missing_order_is_403_for_store_staff_and_404_for_support():
    assert error_of(move_to(999999, "paid", "picking", as_staff(ISLA))) == (403, "other_store")
    assert error_of(move_to(999999, "paid", "picking", as_staff(NORA))) == (404, "not_found")


def test_a_stale_screen_is_told_the_current_status():
    order = bought()
    move(order.order_id, "picking", staff_id=AIDEN)              # someone else got there first
    response = move_to(order.order_id, "paid", "picking", as_staff(AIDEN))
    assert error_of(response) == (409, "status_changed")
    assert response.json()["error"]["detail"] == {"status": "picking"}


def test_sending_the_same_move_twice_moves_the_order_once():
    order = bought()
    assert move_to(order.order_id, "paid", "picking", as_staff(AIDEN)).status_code == 200
    assert error_of(move_to(order.order_id, "paid", "picking", as_staff(AIDEN))) == (409, "status_changed")
    assert [row[1] for row in history_of(order.order_id)] == ["placed", "paid", "picking"]


# ---------------------------------------------------------------- the store queue

def queue(store_id: int, headers: dict, *statuses: str):
    return client.get(f"{API}/stores/{store_id}/orders", params=[("status", s) for s in statuses], headers=headers)


def test_the_queue_lists_the_stores_orders_oldest_first_with_a_status_filter():
    first, second = bought(), bought()
    move(second.order_id, "picking", staff_id=AIDEN)
    elsewhere = bought(store_id=BONDI)

    everything = queue(SYDNEY_CBD, as_staff(AIDEN))
    assert everything.status_code == 200
    ids = [row["order_id"] for row in everything.json()]
    assert ids.index(first.order_id) < ids.index(second.order_id)
    assert elsewhere.order_id not in ids
    assert {row["fulfilling_store_id"] for row in everything.json()} == {SYDNEY_CBD}

    picking = [row["order_id"] for row in queue(SYDNEY_CBD, as_staff(AIDEN), "picking").json()]
    assert second.order_id in picking and first.order_id not in picking
    to_do = [row["order_id"] for row in queue(SYDNEY_CBD, as_staff(AIDEN), "paid", "picking").json()]
    assert {first.order_id, second.order_id} <= set(to_do)


def test_the_queue_is_for_that_stores_staff_and_support():
    assert queue(SYDNEY_CBD, as_staff(NORA)).status_code == 200
    assert error_of(queue(SYDNEY_CBD, as_staff(ISLA))) == (403, "other_store")
    assert error_of(queue(SYDNEY_CBD, as_customer("queue.peek@example.com"))) == (403, "staff_only")
    assert error_of(queue(SYDNEY_CBD, {})) == (401, "not_signed_in")
    assert error_of(queue(99, as_staff(NORA))) == (404, "not_found")
    assert error_of(queue(SYDNEY_CBD, as_staff(AIDEN), "bogus")) == (422, "validation_error")

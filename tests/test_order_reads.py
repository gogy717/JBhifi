"""Reading orders: GET /orders/{id} (one order in full) and GET /customers/{id}/orders (newest first).

Who may read which order, what a paid order shows, and that one read sees one moment. The orders are built
in SQL as a checkout leaves them (tests/orders_support.py), for customers who sign up inside each test, so
nothing here depends on what other tests committed.
"""
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth import Actor
from app.main import app
from app.services.orders import get_order
from tests.auth_support import as_customer, as_staff
from tests.orders_support import customer_id, move, paid_order
from tests.support import connect, unique_sku

client = TestClient(app)
API = "/api/v1"
OLIVIA, AIDEN = 1, 14           # Sydney CBD (store 1): its manager, and a member of staff
ISLA = 16                       # Bondi Junction (store 2)
SAMUEL = 38                     # the warehouse (store 13)
NORA = 40                       # support
WAREHOUSE = 13
NEW_ADDRESS = {"line1": "5 New Street", "suburb": "Newtown", "state": "NSW", "postcode": "2042"}


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def new_email() -> str:
    return f"reader.{uuid.uuid4().hex[:10]}@example.com"


def read(order_id: int, headers: dict):
    return client.get(f"{API}/orders/{order_id}", headers=headers)


def committed(query: str, params=()):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(query, params)
    finally:
        conn.close()


def with_an_address() -> tuple[str, int]:
    """A new customer who adds one delivery address: (email, address_no)."""
    email = new_email()
    response = client.post(f"{API}/customers/{customer_id(email)}/addresses", headers=as_customer(email),
                           json=NEW_ADDRESS)
    assert response.status_code == 201, response.text
    return email, response.json()["address_no"]


def a_product(price: str) -> str:
    """A new product selling at price (no promotion); returns its SKU."""
    sku = unique_sku()
    committed(
        """
        INSERT INTO product (sku, name, brand_id, category_id, base_price)
        SELECT %s, 'Order read test item', b.brand_id, c.category_id, %s
        FROM brand b, category c
        WHERE b.name = 'JBL' AND c.name = 'Speakers'
        """,
        (sku, price),
    )
    return sku


# ---------------------------------------------------------------- one order: who may read it

def test_a_customer_reads_their_own_order_with_money_as_two_decimal_strings():
    email = new_email()
    order_id = paid_order(email, [("APL-AP4", 2), ("JBL-FLIP7-B", 1)])      # on sale: 189.00 and 149.95
    response = read(order_id, as_customer(email))
    assert response.status_code == 200, response.text
    order = response.json()
    assert (order["order_id"], order["customer_id"], order["status"]) == (order_id, customer_id(email), "paid")
    assert (order["fulfilment_method"], order["fulfilling_store_id"], order["fulfilling_store_name"]) \
        == ("click_collect", 1, "Sydney CBD")
    assert (order["total"], order["line_count"], order["delivery_address"]) == ("527.95", 2, None)
    assert [line["line_no"] for line in order["lines"]] == [1, 2]
    lines = sorted((line["sku"], line["quantity"], line["unit_price"], line["line_total"]) for line in order["lines"])
    assert lines == [("APL-AP4", 2, "189.00", "378.00"), ("JBL-FLIP7-B", 1, "149.95", "149.95")]
    assert order["payment"] == {"charged": "527.95", "refunded": "0.00", "balance": "527.95"}
    assert [(entry["seq"], entry["from_status"], entry["to_status"], entry["changed_by_name"])
            for entry in order["history"]] == [(1, None, "placed", None), (2, "placed", "paid", None)]
    assert order["last_updated_at"] == order["history"][-1]["changed_at"]


def test_a_customer_gets_the_same_403_for_someone_elses_order_and_a_missing_one():
    owner = new_email()
    order_id = paid_order(owner, [("APL-AP4", 1)])
    stranger = as_customer(new_email())
    assert error_of(read(order_id, stranger)) == (403, "not_your_order")
    assert error_of(read(999999, stranger)) == (403, "not_your_order")      # so order ids can't be probed
    assert read(order_id, as_customer(owner)).status_code == 200


def test_store_staff_read_their_own_stores_orders_and_no_others():
    order_id = paid_order(new_email(), [("APL-AP4", 1)])                    # Click & Collect at Sydney CBD
    assert read(order_id, as_staff(AIDEN)).status_code == 200
    assert read(order_id, as_staff(OLIVIA)).status_code == 200
    assert error_of(read(order_id, as_staff(ISLA))) == (403, "other_store")
    assert error_of(read(999999, as_staff(ISLA))) == (403, "other_store")


def test_support_reads_any_order_and_gets_404_for_a_missing_one():
    email, address_no = with_an_address()
    order_id = paid_order(email, [("APL-AP4", 1)], method="delivery", store_id=WAREHOUSE, address_no=address_no)
    assert read(order_id, as_staff(NORA)).status_code == 200
    assert error_of(read(999999, as_staff(NORA))) == (404, "not_found")    # support may read every order
    assert error_of(read(order_id, as_staff(AIDEN))) == (403, "other_store")   # it ships from the warehouse


def test_a_guest_must_sign_in_to_read_orders():
    assert error_of(client.get(f"{API}/orders/1")) == (401, "not_signed_in")
    assert error_of(client.get(f"{API}/customers/1/orders")) == (401, "not_signed_in")


# ---------------------------------------------------------------- what an order shows

def test_the_detail_keeps_the_sold_price_and_the_address_it_was_placed_with():
    email, address_no = with_an_address()
    sku = a_product("189.00")
    order_id = paid_order(email, [(sku, 1)], method="delivery", store_id=WAREHOUSE, address_no=address_no)
    # Afterwards the price goes up, and the customer retires the address.
    committed("UPDATE product SET base_price = 999.00 WHERE sku = %s", (sku,))
    headers = as_customer(email)
    retired = client.patch(f"{API}/customers/{customer_id(email)}/addresses/{address_no}", headers=headers,
                           json={"is_active": False})
    assert retired.status_code == 200, retired.text

    order = read(order_id, headers).json()
    assert (order["lines"][0]["unit_price"], order["total"]) == ("189.00", "189.00")    # the price it sold at (BR08)
    assert order["delivery_address"] == {"address_no": address_no, **NEW_ADDRESS}         # as placed (BR16)


def test_the_detail_lists_the_next_statuses_the_transition_table_allows():
    def next_statuses(order_id, headers=None):
        return read(order_id, headers or as_staff(NORA)).json()["allowed_next_statuses"]

    email = new_email()
    collect = paid_order(email, [("APL-AP4", 1)])
    assert next_statuses(collect) == ["picking", "cancelled"]                # the way forward first
    # The same list for every reader: it describes the order, not what the reader may do.
    assert next_statuses(collect, as_customer(email)) == next_statuses(collect, as_staff(AIDEN)) \
        == ["picking", "cancelled"]
    move(collect, "picking", "ready", staff_id=AIDEN)
    assert next_statuses(collect) == ["collected", "cancelled"]              # cancelled if never collected
    move(collect, "collected", staff_id=AIDEN)
    assert next_statuses(collect) == []

    email, address_no = with_an_address()
    delivery = paid_order(email, [("APL-AP4", 1)], method="delivery", store_id=WAREHOUSE, address_no=address_no)
    move(delivery, "picking", staff_id=SAMUEL)
    assert next_statuses(delivery) == ["shipped"]               # once a delivery is being picked, no cancelling


def start_picking(conn, order_id: int):
    """Aiden moves the order paid → picking on conn, giving up if he waits more than 200 ms for a lock."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '200ms'")
        cur.execute("SELECT set_config('app.staff_id', %s, true)", (str(AIDEN),))
        cur.execute("UPDATE customer_order SET status = 'picking' WHERE order_id = %s", (order_id,))


def test_reading_an_order_holds_off_a_status_change_until_the_read_ends():
    order_id = paid_order(new_email(), [("APL-AP4", 1)])
    support = Actor("staff", NORA, "Nora Fitzgerald", staff_type="support")
    reader, writer = connect(), connect()
    try:
        with reader.cursor() as cur:
            assert get_order(cur, support, order_id)["status"] == "paid"    # the read's transaction stays open
        # The read holds the order row FOR SHARE, so the status UPDATE waits for it — and gives up.
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            start_picking(writer, order_id)
        writer.rollback()
        reader.commit()                                                     # the read ends: its lock goes
        start_picking(writer, order_id)
        writer.commit()
    finally:
        reader.close()
        writer.close()
    history = read(order_id, as_staff(NORA)).json()["history"]
    assert (history[-1]["from_status"], history[-1]["to_status"], history[-1]["changed_by_name"]) \
        == ("paid", "picking", "Aiden Chen")


# ---------------------------------------------------------------- a customer's orders

def test_the_customer_lists_their_own_orders_newest_first():
    email = new_email()
    first = paid_order(email, [("APL-AP4", 1)])
    second = paid_order(email, [("JBL-FLIP7-B", 2)])
    response = client.get(f"{API}/customers/{customer_id(email)}/orders", headers=as_customer(email))
    assert response.status_code == 200, response.text
    assert [(order["order_id"], order["status"], order["total"], order["line_count"], order["fulfilling_store_name"])
            for order in response.json()] == [(second, "paid", "299.90", 1, "Sydney CBD"),
                                              (first, "paid", "189.00", 1, "Sydney CBD")]


def test_a_customer_cannot_list_another_customers_orders():
    owner = new_email()
    paid_order(owner, [("APL-AP4", 1)])
    url = f"{API}/customers/{customer_id(owner)}/orders"
    assert error_of(client.get(url, headers=as_customer(new_email()))) == (403, "not_your_account")


def test_support_lists_any_customers_orders_but_store_staff_cannot():
    email = new_email()
    order_id = paid_order(email, [("APL-AP4", 1)])                          # at Sydney CBD, Aiden's store
    url = f"{API}/customers/{customer_id(email)}/orders"
    response = client.get(url, headers=as_staff(NORA))
    assert response.status_code == 200, response.text
    assert [order["order_id"] for order in response.json()] == [order_id]
    assert error_of(client.get(url, headers=as_staff(AIDEN))) == (403, "support_only")
    assert error_of(client.get(f"{API}/customers/999999/orders", headers=as_staff(NORA))) == (404, "not_found")

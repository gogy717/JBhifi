"""T06: a customer prepares delivery addresses by adding new ones and retiring old ones — never editing."""
import psycopg2

from tests.shop import a_customer, error_of, shop_client, staff_client, SUPPORT
from tests.support import connect, unique_sku
from tests.concurrency import run_at_once

API = "/api/v1"
NEW_ADDRESS = {"line1": "5 New Street", "suburb": "Newtown", "state": "NSW", "postcode": "2042"}


def addresses(client, customer_id):
    return client.get(f"{API}/customers/{customer_id}").json()["addresses"]


def test_a_new_address_gets_the_next_number():
    customer_id, numbers = a_customer(addresses=2)
    client = shop_client(customer_id)
    response = client.post(f"{API}/customers/{customer_id}/addresses", json=NEW_ADDRESS)
    assert response.status_code == 201, response.text
    assert response.json()["address_no"] == 3
    assert response.json()["is_active"] is True
    assert [row["address_no"] for row in addresses(client, customer_id)] == [1, 2, 3]


def test_concurrent_adds_get_distinct_numbers():
    customer_id, _ = a_customer(addresses=0)

    def add(_):
        client = shop_client(customer_id)
        try:
            return client.post(f"{API}/customers/{customer_id}/addresses", json=NEW_ADDRESS).json()
        finally:
            client.close()

    results = run_at_once(3, add)
    assert all(isinstance(result, dict) for result in results), results
    assert sorted(result["address_no"] for result in results) == [1, 2, 3]


def test_retiring_is_idempotent_and_keeps_the_address():
    customer_id, numbers = a_customer()
    client = shop_client(customer_id)
    url = f"{API}/customers/{customer_id}/addresses/{numbers[0]}"

    first = client.patch(url, json={"is_active": False})
    assert first.status_code == 200, first.text
    assert first.json()["is_active"] is False
    again = client.patch(url, json={"is_active": False})
    assert again.status_code == 200
    assert again.json() == first.json()                      # unchanged, and still listed
    assert [(row["address_no"], row["is_active"]) for row in addresses(client, customer_id)] \
        == [(1, False)]


def test_address_text_cannot_be_patched_and_the_number_must_exist():
    customer_id, numbers = a_customer()
    client = shop_client(customer_id)
    url = f"{API}/customers/{customer_id}/addresses/{numbers[0]}"

    assert client.patch(url, json={"line1": "Somewhere else"}).status_code == 422
    assert client.patch(url, json={"is_active": True}).status_code == 422     # only retiring, never back
    assert client.patch(url, json={"is_active": False, "line1": "x"}).status_code == 422
    assert error_of(client.patch(f"{API}/customers/{customer_id}/addresses/99",
                                 json={"is_active": False})) == (404, "not_found")
    # BR16 still guards the row itself.
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT s")
            try:
                cur.execute("UPDATE customer_address SET line1 = 'x' WHERE customer_id = %s AND address_no = %s",
                            (customer_id, numbers[0]))
            except psycopg2.Error as error:
                assert error.diag.constraint_name == "br16_address_immutable"
                cur.execute("ROLLBACK TO SAVEPOINT s")
            else:
                raise AssertionError("BR16 should have refused the edit")
    finally:
        conn.rollback()
        conn.close()


def test_a_new_address_must_be_well_formed():
    customer_id, _ = a_customer()
    client = shop_client(customer_id)
    url = f"{API}/customers/{customer_id}/addresses"
    assert error_of(client.post(url, json={**NEW_ADDRESS, "state": "XX"})) == (409, "au_state_valid")
    assert error_of(client.post(url, json={**NEW_ADDRESS, "postcode": "12"})) == (422, "validation_error")
    assert error_of(client.post(url, json={**NEW_ADDRESS, "postcode": "ABCD"})) == (409, "au_postcode_format")
    assert error_of(client.post(url, json={**NEW_ADDRESS, "line1": ""})) == (422, "validation_error")


def test_only_the_owner_can_change_their_addresses():
    customer_id, numbers = a_customer()
    stranger = shop_client(a_customer()[0])
    url = f"{API}/customers/{customer_id}/addresses"
    assert error_of(stranger.post(url, json=NEW_ADDRESS)) == (403, "not_your_account")
    assert error_of(stranger.patch(f"{url}/{numbers[0]}", json={"is_active": False})) \
        == (403, "not_your_account")
    # Support staff read records but do not edit someone's addresses for them.
    assert error_of(staff_client(SUPPORT).post(url, json=NEW_ADDRESS)) == (403, "customer_only")
    assert unique_sku() is not None


def test_an_old_order_still_shows_the_address_it_was_placed_with():
    from tests.shop import WAREHOUSE, a_product, order_body, place
    customer_id, numbers = a_customer()
    product = a_product(stock=2, store_id=WAREHOUSE)
    client = shop_client(customer_id)
    order = place(client, order_body([(product, 1)], method="delivery", store_id=WAREHOUSE,
                                     address_no=numbers[0])).json()

    added = client.post(f"{API}/customers/{customer_id}/addresses", json=NEW_ADDRESS).json()
    client.patch(f"{API}/customers/{customer_id}/addresses/{numbers[0]}", json={"is_active": False})

    detail = client.get(f"{API}/orders/{order['order_id']}").json()
    assert detail["delivery_address"]["address_no"] == numbers[0]
    assert detail["delivery_address"]["line1"] == "1 Test St"          # unchanged by the retirement
    assert added["address_no"] == 2

"""Delivery addresses (BR16): a customer adds new ones and retires old ones — an address is never edited,
because orders keep pointing at the address they were placed with. Only the customer changes them.

These tests commit, so each one signs up a new customer (a new email) and works on that customer only.
"""
import uuid

from fastapi.testclient import TestClient

from app.auth import Actor
from app.main import app
from app.schemas.customers import AddressCreate
from app.services.customers import add_address
from tests.auth_support import as_customer, as_staff
from tests.support import connect, run_at_once

client = TestClient(app)
API = "/api/v1"
AIDEN, NORA = 14, 40            # store staff at Sydney CBD; support
NEW_ADDRESS = {"line1": "5 New Street", "suburb": "Newtown", "state": "NSW", "postcode": "2042"}
RETIRE = {"is_active": False}


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def new_customer() -> tuple[int, dict]:
    """Someone who has just signed up with a new email: (customer_id, sign-in headers). No addresses yet."""
    headers = as_customer(f"addresses.{uuid.uuid4().hex[:10]}@example.com")
    response = client.get(f"{API}/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"], headers


def add(customer_id: int, headers: dict, body=None):
    return client.post(f"{API}/customers/{customer_id}/addresses", headers=headers, json=body or NEW_ADDRESS)


def addresses_of(customer_id: int, headers: dict) -> list[tuple[int, bool]]:
    """(address_no, is_active) of each of the customer's addresses, as GET /customers/{id} lists them."""
    response = client.get(f"{API}/customers/{customer_id}", headers=headers)
    assert response.status_code == 200, response.text
    return [(address["address_no"], address["is_active"]) for address in response.json()["addresses"]]


def test_each_new_address_takes_the_next_number():
    customer_id, headers = new_customer()
    responses = [add(customer_id, headers) for _ in range(3)]
    assert [response.status_code for response in responses] == [201, 201, 201], responses[-1].text
    assert [response.json()["address_no"] for response in responses] == [1, 2, 3]
    assert responses[-1].json() == {"address_no": 3, **NEW_ADDRESS, "is_active": True}
    assert addresses_of(customer_id, headers) == [(1, True), (2, True), (3, True)]


def test_an_address_is_trimmed():
    customer_id, headers = new_customer()
    response = add(customer_id, headers,
                   {"line1": "  5 New Street ", "suburb": " Newtown", "state": " NSW ", "postcode": "2042 "})
    assert response.status_code == 201, response.text
    assert response.json() == {"address_no": 1, **NEW_ADDRESS, "is_active": True}


def test_a_lower_case_state_is_the_databases_call():
    """Pydantic only trims and checks lengths; whether 'nsw' is a state is the au_state domain's decision."""
    customer_id, headers = new_customer()
    response = add(customer_id, headers, {**NEW_ADDRESS, "state": "nsw"})
    assert (response.status_code, response.json()["error"]["code"]) == (409, "au_state_valid"), response.text


def test_concurrent_adds_get_distinct_numbers():
    customer_id, _ = new_customer()
    owner = Actor("customer", customer_id, "Test User")

    def one_request():
        """What the API does for one POST: its own connection and one transaction (app/db.py)."""
        conn = connect()
        try:
            with conn, conn.cursor() as cur:
                return dict(add_address(cur, owner, customer_id, AddressCreate(**NEW_ADDRESS)))
        finally:
            conn.close()

    results = run_at_once(3, one_request)
    assert all(isinstance(result, dict) for result in results), results
    # The customer row lock made the three adds take turns, and each saw the one before it.
    assert sorted(result["address_no"] for result in results) == [1, 2, 3]


def test_retiring_an_address_keeps_it_and_retiring_it_again_changes_nothing():
    customer_id, headers = new_customer()
    add(customer_id, headers)
    url = f"{API}/customers/{customer_id}/addresses/1"
    first = client.patch(url, headers=headers, json=RETIRE)
    assert first.status_code == 200, first.text
    assert first.json() == {"address_no": 1, **NEW_ADDRESS, "is_active": False}
    again = client.patch(url, headers=headers, json=RETIRE)
    assert (again.status_code, again.json()) == (200, first.json())
    assert addresses_of(customer_id, headers) == [(1, False)]          # kept: past orders still point at it


def test_retiring_is_the_only_change_an_address_accepts():
    customer_id, headers = new_customer()
    add(customer_id, headers)
    url = f"{API}/customers/{customer_id}/addresses/1"
    for body in ({"line1": "6 Other Street"}, {"is_active": True}, {"is_active": False, "line1": "6 Other Street"}):
        assert error_of(client.patch(url, headers=headers, json=body)) == (422, "validation_error"), body
    assert addresses_of(customer_id, headers) == [(1, True)]


def test_a_new_address_must_be_well_formed():
    customer_id, headers = new_customer()
    # What a state or a postcode is, the database's domains decide (409, named after the domain's CHECK);
    # the API only checks the shape of the request (422).
    assert error_of(add(customer_id, headers, {**NEW_ADDRESS, "state": "XX"})) == (409, "au_state_valid")
    assert error_of(add(customer_id, headers, {**NEW_ADDRESS, "postcode": "ABCD"})) == (409, "au_postcode_format")
    assert error_of(add(customer_id, headers, {**NEW_ADDRESS, "postcode": "12"})) == (422, "validation_error")
    assert error_of(add(customer_id, headers, {**NEW_ADDRESS, "line1": "   "})) == (422, "validation_error")
    # The number is the server's to give, so a client can't send one.
    assert error_of(add(customer_id, headers, {**NEW_ADDRESS, "address_no": 7})) == (422, "validation_error")
    assert addresses_of(customer_id, headers) == []


def test_only_the_customer_changes_their_addresses():
    customer_id, headers = new_customer()
    add(customer_id, headers)
    url = f"{API}/customers/{customer_id}/addresses"
    _, stranger = new_customer()
    assert error_of(client.post(url, headers=stranger, json=NEW_ADDRESS)) == (403, "not_your_account")
    assert error_of(client.patch(f"{url}/1", headers=stranger, json=RETIRE)) == (403, "not_your_account")
    # Staff never change a customer's addresses for them — not even support, who can look the customer up.
    for staff_id in (AIDEN, NORA):
        assert error_of(client.post(url, headers=as_staff(staff_id), json=NEW_ADDRESS)) == (403, "customer_only")
        assert error_of(client.patch(f"{url}/1", headers=as_staff(staff_id), json=RETIRE)) == (403, "customer_only")
    assert addresses_of(customer_id, headers) == [(1, True)]


def test_a_missing_address_is_404_for_its_owner_and_403_for_anyone_else():
    customer_id, headers = new_customer()
    url = f"{API}/customers/{customer_id}/addresses/99"
    assert error_of(client.patch(url, headers=headers, json=RETIRE)) == (404, "not_found")
    _, stranger = new_customer()
    assert error_of(client.patch(url, headers=stranger, json=RETIRE)) == (403, "not_your_account")
    assert error_of(client.patch(url, headers=as_staff(NORA), json=RETIRE)) == (403, "customer_only")

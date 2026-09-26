"""T01: the API acts as the identity in the signed session cookie, and permissions are enforced by the
server — not by the request body, the URL or browser storage.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME
from app.main import app
from tests.support import unique_sku

API = "/api/v1"
AIDEN = 14        # store staff at Sydney CBD (store 1), not its manager
OLIVIA = 1        # manager of Sydney CBD (store 1)
ISLA = 16         # store staff at Bondi Junction (store 2)
SUPPORT = 40      # support staff, no store
ALICE = 1         # demo customer
BEN = 2           # demo customer


@pytest.fixture
def client():
    """A fresh client per test, so one test's cookie never leaks into another."""
    with TestClient(app) as test_client:
        yield test_client


def sign_in(client, kind, identity):
    response = client.post(f"{API}/session", json={"kind": kind, "id": identity})
    assert response.status_code == 201, response.text
    return response.json()


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


# ---------------------------------------------------------------- browsing stays open

def test_a_guest_can_browse_the_shop(client):
    assert client.get(f"{API}/stores").status_code == 200
    assert client.get(f"{API}/products").status_code == 200
    assert client.get(f"{API}/promotions").status_code == 200
    assert client.get(f"{API}/customers").status_code == 200          # the demo directory
    assert client.get(f"{API}/session").json() is None


# ---------------------------------------------------------------- the session itself

def test_signing_in_sets_an_http_only_cookie_and_reports_the_actor(client):
    response = client.post(f"{API}/session", json={"kind": "staff", "id": AIDEN})
    assert response.status_code == 201, response.text
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header and "samesite=lax" in cookie_header
    assert response.json()["display_name"] == "Aiden Chen"
    assert response.json()["store_id"] == 1
    assert response.json()["runs_store"] is False
    assert client.get(f"{API}/session").json()["id"] == AIDEN


def test_signing_out_ends_the_session(client):
    sign_in(client, "customer", ALICE)
    assert client.delete(f"{API}/session").status_code == 204
    assert client.get(f"{API}/session").json() is None


def test_a_tampered_cookie_is_ignored(client):
    client.cookies.set(COOKIE_NAME, "eyJraW5kIjoic3RhZmYiLCJpZCI6MX0.forged-signature")
    assert client.get(f"{API}/session").json() is None
    response = client.post(f"{API}/stores/1/inventory/1/adjustments",
                           json={"delta": 1, "reason": "received"})
    assert error_of(response) == (401, "not_signed_in")


def test_sign_in_requires_an_identity_that_exists(client):
    assert error_of(client.post(f"{API}/session", json={"kind": "customer", "id": 999999})) \
        == (404, "not_found")
    assert client.get(f"{API}/session").json() is None


def test_demo_sign_in_can_be_turned_off(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    assert error_of(client.post(f"{API}/session", json={"kind": "customer", "id": ALICE})) \
        == (403, "demo_sign_in_disabled")
    monkeypatch.setenv("DEMO_MODE", "1")
    assert client.post(f"{API}/session", json={"kind": "customer", "id": ALICE}).status_code == 201


# ---------------------------------------------------------------- customers

def test_a_customer_can_only_read_their_own_record(client):
    assert client.get(f"{API}/customers/{ALICE}").status_code == 401
    sign_in(client, "customer", ALICE)
    assert client.get(f"{API}/customers/{ALICE}").status_code == 200
    assert error_of(client.get(f"{API}/customers/{BEN}")) == (403, "not_your_account")


def test_support_staff_may_read_any_customer(client):
    sign_in(client, "staff", SUPPORT)
    assert client.get(f"{API}/customers/{BEN}").status_code == 200


def test_store_staff_may_not_read_customer_records(client):
    sign_in(client, "staff", AIDEN)
    assert error_of(client.get(f"{API}/customers/{ALICE}")) == (403, "staff_cannot_read_this")


# ---------------------------------------------------------------- stock

def test_the_body_cannot_choose_the_staff_member(client):
    sign_in(client, "staff", AIDEN)
    response = client.post(f"{API}/stores/1/inventory/1/adjustments",
                           json={"staff_id": ISLA, "delta": 1, "reason": "received"})
    assert error_of(response) == (422, "validation_error")     # extra fields are refused


def test_only_staff_of_that_store_may_adjust_its_stock(client):
    body = {"delta": 1, "reason": "received"}
    assert error_of(client.post(f"{API}/stores/1/inventory/1/adjustments", json=body)) \
        == (401, "not_signed_in")
    sign_in(client, "customer", ALICE)
    assert error_of(client.post(f"{API}/stores/1/inventory/1/adjustments", json=body)) \
        == (403, "staff_only")
    sign_in(client, "staff", SUPPORT)                           # support reads, but does not handle stock
    assert error_of(client.post(f"{API}/stores/1/inventory/1/adjustments", json=body)) \
        == (403, "store_staff_only")
    sign_in(client, "staff", ISLA)                              # works at store 2
    assert error_of(client.post(f"{API}/stores/1/inventory/1/adjustments", json=body)) \
        == (403, "other_store")
    sign_in(client, "staff", AIDEN)                             # works at store 1
    assert client.post(f"{API}/stores/1/inventory/1/adjustments", json=body).status_code == 201


def test_the_adjustment_history_is_store_scoped(client):
    assert error_of(client.get(f"{API}/stores/1/adjustments")) == (401, "not_signed_in")
    sign_in(client, "staff", ISLA)
    assert error_of(client.get(f"{API}/stores/1/adjustments")) == (403, "other_store")
    sign_in(client, "staff", SUPPORT)
    assert client.get(f"{API}/stores/1/adjustments").status_code == 200


# ---------------------------------------------------------------- catalogue

def test_catalogue_writes_need_a_manager_or_support(client):
    new_product = {"sku": unique_sku(), "name": "Auth test item", "brand_id": 15,
                   "category_id": 1, "base_price": "10.00"}
    assert error_of(client.post(f"{API}/products", json=new_product)) == (401, "not_signed_in")
    sign_in(client, "customer", ALICE)
    assert error_of(client.post(f"{API}/products", json=new_product)) == (403, "staff_only")
    sign_in(client, "staff", AIDEN)                             # store staff, not the manager
    assert error_of(client.post(f"{API}/products", json=new_product)) == (403, "manager_only")
    sign_in(client, "staff", OLIVIA)                            # Sydney CBD's manager
    assert client.post(f"{API}/products", json=new_product).status_code == 201
    sign_in(client, "staff", SUPPORT)
    assert client.post(f"{API}/products", json={**new_product, "sku": unique_sku()}).status_code == 201


def test_promotions_need_a_manager_or_support(client):
    assert error_of(client.delete(f"{API}/promotions/1")) == (401, "not_signed_in")
    sign_in(client, "staff", AIDEN)
    assert error_of(client.delete(f"{API}/promotions/1")) == (403, "manager_only")
    assert client.get(f"{API}/promotions").status_code == 200    # reading stays public

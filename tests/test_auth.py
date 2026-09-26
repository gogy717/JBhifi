"""T01: the API acts as the identity in the signed session cookie, and permissions are enforced by the
server — not by the request body, the URL or browser storage.
"""
import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME
from app.main import app
from tests.shop import a_customer, a_product
from tests.support import connect, unique_sku

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


def one(sql, params=None):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


# ---------------------------------------------------------------- browsing stays open

def test_a_guest_can_browse_the_shop(client):
    assert client.get(f"{API}/stores").status_code == 200
    assert client.get(f"{API}/products").status_code == 200
    assert client.get(f"{API}/promotions").status_code == 200
    assert client.get(f"{API}/customers").status_code == 200          # the demo directory
    assert client.get(f"{API}/session").json() is None


def test_guest_cannot_mutate(client):
    """Every mutation needs a session; a guest gets 401 and no row changes."""
    product = a_product(stock=2)
    customer_id, numbers = a_customer()
    attempts = [
        ("POST", f"{API}/stores/1/inventory/{product['product_id']}/adjustments",
         {"delta": 1, "reason": "received"}),
        ("POST", f"{API}/products",
         {"sku": unique_sku(), "name": "Guest", "brand_id": 15, "category_id": 1, "base_price": "1.00"}),
        ("DELETE", f"{API}/promotions/1", None),
        ("PATCH", f"{API}/customers/{customer_id}/addresses/{numbers[0]}", {"is_active": False}),
        ("POST", f"{API}/orders", {"fulfilment_method": "click_collect", "fulfilling_store_id": 1,
                                   "items": [{"product_id": product["product_id"], "quantity": 1}],
                                   "expected_total": "1.00"}),
        ("POST", f"{API}/returns/1/receive", {"expected_status": "requested"}),
    ]
    for method, path, body in attempts:
        response = client.request(method, path, json=body,
                                  headers={"Idempotency-Key": "0b6f1d4e-5c3a-4a8e-9f2b-7d1e3c5a9b0f"})
        assert error_of(response) == (401, "not_signed_in"), (method, path, response.text)

    assert one("SELECT quantity FROM inventory WHERE store_id = 1 AND product_id = %s",
               (product["product_id"],))["quantity"] == 2


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


def test_forged_actor_is_ignored(client):
    client.cookies.set(COOKIE_NAME, "eyJraW5kIjoic3RhZmYiLCJpZCI6MX0.forged-signature")
    assert client.get(f"{API}/session").json() is None
    response = client.post(f"{API}/stores/1/inventory/1/adjustments",
                           json={"delta": 1, "reason": "received"})
    assert error_of(response) == (401, "not_signed_in")


def test_sign_in_requires_an_identity_that_exists(client):
    assert error_of(client.post(f"{API}/session", json={"kind": "customer", "id": 999999})) \
        == (404, "not_found")
    assert client.get(f"{API}/session").json() is None


def test_demo_login_disabled(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    assert error_of(client.post(f"{API}/session", json={"kind": "customer", "id": ALICE})) \
        == (403, "demo_sign_in_disabled")
    monkeypatch.setenv("DEMO_MODE", "1")
    assert client.post(f"{API}/session", json={"kind": "customer", "id": ALICE}).status_code == 201


# ---------------------------------------------------------------- cookie and cross-origin hardening

def test_the_session_cookie_is_marked_secure_when_the_deployment_is(client, monkeypatch):
    """Plain HTTP locally (no `Secure`, or the browser would drop it); HTTPS deployments set COOKIE_SECURE."""
    assert "secure" not in client.post(f"{API}/session", json={"kind": "customer", "id": ALICE}) \
        .headers["set-cookie"].lower()
    monkeypatch.setenv("COOKIE_SECURE", "1")
    signed_in = client.post(f"{API}/session", json={"kind": "customer", "id": ALICE})
    assert "secure" in signed_in.headers["set-cookie"].lower()
    monkeypatch.delenv("COOKIE_SECURE")


def test_a_mutation_from_another_site_is_refused(client):
    """SameSite=Lax is the first line; this is the second, for a client that ignores it."""
    body = {"kind": "customer", "id": ALICE}
    cross_site = client.post(f"{API}/session", json=body, headers={"Origin": "https://evil.example"})
    assert error_of(cross_site) == (403, "cross_origin_refused")
    assert client.get(f"{API}/session").json() is None            # the refusal changed nothing

    # The same request from the web app (another loopback port, as the Next.js proxy arranges) is allowed.
    assert client.post(f"{API}/session", json=body, headers={"Origin": "http://localhost:3000"}).status_code == 201
    assert client.post(f"{API}/session", json=body, headers={"Origin": "http://127.0.0.1:3000"}).status_code == 201
    # A configured origin is trusted too; a look-alike host is not.
    import os
    os.environ["TRUSTED_ORIGINS"] = "https://shop.example.test"
    try:
        assert client.post(f"{API}/session", json=body,
                           headers={"Origin": "https://shop.example.test"}).status_code == 201
        assert error_of(client.post(f"{API}/session", json=body,
                                   headers={"Origin": "https://shop.example.test.evil"})) \
            == (403, "cross_origin_refused")
    finally:
        del os.environ["TRUSTED_ORIGINS"]


def test_a_request_without_an_origin_is_not_a_browser_session(client):
    """curl, a script or a test client sends no Origin; the permission checks still apply."""
    assert client.post(f"{API}/session", json={"kind": "customer", "id": ALICE}).status_code == 201
    assert error_of(client.post(f"{API}/stores/1/inventory/1/adjustments",
                                json={"delta": 1, "reason": "received"})) == (403, "staff_only")
    assert client.get(f"{API}/session").json()["id"] == ALICE


# ---------------------------------------------------------------- customers

def test_customer_cannot_read_another_customer(client):
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


def test_staff_store_scope(client):
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

"""T18: the one error contract, and what a refusal may say.

The frontend prints `error.code` verbatim — that is how a page names the database rule that refused it —
so these tests pin the envelope, the status each kind of refusal carries, and the codes the pages switch
on. They also pin what a failure may *not* say: the driver's message names the host, the role and
sometimes a password, and a route's traceback names the schema, so both go to the log instead.
"""
import logging
import os
import uuid

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import DbCursor
from app.errors import DATABASE_UNAVAILABLE, register_error_handlers
from app.main import app
from tests.shop import (AIDEN, BONDI, ISLA, SUPPORT, SYDNEY_CBD, WAREHOUSE, a_customer, a_product,
                        error_of, order_body, place, shop_client, staff_client)
from tests.support import connect, unique_sku

API = "/api/v1"
OLIVIA = 1          # the manager of store 1

ENVELOPE = {"code", "message", "detail"}


def body_of(response):
    """The parsed envelope, asserted to be exactly the one shape every failure uses."""
    assert set(response.json()) == {"error"}, response.text
    error = response.json()["error"]
    assert set(error) == ENVELOPE, error
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    return error


def one(sql, params=None, autocommit=False):
    conn = connect()
    conn.autocommit = autocommit
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------- the envelope

def test_every_failure_uses_the_same_envelope():
    """A 401, a 403, a 404, a 409 and a 422 differ in status and code, never in shape."""
    product = a_product(stock=1)
    customer_id, numbers = a_customer()
    customer = shop_client(customer_id)
    staff = staff_client(AIDEN)
    try:
        failures = {
            "guest": TestClient(app).post(f"{API}/orders", json={}),
            "wrong actor": place(staff, order_body([(product, 1)])),
            "unknown": customer.get(f"{API}/orders/99999999"),
            "rule": staff.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}"
                               f"/adjustments", json={"delta": -5, "reason": "damaged"}),
            "malformed": customer.post(f"{API}/customers/{customer_id}/addresses", json={"line1": ""}),
        }
        assert [response.status_code for response in failures.values()] == [401, 403, 404, 409, 422]
        assert [body_of(response)["code"] for response in failures.values()] == [
            "not_signed_in", "customer_only", "not_found", "br03_inventory_qty_nonneg", "validation_error",
        ]
        # The rule's own name is inspectable, and the page can show it.
        assert body_of(failures["rule"])["code"].startswith("br")
    finally:
        customer.close()
        staff.close()


def test_a_guest_is_told_to_sign_in_everywhere_it_matters():
    product = a_product(stock=3)
    customer_id, numbers = a_customer()
    with TestClient(app) as guest:
        assert error_of(guest.post(f"{API}/orders", json=order_body([(product, 1)]))) == (401, "not_signed_in")
        assert error_of(guest.patch(f"{API}/orders/1/status",
                                    json={"to_status": "picking", "expected_status": "paid"})) \
            == (401, "not_signed_in")
        assert error_of(guest.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}/adjustments",
                                   json={"delta": 1, "reason": "received"})) == (401, "not_signed_in")
        assert error_of(guest.get(f"{API}/stores/{SYDNEY_CBD}/orders")) == (401, "not_signed_in")
        assert error_of(guest.post(f"{API}/customers/{customer_id}/addresses",
                                   json={"line1": "1 Sign In St", "suburb": "Sydney", "state": "NSW",
                                         "postcode": "2000"})) == (401, "not_signed_in")
        # Reading the catalogue stays public: the storefront works for a guest.
        assert guest.get(f"{API}/products").status_code == 200
        assert guest.get(f"{API}/promotions").status_code == 200


def test_each_actor_is_refused_what_it_may_not_do():
    customer_id, numbers = a_customer()
    customer = shop_client(customer_id)
    store_staff = staff_client(ISLA)                 # works at Bondi Junction (store 2)
    support = staff_client(SUPPORT)
    product = a_product(stock=5)
    # A real order of this customer's, so the fulfilment checks below have a row to look at.
    placed = place(customer, order_body([(product, 1)]))
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["order_id"]
    try:
        # A customer does not adjust stock, fulfil orders or edit the catalogue.
        assert error_of(customer.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}"
                                      f"/adjustments", json={"delta": 1, "reason": "received"})) \
            == (403, "staff_only")
        assert error_of(customer.patch(f"{API}/orders/{order_id}/status",
                                       json={"to_status": "picking", "expected_status": "paid"})) \
            == (403, "staff_only")
        assert error_of(customer.post(f"{API}/products", json={"sku": unique_sku(), "name": "n",
                                                               "brand_id": 1, "category_id": 1,
                                                               "base_price": "10.00"})) == (403, "staff_only")
        # Store staff shop as staff, not as a customer, and only inside their own store.
        assert error_of(place(store_staff, order_body([(product, 1)]))) \
            == (403, "customer_only")
        assert error_of(store_staff.get(f"{API}/stores/{SYDNEY_CBD}/orders")) == (403, "other_store")
        assert error_of(store_staff.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}"
                                         f"/adjustments", json={"delta": 1, "reason": "received"})) \
            == (403, "other_store")
        # Support staff read across stores but do not handle stock themselves.
        assert support.get(f"{API}/stores/{SYDNEY_CBD}/orders").status_code == 200
        assert error_of(support.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}"
                                     f"/adjustments", json={"delta": 1, "reason": "received"})) \
            == (403, "store_staff_only")
        # …and nobody reads another household's record.
        assert error_of(shop_client(a_customer()[0]).get(f"{API}/customers/{customer_id}")) \
            == (403, "not_your_account")
        assert error_of(store_staff.get(f"{API}/customers/{customer_id}")) \
            == (403, "staff_cannot_read_this")
    finally:
        customer.close()
        store_staff.close()
        support.close()


def test_an_unknown_id_is_a_404_and_someone_elses_order_looks_the_same():
    """Ids cannot be probed: "not yours" and "does not exist" are one answer (T09)."""
    owner, _owner_staff, _product, order = _a_completed_order()
    stranger = shop_client(a_customer()[0])
    try:
        assert error_of(owner.get(f"{API}/products/99999999")) == (404, "not_found")
        assert error_of(owner.get(f"{API}/orders/99999999")) == (404, "not_found")
        assert error_of(owner.get(f"{API}/returns/99999999")) == (404, "not_found")
        missing = owner.get(f"{API}/orders/99999999").json()
        foreign = stranger.get(f"{API}/orders/{order['order_id']}")
        assert foreign.status_code == 404
        assert body_of(foreign)["code"] == body_of(owner.get(f"{API}/orders/99999999"))["code"]
        assert body_of(foreign)["code"] == missing["error"]["code"]
        # The owner still reads their own order.
        assert owner.get(f"{API}/orders/{order['order_id']}").status_code == 200
    finally:
        owner.close()
        stranger.close()


# ---------------------------------------------------------------- refusals that name a rule

def test_a_rule_refusal_names_the_constraint_that_fired():
    product = a_product(price="100.00", stock=1)
    staff = staff_client(AIDEN)
    manager = staff_client(OLIVIA)
    customer_id, numbers = a_customer()
    customer = shop_client(customer_id)
    try:
        # BR03: stock never goes negative.
        assert error_of(staff.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}"
                                   f"/adjustments", json={"delta": -4, "reason": "damaged"})) \
            == (409, "br03_inventory_qty_nonneg")
        # BR18: the sign has to match the reason.
        assert error_of(staff.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}"
                                   f"/adjustments", json={"delta": 2, "reason": "damaged"})) \
            == (409, "br18_adjustment_delta_matches_reason")
        # A UNIQUE constraint from the table itself.
        existing = one("SELECT sku FROM product LIMIT 1")["sku"]
        assert error_of(manager.post(f"{API}/products", json={"sku": existing, "name": "Duplicate",
                                                              "brand_id": 1, "category_id": 1,
                                                              "base_price": "10.00"})) \
            == (409, "product_sku_unique")
        # BR06 has one name whether the API or the database refuses it.
        assert error_of(place(customer, order_body([(product, 1)], method="click_collect",
                                                   store_id=WAREHOUSE))) == (409, "br06_collect_at_retail_store")
    finally:
        staff.close()
        manager.close()
        customer.close()


def test_a_malformed_request_is_a_422_and_never_a_500():
    """400-class answers for shape; the rules the *database* enforces are 409 (T00/T01)."""
    product = a_product(stock=2)
    manager = staff_client(OLIVIA)
    try:
        # Missing a required field.
        assert error_of(manager.post(f"{API}/products", json={"name": "No SKU"})) \
            == (422, "validation_error")
        # The wrong type, and an out-of-range value.
        assert error_of(manager.post(f"{API}/products", json={
            "sku": unique_sku(), "name": "Wrong type", "brand_id": 1, "category_id": 1,
            "base_price": "ten dollars"})) == (422, "validation_error")
        assert error_of(manager.post(f"{API}/stores/{SYDNEY_CBD}/inventory/{product['product_id']}"
                                     f"/adjustments", json={"delta": 0, "reason": "received"})) \
            == (409, "br18_adjustment_delta_matches_reason")
        # An unknown query value is the shape of the filter, not a rule.
        assert error_of(manager.get(f"{API}/promotions", params={"status": "whenever"})) \
            == (422, "validation_error")
    finally:
        manager.close()


def test_a_field_that_is_not_a_price_is_ignored_not_obeyed():
    """The price is the server's: a smuggled `current_price` is dropped, not used (T09)."""
    manager = staff_client(OLIVIA)
    sku = unique_sku()
    try:
        response = manager.post(f"{API}/products", json={
            "sku": sku, "name": "Smuggler", "brand_id": 1, "category_id": 1,
            "base_price": "10.00", "current_price": "1.00"})
        assert response.status_code == 201, response.text
        assert response.json()["base_price"] == "10.00"
        assert response.json()["current_price"] == "10.00"      # no promotion, and no smuggled price
    finally:
        manager.close()


def test_unknown_routes_and_methods_keep_the_envelope():
    with TestClient(app) as guest:
        unknown = guest.get(f"{API}/nope")
        assert unknown.status_code == 404
        assert body_of(unknown)["code"] == "http_404"
        wrong_method = guest.put(f"{API}/products")
        assert wrong_method.status_code == 405
        assert body_of(wrong_method)["code"] == "http_405"


def test_the_smoke_endpoints_stay_public():
    """`/health` and the catalogue reads are what a deployment watches; `/promotions` is filterable."""
    with TestClient(app) as guest:
        health = guest.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["db"]

        promotions = guest.get(f"{API}/promotions")
        assert promotions.status_code == 200
        assert isinstance(promotions.json(), list)
        active = guest.get(f"{API}/promotions", params={"status": "active"})
        assert active.status_code == 200
        assert all(promotion["status"] == "active" for promotion in active.json())


# ---------------------------------------------------------------- what a failure may not say

def test_a_database_outage_is_a_503_that_says_nothing_about_the_database(monkeypatch, caplog):
    """The driver's own message (host, role, password) is logged, never returned."""
    leak = ("connection to server at \"db.internal\" (10.0.0.9), port 5433 failed: FATAL:  password "
            "authentication failed for user \"jbhifi_app\" (password=hunter2)")

    def refuse():
        raise psycopg2.OperationalError(leak)

    monkeypatch.setattr("app.db.get_connection", refuse)
    with TestClient(app) as client, caplog.at_level(logging.ERROR, logger="jbhifi.api"):
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "database_unavailable",
                                         "message": DATABASE_UNAVAILABLE, "detail": None}}
    for secret in ("hunter2", "jbhifi_app", "10.0.0.9", "db.internal", "FATAL"):
        assert secret not in response.text
    # The operator still gets the whole thing in the log.
    assert any("hunter2" in record.getMessage() for record in caplog.records)


def test_an_unexpected_failure_is_logged_and_says_nothing_about_itself(caplog):
    """A traceback names tables and columns; the client gets one sentence and a code."""
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/boom")
    def boom():
        raise RuntimeError("SELECT password FROM jbhifi_credentials -- hunter2")

    with TestClient(test_app, raise_server_exceptions=False) as client, \
            caplog.at_level(logging.ERROR, logger="jbhifi.api"):
        response = client.get("/boom")

    assert response.status_code == 500
    assert body_of(response)["code"] == "internal_error"
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    assert "hunter2" in caplog.text


# ---------------------------------------------------------------- commit-time failures

def test_a_deferred_rule_is_answered_as_a_409_and_commits_nothing(monkeypatch):
    """BR04's manager key is DEFERRABLE: the INSERT is accepted, the COMMIT is refused (T03).

    The API has to return that refusal as the ordinary 409 envelope — a deferred rule must not escape as
    a 500 (or worse, as a success) because it fired after the route had returned.
    """
    store_id = 9001
    name = f"Deferred {uuid.uuid4().hex[:8]}"
    test_app = _app_with_pair_route(monkeypatch)

    with TestClient(test_app) as client:
        response = client.post("/pairs", json={"store_id": store_id, "name": name, "complete": False})

    assert response.status_code == 409, response.text
    assert body_of(response)["code"] == "br04_store_manager_works_here"
    # The whole transaction went back: neither the store nor a manager exists.
    assert one("SELECT 1 AS x FROM store WHERE store_id = %s", (store_id,)) is None


def test_the_same_two_rows_in_the_right_order_commit_before_the_answer(monkeypatch):
    """The positive half of the same transaction: store, then its manager, then COMMIT — a 201."""
    store_id = 9002
    name = f"Paired {uuid.uuid4().hex[:8]}"
    test_app = _app_with_pair_route(monkeypatch)
    try:
        with TestClient(test_app) as client:
            response = client.post("/pairs", json={"store_id": store_id, "name": name, "complete": True})

        assert response.status_code == 201, response.text
        # The rows are visible to *another* connection, so the commit happened before the answer was sent.
        assert one("SELECT name FROM store WHERE store_id = %s", (store_id,))["name"] == name
        assert one("SELECT full_name FROM staff WHERE staff_id = %s", (store_id,)) is not None
    finally:
        # This test commits on purpose, so it cleans up after itself: no later test sees an extra store.
        # store and staff point at each other, so both rows go in one transaction (BR04 is deferred).
        with connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM staff WHERE staff_id = %s", (store_id,))
            cur.execute("DELETE FROM store WHERE store_id = %s", (store_id,))


def _app_with_pair_route(monkeypatch):
    """A tiny app with the real error handlers and one route that writes a deferred pair (BR04).

    The route runs through the same `DbCursor` dependency the real app uses (that is the code whose
    commit-time behaviour this tests), but as the bootstrap role: creating a store is not something the
    least-privilege application role may do.
    """
    from pydantic import BaseModel

    monkeypatch.setattr("app.db.credentials",
                        lambda: (os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"]))

    class Pair(BaseModel):
        store_id: int
        name: str
        complete: bool

    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.post("/pairs", status_code=201)
    def create_pair(body: Pair, cur: DbCursor):
        cur.execute("INSERT INTO store (store_id, name, store_type, suburb, state, manager_id) "
                    "VALUES (%s, %s, 'retail', 'Testville', 'NSW', %s)",
                    (body.store_id, body.name, body.store_id))
        if body.complete:
            # The manager works at the store the row above creates; the composite FK is deferred, so the
            # pair only has to be consistent by COMMIT.
            cur.execute("INSERT INTO staff (staff_id, store_id, staff_type, full_name, email) "
                        "VALUES (%s, %s, 'store', %s, %s)",
                        (body.store_id, body.store_id, f"Manager {body.store_id}",
                         f"manager.{body.store_id}@example.com"))
        return {"store_id": body.store_id}

    return test_app


def _a_completed_order():
    from tests.shop import a_completed_order
    return a_completed_order()

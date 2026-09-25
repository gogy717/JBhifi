"""API smoke tests: every endpoint answers, and a request that breaks a database rule comes back as
409 with the rule's constraint name as the error code — rolled back as a whole."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.support import unique_sku

client = TestClient(app)
API = "/api/v1"
AIDEN = 14          # works at Sydney CBD (store 1)
ISLA = 16           # works at Bondi Junction (store 2)


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


@pytest.fixture
def new_product():
    """A product created through the API (committed): Sony headphones at $199.00, no stock anywhere."""
    brands = {b["name"]: b["brand_id"] for b in client.get(f"{API}/brands").json()}
    categories = {c["name"]: c["category_id"] for c in client.get(f"{API}/categories").json()}
    response = client.post(f"{API}/products", json={
        "sku": unique_sku(), "name": "API test headphones", "brand_id": brands["Sony"],
        "category_id": categories["Headphones"], "base_price": "199.00",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_reference_lists():
    assert len(client.get(f"{API}/stores").json()) == 13
    staff = client.get(f"{API}/staff", params={"store_id": 1}).json()
    assert [s["is_manager"] for s in staff] == [True, False, False]
    assert len(client.get(f"{API}/categories").json()) == 15
    assert len(client.get(f"{API}/brands").json()) == 16
    assert client.get(f"{API}/stores/99/inventory").status_code == 404


def test_demo_customers():
    customers = {c["email"]: c["customer_id"] for c in client.get(f"{API}/customers").json()}
    assert {"alice.morgan@example.com", "ben.okafor@example.com"} <= set(customers)
    ben = client.get(f"{API}/customers/{customers['ben.okafor@example.com']}").json()
    # The current address comes first; the old one is still there, inactive (BR16: never edited).
    assert [(a["address_no"], a["is_active"]) for a in ben["addresses"]] == [(2, True), (1, False)]
    assert client.get(f"{API}/customers/999999").status_code == 404


def test_adjust_stock_round_trip(new_product):
    pid, sku = new_product["product_id"], new_product["sku"]
    response = client.post(f"{API}/stores/1/inventory/{pid}/adjustments",
                           json={"staff_id": AIDEN, "delta": 5, "reason": "received", "note": "Delivery #123"})
    assert response.status_code == 201, response.text
    assert (response.json()["quantity_after"], response.json()["staff_name"]) == (5, "Aiden Chen")

    rows = client.get(f"{API}/stores/1/inventory", params={"q": sku}).json()
    assert [(row["product_id"], row["quantity"]) for row in rows] == [(pid, 5)]
    history = client.get(f"{API}/stores/1/adjustments", params={"product_id": pid}).json()
    assert [(h["delta"], h["reason"], h["note"]) for h in history] == [(5, "received", "Delivery #123")]
    assert client.get(f"{API}/products/{pid}").json()["total_stock"] == 5


def test_rule_violations_are_409_with_the_rule_name_and_change_nothing(new_product):
    pid = new_product["product_id"]
    url = f"{API}/stores/1/inventory/{pid}/adjustments"
    assert error_of(client.post(url, json={"staff_id": AIDEN, "delta": -1, "reason": "damaged"})) \
        == (409, "br03_inventory_qty_nonneg")
    assert error_of(client.post(url, json={"staff_id": ISLA, "delta": 1, "reason": "received"})) \
        == (409, "br18_adjustment_staff_at_store")
    assert error_of(client.post(url, json={"staff_id": AIDEN, "delta": 1, "reason": "damaged"})) \
        == (409, "br18_adjustment_delta_matches_reason")
    assert client.get(f"{API}/stores/1/adjustments", params={"product_id": pid}).json() == []
    assert client.get(f"{API}/products/{pid}").json()["total_stock"] == 0


def test_product_rules(new_product):
    valid = {"sku": unique_sku(), "name": "X", "brand_id": new_product["brand_id"],
             "category_id": new_product["category_id"], "base_price": "10.00"}
    for change, expected in [
        ({"sku": "lower-case"}, "product_sku_format"),
        ({"sku": new_product["sku"]}, "product_sku_unique"),
        ({"base_price": "-1.00"}, "br02_money_nonneg"),
        ({"brand_id": 999999}, "product_brand_fk"),
    ]:
        response = client.post(f"{API}/products", json={**valid, **change})
        assert error_of(response) == (409, expected), response.text
    assert error_of(client.post(f"{API}/products", json={"sku": unique_sku()})) == (422, "validation_error")


def test_update_product_and_replace_specs(new_product):
    pid = new_product["product_id"]
    response = client.patch(f"{API}/products/{pid}", json={"base_price": "179.00", "is_active": False})
    assert response.status_code == 200, response.text
    assert (response.json()["base_price"], response.json()["is_active"]) == ("179.00", False)
    assert pid not in {p["product_id"] for p in client.get(f"{API}/products").json()}
    assert pid in {p["product_id"] for p in client.get(f"{API}/products", params={"include_inactive": True}).json()}

    specs = [{"spec_name": "Type", "spec_value": "Over-ear"}, {"spec_name": "Battery life", "spec_value": "40 h"}]
    assert len(client.put(f"{API}/products/{pid}/specs", json=specs).json()) == 2
    duplicate = specs + [{"spec_name": "Type", "spec_value": "In-ear"}]
    assert error_of(client.put(f"{API}/products/{pid}/specs", json=duplicate)) == (409, "product_spec_pk")
    assert len(client.get(f"{API}/products/{pid}").json()["specs"]) == 2    # the failed replace changed nothing


def test_promotions(new_product):
    pid = new_product["product_id"]                                         # base price 199.00
    now = datetime.now(timezone.utc)

    def promotion(price, start_days, end_days):
        return {"product_id": pid, "sale_price": price,
                "starts_at": (now + timedelta(days=start_days)).isoformat(),
                "ends_at": (now + timedelta(days=end_days)).isoformat()}

    assert error_of(client.post(f"{API}/promotions", json=promotion("199.00", 0, 7))) \
        == (409, "br15_promotion_below_base_price")
    response = client.post(f"{API}/promotions", json=promotion("149.00", -1, 7))
    assert (response.status_code, response.json()["status"]) == (201, "active"), response.text
    assert response.json()["product_active"] is True
    promotion_id = response.json()["promotion_id"]
    assert client.get(f"{API}/products/{pid}").json()["current_price"] == "149.00"

    assert error_of(client.post(f"{API}/promotions", json=promotion("139.00", 5, 10))) \
        == (409, "br15_promotion_no_overlap")
    assert error_of(client.patch(f"{API}/products/{pid}", json={"base_price": "149.00"})) \
        == (409, "br15_promotion_below_base_price")
    naive = {**promotion("139.00", 20, 30), "starts_at": "2026-12-01T00:00:00"}     # no UTC offset
    assert error_of(client.post(f"{API}/promotions", json=naive)) == (422, "validation_error")

    assert client.delete(f"{API}/promotions/{promotion_id}").status_code == 204
    assert client.delete(f"{API}/promotions/{promotion_id}").status_code == 404

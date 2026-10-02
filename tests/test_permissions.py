"""Who may call what (spec §4.5). Each row lists the callers allowed past the permission check; everyone
else is refused — a guest with 401 not_signed_in, anyone signed in with 403. "Allowed" may still end in a
404 or 409 from the data: the ids don't exist and the bodies break rules, so nothing here changes anything.
"""
from functools import cache

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.auth_support import as_customer, as_staff

client = TestClient(app)
API = "/api/v1"
ALICE, BEN = "alice.morgan@example.com", "ben.okafor@example.com"
CALLERS = {
    "guest": lambda: {},
    "alice": lambda: as_customer(ALICE),
    "ben": lambda: as_customer(BEN),
    "aiden": lambda: as_staff(14),          # store staff, Sydney CBD (store 1)
    "isla": lambda: as_staff(16),           # store staff, Bondi Junction (store 2)
    "olivia": lambda: as_staff(1),          # manager, Sydney CBD
    "nora": lambda: as_staff(40),           # support
}
EVERYONE = set(CALLERS)
SIGNED_IN = EVERYONE - {"guest"}
STAFF = {"aiden", "isla", "olivia", "nora"}
CATALOGUE = {"olivia", "nora"}
NEW_STOCK = {"delta": 1, "reason": "received"}
PROMOTION = {"product_id": 999999, "sale_price": "1.00",
             "starts_at": "2030-01-01T00:00:00+00:00", "ends_at": "2030-01-02T00:00:00+00:00"}
PRODUCT = {"sku": "APL-AP4", "name": "Duplicate SKU", "brand_id": 1, "category_id": 1, "base_price": "1.00"}
ADDRESS = {"line1": "1 Test St", "suburb": "Sydney", "state": "XX", "postcode": "2000"}   # au_state_valid
RETIRE = {"is_active": False}

ENDPOINTS = [
    ("GET", "/me", None, SIGNED_IN),
    ("GET", "/stores", None, EVERYONE),
    ("GET", "/products", None, EVERYONE),
    ("GET", "/promotions", None, EVERYONE),
    ("GET", "/stores/1/inventory", None, EVERYONE),
    ("GET", "/staff", None, STAFF),
    ("GET", "/customers", None, {"nora"}),
    ("GET", "/customers/{alice}", None, {"alice", "nora"}),
    ("GET", "/customers/999999", None, {"nora"}),                         # others learn nothing: 403
    ("POST", "/stores/1/inventory/999999/adjustments", NEW_STOCK, {"aiden", "olivia"}),
    ("POST", "/stores/99/inventory/999999/adjustments", NEW_STOCK, set()),  # no such store: still 403
    ("GET", "/stores/1/adjustments", None, {"aiden", "olivia", "nora"}),
    ("POST", "/products", PRODUCT, CATALOGUE),
    ("PATCH", "/products/999999", {"name": "Nothing"}, CATALOGUE),
    ("PUT", "/products/999999/specs", [], CATALOGUE),
    ("POST", "/promotions", PROMOTION, CATALOGUE),
    ("DELETE", "/promotions/999999", None, CATALOGUE),
    ("POST", "/customers/{alice}/addresses", ADDRESS, {"alice"}),           # 409: XX is no state, nothing added
    ("POST", "/customers/999999/addresses", ADDRESS, set()),
    ("PATCH", "/customers/{alice}/addresses/999999", RETIRE, {"alice"}),    # 404: no such address
]


@cache
def alice_id() -> int:
    return client.get(f"{API}/me", headers=as_customer(ALICE)).json()["id"]


@pytest.mark.parametrize("method, path, body, allowed", ENDPOINTS, ids=[f"{m} {p}" for m, p, _, _ in ENDPOINTS])
@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_who_may_call_what(caller, method, path, body, allowed):
    url = API + path.format(alice=alice_id())
    response = client.request(method, url, json=body, headers=CALLERS[caller]())
    if caller in allowed:
        assert response.status_code not in (401, 403), response.text
    elif caller == "guest":
        assert (response.status_code, response.json()["error"]["code"]) == (401, "not_signed_in"), response.text
    else:
        assert response.status_code == 403, response.text

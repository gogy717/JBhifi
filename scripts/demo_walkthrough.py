"""Run the customer → staff → customer demonstration against a running, seeded API.

Start the API against the database built by `scripts/seed_demo.py` (see `doc/demo.md`), then:

    python scripts/demo_walkthrough.py                      # API on http://127.0.0.1:8001
    python scripts/demo_walkthrough.py --api http://127.0.0.1:8000

The script drives the same HTTP endpoints the browser uses: guest browsing, a delivery checkout and a
Click & Collect checkout, a safe retry of each, staff fulfilment, a customer return, staff receipt and
refund, and the customer's timeline afterwards. It also shows two refusals: an out-of-stock checkout and a
staff member trying to act on another store's order. Every step prints PASS/FAIL and the run exits non-zero
if any step fails.

The cart lives in the browser, so this script submits the reviewed basket directly — the same body the cart
page posts. `doc/demo.md` has the browser version of the same journey.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from decimal import Decimal

import httpx

WH = 13                  # Eastern Creek DC (warehouse)
SYDNEY_CBD = 1
ALICE = "alice.morgan@example.com"


class Demo:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.guest = httpx.Client(base_url=base_url, timeout=30)
        self.ran = 0
        self.failed = 0

    def step(self, label: str, outcome):
        """Run one step, print PASS/FAIL, and return its value (or None after a failure)."""
        try:
            value = outcome()
        except AssertionError as error:
            self.failed += 1
            print(f"FAIL  {label}: {error}")
            return None
        self.ran += 1
        print(f"PASS  {label}")
        return value

    # ---------------------------------------------------------------- helpers
    def client(self, kind: str, identity: int) -> httpx.Client:
        client = httpx.Client(base_url=self.base_url, timeout=30)
        response = client.post("/api/v1/session", json={"kind": kind, "id": identity})
        assert response.status_code == 201, f"sign-in failed: {response.status_code} {response.text}"
        return client

    def products(self, store_id: int, minimum: int = 2) -> list[dict]:
        rows = self.guest.get(f"/api/v1/stores/{store_id}/inventory").json()
        return [row for row in rows if row["is_active"] and row["quantity"] >= minimum]

    def place(self, client, body, key) -> httpx.Response:
        return client.post("/api/v1/orders", json=body, headers={"Idempotency-Key": str(key)})


def order_body(product: dict, store_id: int, method: str, quantity: int = 1,
               address_no: int | None = None) -> dict:
    """The reviewed basket the cart page would POST. Prices are decimal strings, never floats."""
    total = str((Decimal(product["current_price"]) * quantity).quantize(Decimal("0.01")))
    return {
        "fulfilment_method": method,
        "fulfilling_store_id": store_id,
        "delivery_address_no": address_no,
        "items": [{"product_id": product["product_id"], "quantity": quantity}],
        "expected_total": total,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the seeded end-to-end demo over the API.")
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="base URL of the running API")
    args = parser.parse_args(argv)

    demo = Demo(args.api)
    try:
        health = demo.guest.get("/health")
    except httpx.HTTPError as error:
        print(f"FAIL  API unreachable at {args.api}: {error}")
        return 2
    if health.status_code != 200:
        print(f"FAIL  /health returned {health.status_code}")
        return 2
    print(f"API {args.api} -> {health.json()}")

    # 1. Guest browsing: the catalogue and the demo identities are public reads.
    customers = demo.step("guest reads the demo customers",
                          lambda: _check(demo.guest.get("/api/v1/customers")))
    alice = next((c for c in customers if c["email"] == ALICE), None)
    demo.step("Alice Morgan is one of them", lambda: _assert(alice is not None, "not found"))
    if alice is None:
        return 1

    stores = demo.guest.get("/api/v1/stores").json()
    retail = [s for s in stores if s["store_type"] == "retail"]
    demo.step("guest sees the stores, including a warehouse",
              lambda: _assert(any(s["store_type"] == "warehouse" for s in stores), "no warehouse"))

    # 2. Filter the catalogue the way the header search does.
    found = demo.step(
        "catalogue filter q=AirPods returns the Apple earbuds",
        lambda: _assert(
            any("AirPods" in p["name"] for p in demo.guest.get("/api/v1/products",
                                                               params={"q": "AirPods"}).json()),
            "no AirPods in the result",
        ),
    )

    # 3. Sign in as the customer and read the account (its addresses are private).
    alice_client = demo.client("customer", alice["customer_id"])
    account = demo.step("Alice reads her own account",
                        lambda: alice_client.get(f"/api/v1/customers/{alice['customer_id']}").json())
    address_no = next((a["address_no"] for a in account["addresses"] if a["is_active"]), None)
    demo.step("Alice has an address to deliver to", lambda: _assert(address_no is not None, "none active"))

    # 4. Delivery checkout from the warehouse, and Click & Collect at Sydney CBD.
    warehouse_stock = demo.products(WH, minimum=2)
    sydney_stock = demo.products(SYDNEY_CBD, minimum=2)
    delivery_product = warehouse_stock[0]
    collection_product = next(p for p in sydney_stock if p["product_id"] != delivery_product["product_id"])

    delivery_key = uuid.uuid4()
    delivery = demo.step(
        "delivery checkout commits order, stock, charge and history",
        lambda: _expect(demo.place(alice_client,
                                   order_body(delivery_product, WH, "delivery", address_no=address_no),
                                   delivery_key), 201),
    )
    demo.step("a retry with the same key returns the same order",
              lambda: _assert(
                  demo.place(alice_client,
                             order_body(delivery_product, WH, "delivery", address_no=address_no),
                             delivery_key).status_code == 200
                  and _detail(demo.place(alice_client,
                                         order_body(delivery_product, WH, "delivery", address_no=address_no),
                                         delivery_key))["order_id"] == delivery["order_id"],
                  "the retry did not replay",
              ))

    collection_key = uuid.uuid4()
    collection = demo.step(
        "Click & Collect checkout commits at a retail store",
        lambda: _expect(demo.place(alice_client,
                                   order_body(collection_product, SYDNEY_CBD, "click_collect"),
                                   collection_key), 201),
    )
    demo.step("collected-at warehouse is refused (BR06)",
              lambda: _assert(
                  demo.place(alice_client,
                             order_body(collection_product, WH, "click_collect"),
                             uuid.uuid4()).status_code == 409,
                  "a warehouse collection was accepted",
              ))

    # 5. Staff fulfilment: paid → picking → ready → collected, then the customer's timeline.
    store_staff = demo.client("staff", 14)                    # Aiden Chen, Sydney CBD
    queue = demo.step(
        "the store queue lists the new collection order",
        lambda: _assert(
            any(o["order_id"] == collection["order_id"]
                for o in store_staff.get(f"/api/v1/stores/{SYDNEY_CBD}/orders",
                                         params={"status": "paid"}).json()),
            "the order is not in the queue",
        ),
    )
    for expected, move in (("paid", "picking"), ("picking", "ready"), ("ready", "collected")):
        demo.step(
            f"staff move the collection order {expected} -> {move}",
            lambda expected=expected, move=move: _expect(
                store_staff.patch(f"/api/v1/orders/{collection['order_id']}/status",
                                  json={"to_status": move, "expected_status": expected}), 200),
        )
    other_store = demo.client("staff", 16)                     # Isla Robinson, Bondi Junction
    demo.step("another store's staff cannot move it",
              lambda: _assert(
                  other_store.patch(f"/api/v1/orders/{collection['order_id']}/status",
                                    json={"to_status": "delivered", "expected_status": "collected"}
                                    ).status_code == 403,
                  "another store was allowed",
              ))
    detail = demo.step("the customer sees the full timeline",
                       lambda: _assert(
                           [h["to_status"] for h in
                            alice_client.get(f"/api/v1/orders/{collection['order_id']}").json()["history"]]
                           == ["placed", "paid", "picking", "ready", "collected"],
                           "the timeline is not the collected one",
                       ))

    # 6. The customer requests a return; the server's eligibility decides what is left.
    eligibility = alice_client.get(f"/api/v1/orders/{collection['order_id']}").json()["return_eligibility"]
    demo.step("the completed order is still returnable",
              lambda: _assert(eligibility["eligible"] and eligibility["deadline"], eligibility["reason"]))
    return_key = uuid.uuid4()
    body = {"reason": "Changed my mind", "lines": [{"line_no": 1, "quantity": 1}]}
    created_return = demo.step(
        "the customer requests a return",
        lambda: _expect(alice_client.post(
            f"/api/v1/orders/{collection['order_id']}/returns", json=body,
            headers={"Idempotency-Key": str(return_key)}), 201),
    )
    demo.step("replaying the return key returns the same request",
              lambda: _assert(
                  alice_client.post(f"/api/v1/orders/{collection['order_id']}/returns", json=body,
                                    headers={"Idempotency-Key": str(return_key)}).json()["return_id"]
                  == created_return["return_id"],
                  "the retry created a second request",
              ))

    # 7. Staff receive it, then process it: restock and refund in one transaction.
    demo.step("staff receive the return (no restock yet)",
              lambda: _expect(store_staff.post(f"/api/v1/returns/{created_return['return_id']}/receive",
                                               json={"expected_status": "requested"}), 200))
    processed = demo.step("staff process it: restock and refund",
                          lambda: _expect(store_staff.post(
                              f"/api/v1/returns/{created_return['return_id']}/process",
                              json={"expected_status": "received"}), 200))
    demo.step("the refund equals the price it was bought at",
              lambda: _assert(str(processed["refund_amount"]) == str(created_return["refund_preview"]),
                              f"{processed['refund_amount']} != {created_return['refund_preview']}"))
    demo.step("the customer sees the refunded return",
              lambda: _assert(
                  alice_client.get(f"/api/v1/returns/{created_return['return_id']}").json()["status"]
                  == "refunded", "not refunded"))

    # 8. Refusals: an empty store and a delivered order that cannot be cancelled.
    empty = next((p for p in demo.guest.get(
        f"/api/v1/stores/{SYDNEY_CBD}/inventory").json() if p["sku"] == "LG-43UT8050"), None)
    demo.step("the seeded example product is out of stock",
              lambda: _assert(empty is not None and empty["quantity"] == 0, "it still has stock"))
    refusal = demo.place(alice_client,
                         order_body(empty, SYDNEY_CBD, "click_collect"), uuid.uuid4())
    demo.step("an out-of-stock checkout is refused with nothing written",
              lambda: _assert(refusal.status_code == 409
                              and refusal.json()["error"]["code"] == "out_of_stock",
                              f"{refusal.status_code} {refusal.text}"))

    print(f"\n{demo.ran - demo.failed}/{demo.ran} steps passed"
          f"{'' if demo.failed == 0 else f' — {demo.failed} failed'}")
    print(f"orders: delivery {delivery and delivery['order_id']}, "
          f"collection {collection and collection['order_id']}, return {created_return['return_id']}")
    return 1 if demo.failed else 0


def _check(response: httpx.Response):
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    return response.json()


def _expect(response: httpx.Response, status: int):
    assert response.status_code == status, f"expected {status}, got {response.status_code} {response.text}"
    return response.json()


def _detail(response: httpx.Response) -> dict:
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    return response.json()


def _assert(condition, message: str):
    assert condition, message
    return True


if __name__ == "__main__":
    raise SystemExit(main())

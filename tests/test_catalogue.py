"""T04: catalogue filters use the current price, walk the category tree to any depth, and can report
one store's stock in the same request."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.support import connect, unique_sku

API = "/api/v1"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def committed(work):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            return work(cur)
    finally:
        conn.close()


def a_product(price="100.00", sale=None, category_id=None, brand_id=None, active=True, stock=None,
              store_id=1, name=None):
    """A committed product, optionally on an active promotion and/or stocked at one store."""
    def work(cur):
        sku = unique_sku()
        cur.execute(
            """
            INSERT INTO product (sku, name, brand_id, category_id, base_price, is_active)
            VALUES (%s, %s, COALESCE(%s, (SELECT brand_id FROM brand WHERE name = 'JBL')),
                    COALESCE(%s, (SELECT category_id FROM category WHERE name = 'Speakers')), %s, %s)
            RETURNING product_id
            """,
            (sku, name or f"Catalogue {sku}", brand_id, category_id, price, active),
        )
        product_id = cur.fetchone()["product_id"]
        if stock is not None:
            cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                        (store_id, product_id, stock))
        if sale is not None:
            cur.execute("INSERT INTO promotion (product_id, sale_price, starts_at, ends_at) "
                        "VALUES (%s, %s, now() - interval '1 day', now() + interval '1 day')",
                        (product_id, sale))
        return {"product_id": product_id, "sku": sku}
    return committed(work)


def a_category(name, parent_id=None):
    def work(cur):
        cur.execute("INSERT INTO category (name, parent_id) VALUES (%s, %s) RETURNING category_id",
                    (name, parent_id))
        return cur.fetchone()["category_id"]
    return committed(work)


def find(client, params=None):
    response = client.get(f"{API}/products", params=params)
    assert response.status_code == 200, response.text
    return {product["product_id"]: product for product in response.json()}


# ---------------------------------------------------------------- price

def test_price_filter_uses_the_sale_price(client):
    product = a_product(price="100.00", sale="80.00")
    inside = find(client, {"min_price": "75.00", "max_price": "85.00"})
    assert product["product_id"] in inside                     # 80.00 is what it sells for
    assert inside[product["product_id"]]["current_price"] == "80.00"
    assert inside[product["product_id"]]["on_sale"] is True
    assert product["product_id"] not in find(client, {"min_price": "85.01"})


def test_price_bounds_are_inclusive(client):
    product = a_product(price="80.00")
    assert product["product_id"] in find(client, {"min_price": "80.00"})
    assert product["product_id"] in find(client, {"max_price": "80.00"})


def test_a_malformed_price_range_is_refused(client):
    assert client.get(f"{API}/products", params={"min_price": "-1"}).status_code == 422
    assert client.get(f"{API}/products", params={"min_price": "cheap"}).status_code == 422
    response = client.get(f"{API}/products", params={"min_price": "100.00", "max_price": "50.00"})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "invalid_price_range")


# ---------------------------------------------------------------- categories

def test_category_filter_includes_grandchildren(client):
    root = a_category(f"Root {unique_sku()}")
    child = a_category(f"Child {unique_sku()}", parent_id=root)
    grandchild = a_category(f"Grandchild {unique_sku()}", parent_id=child)
    deep = a_product(category_id=grandchild)
    shallow = a_product(category_id=root)
    elsewhere = a_product()

    found = find(client, {"category_id": root})
    assert {deep["product_id"], shallow["product_id"]} <= set(found)
    assert elsewhere["product_id"] not in found
    # The middle of the tree sees its own subtree too.
    assert deep["product_id"] in find(client, {"category_id": child})
    assert shallow["product_id"] not in find(client, {"category_id": child})


def test_the_store_inventory_uses_the_same_category_walk(client):
    root = a_category(f"Stock root {unique_sku()}")
    child = a_category(f"Stock child {unique_sku()}", parent_id=root)
    grandchild = a_category(f"Stock grandchild {unique_sku()}", parent_id=child)
    product = a_product(category_id=grandchild, stock=4)

    rows = client.get(f"{API}/stores/1/inventory", params={"category_id": root}).json()
    assert product["product_id"] in {row["product_id"] for row in rows}


# ---------------------------------------------------------------- store stock

def test_a_missing_inventory_row_is_zero_not_missing(client):
    product = a_product(stock=0, store_id=2)                 # a row exists at store 2 only
    found = find(client, {"store_id": 1})[product["product_id"]]
    assert found["store_quantity"] == 0
    assert found["total_stock"] == 0
    assert find(client, {"store_id": 2})[product["product_id"]]["store_quantity"] == 0


def test_store_quantity_is_the_stores_own_and_null_without_a_store(client):
    product = a_product(stock=7, store_id=1)
    committed(lambda cur: cur.execute(
        "INSERT INTO inventory (store_id, product_id, quantity) VALUES (2, %s, 3)",
        (product["product_id"],)))

    assert find(client, {"store_id": 1})[product["product_id"]]["store_quantity"] == 7
    assert find(client, {"store_id": 2})[product["product_id"]]["store_quantity"] == 3
    assert find(client)[product["product_id"]]["store_quantity"] is None
    assert find(client)[product["product_id"]]["total_stock"] == 10


def test_an_unknown_store_is_not_found_but_an_unknown_store_with_filters_is_still_checked(client):
    assert client.get(f"{API}/products", params={"store_id": 999999}).status_code == 404


def test_detail_still_reports_every_store_and_no_single_store_quantity(client):
    product = a_product(stock=2, store_id=1)
    detail = client.get(f"{API}/products/{product['product_id']}").json()
    assert detail["store_quantity"] is None
    assert len(detail["stock"]) == 13
    assert {(row["store_id"], row["quantity"]) for row in detail["stock"] if row["quantity"]} == {(1, 2)}


# ---------------------------------------------------------------- search

def test_filters_treat_wildcards_as_text(client):
    literal = a_product(name="100% genuine_thing")
    other = a_product(name="100x genuineAthing")
    assert literal["product_id"] in find(client, {"q": "genuine_thing"})
    assert other["product_id"] not in find(client, {"q": "genuine_thing"})
    assert literal["product_id"] in find(client, {"q": "100%"})
    assert other["product_id"] not in find(client, {"q": "100%"})


def test_filters_combine(client):
    brand_id = committed(lambda cur: (cur.execute("SELECT brand_id FROM brand WHERE name = 'Sony'"),
                                      cur.fetchone()["brand_id"])[1])
    match = a_product(price="100.00", sale="60.00", brand_id=brand_id)
    wrong_brand = a_product(price="100.00", sale="60.00")
    found = find(client, {"brand_id": brand_id, "min_price": "50.00", "max_price": "70.00", "q": "Catalogue"})
    assert match["product_id"] in found
    assert wrong_brand["product_id"] not in found
    assert found[match["product_id"]]["brand"] == "Sony"
    assert Decimal(found[match["product_id"]]["current_price"]) == Decimal("60.00")

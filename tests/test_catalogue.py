"""The catalogue list (R1–R3): the price filter uses the price a product sells for now, a top-level category
includes its subcategories, and one store's stock can come with the list.

The products made here are committed (the API reads through its own connection), so each assertion looks
only at this file's own products, or at seeded rows that no test changes.
"""
from fastapi.testclient import TestClient

from app.main import app
from tests.support import connect, unique_sku

client = TestClient(app)
API = "/api/v1"


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


def a_product(base_price="100.00", sale_price=None, stock=None) -> int:
    """A committed JBL speaker at base_price, on a running promotion at sale_price if one is given, with
    inventory rows only where stock = {store_id: quantity} says. Returns its product_id."""
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO product (sku, name, brand_id, category_id, base_price)
                SELECT %s, 'Catalogue test speaker', b.brand_id, c.category_id, %s
                FROM brand b, category c
                WHERE b.name = 'JBL' AND c.name = 'Speakers'
                RETURNING product_id
                """,
                (unique_sku(), base_price),
            )
            product_id = cur.fetchone()["product_id"]
            if sale_price is not None:
                cur.execute(
                    """
                    INSERT INTO promotion (product_id, sale_price, starts_at, ends_at)
                    VALUES (%s, %s, now() - interval '1 day', now() + interval '1 day')
                    """,
                    (product_id, sale_price),
                )
            for store_id, quantity in (stock or {}).items():
                cur.execute("INSERT INTO inventory (store_id, product_id, quantity) VALUES (%s, %s, %s)",
                            (store_id, product_id, quantity))
    finally:
        conn.close()
    return product_id


def listed(**filters) -> dict:
    """GET /products with these query parameters -> {product_id: product}."""
    response = client.get(f"{API}/products", params=filters)
    assert response.status_code == 200, response.text
    return {product["product_id"]: product for product in response.json()}


# ---------------------------------------------------------------- price (R1, R2)

def test_the_price_filter_uses_the_current_price_not_the_base_price():
    on_sale = a_product(base_price="100.00", sale_price="80.00")
    # The sale price is inside the range, the base price outside it: listed, at the price it sells for.
    found = listed(min_price="75.00", max_price="85.00")
    assert on_sale in found
    assert (found[on_sale]["current_price"], found[on_sale]["on_sale"]) == ("80.00", True)
    # The base price is inside the range, the sale price outside it: not listed.
    assert on_sale not in listed(min_price="95.00", max_price="105.00")


def test_price_bounds_are_inclusive():
    product = a_product(base_price="80.00")
    assert product in listed(min_price="80.00", max_price="80.00")
    assert product not in listed(min_price="80.01")
    assert product not in listed(max_price="79.99")


def test_a_malformed_price_range_is_refused():
    inverted = client.get(f"{API}/products", params={"min_price": "100.00", "max_price": "50.00"})
    assert error_of(inverted) == (422, "invalid_price_range")
    for malformed in ({"min_price": "-1"}, {"max_price": "cheap"}, {"min_price": "1.005"}):
        assert error_of(client.get(f"{API}/products", params=malformed)) == (422, "validation_error")


# ---------------------------------------------------------------- categories (R1)

def test_a_top_level_category_includes_its_subcategories():
    categories = {c["name"]: c["category_id"] for c in client.get(f"{API}/categories").json()}
    audio = listed(category_id=categories["Audio"])
    headphones = listed(category_id=categories["Headphones"])
    # The seed puts no product in Audio itself: its list is its subcategories' products.
    audio_categories = {product["category"] for product in audio.values()}
    assert {"Headphones", "Speakers"} <= audio_categories <= {"Audio", "Headphones", "Speakers"}
    assert {product["category"] for product in headphones.values()} == {"Headphones"}
    assert set(headphones) < set(audio)


# ---------------------------------------------------------------- one store's stock (R3)

def test_store_quantity_is_the_stores_own_and_null_without_a_store():
    product = a_product(stock={1: 7, 2: 3})
    assert listed(store_id=1)[product]["store_quantity"] == 7
    assert listed(store_id=2)[product]["store_quantity"] == 3
    # With other filters as well: the store's parameter has to come first in the query.
    assert listed(store_id=2, max_price="100.00", q="Catalogue test")[product]["store_quantity"] == 3
    everywhere = listed()[product]
    assert (everywhere["store_quantity"], everywhere["total_stock"]) == (None, 10)
    assert client.get(f"{API}/products/{product}").json()["store_quantity"] is None


def test_a_store_without_an_inventory_row_shows_zero():
    product = a_product(stock={2: 5})                      # no inventory row at store 1
    assert listed(store_id=1)[product]["store_quantity"] == 0   # still listed: stock is information, not a filter


def test_an_unknown_store_is_not_found():
    assert error_of(client.get(f"{API}/products", params={"store_id": 999999})) == (404, "not_found")

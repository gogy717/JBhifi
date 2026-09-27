from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth import RequiredActor, require_catalogue_writer
from app.db import DbCursor
from app.errors import ERROR_RESPONSES, ApiError
from app.schemas.products import ProductCreate, ProductDetail, ProductSummary, ProductUpdate, Spec
from app.services import products

router = APIRouter(prefix="/products", tags=["products"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[ProductSummary])
def list_products(
    cur: DbCursor,
    q: str | None = None,
    category_id: int | None = None,
    brand_id: int | None = None,
    include_inactive: bool = False,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    store_id: int | None = None,
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError(422, "invalid_price_range", "The lowest price is above the highest price.",
                       {"min_price": str(min_price), "max_price": str(max_price)})
    return products.list_products(cur, q, category_id, brand_id, include_inactive, min_price, max_price, store_id)


@router.post("", response_model=ProductDetail, status_code=201)
def create_product(body: ProductCreate, actor: RequiredActor, cur: DbCursor):
    require_catalogue_writer(actor)
    return products.create_product(cur, body)


@router.get("/{product_id}", response_model=ProductDetail)
def get_product(product_id: int, cur: DbCursor):
    return products.get_product(cur, product_id)


@router.patch("/{product_id}", response_model=ProductDetail)
def update_product(product_id: int, body: ProductUpdate, actor: RequiredActor, cur: DbCursor):
    require_catalogue_writer(actor)
    return products.update_product(cur, product_id, body.model_dump(exclude_unset=True, exclude_none=True))


@router.put("/{product_id}/specs", response_model=list[Spec])
def replace_specs(product_id: int, body: list[Spec], actor: RequiredActor, cur: DbCursor):
    require_catalogue_writer(actor)
    return products.replace_specs(cur, product_id, body)

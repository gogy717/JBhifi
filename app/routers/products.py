from fastapi import APIRouter, Query

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas import Money
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
    min_price: Money | None = Query(None, ge=0),
    max_price: Money | None = Query(None, ge=0),
    store_id: int | None = None,
):
    return products.list_products(cur, q, category_id, brand_id, include_inactive, min_price, max_price, store_id)


@router.post("", response_model=ProductDetail, status_code=201)
def create_product(body: ProductCreate, cur: DbCursor, actor: CurrentActor):
    return products.create_product(cur, actor, body)


@router.get("/{product_id}", response_model=ProductDetail)
def get_product(product_id: int, cur: DbCursor):
    return products.get_product(cur, product_id)


@router.patch("/{product_id}", response_model=ProductDetail)
def update_product(product_id: int, body: ProductUpdate, cur: DbCursor, actor: CurrentActor):
    return products.update_product(cur, actor, product_id, body.model_dump(exclude_unset=True, exclude_none=True))


@router.put("/{product_id}/specs", response_model=list[Spec])
def replace_specs(product_id: int, body: list[Spec], cur: DbCursor, actor: CurrentActor):
    return products.replace_specs(cur, actor, product_id, body)

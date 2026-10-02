from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas import Money
from app.schemas.promotions import PromotionOut


class ProductSummary(BaseModel):
    product_id: int
    sku: str
    name: str
    brand_id: int
    brand: str
    category_id: int
    category: str
    base_price: Decimal
    current_price: Decimal          # from v_product_current_price: sale price while a promotion runs
    on_sale: bool
    is_active: bool
    total_stock: int                # across all stores and the warehouse
    store_quantity: int | None = None   # at the store in ?store_id= (0 if it has none); null without one


class Spec(BaseModel):
    spec_name: str = Field(min_length=1, max_length=100)
    spec_value: str = Field(min_length=1, max_length=200)


class StoreStock(BaseModel):
    store_id: int
    store_name: str
    store_type: str
    state: str
    quantity: int


class ProductDetail(ProductSummary):
    specs: list[Spec]
    stock: list[StoreStock]
    promotions: list[PromotionOut]


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    brand_id: int
    category_id: int
    base_price: Money


class ProductUpdate(BaseModel):
    """Only the fields that are sent are changed."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand_id: int | None = None
    category_id: int | None = None
    base_price: Money | None = None
    is_active: bool | None = None

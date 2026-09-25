from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel

from app.schemas import Money

PromotionStatus = Literal["upcoming", "active", "ended"]


class PromotionOut(BaseModel):
    promotion_id: int
    product_id: int
    sku: str
    brand: str
    product_name: str
    base_price: Decimal
    product_active: bool            # a retired product's promotion isn't advertised to customers
    sale_price: Decimal
    starts_at: datetime
    ends_at: datetime
    status: PromotionStatus


class PromotionCreate(BaseModel):
    product_id: int
    sale_price: Money
    starts_at: AwareDatetime        # with a UTC offset, so there's no guessing whose midnight it is
    ends_at: AwareDatetime          # exclusive: the promotion runs over [starts_at, ends_at)

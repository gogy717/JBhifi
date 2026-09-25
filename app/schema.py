from decimal import Decimal

from pydantic import BaseModel, Field


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    stock: int = Field(default=0, ge=0)
    category_id: int | None = None


class ProductOut(ProductIn):
    id: int


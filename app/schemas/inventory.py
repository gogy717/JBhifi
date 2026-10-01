from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The database re-checks this list and the sign that goes with each reason (BR18).
AdjustmentReason = Literal["received", "damaged", "stocktake"]


class InventoryRow(BaseModel):
    product_id: int
    sku: str
    name: str
    brand: str
    category: str
    current_price: Decimal
    on_sale: bool
    is_active: bool
    quantity: int                   # 0 when the product has never been stocked at this store


class AdjustmentCreate(BaseModel):
    """Who makes the change is the signed-in staff member; a staff_id in the body is refused (extra)."""
    model_config = ConfigDict(extra="forbid")

    delta: int                     # relative change: +5 received, -1 damaged, ±n after a stocktake
    reason: AdjustmentReason
    note: str | None = Field(default=None, max_length=500)


class AdjustmentOut(BaseModel):
    adjustment_id: int
    store_id: int
    product_id: int
    sku: str
    product_name: str
    staff_id: int
    staff_name: str
    delta: int
    reason: AdjustmentReason
    note: str | None
    quantity_after: int
    adjusted_at: datetime

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Money

FulfilmentMethod = Literal["delivery", "click_collect"]


class OrderItemIn(BaseModel):
    """One requested line. There is no unit price and no customer: those are the server's."""
    model_config = ConfigDict(extra="forbid")

    product_id: int
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fulfilment_method: FulfilmentMethod
    fulfilling_store_id: int
    delivery_address_no: int | None = None
    items: list[OrderItemIn] = Field(min_length=1)
    expected_total: Money          # what the customer reviewed; compared, never trusted as the price


class OrderLine(BaseModel):
    line_no: int
    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal            # the price at purchase time (BR08)
    line_total: Decimal


class DeliveryAddress(BaseModel):
    address_no: int
    line1: str
    suburb: str
    state: str
    postcode: str


class Payment(BaseModel):
    payment_id: int
    kind: Literal["charge", "refund"]
    amount: Decimal
    return_id: int | None
    cancellation_id: int | None
    created_at: datetime


class StatusChange(BaseModel):
    seq: int
    from_status: str | None
    to_status: str
    changed_at: datetime
    changed_by_staff_id: int | None
    changed_by_name: str | None


class OrderSummary(BaseModel):
    order_id: int
    customer_id: int
    placed_at: datetime
    status: str
    fulfilment_method: FulfilmentMethod
    fulfilling_store_id: int
    fulfilling_store_name: str
    total: Decimal
    line_count: int


class OrderDetail(OrderSummary):
    lines: list[OrderLine]
    delivery_address: DeliveryAddress | None
    payments: list[Payment]
    history: list[StatusChange]
    # What this actor may do next, computed by the server from the order's status.
    allowed_actions: list[str]

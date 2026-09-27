from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReturnStatus = Literal["requested", "received", "refunded", "rejected"]


class ReturnLineIn(BaseModel):
    """One requested line of a return, named by the order line it comes from."""
    model_config = ConfigDict(extra="forbid")

    line_no: int = Field(gt=0)
    quantity: int = Field(gt=0)


class ReturnCreate(BaseModel):
    """A return request. The customer, the order, the time and the refund are the server's."""
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    lines: list[ReturnLineIn] = Field(min_length=1)


class ReturnLine(BaseModel):
    line_no: int
    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal            # the price it was bought at, not today's price
    line_total: Decimal


class ReceivingStore(BaseModel):
    store_id: int
    name: str


class ReturnStatusEntry(BaseModel):
    seq: int
    from_status: ReturnStatus | None
    to_status: ReturnStatus
    changed_at: datetime
    changed_by_staff_id: int | None
    changed_by_name: str | None


class ReturnableLine(BaseModel):
    line_no: int
    product_id: int
    sku: str
    name: str
    quantity: int                   # bought
    unit_price: Decimal
    returned_quantity: int          # already requested and not rejected
    remaining_quantity: int


class ReturnEligibility(BaseModel):
    """Whether this order can still be returned, why not, and how much of each line is left."""
    eligible: bool
    deadline: datetime | None
    reason: str | None
    lines: list[ReturnableLine]


class ReturnSummary(BaseModel):
    return_id: int
    order_id: int
    status: ReturnStatus
    requested_at: datetime
    reason: str
    refund_amount: Decimal | None   # null until refunded; a zero-value refund stays null


class ReturnDetail(ReturnSummary):
    lines: list[ReturnLine]
    receiving_store: ReceivingStore | None
    history: list[ReturnStatusEntry]
    allowed_actions: list[str]
    refund_preview: Decimal         # what processing would refund, from purchase-time prices


class ReturnAction(BaseModel):
    """A staff action on a return. `expected_status` is what the screen was showing."""
    model_config = ConfigDict(extra="forbid")

    expected_status: ReturnStatus

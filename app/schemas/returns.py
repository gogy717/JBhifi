"""What a return looks like to its readers, and what customers and staff send. Statuses are plain strings
here: return_request_status_valid decides which values exist."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Surrounding spaces are trimmed, so a reason of only spaces is empty: malformed (422), not a rule.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ReturnLine(BaseModel):
    line_no: int                    # the order line it comes from
    product_id: int
    sku: str
    name: str
    quantity: int                   # how many of that line come back
    unit_price: Decimal             # the price it was bought at (BR08): what is refunded per unit
    line_total: Decimal


class ReturnSummary(BaseModel):
    """One return as lists show it. quantity and value come from v_return_value."""
    return_id: int
    order_id: int
    status: str
    reason: str
    requested_at: datetime
    quantity: int
    value: Decimal                  # what a refund pays: its items at the prices they were bought at
    refunded: Decimal | None        # the refund paid, if any (none yet, or none for a zero value)
    received_store_id: int | None
    received_store_name: str | None
    received_at: datetime | None
    resolved_at: datetime | None    # when it was refunded or rejected
    rejection_reason: str | None


class ReturnDetail(ReturnSummary):
    customer_id: int
    fulfilling_store_id: int        # the store of the order being returned
    processed_by_name: str | None   # who received it
    resolved_by_name: str | None    # who refunded or rejected it
    lines: list[ReturnLine]


# ---------------------------------------------------------------- requests

class ReturnLineIn(BaseModel):
    """One line to return. Quantity is only typed here: quantity > 0 is return_line_qty_positive's (409), and
    "no more than was bought" is BR12's."""
    model_config = ConfigDict(extra="forbid")

    line_no: int
    quantity: int


class ReturnCreate(BaseModel):
    """What the customer asks to return. The order is in the path; the customer is whoever is signed in."""
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    lines: list[ReturnLineIn] = Field(min_length=1)     # a return of nothing is malformed (422)


class ReturnReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason                  # shown to the customer

"""What an order looks like to its readers. Statuses and fulfilment methods are plain strings here: the
database's order_status and fulfilment domains decide which values exist."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Money


class OrderLine(BaseModel):
    line_no: int
    product_id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal             # the price it was sold at (BR08), not today's price
    line_total: Decimal


class DeliveryAddress(BaseModel):
    """The address the order was placed with — still shown after the customer retires it (BR16)."""
    address_no: int
    line1: str
    suburb: str
    state: str
    postcode: str


class PaymentSummary(BaseModel):
    """From v_order_payment: charged, refunded, and the balance the shop holds (charged − refunded)."""
    charged: Decimal
    refunded: Decimal
    balance: Decimal


class HistoryEntry(BaseModel):
    """One row of v_order_timeline (R11)."""
    seq: int
    from_status: str | None         # None on the first row: the order's creation
    to_status: str
    changed_at: datetime
    changed_by_staff_id: int | None  # None when the customer or the system made the change
    changed_by_name: str | None


class OrderSummary(BaseModel):
    """One row of v_order_summary."""
    order_id: int
    customer_id: int
    placed_at: datetime
    status: str
    fulfilment_method: str
    fulfilling_store_id: int        # ships from (delivery) or is collected at (Click & Collect)
    fulfilling_store_name: str
    total: Decimal
    line_count: int
    last_updated_at: datetime       # when the status last changed (its newest history row)


class OrderDetail(OrderSummary):
    lines: list[OrderLine]
    delivery_address: DeliveryAddress | None    # None for Click & Collect
    payment: PaymentSummary
    history: list[HistoryEntry]                 # oldest first
    # Where the transition table (BR09) lets the order go from its current status — the same for every
    # reader, and shown as text: the staff screens that move orders come with sub-project 2.
    allowed_next_statuses: list[str]


# ---------------------------------------------------------------- checkout (T1) requests

class OrderLineIn(BaseModel):
    """One line of the basket. There is no price: the server takes it from v_product_current_price (BR08).
    Quantity is only typed here; quantity > 0 is BR07's CHECK, answered as 409 br07_order_line_qty_positive."""
    model_config = ConfigDict(extra="forbid")       # a unit_price sent by the client is refused, not ignored

    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    """The basket the customer reviewed. The customer is whoever is signed in, never a field here."""
    model_config = ConfigDict(extra="forbid")

    fulfilment_method: Literal["delivery", "click_collect"]
    fulfilling_store_id: int                        # ships from (delivery) or is collected at (Click & Collect)
    delivery_address_no: int | None = None          # delivery only: BR06's CHECK says so, not this model
    items: list[OrderLineIn] = Field(min_length=1)  # an empty basket is malformed (422), not a rule
    expected_total: Money                           # the total the customer saw: compared, never charged

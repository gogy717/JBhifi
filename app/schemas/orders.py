"""What an order looks like to its readers. Statuses and fulfilment methods are plain strings here: the
database's order_status and fulfilment domains decide which values exist."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


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

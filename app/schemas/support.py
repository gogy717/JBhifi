from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class HistoryEvent(BaseModel):
    """One thing that happened to a customer: an order status change, a payment, or a return request."""
    at: datetime
    kind: str                           # status | charge | refund | return_requested
    order_id: int
    return_id: int | None               # return_requested, and a refund for a return
    from_status: str | None             # status only (None on the order's creation)
    to_status: str | None               # status only
    amount: Decimal | None              # charge and refund only
    staff_name: str | None              # status only: the staff member who made the change, if one did

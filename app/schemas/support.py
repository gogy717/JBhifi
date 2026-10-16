from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class HistoryEvent(BaseModel):
    """One thing that happened to a customer: an order status change, a payment, or a step of a return."""
    at: datetime
    kind: str                           # status | charge | refund | return_requested | return_received |
                                        # return_refunded | return_rejected
    order_id: int
    return_id: int | None               # the return events, and a refund for a return
    from_status: str | None             # status only (None on the order's creation)
    to_status: str | None               # status only
    amount: Decimal | None              # charge and refund only
    staff_name: str | None              # who made the status change, received the return, or resolved it
    note: str | None                    # return_rejected: the reason the customer is given

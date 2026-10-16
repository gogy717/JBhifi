"""Requests that move an order along or cancel it. The answer to both is the order in full (OrderDetail).

Each request carries the status the caller's screen showed (from_status): the service compares it with the order's
status under the row lock, so a stale screen or a retried request is told where the order is now instead of
moving it (spec §3). Which moves are legal is BR09's transition table; these models only name the values.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict

# The values of the order_status domain (sql/00_domains.sql).
OrderStatus = Literal["placed", "paid", "picking", "shipped", "delivered", "ready", "collected", "cancelled"]


class StatusMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_status: OrderStatus
    # The moves staff make. Not paid (checkout's, T1) and not cancelled (T4 also restocks and refunds, so it has
    # its own request): sending either is malformed (422).
    to_status: Literal["picking", "ready", "shipped", "collected", "delivered"]


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_status: OrderStatus

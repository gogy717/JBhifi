from typing import Annotated

from fastapi import APIRouter, Query

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.fulfilment import CancelRequest, OrderStatus, StatusMove
from app.schemas.orders import OrderDetail, OrderSummary
from app.services import fulfilment

router = APIRouter(tags=["fulfilment"], responses=ERROR_RESPONSES)


@router.get("/stores/{store_id}/orders", response_model=list[OrderSummary])
def list_store_orders(store_id: int, cur: DbCursor, actor: CurrentActor,
                      status: Annotated[list[OrderStatus] | None, Query()] = None):
    """The store's orders, oldest first: its staff's work queue. Repeat `status` to show only those statuses."""
    return fulfilment.list_store_orders(cur, actor, store_id, status)


@router.post("/orders/{order_id}/status", response_model=OrderDetail)
def move_order(order_id: int, body: StatusMove, cur: DbCursor, actor: CurrentActor):
    """Move an order one step along its path, as the fulfilling store's staff or support. 409 status_changed
    (detail: the current status) when the order is no longer at `from_status`."""
    return fulfilment.advance_order(cur, actor, order_id, body)


@router.post("/orders/{order_id}/cancel", response_model=OrderDetail)
def cancel_order(order_id: int, body: CancelRequest, cur: DbCursor, actor: CurrentActor):
    """Cancel an order (T4): its stock goes back to the fulfilling store and what was charged is refunded, in
    one transaction. The customer may cancel before picking starts; the fulfilling store's staff whenever the
    transition table allows. 409 status_changed (detail: the current status) when it is no longer at
    `from_status`."""
    return fulfilment.cancel_order(cur, actor, order_id, body)

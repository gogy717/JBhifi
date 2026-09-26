from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.auth import (RequiredActor, require_customer, require_customer_self,
                      require_store_or_support_reader)
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.orders import (CancellationCreate, OrderCreate, OrderDetail, OrderStatus, OrderSummary,
                                StatusChange)
from app.services import cancellations, orders

router = APIRouter(tags=["orders"], responses=ERROR_RESPONSES)

# The customer's retry token. Sending the same key with the same body returns the same order (200) instead
# of creating a second one; the same key with a different body is a 409 conflict.
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post("/orders", response_model=OrderDetail, status_code=201)
def create_order(body: OrderCreate, response: Response, actor: RequiredActor, cur: DbCursor,
                 idempotency_key: IdempotencyKey):
    require_customer(actor)
    order, replay = orders.checkout(cur, actor, idempotency_key, body)
    if replay:
        response.status_code = 200
    return order


@router.get("/orders/{order_id}", response_model=OrderDetail)
def read_order(order_id: int, actor: RequiredActor, cur: DbCursor):
    return orders.get_order(cur, actor, order_id)


@router.get("/customers/{customer_id}/orders", response_model=list[OrderSummary])
def list_customer_orders(customer_id: int, actor: RequiredActor, cur: DbCursor):
    require_customer_self(actor, customer_id)
    return orders.list_customer_orders(cur, actor, customer_id)


@router.get("/stores/{store_id}/orders", response_model=list[OrderSummary])
def list_store_orders(store_id: int, actor: RequiredActor, cur: DbCursor, status: OrderStatus | None = None):
    """The store's fulfilment queue. Support staff may read any store; store staff only their own."""
    require_store_or_support_reader(actor, store_id)
    return orders.list_store_orders(cur, store_id, status)


@router.patch("/orders/{order_id}/status", response_model=OrderDetail)
def change_order_status(order_id: int, body: StatusChange, actor: RequiredActor, cur: DbCursor):
    """One legal fulfilment move. Cancelling has its own endpoint, so it cannot slip in as a status."""
    return orders.transition_order(cur, actor, order_id, body)


@router.post("/orders/{order_id}/cancel", response_model=OrderDetail)
def cancel_order(order_id: int, body: CancellationCreate, actor: RequiredActor, cur: DbCursor):
    """Cancel in one transaction: restock, refund the captured balance, record the cancellation."""
    return cancellations.cancel_order(cur, actor, order_id, body)

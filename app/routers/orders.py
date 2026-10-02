from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.orders import OrderCreate, OrderDetail, OrderSummary
from app.services import orders

router = APIRouter(tags=["orders"], responses=ERROR_RESPONSES)

# The customer's retry token for one reviewed basket (BR10). Sending the same key again returns the order
# already placed with it (200) instead of placing a second one, so a lost answer can be retried safely.
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.get("/orders/{order_id}", response_model=OrderDetail)
def read_order(order_id: int, cur: DbCursor, actor: CurrentActor):
    """One order: lines, delivery address, payments, status timeline and the statuses it can move to next."""
    return orders.get_order(cur, actor, order_id)


@router.get("/customers/{customer_id}/orders", response_model=list[OrderSummary])
def list_customer_orders(customer_id: int, cur: DbCursor, actor: CurrentActor):
    """A customer's orders, newest first: the customer themselves, or support staff."""
    return orders.list_customer_orders(cur, actor, customer_id)


@router.post(
    "/orders",
    response_model=OrderDetail,
    status_code=201,
    responses={200: {"model": OrderDetail, "description": "A retry: the order already placed with this key"}},
)
def create_order(body: OrderCreate, response: Response, idempotency_key: IdempotencyKey, cur: DbCursor,
                 actor: CurrentActor):
    """Check out (T1): place and pay for the reviewed basket in one transaction. 201 for a new order; 200
    with the same order when this Idempotency-Key was already used by this customer."""
    order, replayed = orders.checkout(cur, actor, idempotency_key, body)
    if replayed:
        response.status_code = 200
    return order

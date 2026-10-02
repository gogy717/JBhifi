from fastapi import APIRouter

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.orders import OrderDetail, OrderSummary
from app.services import orders

router = APIRouter(tags=["orders"], responses=ERROR_RESPONSES)


@router.get("/orders/{order_id}", response_model=OrderDetail)
def read_order(order_id: int, cur: DbCursor, actor: CurrentActor):
    """One order: lines, delivery address, payments, status timeline and the statuses it can move to next."""
    return orders.get_order(cur, actor, order_id)


@router.get("/customers/{customer_id}/orders", response_model=list[OrderSummary])
def list_customer_orders(customer_id: int, cur: DbCursor, actor: CurrentActor):
    """A customer's orders, newest first: the customer themselves, or support staff."""
    return orders.list_customer_orders(cur, actor, customer_id)

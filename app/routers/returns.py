from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.returns import ReturnCreate, ReturnDetail, ReturnReject, ReturnSummary
from app.services import returns

router = APIRouter(tags=["returns"], responses=ERROR_RESPONSES)

# The customer's retry token for one return request (BR10). Sending the same key again returns the return
# already asked for with it (200), so a lost answer can be retried without asking twice.
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post(
    "/orders/{order_id}/returns",
    response_model=ReturnDetail,
    status_code=201,
    responses={200: {"model": ReturnDetail, "description": "A retry: the return already asked for with this key"}},
)
def request_return(order_id: int, body: ReturnCreate, response: Response, idempotency_key: IdempotencyKey,
                   cur: DbCursor, actor: CurrentActor):
    """Ask to return lines of a completed order (BR11, BR12). 201 for a new return; 200 with the same return
    when this Idempotency-Key was already used on this order."""
    detail, replayed = returns.request_return(cur, actor, order_id, idempotency_key, body)
    if replayed:
        response.status_code = 200
    return detail


@router.get("/returns/{return_id}", response_model=ReturnDetail)
def read_return(return_id: int, cur: DbCursor, actor: CurrentActor):
    """One return: its lines at the prices they were bought at, what it is worth, and where it is."""
    return returns.get_return(cur, actor, return_id)


@router.get("/customers/{customer_id}/returns", response_model=list[ReturnSummary])
def list_customer_returns(customer_id: int, cur: DbCursor, actor: CurrentActor):
    """A customer's returns, newest first: the customer themselves, or support staff."""
    return returns.list_customer_returns(cur, actor, customer_id)


@router.get("/stores/{store_id}/returns", response_model=list[ReturnSummary])
def list_store_returns(store_id: int, cur: DbCursor, actor: CurrentActor):
    """The store's returns desk, newest first: requested returns of its orders, and every return it received."""
    return returns.list_store_returns(cur, actor, store_id)


@router.post("/returns/{return_id}/receive", response_model=ReturnDetail)
def receive_return(return_id: int, cur: DbCursor, actor: CurrentActor):
    """Take a requested return in at your own (retail) store. Nothing is restocked or refunded yet."""
    return returns.receive_return(cur, actor, return_id)


@router.post("/returns/{return_id}/refund", response_model=ReturnDetail)
def refund_return(return_id: int, cur: DbCursor, actor: CurrentActor):
    """T2: restock the receiving store, refund what the items were bought for, and mark the return refunded —
    all or nothing. Only the receiving store; 409 return_status_transition if it isn't received."""
    return returns.refund_return(cur, actor, return_id)


@router.post("/returns/{return_id}/reject", response_model=ReturnDetail)
def reject_return(return_id: int, body: ReturnReject, cur: DbCursor, actor: CurrentActor):
    """Refuse a received return, with a reason the customer sees. Nothing is restocked or refunded."""
    return returns.reject_return(cur, actor, return_id, body)

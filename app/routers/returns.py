from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.auth import (RequiredActor, require_customer, require_customer_self,
                      require_store_or_support_reader)
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.returns import (ReturnAction, ReturnCreate, ReturnDetail, ReturnStatus, ReturnSummary)
from app.services import returns

router = APIRouter(tags=["returns"], responses=ERROR_RESPONSES)

# Scoped to the order (T13): the same key on another order is a different request.
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post("/orders/{order_id}/returns", response_model=ReturnDetail, status_code=201)
def request_return(order_id: int, body: ReturnCreate, response: Response, actor: RequiredActor,
                   cur: DbCursor, idempotency_key: IdempotencyKey):
    require_customer(actor)
    detail, replay = returns.request_return(cur, actor, order_id, idempotency_key, body)
    if replay:
        response.status_code = 200
    return detail


@router.get("/customers/{customer_id}/returns", response_model=list[ReturnSummary])
def list_customer_returns(customer_id: int, actor: RequiredActor, cur: DbCursor):
    require_customer_self(actor, customer_id)
    return returns.list_customer_returns(cur, actor, customer_id)


@router.get("/stores/{store_id}/returns", response_model=list[ReturnSummary])
def list_store_returns(store_id: int, actor: RequiredActor, cur: DbCursor,
                       status: ReturnStatus | None = None):
    """The store's returns desk: requests to take in, and the ones it has already taken in."""
    require_store_or_support_reader(actor, store_id)
    return returns.list_store_returns(cur, store_id, status)


@router.get("/returns/{return_id}", response_model=ReturnDetail)
def read_return(return_id: int, actor: RequiredActor, cur: DbCursor):
    return returns.get_return(cur, actor, return_id)


@router.post("/returns/{return_id}/receive", response_model=ReturnDetail)
def receive_return(return_id: int, body: ReturnAction, actor: RequiredActor, cur: DbCursor):
    """Take the item in at the actor's own retail store. Nothing is restocked yet."""
    return returns.receive_return(cur, actor, return_id, body)


@router.post("/returns/{return_id}/reject", response_model=ReturnDetail)
def reject_return(return_id: int, body: ReturnAction, actor: RequiredActor, cur: DbCursor):
    return returns.reject_return(cur, actor, return_id, body)


@router.post("/returns/{return_id}/process", response_model=ReturnDetail)
def process_return(return_id: int, body: ReturnAction, actor: RequiredActor, cur: DbCursor):
    """Restock and refund in one transaction, from the prices the items were bought at."""
    return returns.process_return(cur, actor, return_id, body)

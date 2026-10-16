from fastapi import APIRouter

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.support import HistoryEvent
from app.services import support

router = APIRouter(tags=["support"], responses=ERROR_RESPONSES)


@router.get("/customers/{customer_id}/history", response_model=list[HistoryEvent])
def customer_history(customer_id: int, cur: DbCursor, actor: CurrentActor):
    """Everything that happened to a customer — status changes, payments, return requests — newest first: the
    customer themselves, or support staff."""
    return support.customer_history(cur, actor, customer_id)

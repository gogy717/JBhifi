from typing import Annotated

from fastapi import APIRouter, Query

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.reports import StockedEverywhere, StoreReport
from app.services import reports

router = APIRouter(tags=["reports"], responses=ERROR_RESPONSES)

Days = Annotated[int, Query(ge=1, le=365, description="The window: sales placed in the last `days` days")]


@router.get("/stores/{store_id}/report", response_model=StoreReport)
def store_report(store_id: int, cur: DbCursor, actor: CurrentActor, days: Days = 30):
    """Low stock, sales by category and return rate for one store, read from one snapshot: its manager, or
    support staff for any store."""
    return reports.store_report(cur, actor, store_id, days)


@router.get("/reports/stocked-in-every-store", response_model=StockedEverywhere)
def stocked_in_every_store(cur: DbCursor, actor: CurrentActor,
                           state: Annotated[str, Query(description="e.g. NSW; the au_state domain decides which exist")]):
    """The products in stock at every retail store of a state (relational division). Any staff member."""
    return reports.stocked_in_every_store(cur, actor, state)

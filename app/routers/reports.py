from typing import Annotated

from fastapi import APIRouter, Query

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.reports import StoreReport
from app.services import reports

router = APIRouter(tags=["reports"], responses=ERROR_RESPONSES)

Days = Annotated[int, Query(ge=1, le=365, description="The window: sales placed in the last `days` days")]


@router.get("/stores/{store_id}/report", response_model=StoreReport)
def store_report(store_id: int, cur: DbCursor, actor: CurrentActor, days: Days = 30):
    """Low stock, sales by category and return rate for one store, read from one snapshot: its manager, or
    support staff for any store."""
    return reports.store_report(cur, actor, store_id, days)

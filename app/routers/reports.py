from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth import RequiredActor, require_actor, require_store_or_support_reader
from app.db import DbCursor
from app.errors import ERROR_RESPONSES, ApiError
from app.schemas.reports import LowStockReport, ReturnsReport, SalesReport
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reports"], responses=ERROR_RESPONSES)

Threshold = Annotated[int, Query(ge=0, le=1000)]


def _scope(actor, store_id: int | None) -> int | None:
    """One store's report: its own staff or support. All stores: support only."""
    actor = require_actor(actor)
    if actor.kind != "staff":
        raise ApiError(403, "staff_only", "Reports are for staff.")
    if store_id is None:
        if not actor.is_support:
            raise ApiError(403, "support_only",
                           "Choose a store: only support staff may report across all of them.",
                           {"store_id": actor.store_id})
        return None
    require_store_or_support_reader(actor, store_id)
    return store_id


@router.get("/sales", response_model=SalesReport)
def sales(actor: RequiredActor, cur: DbCursor, store_id: int | None = None,
          from_date: date | None = None, to_date: date | None = None):
    """Money captured and refunded in the period, by each payment's own event time, per store."""
    return reports.sales(cur, _scope(actor, store_id), from_date, to_date)


@router.get("/low-stock", response_model=LowStockReport)
def low_stock(actor: RequiredActor, cur: DbCursor, store_id: int | None = None, threshold: Threshold = 3):
    """Active products at or below the threshold, including ones never stocked at that store."""
    scope = _scope(actor, store_id if store_id is not None else actor.store_id)
    if scope is None:
        raise ApiError(422, "store_required", "Low stock is reported for one store at a time.")
    return reports.low_stock(cur, scope, threshold)


@router.get("/returns", response_model=ReturnsReport)
def returns(actor: RequiredActor, cur: DbCursor, store_id: int | None = None,
            from_date: date | None = None, to_date: date | None = None):
    """The cohort of return requests created in the period, with their current status and refunds."""
    return reports.returns(cur, _scope(actor, store_id), from_date, to_date)

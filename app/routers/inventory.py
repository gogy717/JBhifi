from fastapi import APIRouter, Query

from app.auth import RequiredActor, require_store_or_support_reader, require_store_staff
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.inventory import AdjustmentCreate, AdjustmentOut, InventoryRow
from app.services import inventory

router = APIRouter(prefix="/stores/{store_id}", tags=["inventory"], responses=ERROR_RESPONSES)


@router.get("/inventory", response_model=list[InventoryRow])
def list_store_inventory(
    store_id: int,
    cur: DbCursor,
    q: str | None = None,
    category_id: int | None = None,
    low_stock_only: bool = False,
    low_stock_threshold: int = Query(3, ge=0),
):
    return inventory.list_store_inventory(cur, store_id, q, category_id, low_stock_only, low_stock_threshold)


@router.post("/inventory/{product_id}/adjustments", response_model=AdjustmentOut, status_code=201)
def adjust_stock(store_id: int, product_id: int, body: AdjustmentCreate, actor: RequiredActor, cur: DbCursor):
    # The staff member is the session's, not the body's: a request cannot claim someone else's name.
    require_store_staff(actor, store_id)
    return inventory.adjust_stock(cur, store_id, product_id, actor.id, body.delta, body.reason, body.note)


@router.get("/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(
    store_id: int,
    actor: RequiredActor,
    cur: DbCursor,
    product_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    require_store_or_support_reader(actor, store_id)
    return inventory.list_adjustments(cur, store_id, product_id, limit)

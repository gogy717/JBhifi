from fastapi import APIRouter, Query

from app.auth import CurrentActor
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
def adjust_stock(store_id: int, product_id: int, body: AdjustmentCreate, cur: DbCursor, actor: CurrentActor):
    return inventory.adjust_stock(cur, actor, store_id, product_id, body.delta, body.reason, body.note)


@router.get("/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(
    store_id: int,
    cur: DbCursor,
    actor: CurrentActor,
    product_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    return inventory.list_adjustments(cur, actor, store_id, product_id, limit)

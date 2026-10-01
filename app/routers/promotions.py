from fastapi import APIRouter, Response

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.promotions import PromotionCreate, PromotionOut, PromotionStatus
from app.services import promotions

router = APIRouter(prefix="/promotions", tags=["promotions"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[PromotionOut])
def list_promotions(cur: DbCursor, product_id: int | None = None, status: PromotionStatus | None = None):
    return promotions.list_promotions(cur, product_id, status)


@router.post("", response_model=PromotionOut, status_code=201)
def create_promotion(body: PromotionCreate, cur: DbCursor, actor: CurrentActor):
    return promotions.create_promotion(cur, actor, body)


@router.delete("/{promotion_id}", status_code=204)
def delete_promotion(promotion_id: int, cur: DbCursor, actor: CurrentActor):
    promotions.delete_promotion(cur, actor, promotion_id)
    return Response(status_code=204)

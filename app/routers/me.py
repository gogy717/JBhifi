from dataclasses import asdict

from fastapi import APIRouter

from app.auth import CurrentActor, require_actor
from app.errors import ERROR_RESPONSES
from app.schemas.auth import Me

router = APIRouter(tags=["auth"], responses=ERROR_RESPONSES)


@router.get("/me", response_model=Me)
def who_am_i(actor: CurrentActor):
    """The signed-in caller as our database knows them: a customer, or staff with their store and role."""
    return asdict(require_actor(actor))

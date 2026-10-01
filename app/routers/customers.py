from fastapi import APIRouter

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.customers import CustomerDetail, CustomerSummary
from app.services import customers

router = APIRouter(prefix="/customers", tags=["customers"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[CustomerSummary])
def list_customers(cur: DbCursor, actor: CurrentActor):
    return customers.list_customers(cur, actor)


@router.get("/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: int, cur: DbCursor, actor: CurrentActor):
    return customers.get_customer(cur, actor, customer_id)

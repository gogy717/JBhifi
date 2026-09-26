from fastapi import APIRouter

from app.auth import CurrentActor, require_customer_self
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.customers import CustomerDetail, CustomerSummary
from app.services import customers

router = APIRouter(prefix="/customers", tags=["customers"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[CustomerSummary])
def list_customers(cur: DbCursor):
    return customers.list_customers(cur)


@router.get("/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: int, actor: CurrentActor, cur: DbCursor):
    # A customer's own record; support staff may look anyone up. The list above stays a demo directory.
    require_customer_self(actor, customer_id)
    return customers.get_customer(cur, customer_id)

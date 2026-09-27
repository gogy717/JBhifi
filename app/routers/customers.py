from fastapi import APIRouter

from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.customers import CustomerDetail, CustomerSummary
from app.services import customers

router = APIRouter(prefix="/customers", tags=["customers"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[CustomerSummary])
def list_customers(cur: DbCursor):
    return customers.list_customers(cur)


@router.get("/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: int, cur: DbCursor):
    return customers.get_customer(cur, customer_id)

from fastapi import APIRouter

from app.auth import CurrentActor
from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.customers import Address, AddressCreate, AddressRetire, CustomerDetail, CustomerSummary
from app.services import customers

router = APIRouter(prefix="/customers", tags=["customers"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[CustomerSummary])
def list_customers(cur: DbCursor, actor: CurrentActor):
    return customers.list_customers(cur, actor)


@router.get("/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: int, cur: DbCursor, actor: CurrentActor):
    return customers.get_customer(cur, actor, customer_id)


@router.post("/{customer_id}/addresses", response_model=Address, status_code=201)
def add_address(customer_id: int, body: AddressCreate, cur: DbCursor, actor: CurrentActor):
    """Add a delivery address; the server gives it the next number. Only the customer themselves."""
    return customers.add_address(cur, actor, customer_id, body)


@router.patch("/{customer_id}/addresses/{address_no}", response_model=Address)
def retire_address(customer_id: int, address_no: int, body: AddressRetire, cur: DbCursor, actor: CurrentActor):
    """Retire an address — `{"is_active": false}` is the only change accepted (BR16). Doing it twice is harmless."""
    return customers.retire_address(cur, actor, customer_id, address_no)

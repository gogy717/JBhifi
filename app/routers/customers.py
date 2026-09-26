from fastapi import APIRouter

from app.auth import CurrentActor, require_customer, require_customer_self
from app.db import DbCursor
from app.errors import ERROR_RESPONSES, ApiError
from app.schemas.customers import Address, AddressCreate, AddressRetire, CustomerDetail, CustomerSummary
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


def _own_account(actor, customer_id: int) -> None:
    """Addresses are the customer's own: staff may read them, but only the owner changes them."""
    if require_customer(actor).id != customer_id:
        raise ApiError(403, "not_your_account", "That account belongs to another customer.")


@router.post("/{customer_id}/addresses", response_model=Address, status_code=201)
def add_address(customer_id: int, body: AddressCreate, actor: CurrentActor, cur: DbCursor):
    _own_account(actor, customer_id)
    return customers.add_address(cur, customer_id, body)


@router.patch("/{customer_id}/addresses/{address_no}", response_model=Address)
def retire_address(customer_id: int, address_no: int, body: AddressRetire, actor: CurrentActor,
                   cur: DbCursor):
    """Retire an address (is_active: false only). Order history keeps pointing at it unchanged (BR16)."""
    _own_account(actor, customer_id)
    return customers.retire_address(cur, customer_id, address_no)

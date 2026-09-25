from datetime import datetime

from pydantic import BaseModel


class CustomerSummary(BaseModel):
    customer_id: int
    full_name: str
    email: str


class Address(BaseModel):
    address_no: int
    line1: str
    suburb: str
    state: str
    postcode: str
    is_active: bool                 # an inactive address is a past one, kept because addresses are immutable (BR16)


class CustomerDetail(CustomerSummary):
    phone: str | None
    created_at: datetime
    addresses: list[Address]

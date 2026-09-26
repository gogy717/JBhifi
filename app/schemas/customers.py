from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class AddressCreate(BaseModel):
    """A new address. An address is never edited afterwards (BR16): add one, retire the old one."""
    model_config = ConfigDict(extra="forbid")

    line1: str = Field(min_length=1, max_length=200)
    suburb: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=2, max_length=3)      # the domain checks it is a real state
    postcode: str = Field(min_length=4, max_length=4)   # and a four-digit postcode


class AddressRetire(BaseModel):
    """Retiring is the only change an address accepts, and it only ever goes one way."""
    model_config = ConfigDict(extra="forbid")

    is_active: Literal[False]

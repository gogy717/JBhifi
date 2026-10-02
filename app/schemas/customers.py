from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


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
    """A new delivery address. It is never edited afterwards (BR16): add a new one, retire the old one.

    Shape only: each field is trimmed, then its length checked. Which states and postcodes exist is the
    database's call — the au_state and au_postcode domains answer 409 au_state_valid / au_postcode_format.
    """
    model_config = ConfigDict(extra="forbid")       # the address number is the server's to give

    line1: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    suburb: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    state: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=3)]
    postcode: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=4)]


class AddressRetire(BaseModel):
    """Retiring is the only change an address accepts, and it only goes one way."""
    model_config = ConfigDict(extra="forbid")

    is_active: Literal[False]

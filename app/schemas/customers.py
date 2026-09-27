from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    # Normalise before the length checks, so " nsw " is three characters of state, not five.
    @field_validator("line1", "suburb", mode="before")
    @classmethod
    def _not_blank(cls, value):
        """Trim the edges, and refuse whitespace: the address is written once, so it has to be right."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("must not be blank")
        return value

    @field_validator("state", mode="before")
    @classmethod
    def _upper_state(cls, value):
        """`nsw` is the same state as `NSW`; the database domain only accepts the upper-case code."""
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("postcode", mode="before")
    @classmethod
    def _trim_postcode(cls, value):
        return value.strip() if isinstance(value, str) else value


class AddressRetire(BaseModel):
    """Retiring is the only change an address accepts, and it only ever goes one way."""
    model_config = ConfigDict(extra="forbid")

    is_active: Literal[False]

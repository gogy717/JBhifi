"""Pydantic models for request and response bodies.

Request models check only the shape of the input (types, lengths, two decimals). Business rules such as
"a price is never negative" (BR02) are left to the database, so each rule lives in exactly one place.
"""
from decimal import Decimal
from typing import Annotated

from pydantic import Field

Money = Annotated[Decimal, Field(max_digits=10, decimal_places=2)]

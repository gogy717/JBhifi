from typing import Literal

from pydantic import BaseModel


class Me(BaseModel):
    """Who the API takes the caller to be — decided by our database (user_account, BR19), not the token."""
    kind: Literal["customer", "staff"]
    id: int
    display_name: str
    store_id: int | None = None
    store_name: str | None = None
    staff_type: Literal["store", "support"] | None = None
    runs_store: bool = False

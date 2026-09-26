from typing import Literal

from pydantic import BaseModel, ConfigDict


class SessionIn(BaseModel):
    """The demo sign-in request. The server issues the session; the body only says who to become."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["customer", "staff"]
    id: int


class SessionOut(BaseModel):
    kind: Literal["customer", "staff"]
    id: int
    display_name: str
    store_id: int | None = None
    store_name: str | None = None
    staff_type: str | None = None
    runs_store: bool = False

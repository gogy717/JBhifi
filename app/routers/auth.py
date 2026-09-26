"""Demo sign-in: who this browser is for the API.

``POST /session`` is the only place an identity is chosen, and it is disabled when ``DEMO_MODE`` is off
(a real deployment replaces it with a real login). Everything else reads the signed cookie through
``app/auth.py``.
"""
from fastapi import APIRouter, Response

from app.auth import (COOKIE_NAME, CurrentActor, demo_mode_enabled, load_actor, session_payload,
                      sign_session)
from app.db import DbCursor
from app.errors import ERROR_RESPONSES, ApiError, NotFound
from app.schemas.auth import SessionIn, SessionOut

router = APIRouter(prefix="/session", tags=["session"], responses=ERROR_RESPONSES)


@router.get("", response_model=SessionOut | None)
def who_am_i(actor: CurrentActor):
    """The current identity, or null for a guest."""
    return None if actor is None else session_payload(actor)


@router.post("", response_model=SessionOut, status_code=201)
def sign_in(body: SessionIn, response: Response, cur: DbCursor):
    if not demo_mode_enabled():
        raise ApiError(403, "demo_sign_in_disabled", "Demo sign-in is turned off.")
    actor = load_actor(cur, {"kind": body.kind, "id": body.id})
    if actor is None:
        raise NotFound("Customer" if body.kind == "customer" else "Staff member", body.id)
    # HTTP-only, so the page's own scripts cannot read or forge it; same-site lax, so it rides along with
    # the same-origin requests the storefront and admin make through the Next.js proxy.
    response.set_cookie(COOKIE_NAME, sign_session({"kind": body.kind, "id": body.id}),
                        httponly=True, samesite="lax", path="/")
    return session_payload(actor)


@router.delete("", status_code=204)
def sign_out(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return None

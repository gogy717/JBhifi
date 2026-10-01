"""Who signed this token? The one file that knows the API's sign-in provider is Clerk.

Clerk gives the signed-in browser a short-lived session token (a JWT). The API checks it against Clerk's
public keys — no shared secret, and no network call per request once the keys are cached — and takes only
its subject (`sub`) from it. Who that subject *is* (customer or staff, which store, what they may do) is
decided by our database, in app/auth.py. Moving to another OIDC provider changes this file only.
"""
import os
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt

from app.errors import ApiError

CLERK_API = "https://api.clerk.com/v1"


def _issuer() -> str:
    issuer = os.environ.get("CLERK_ISSUER", "").rstrip("/")
    if not issuer:
        raise ApiError(503, "auth_not_configured", "Sign-in is not configured: set CLERK_ISSUER in .env.")
    return issuer


def _authorized_parties() -> set[str]:
    raw = os.environ.get("AUTH_AUTHORIZED_PARTIES", "")
    return {party.strip().rstrip("/") for party in raw.split(",") if party.strip()}


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Fetches and caches the provider's public keys; refetches when a token names an unknown key."""
    return jwt.PyJWKClient(jwks_url)


def _signing_key(token: str):
    try:
        return _jwks_client(f"{_issuer()}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
    except jwt.exceptions.PyJWKClientConnectionError:
        raise ApiError(503, "identity_provider_unavailable",
                       "Can't reach the sign-in provider to check your sign-in. Try again shortly.") from None


def invalid(reason: str) -> ApiError:
    return ApiError(401, "invalid_token", "Your sign-in has expired or isn't valid. Sign in again.",
                    {"reason": reason})


def verify_token(token: str) -> str:
    """The token's subject if the provider signed it, for one of our sites, and it is current; else 401."""
    try:
        claims = jwt.decode(
            token, _signing_key(token), algorithms=["RS256"], issuer=_issuer(), leeway=5,
            options={"require": ["exp", "nbf", "sub", "iss"]},
        )
    except jwt.PyJWTError as error:            # bad signature, expired, wrong issuer, not a JWT at all, …
        raise invalid(type(error).__name__) from None
    if claims.get("azp") not in _authorized_parties():
        raise invalid("azp")                   # a token minted for some other site
    return claims["sub"]


@dataclass(frozen=True)
class Profile:
    email: str
    verified: bool
    full_name: str


def fetch_profile(subject: str) -> Profile:
    """The user's primary email (and whether it is verified) and name, from Clerk's Backend API.

    Called once per person: the first time their token reaches the API (app/auth.py links them then).
    """
    secret = os.environ.get("CLERK_SECRET_KEY")
    if not secret:
        raise ApiError(503, "auth_not_configured", "Sign-in is not configured: set CLERK_SECRET_KEY in .env.")
    try:
        response = httpx.get(f"{CLERK_API}/users/{subject}", headers={"Authorization": f"Bearer {secret}"},
                             timeout=5)
        response.raise_for_status()
        user = response.json()
    except (httpx.HTTPError, ValueError):
        raise ApiError(503, "identity_provider_unavailable",
                       "Can't reach the sign-in provider. Try again shortly.") from None
    primary = next((address for address in user.get("email_addresses", [])
                    if address.get("id") == user.get("primary_email_address_id")), None)
    if primary is None:
        return Profile(email="", verified=False, full_name="")
    email = primary["email_address"]
    verified = (primary.get("verification") or {}).get("status") == "verified"
    name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part)
    return Profile(email=email, verified=verified, full_name=name or email.split("@")[0])

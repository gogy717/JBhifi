"""Sign-in for tests: tokens signed by a key the tests own, so no test ever calls Clerk.

conftest.py points app/identity.py at this key and sets the issuer and allowed origins below; a test then
mints whatever token it needs.
"""
import time
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.errors import ApiError
from app.identity import Profile

ISSUER = "https://test-clerk.example"
PARTY = "http://localhost:3000"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)     # "somebody else's" key


class OwnKeys:
    """Stands in for PyJWKClient: the signing key of any token is the tests' own public key."""
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


def token(subject, *, issuer=ISSUER, party=PARTY, expires_in=60, valid_from=0, key=KEY) -> str:
    """A session token shaped like Clerk's (RS256; sub, iss, azp, iat, nbf, exp). None leaves a claim out."""
    now = int(time.time())
    claims = {"sub": subject, "iss": issuer, "azp": party, "iat": now, "nbf": now + valid_from,
              "exp": now + expires_in}
    return jwt.encode({name: value for name, value in claims.items() if value is not None}, key, algorithm="RS256")


def bearer(subject, **options) -> dict:
    return {"Authorization": f"Bearer {token(subject, **options)}"}


PROFILES: dict[str, Profile] = {}


def fake_fetch_profile(subject: str) -> Profile:
    """Stands in for Clerk's Backend API: it knows only the users a test registered."""
    if subject not in PROFILES:
        raise ApiError(503, "identity_provider_unavailable", "The fake provider has no such user.")
    return PROFILES[subject]


def as_subject(subject: str, email: str, *, name: str = "Test User", verified: bool = True) -> dict:
    """Register what the provider knows about this subject, and return headers signed in as them."""
    PROFILES[subject] = Profile(email=email, verified=verified, full_name=name)
    return bearer(subject)


# Seeded staff the tests sign in as (sql/10_seed_reference.sql).
STAFF_EMAILS = {
    1: "olivia.nguyen@jbhifi.example",      # manages Sydney CBD (store 1)
    13: "hannah.walker@jbhifi.example",     # manages Eastern Creek DC (store 13, the warehouse)
    14: "aiden.chen@jbhifi.example",        # works at Sydney CBD
    15: "zara.ahmed@jbhifi.example",        # works at Sydney CBD
    16: "isla.robinson@jbhifi.example",     # works at Bondi Junction (store 2)
    40: "nora.fitzgerald@jbhifi.example",   # support
}


def as_staff(staff_id: int) -> dict:
    return as_subject(f"test_staff_{staff_id}", STAFF_EMAILS[staff_id])


def as_customer(email: str) -> dict:
    return as_subject(f"test_customer_{email}", email)

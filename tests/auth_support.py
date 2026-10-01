"""Sign-in for tests: tokens signed by a key the tests own, so no test ever calls Clerk.

conftest.py points app/identity.py at this key and sets the issuer and allowed origins below; a test then
mints whatever token it needs.
"""
import time
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

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

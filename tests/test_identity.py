"""Token checks (app/identity.py): only a current token, signed by the provider for one of our sites."""
import httpx
import jwt
import pytest

from app import identity
from app.errors import ApiError
# Imported at collection time, before conftest.py's session fixture swaps identity.fetch_profile for a fake:
# this is the real function, which reads Clerk's Backend API.
from app.identity import Profile, fetch_profile as clerk_fetch_profile
from tests.auth_support import OTHER_KEY, token


def refusal(bad_token) -> str:
    """Assert the token is refused with 401 invalid_token, and return the reason."""
    with pytest.raises(ApiError) as caught:
        identity.verify_token(bad_token)
    assert (caught.value.status, caught.value.code) == (401, "invalid_token")
    return caught.value.detail["reason"]


def test_a_current_token_gives_its_subject():
    assert identity.verify_token(token("user_alice")) == "user_alice"


def test_either_configured_origin_is_accepted():
    assert identity.verify_token(token("user_alice", party="http://127.0.0.1:3000")) == "user_alice"


@pytest.mark.parametrize("options, reason", [
    ({"expires_in": -60}, "ExpiredSignatureError"),
    ({"valid_from": 60}, "ImmatureSignatureError"),
    ({"key": OTHER_KEY}, "InvalidSignatureError"),
    ({"issuer": "https://someone-else.example"}, "InvalidIssuerError"),
    ({"party": "https://evil.example"}, "azp"),
    ({"party": None}, "azp"),
])
def test_a_bad_token_is_refused(options, reason):
    assert refusal(token("user_alice", **options)) == reason


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "é.é.é"])
def test_garbage_is_refused_not_a_crash(garbage):
    refusal(garbage)


def test_an_unreachable_key_server_is_a_503(monkeypatch):
    class Unreachable:
        def get_signing_key_from_jwt(self, token):
            raise jwt.exceptions.PyJWKClientConnectionError("no network")

    monkeypatch.setattr(identity, "_jwks_client", lambda url: Unreachable())
    with pytest.raises(ApiError) as caught:
        identity.verify_token(token("user_alice"))
    assert (caught.value.status, caught.value.code) == (503, "identity_provider_unavailable")


def clerk_answers(monkeypatch, status, body=None):
    """Make Clerk's Backend API answer every GET with this status and JSON body."""
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_not_a_real_key")
    monkeypatch.setattr(httpx, "get", lambda url, **options:
                        httpx.Response(status, json=body, request=httpx.Request("GET", url)))


def test_the_profile_is_the_primary_email_and_its_own_verification(monkeypatch):
    clerk_answers(monkeypatch, 200, {
        "primary_email_address_id": "idn_2", "first_name": "Mei", "last_name": None,
        "email_addresses": [
            {"id": "idn_1", "email_address": "old@example.com", "verification": {"status": "verified"}},
            {"id": "idn_2", "email_address": "Mei.Zhou@Example.com", "verification": {"status": "unverified"}},
        ],
    })
    assert clerk_fetch_profile("user_mei") == Profile("Mei.Zhou@Example.com", False, "Mei")


def test_a_provider_error_is_a_503(monkeypatch):
    clerk_answers(monkeypatch, 500)
    with pytest.raises(ApiError) as caught:
        clerk_fetch_profile("user_mei")
    assert (caught.value.status, caught.value.code) == (503, "identity_provider_unavailable")

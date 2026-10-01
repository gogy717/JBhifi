"""Token checks (app/identity.py): only a current token, signed by the provider for one of our sites."""
import jwt
import pytest

from app import identity
from app.errors import ApiError
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

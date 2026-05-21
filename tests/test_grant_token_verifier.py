from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from plural_mpp_seller.server.grant_token_verifier import GrantTokenVerifier
from plural_mpp_seller.types.grantex import SellerGrantexConfig


class _StaticKeyGrantTokenVerifier(GrantTokenVerifier):
    def __init__(self, public_key) -> None:
        super().__init__(
            SellerGrantexConfig(
                jwksUrl="https://issuer.example.test/.well-known/jwks.json",
                requiredScopes=["ride:book"],
            )
        )
        self._public_key = public_key

    def _get_signing_key(self, kid):
        del kid
        return self._public_key


@pytest.fixture()
def rsa_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _grant_claims(**overrides):
    now = int(time.time())
    claims = {
        "iss": "https://issuer.example.test",
        "sub": "user-1",
        "agt": "agent-1",
        "scp": ["ride:book"],
        "grnt": "grant-1",
        "iat": now - 10,
        "nbf": now - 5,
        "exp": now + 60,
    }
    claims.update(overrides)
    return claims


def test_grant_token_verifier_rejects_expired_tokens_with_pyjwt_validation(rsa_key_pair) -> None:
    private_key, public_key = rsa_key_pair
    token = jwt.encode(
        _grant_claims(exp=int(time.time()) - 1),
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    result = _StaticKeyGrantTokenVerifier(public_key).verify(token)

    assert result.valid is False
    assert "expired" in (result.error or "").lower()


def test_grant_token_verifier_rejects_not_before_tokens_with_pyjwt_validation(rsa_key_pair) -> None:
    private_key, public_key = rsa_key_pair
    token = jwt.encode(
        _grant_claims(nbf=int(time.time()) + 60),
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    result = _StaticKeyGrantTokenVerifier(public_key).verify(token)

    assert result.valid is False
    assert "not yet valid" in (result.error or "").lower()


def test_grant_token_verifier_does_not_disable_pyjwt_time_claim_validation(monkeypatch) -> None:
    captured_options = {}

    monkeypatch.setattr(jwt, "get_unverified_header", lambda token: {"alg": "RS256", "kid": "test-key"})

    def _fake_decode(token, key, *, algorithms, options):
        del token, key, algorithms
        captured_options.update(options or {})
        raise jwt.ExpiredSignatureError("Signature has expired")

    monkeypatch.setattr(jwt, "decode", _fake_decode)

    result = _StaticKeyGrantTokenVerifier(public_key=object()).verify("header.payload.signature")

    assert result.valid is False
    assert captured_options.get("verify_exp") is not False
    assert captured_options.get("verify_nbf") is not False

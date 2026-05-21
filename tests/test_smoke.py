"""Seller SDK tests — covered transitively by the buyer SDK's e2e test."""
from types import SimpleNamespace

from plural_mpp_seller import (
    Amount,
    ChargeOptions,
    MppEnvironment,
    MppCaptureError,
    MppError,
    PluralMPP,
    PluralSellerConfig,
    decide_payment,
)
from plural_mpp_seller.server.credential_verifier import CredentialVerifier


def _config() -> PluralSellerConfig:
    return PluralSellerConfig(
        clientId="seller-id",
        clientSecret="seller-secret",
        challengeSecretKey="shared-hmac-secret-please-change",
        realm=MppEnvironment.SANDBOX,
        baseUrl=MppEnvironment.SANDBOX,
    )


def test_challenge_generator_produces_stable_id() -> None:
    mpp = PluralMPP.create(_config())
    a = mpp.generate_challenge(
        ChargeOptions(amount=Amount(value=10000, currency="INR"), resource="/api/x")
    )
    assert a.challenge.id.startswith("ch_")
    assert a.challenge.realm == MppEnvironment.SANDBOX
    assert a.challenge.request.amount == "100.00"
    assert a.problemDetails.status == 402


def test_credential_verifier_rejects_missing_header() -> None:
    verifier = CredentialVerifier(_config())
    result = verifier.verify(None)
    assert result.valid is False
    assert "Authorization" in (result.error or "")


def test_decide_payment_propagates_upstream_capture_failures(monkeypatch) -> None:
    def _fake_verify(self, authorization_header):
        del authorization_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(token="ppt_test"),
                challenge=SimpleNamespace(id="ch_test"),
            ),
        )

    def _fake_capture(self, options):
        del options
        raise MppCaptureError(
            "Capture failed: Unknown error",
            MppError(
                "INTERNAL_ERROR",
                "Unknown error",
                500,
                {"reason": "SOMETHING_WENT_WRONG"},
            ),
        )

    monkeypatch.setattr(
        "plural_mpp_seller.server.middleware.generic.CredentialVerifier.verify",
        _fake_verify,
    )
    monkeypatch.setattr(
        "plural_mpp_seller.server.middleware.generic.CaptureClient.capture",
        _fake_capture,
    )

    decision = decide_payment(
        authorization_header="Payment dummy-credential",
        grantex_token_header=None,
        config=_config(),
        charge_options=ChargeOptions(
            amount=Amount(value=100, currency="INR"),
            resource="/rides/confirm",
        ),
    )

    assert decision.action == "error"
    assert decision.status == 502
    assert decision.problem_details == {
        "type": "urn:plural:error:payment-capture-failed",
        "title": "Payment Capture Failed",
        "status": 502,
        "detail": "Capture failed: Unknown error",
        "upstream": {
            "code": "INTERNAL_ERROR",
            "http_status": 500,
            "details": {"reason": "SOMETHING_WENT_WRONG"},
        },
    }

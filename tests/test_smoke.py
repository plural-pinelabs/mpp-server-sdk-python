"""Server SDK tests — covered transitively by the client SDK's e2e test."""
from dataclasses import asdict
from types import SimpleNamespace

from pinelabs_p3p_server import (
    Amount,
    ChargeOptions,
    P3PEnvironment,
    P3PCaptureError,
    P3PError,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineP3P,
    PineLabsOnlineServerConfig,
    decide_payment,
)
from pinelabs_p3p_server.server.credential_verifier import CredentialVerifier
from pinelabs_p3p_server.utils.base64url import decode_json, encode_json
from pinelabs_p3p_server.utils.hmac_sig import CHALLENGE_HMAC_KEY_PREFIX, derive_challenge_hmac_key


def _config() -> PineLabsOnlineServerConfig:
    return PineLabsOnlineServerConfig(
        clientId="server-id",
        clientSecret="server-secret",
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
        realm=P3PEnvironment.SANDBOX,
        env=P3PEnvironment.SANDBOX,
    )


def test_challenge_generator_produces_stable_id() -> None:
    mpp = PineLabsOnlineP3P.create(_config())
    a = mpp.generate_challenge(
        ChargeOptions(amount=Amount(value=10000, currency="INR"), resource="/api/x")
    )
    assert a.challenge.id.startswith("ch_")
    assert a.challenge.realm == P3PEnvironment.SANDBOX
    assert a.challenge.paymentGateway is None
    assert a.challenge.request.amount == "100.00"
    assert a.challenge.request.availablePaymentMethods == [PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto]
    assert a.problemDetails.status == 402


def test_server_derives_challenge_hmac_key_from_client_secret() -> None:
    assert CHALLENGE_HMAC_KEY_PREFIX == "p3p-challenge-v1:"
    assert derive_challenge_hmac_key("server-secret") == "p3p-challenge-v1:server-secret"

    server = PineLabsOnlineP3P.create(_config())
    challenge = server.generate_challenge(
        ChargeOptions(amount=Amount(value=10000, currency="INR"), resource="/api/x")
    ).challenge
    credential = {
        "challenge": asdict(challenge),
        "source": "client-client",
        "payload": {
            "type": "token",
            "token": "MPP_TOK_test",
            "payment_method": "RESERVE_PAY",
        },
    }

    valid = server.verify_credential(f"Payment {encode_json(credential)}")
    invalid = PineLabsOnlineP3P.create(
        PineLabsOnlineServerConfig(
            clientId="server-id",
            clientSecret="different-server-secret",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
            realm=P3PEnvironment.SANDBOX,
            env=P3PEnvironment.SANDBOX,
        )
    ).verify_credential(f"Payment {encode_json(credential)}")

    assert valid.valid is True
    assert invalid.valid is False
    assert "HMAC verification failed" in (invalid.error or "")


def test_credential_verifier_rejects_missing_header() -> None:
    verifier = CredentialVerifier(_config())
    result = verifier.verify(None)
    assert result.valid is False
    assert "P3P-Credential" in (result.error or "")


def test_decide_payment_propagates_upstream_capture_failures(monkeypatch) -> None:
    def _fake_verify(self, authorization_header):
        del authorization_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(token="ppt_test", payment_method=PaymentMethod.UPI_RESERVE_PAY),
                challenge=SimpleNamespace(id="ch_test"),
            ),
        )

    def _fake_capture(self, options):
        del options
        raise P3PCaptureError(
            "Capture failed: Unknown error",
            P3PError(
                "INTERNAL_ERROR",
                "Unknown error",
                500,
                {"reason": "SOMETHING_WENT_WRONG"},
            ),
        )

    monkeypatch.setattr(
        "pinelabs_p3p_server.server.middleware.generic.CredentialVerifier.verify",
        _fake_verify,
    )
    monkeypatch.setattr(
        "pinelabs_p3p_server.server.middleware.generic.CaptureClient.capture",
        _fake_capture,
    )

    decision = decide_payment(
            credential_header="Payment dummy-credential",
        config=_config(),
        charge_options=ChargeOptions(
            amount=Amount(value=100, currency="INR"),
            resource="/rides/confirm",
        ),
    )

    assert decision.action == "error"
    assert decision.status == 502
    assert decision.problem_details == {
        "type": "urn:pinelabs:error:payment-capture-failed",
        "title": "Payment Capture Failed",
        "status": 502,
        "detail": "Capture failed: Unknown error",
        "upstream": {
            "code": "INTERNAL_ERROR",
            "http_status": 500,
            "details": {"reason": "SOMETHING_WENT_WRONG"},
        },
    }


def test_decide_payment_receipt_includes_gateway_and_payment_method(monkeypatch) -> None:
    def _fake_verify(self, authorization_header):
        del authorization_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                        token="ppt_test",
                        payment_method=PaymentMethod.Crypto,
                        customer_reference="cust-ref-1",
                        mobile_number="9876543210",
                    ),
                challenge=SimpleNamespace(id="ch_test"),
            ),
        )

    def _fake_capture(self, options):
        assert options.challengeId == "ch_test"
        return SimpleNamespace(
            capture_id="cap_test",
            order_id="ord_test",
            merchant_order_reference=options.merchantOrderReference,
            amount=options.amount,
            settled_at="2030-01-01T00:00:00Z",
        )

    monkeypatch.setattr(
        "pinelabs_p3p_server.server.middleware.generic.CredentialVerifier.verify",
        _fake_verify,
    )
    monkeypatch.setattr(
        "pinelabs_p3p_server.server.middleware.generic.CaptureClient.capture",
        _fake_capture,
    )

    decision = decide_payment(
            credential_header="Payment dummy-credential",
        config=_config(),
        charge_options=ChargeOptions(
            amount=Amount(value=100, currency="INR"),
            resource="/rides/confirm",
        ),
    )

    receipt = decode_json(decision.receipt_header[len("Payment "):])
    assert "method" not in receipt
    assert receipt["paymentGateway"] == "PINE LABS ONLINE"
    assert receipt["paymentMethod"] == "CRYPTO"


def test_credential_verifier_rejects_payment_method_outside_signed_challenge() -> None:
    config = PineLabsOnlineServerConfig(
        clientId="server-id",
        clientSecret="server-secret",
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY],
        realm=P3PEnvironment.SANDBOX,
        env=P3PEnvironment.SANDBOX,
    )
    server = PineLabsOnlineP3P.create(config)
    challenge = server.generate_challenge(
        ChargeOptions(amount=Amount(value=10000, currency="INR"), resource="/api/x")
    ).challenge

    credential = {
        "challenge": asdict(challenge),
        "source": "client-client",
        "payload": {
            "type": "token",
            "token": "MPP_TOK_test",
            "payment_method": "CRYPTO",
        },
    }
    result = server.verify_credential(f"Payment {encode_json(credential)}")

    assert result.valid is False
    assert "Selected payment method CRYPTO is not accepted" in (result.error or "")

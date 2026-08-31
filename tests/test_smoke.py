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
        merchantId="merchant-test",
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
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
    assert a.challenge.request.availablePaymentMethods == [PaymentMethod.RESERVE_PAY, PaymentMethod.OTM]
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
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
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


def test_payment_method_exposes_reserve_pay_member() -> None:
    assert PaymentMethod.RESERVE_PAY.value == "RESERVE_PAY"
    assert PaymentMethod.OTM.value == "OTM"
    assert not hasattr(PaymentMethod, "UPI_RESERVE_PAY")


def test_server_verifies_otm_payment_method_when_advertised() -> None:
    server = PineLabsOnlineP3P.create(
        PineLabsOnlineServerConfig(
            clientId="server-id",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.OTM],
            realm=P3PEnvironment.SANDBOX,
            env=P3PEnvironment.SANDBOX,
        )
    )
    challenge = server.generate_challenge(
        ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/otm")
    ).challenge
    credential = {
        "challenge": asdict(challenge),
        "source": "client-client",
        "payload": {
            "type": "token",
            "token": "MPP_TOK_OTM",
            "payment_method": "OTM",
        },
    }

    result = server.verify_credential(f"Payment {encode_json(credential)}")

    assert challenge.request.availablePaymentMethods == [PaymentMethod.OTM]
    assert result.valid is True
    assert result.credential.payload.payment_method == PaymentMethod.OTM


def test_decide_payment_propagates_upstream_capture_failures(monkeypatch) -> None:
    def _fake_verify(self, authorization_header):
        del authorization_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(token="ppt_test", payment_method=PaymentMethod.RESERVE_PAY),
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
    assert decision.headers == {"Content-Type": "application/json"}
    assert decision.problem_details == {
        "code": "INTERNAL_ERROR",
        "message": "Unknown error",
    }
    assert decision.headers.get("WWW-Authenticate") is None
    assert decision.challenge_result is None


def test_decide_payment_returns_upstream_capture_failure_without_new_challenge(monkeypatch) -> None:
    def _fake_verify(self, authorization_header):
        del authorization_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                    token="ppt_test",
                    payment_method=PaymentMethod.RESERVE_PAY,
                    customer_reference="cust-ref-123",
                    mobile_number="9876543210",
                ),
                challenge=SimpleNamespace(id="ch_test"),
            ),
        )

    def _fake_capture(self, options):
        del options
        raise P3PCaptureError(
            "Capture failed: Debit failed with reason: null",
            P3PError("PAYMENT_FAILED", "Debit failed with reason: null", 422),
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

    assert decision.action == "failed"
    assert decision.status == 422
    assert decision.headers == {"Content-Type": "application/json"}
    assert decision.problem_details == {
        "code": "PAYMENT_FAILED",
        "message": "Debit failed with reason: null",
    }
    assert decision.headers.get("WWW-Authenticate") is None
    assert decision.challenge_result is None


def test_decide_payment_returns_gateway_error_for_capture_exceptions(monkeypatch) -> None:
    def _fake_verify(self, authorization_header):
        del authorization_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                    token="ppt_test",
                    payment_method=PaymentMethod.RESERVE_PAY,
                    customer_reference="cust-ref-123",
                    mobile_number="9876543210",
                ),
                challenge=SimpleNamespace(id="ch_test"),
            ),
        )

    def _fake_capture(self, options):
        del options
        raise RuntimeError("network unavailable")

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
    assert decision.headers == {"Content-Type": "application/json"}
    assert decision.problem_details == {
        "code": "CAPTURE_FAILED",
        "message": "Capture failed",
    }
    assert decision.headers.get("WWW-Authenticate") is None
    assert decision.challenge_result is None


def test_decide_payment_receipt_includes_gateway_and_payment_method(monkeypatch) -> None:
    def _fake_verify(self, authorization_header):
        del authorization_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                        token="ppt_test",
                        payment_method=PaymentMethod.OTM,
                        payment_method_reference_id="auth_123",
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
    assert receipt["paymentMethod"] == "OTM"


def test_credential_verifier_rejects_payment_method_outside_signed_challenge() -> None:
    config = PineLabsOnlineServerConfig(
        clientId="server-id",
        clientSecret="server-secret",
        merchantId="merchant-test",
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.RESERVE_PAY],
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

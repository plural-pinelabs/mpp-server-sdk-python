from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from pinelabs_p3p_server import (
    Amount,
    CaptureOptions,
    ChargeOptions,
    CreateMandateOptions,
    P3PEnvironment,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineP3P,
    PineLabsOnlineServerConfig,
    decide_payment,
)
from pinelabs_p3p_server.server.receipt_builder import build_receipt_header
from pinelabs_p3p_server.types.capture import CaptureResult
from pinelabs_p3p_server.utils.base64url import decode_json, encode_json


class _ServerTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/auth/v1/token":
            return httpx.Response(200, json={"data": {"access_token": "server-token", "expires_in": 300}})
        if request.url.path == "/mpp/v1/pre-authorize":
            body = json.loads(request.content.decode() or "{}")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_method": body["payment_method"],
                        "payment_method_reference_id": "auth_123",
                        "customer": body["customer"],
                        "status": "INITIATED",
                        "amount": body["amount"],
                        "challenge_url": "upi://mandate?id=auth_123",
                    }
                },
            )
        if request.url.path == "/mpp/v1/debit":
            body = json.loads(request.content.decode() or "{}")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_method": body["payment_method"],
                        "payment_method_reference_id": "auth_123",
                        "payment_id": "pay_123",
                        "merchant_payment_debit_reference": request.headers.get("Idempotency-Key"),
                        "amount": body["payment_amount"],
                        "status": "SUCCESS",
                        "payment_data": {"order_id": "ord_123", "order_status": "COMPLETED"},
                    }
                },
            )
        if request.url.path == "/mpp/v1/debit/order-123":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_method": "RESERVE_PAY",
                        "payment_method_reference_id": "auth_123",
                        "payment_id": "pay_123",
                        "merchant_payment_debit_reference": "order-123",
                        "amount": {"value": 100, "currency": "INR"},
                        "status": "PROCESSED",
                        "payment_data": {"order_id": "ord_123", "order_status": "COMPLETED"},
                    }
                },
            )
        return httpx.Response(404)


def _config() -> PineLabsOnlineServerConfig:
    return PineLabsOnlineServerConfig(
        clientId="server-client",
        clientSecret="server-secret",
        env=P3PEnvironment.SANDBOX,
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
        realm="Pine Labs Online P3P",
        maxRetries=0,
    )


def test_server_create_mandate_and_capture_use_env_and_mobile_number(monkeypatch) -> None:
    transport = _ServerTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(_config())

    mandate = server.create_mandate(
        CreateMandateOptions(
            mobileNumber="9876543210",
            customerReference="9876543210",
            amount=Amount(value=100000, currency="INR"),
            paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
        )
    )
    capture = server.capture(
        CaptureOptions(
            token="tok_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            customerReference="9876543210",
            mobileNumber="9876543210",
            challengeId="ch_123",
            merchantOrderReference="order-123",
        )
    )

    assert mandate.mandate_id == "auth_123"
    assert capture.merchant_payment_debit_reference == "order-123"
    mandate_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/pre-authorize")
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    assert json.loads(mandate_request.content.decode() or "{}")["customer"] == {"mobile_number": "9876543210"}
    assert json.loads(debit_request.content.decode() or "{}")["customer"] == {"mobile_number": "9876543210"}


def test_server_get_debit_status_uses_env_and_returns_result(monkeypatch) -> None:
    transport = _ServerTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(_config())

    status = server.get_debit_status("order-123")

    assert status.status == "PROCESSED"
    assert status.merchant_payment_debit_reference == "order-123"
    assert status.idempotencyKey == "order-123"
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit/order-123")
    assert debit_request.method == "GET"


def test_decide_payment_reads_p3p_credential_header(monkeypatch) -> None:
    config = _config()
    server = PineLabsOnlineP3P.create(config)
    challenge = server.generate_challenge(
        ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke")
    ).challenge
    credential = {
        "challenge": {
            "id": challenge.id,
            "realm": challenge.realm,
            "paymentGateway": "PINE LABS ONLINE",
            "intent": challenge.intent,
            "request": {
                "scheme": challenge.request.scheme,
                "amount": challenge.request.amount,
                "currency": challenge.request.currency,
                "resource": challenge.request.resource,
                "availablePaymentMethods": ["RESERVE_PAY", "CRYPTO"],
            },
            "expires": challenge.expires,
        },
        "source": "9876543210",
        "payload": {
            "type": "token",
            "token": "tok_123",
            "customer_reference": "9876543210",
            "mobile_number": "9876543210",
            "payment_method": "RESERVE_PAY",
        },
    }

    def _capture(self, options):
        assert options.mobileNumber == "9876543210"
        return CaptureResult(
            capture_id="cap_123",
            order_id="ord_123",
            merchant_order_reference=options.merchantOrderReference,
            amount=options.amount,
            settled_at="2030-01-01T00:00:00Z",
            payment_gateway=PaymentGateway.PineLabsOnline,
            payment_method=PaymentMethod.UPI_RESERVE_PAY,
        )

    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CaptureClient.capture", _capture)
    decision = decide_payment(
        credential_header=f"Payment {encode_json(credential)}",
        config=config,
        charge_options=ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke"),
    )

    assert decision.action == "proceed"
    assert decision.headers["Payment-Receipt"].startswith("Payment ")
    decoded = decode_json(decision.headers["Payment-Receipt"][len("Payment "):])
    assert decoded["paymentMethod"] == "RESERVE_PAY"


def test_decide_payment_returns_202_when_capture_remains_pending(monkeypatch) -> None:
    def _verify(self, credential_header):
        del credential_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                    token="tok_123",
                    payment_method=PaymentMethod.UPI_RESERVE_PAY,
                    customer_reference="9876543210",
                    mobile_number="9876543210",
                ),
                challenge=SimpleNamespace(id="ch_pending"),
            ),
        )

    def _capture(self, options):
        assert options.challengeId == "ch_pending"
        return CaptureResult(
            merchant_payment_debit_reference="order-123",
            status="PROCESSING",
            idempotencyKey="idem_key_20260601_001",
            retryAfter=321,
        )

    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CredentialVerifier.verify", _verify)
    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CaptureClient.capture", _capture)

    decision = decide_payment(
        credential_header="Payment dummy-credential",
        config=_config(),
        charge_options=ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke"),
    )

    assert decision.action == "pending"
    assert decision.status == 202
    assert decision.headers == {"Content-Type": "application/json"}
    assert decision.problem_details == {
        "status": "PENDING",
        "idempotencyKey": "idem_key_20260601_001",
        "message": "Payment accepted and still processing",
        "debitStatus": "PROCESSING",
        "retryAfter": 321,
    }


def test_server_surface_has_no_mpp_aliases() -> None:
    import pinelabs_p3p_server as server

    assert hasattr(server, "PineLabsOnlineP3P")
    assert hasattr(server, "PineLabsOnlineP3PInstance")
    assert hasattr(server, "P3PEnvironment")
    assert not hasattr(server, "MppEnvironment")


def test_build_receipt_header_falls_back_to_raw_debit_fields() -> None:
    import time

    before = time.time()
    header = build_receipt_header(
        CaptureResult(
            amount={"value": 300, "currency": "INR"},
            settled_at="",
            created_at="2030-01-02T00:00:00Z",
            payment_gateway=PaymentGateway.PineLabsOnline,
            payment_method=PaymentMethod.UPI_RESERVE_PAY,
            merchant_payment_debit_reference="debit-ref-123",
            payment_data={"order_id": "ord_raw_123", "order_status": "PROCESSED"},
            status="PROCESSED",
        ),
        "ch_raw_123",
    )
    after = time.time()

    decoded = decode_json(header[len("Payment "):])
    assert decoded["reference"] == "debit-ref-123"
    assert decoded["orderId"] is None
    assert decoded["merchantOrderReference"] == "debit-ref-123"
    assert isinstance(decoded["timestamp"], str)
    parsed = decoded["timestamp"].replace("Z", "+00:00")
    ts = __import__("datetime").datetime.fromisoformat(parsed).timestamp()
    assert before - 1 <= ts <= after + 1
    assert decoded["settlement"] == {"amount": "3.00", "currency": "INR"}

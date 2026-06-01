from __future__ import annotations

import json

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
from pinelabs_p3p_server.utils.base64url import encode_json


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
    assert capture.merchant_order_reference == "order-123"
    mandate_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/pre-authorize")
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    assert json.loads(mandate_request.content.decode() or "{}")["customer"] == {"mobile_number": "9876543210"}
    assert json.loads(debit_request.content.decode() or "{}")["customer"] == {"mobile_number": "9876543210"}


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
                "availablePaymentMethods": ["SBMD", "CRYPTO"],
            },
            "expires": challenge.expires,
        },
        "source": "9876543210",
        "payload": {
            "type": "token",
            "token": "tok_123",
            "customer_reference": "9876543210",
            "mobile_number": "9876543210",
            "payment_method": "SBMD",
        },
    }

    def _capture(self, options):
        assert options.mobileNumber == "9876543210"
        return type(
            "CaptureResult",
            (),
            {
                "capture_id": "cap_123",
                "order_id": "ord_123",
                "merchant_order_reference": options.merchantOrderReference,
                "amount": options.amount,
                "settled_at": "2030-01-01T00:00:00Z",
                "payment_gateway": PaymentGateway.PineLabsOnline,
                "payment_method": PaymentMethod.UPI_RESERVE_PAY,
            },
        )()

    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CaptureClient.capture", _capture)
    decision = decide_payment(
        credential_header=f"Payment {encode_json(credential)}",
        config=config,
        charge_options=ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke"),
    )

    assert decision.action == "proceed"
    assert decision.headers["Payment-Receipt"].startswith("Payment ")


def test_server_surface_has_no_mpp_aliases() -> None:
    import pinelabs_p3p_server as server

    assert hasattr(server, "PineLabsOnlineP3P")
    assert not hasattr(server, "PineLabsOnlineP3P")
    assert hasattr(server, "P3PEnvironment")
    assert not hasattr(server, "MppEnvironment")

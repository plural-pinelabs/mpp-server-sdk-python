from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from pinelabs_p3p_server import (
    Amount,
    CaptureOptions,
    ChargeOptions,
    CreateMandateOptions,
    CreateMandateRevokeOptions,
    CreatePreAuthorizationOptions,
    GRANTEX_TOKEN_HEADER,
    GrantexAuthorizationOptions,
    GrantexBudgetAllocationOptions,
    GrantexBudgetDebitOptions,
    GrantexExchangeCodeOptions,
    GrantexVerificationResult,
    HostedGrantexConfig,
    MandateBalanceLookupOptions,
    P3PEnvironment,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineP3P,
    PineLabsOnlineServerConfig,
    ServerGrantexConfig,
    create_hosted_grantex_client,
    decide_payment,
)
from pinelabs_p3p_server.server.receipt_builder import build_receipt_header
from pinelabs_p3p_server.types.capture import CaptureResult
from pinelabs_p3p_server.utils.base64url import decode_json, encode_json

SERVER_ROOT = Path(__file__).resolve().parents[1]


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
        if request.url.path == "/mpp/v1/balance":
            params = dict(request.url.params)
            if params.get("authorization_id") == "auth_123":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "payment_method": "RESERVE_PAY",
                            "payment_method_reference_id": "auth_123",
                            "merchant_id": "MERCHANT_123",
                            "customer": {
                                "mobile_number": "9876543210",
                                "merchant_customer_reference": "cust_123",
                                "bank_account_number": "XXXX1234",
                            },
                            "status": "ACTIVE",
                            "amount": {"value": 50000, "currency": "INR"},
                            "description": "Subscription mandate",
                            "validity_in_days": 365,
                            "expiry_at": "2027-06-05T10:30:00Z",
                            "challenge_url": "upi://mandate?id=auth_123",
                            "external_reference_id": "ext_123",
                            "created_at": "2026-06-05T10:30:00Z",
                            "balance_details": {
                                "amount_debited": {"value": 10000, "currency": "INR"},
                                "amount_remaining": {"value": 40000, "currency": "INR"},
                            },
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_method": params.get("type", "RESERVE_PAY"),
                        "payment_method_reference_id": f"auth_{str(params.get('type', 'RESERVE_PAY')).lower()}_123",
                        "merchant_id": "MERCHANT_123",
                        "customer": {"mobile_number": "9876543210"},
                        "status": "PENDING",
                        "created_at": "2026-06-05T10:30:00Z",
                    }
                },
            )
        if request.url.path == "/mpp/v1/revoke":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "payment_method": "RESERVE_PAY",
                        "payment_method_reference_id": "auth_123",
                        "revoke_reference_id": "rvk_123",
                        "status": "CREATED",
                    }
                },
            )
        return httpx.Response(404)


class _GrantVerifier:
    def __init__(self, result: GrantexVerificationResult) -> None:
        self.result = result
        self.tokens: list[str] = []

    def verify(self, token: str) -> GrantexVerificationResult:
        self.tokens.append(token)
        return self.result


def _config() -> PineLabsOnlineServerConfig:
    return PineLabsOnlineServerConfig(
        clientId="server-client",
        clientSecret="server-secret",
        merchantId="merchant-test",
        env=P3PEnvironment.SANDBOX,
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
        realm="Pine Labs Online P3P",
        maxRetries=0,
    )


def test_server_config_requires_merchant_id_before_network() -> None:
    with pytest.raises(ValueError, match="merchantId is required"):
        PineLabsOnlineP3P.create(
            PineLabsOnlineServerConfig(
                clientId="server-client",
                clientSecret="server-secret",
                merchantId="",
                env=P3PEnvironment.SANDBOX,
                paymentGateway=PaymentGateway.PineLabsOnline,
                availablePaymentMethods=[
                    PaymentMethod.RESERVE_PAY,
                    PaymentMethod.OTM,
                    PaymentMethod.CARD,
                    PaymentMethod.CREDIT_EMI,
                ],
            )
        )


def test_server_create_mandate_and_capture_use_env_and_mobile_number(monkeypatch) -> None:
    transport = _ServerTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(_config())
    selected_offer_data = {
        "entities": [
            {
                "entity_id": "6",
                "tenures": [{"tenure_id": "7", "offers": [{"emi_type": "STANDARD"}]}],
            }
        ],
        "timezone": "Asia/Kolkata",
    }

    mandate = server.create_mandate(
        CreateMandateOptions(
            mobileNumber="9876543210",
            customerReference="9876543210",
            amount=Amount(value=100000, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
            paymentMethodOptions={
                "bank_account_number": "1234567890",
                "account_holder_name": "Test Customer",
            },
            merchantMetadata={"offer_data": selected_offer_data},
        )
    )
    capture = server.capture(
        CaptureOptions(
            token="tok_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
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
    assert mandate_request.headers["Merchant-ID"] == "merchant-test"
    assert debit_request.headers["Merchant-ID"] == "merchant-test"
    mandate_body = json.loads(mandate_request.content.decode() or "{}")
    assert mandate_body["customer"] == {"mobile_number": "9876543210"}
    assert mandate_body["payment_method_options"] == {
        "bank_account_number": "1234567890",
        "account_holder_name": "Test Customer",
    }
    assert json.loads(mandate_body["merchant_metadata"]["offer_data"]) == selected_offer_data
    assert json.loads(debit_request.content.decode() or "{}")["customer"] == {"mobile_number": "9876543210"}


def test_server_create_credit_emi_pre_authorization_preserves_payment_method_on_wire(monkeypatch) -> None:
    selected_offer_data = {
        "entities": [
            {
                "entity_id": "6",
                "tenures": [{"tenure_id": "7", "offers": [{"emi_type": "STANDARD"}]}],
            }
        ]
    }

    class _CreditEmiPreAuthTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.requests: list[httpx.Request] = []

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.path == "/api/auth/v1/token":
                return httpx.Response(200, json={"data": {"access_token": "server-token", "expires_in": 300}})
            if request.url.path == "/mpp/v1/pre-authorize":
                body = json.loads(request.content.decode() or "{}")
                assert request.headers["Authorization"] == "Bearer server-token"
                assert request.headers["Idempotency-Key"] == "preauth-key-123"
                assert body == {
                    "payment_method": "CREDIT_EMI",
                    "customer": {"mobile_number": "9876543210"},
                    "amount": {"value": 1000, "currency": "INR"},
                    "validity_in_days": 7,
                    "description": "Postman E2E test",
                    "merchant_metadata": {
                        "offer_data": json.dumps(selected_offer_data, separators=(",", ":")),
                        "p3p_offer_required": "true",
                    },
                }
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "payment_method": "CREDIT_EMI",
                            "customer": {
                                "customer_id": "cust-v1-260602201109-aa-hotwA8",
                                "merchant_customer_reference": "98f20ed3-7efc-40c1-9db6-427a4b65261d",
                                "mobile_number": "9876543210",
                            },
                            "order_id": "v1-260630132707-aa-XRPK0Q",
                            "redirect_url": "https://pluraluat.v2.pinepg.in/api/v3/checkout-bff/redirect/checkout?token=V3_test",
                            "status": "PENDING",
                            "amount": {"value": 1000, "currency": "INR"},
                            "validity_in_days": 7,
                            "expiry_at": "2026-07-07T13:27:07.837993Z",
                        }
                    },
                )
            return httpx.Response(404)

    transport = _CreditEmiPreAuthTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            env=P3PEnvironment.SANDBOX,
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.CREDIT_EMI],
            realm="Pine Labs Online P3P",
            maxRetries=0,
        )
    )

    pre_authorization = server.create_pre_authorization(
        CreatePreAuthorizationOptions(
            paymentMethod=PaymentMethod.CREDIT_EMI,
            mobileNumber="9876543210",
            amount=Amount(value=1000, currency="INR"),
            validityInDays=7,
            description="Postman E2E test",
            idempotencyKey="preauth-key-123",
            merchantMetadata={
                "offer_data": selected_offer_data,
                "p3p_offer_required": "true",
            },
        )
    )

    assert pre_authorization.payment_method == PaymentMethod.CREDIT_EMI
    assert pre_authorization.payment_method_reference_id == "v1-260630132707-aa-XRPK0Q"
    assert pre_authorization.customer.customer_id == "cust-v1-260602201109-aa-hotwA8"
    assert pre_authorization.customer.mobile_number == "9876543210"
    assert pre_authorization.challenge_url == "https://pluraluat.v2.pinepg.in/api/v3/checkout-bff/redirect/checkout?token=V3_test"
    assert pre_authorization.redirect_url == "https://pluraluat.v2.pinepg.in/api/v3/checkout-bff/redirect/checkout?token=V3_test"
    assert pre_authorization.status == "PENDING"
    assert pre_authorization.amount == Amount(value=1000, currency="INR")
    assert pre_authorization.validity_in_days == 7
    assert pre_authorization.expiry_at == "2026-07-07T13:27:07.837993Z"
    request = next(req for req in transport.requests if req.url.path == "/mpp/v1/pre-authorize")
    assert request.headers["Merchant-ID"] == "merchant-test"
    assert [request.url.path for request in transport.requests] == ["/api/auth/v1/token", "/mpp/v1/pre-authorize"]


def test_server_create_card_pre_authorization_builds_redirect_url_from_env(monkeypatch) -> None:
    real_client = httpx.Client
    cases = [
        (
            P3PEnvironment.SANDBOX,
            "V3_M5HqetW6Q4UACVb64QZjaV4t8ntf5Qef",
            "https://pluraluat.v2.pinepg.in/api/v3/checkout-bff/redirect/checkout?token=V3_M5HqetW6Q4UACVb64QZjaV4t8ntf5Qef",
        ),
        (
            P3PEnvironment.PRODUCTION,
            "V3_Uq4iDSRBSbuWRub9%2BfVUgAV5d0CvedJPswx9YbRG1",
            "https://api.pluralpay.in/api/v3/checkout-bff/redirect/checkout?token=V3_Uq4iDSRBSbuWRub9%2BfVUgAV5d0CvedJPswx9YbRG1",
        ),
    ]

    for env, token, expected_url in cases:
        class _CardTokenOnlyTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                if request.url.path == "/api/auth/v1/token":
                    return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 3600}})
                if request.url.path == "/mpp/v1/pre-authorize":
                    return httpx.Response(
                        200,
                        json={
                            "data": {
                                "payment_method": "CARD",
                                "token": token,
                                "order_id": "v1-260706093744-aa-XRPK0Q",
                                "response_code": 200,
                                "response_message": "Order Creation Successful.",
                                "customer": {"mobile_number": "9876543210"},
                                "amount": {"value": 1000, "currency": "INR"},
                                "status": "PENDING",
                            }
                        },
                    )
                return httpx.Response(404)
        def _client(*args, **kwargs):
            kwargs["transport"] = _CardTokenOnlyTransport()
            return real_client(*args, **kwargs)

        monkeypatch.setattr("httpx.Client", _client)
        server = PineLabsOnlineP3P.create(
            PineLabsOnlineServerConfig(
                clientId="server-client",
                clientSecret="server-secret",
                merchantId="merchant-test",
                env=env,
                paymentGateway=PaymentGateway.PineLabsOnline,
                availablePaymentMethods=[PaymentMethod.CARD],
                realm="Pine Labs Online P3P",
                maxRetries=0,
            )
        )

        pre_authorization = server.create_pre_authorization(
            CreatePreAuthorizationOptions(
                paymentMethod=PaymentMethod.CARD,
                mobileNumber="9876543210",
                amount=Amount(value=1000, currency="INR"),
            )
        )

        assert pre_authorization.payment_method_reference_id == "v1-260706093744-aa-XRPK0Q"
        assert pre_authorization.redirect_url == expected_url
        assert pre_authorization.challenge_url == expected_url


def test_server_create_mandate_preserves_snake_case_payment_method_options(monkeypatch) -> None:
    transport = _ServerTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            env=P3PEnvironment.SANDBOX,
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.OTM],
            realm="Pine Labs Online P3P",
            maxRetries=0,
        )
    )

    mandate = server.create_mandate(
        CreateMandateOptions(
            mobileNumber="9876543210",
            amount=Amount(value=100000, currency="INR"),
            paymentMethod=PaymentMethod.OTM,
            payment_method_options={
                "mandate_type": "ON_DEMAND",
                "collect_by_date": "2026-06-07",
            },
        )
    )

    mandate_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/pre-authorize")
    assert mandate_request.headers["Merchant-ID"] == "merchant-test"
    mandate_body = json.loads(mandate_request.content.decode() or "{}")
    assert mandate.mandate_id == "auth_123"
    assert mandate_body["payment_method"] == "OTM"
    assert mandate_body["payment_method_options"] == {
        "mandate_type": "ON_DEMAND",
        "collect_by_date": "2026-06-07",
    }


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


def test_server_get_mandate_balance_and_revoke_use_server_api(monkeypatch) -> None:
    transport = _ServerTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(_config())

    balance = server.get_mandate_balance(
        MandateBalanceLookupOptions(
            authorizationId="auth_123",
            phoneNumber="9876543210",
            paymentMethod=PaymentMethod.RESERVE_PAY,
        )
    )
    revoke = server.revoke_mandate(
        CreateMandateRevokeOptions(
            paymentMethod=PaymentMethod.RESERVE_PAY,
            paymentMethodReferenceId="auth_123",
            customer={"mobileNumber": "9876543210"},
        )
    )

    assert balance.payment_method == PaymentMethod.RESERVE_PAY
    assert balance.balance_details.amount_remaining.value == 40000
    assert balance.raw["external_reference_id"] == "ext_123"
    assert revoke.revoke_reference_id == "rvk_123"
    balance_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/balance")
    revoke_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/revoke")
    assert balance_request.method == "GET"
    assert dict(balance_request.url.params) == {"authorization_id": "auth_123", "phone_number": "9876543210"}
    assert revoke_request.method == "POST"
    assert json.loads(revoke_request.content.decode() or "{}") == {
        "payment_method": "RESERVE_PAY",
        "payment_method_reference_id": "auth_123",
        "customer": {"mobile_number": "9876543210"},
    }


def test_server_get_mandate_balance_rejects_otm_before_network(monkeypatch) -> None:
    transport = _ServerTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(_config())

    with pytest.raises(ValueError, match="OTM is not supported for mandate balance lookup"):
        server.get_mandate_balance(
            MandateBalanceLookupOptions(
                authorizationId="auth_123",
                phoneNumber="9876543210",
                paymentMethod=PaymentMethod.OTM,
            )
        )
    assert not any(req.url.path == "/mpp/v1/balance" for req in transport.requests)


def test_server_balance_and_revoke_validation(monkeypatch) -> None:
    transport = _ServerTransport()
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", _client)
    server = PineLabsOnlineP3P.create(_config())

    with pytest.raises(ValueError, match="paymentMethod is required"):
        server.get_mandate_balance(MandateBalanceLookupOptions(phoneNumber="9876543210"))
    with pytest.raises(ValueError, match="PaymentMethod.Crypto is currently not supported in SDKs"):
        server.get_mandate_balance(
            MandateBalanceLookupOptions(
                phoneNumber="9876543210",
                paymentMethod=PaymentMethod.Crypto,
            )
        )
    with pytest.raises(ValueError, match="paymentMethodReferenceId or customer lookup is required"):
        server.revoke_mandate(CreateMandateRevokeOptions(paymentMethod=PaymentMethod.RESERVE_PAY))


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
                "availablePaymentMethods": ["RESERVE_PAY", "OTM"],
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
            payment_method=PaymentMethod.RESERVE_PAY,
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


def test_decide_payment_enforces_missing_grantex_grant_before_capture(monkeypatch) -> None:
    def _verify(self, credential_header):
        del credential_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                    token="tok_123",
                    payment_method=PaymentMethod.RESERVE_PAY,
                    mobile_number="9876543210",
                ),
                challenge=SimpleNamespace(id="ch_grant_required"),
            ),
        )

    def _capture(self, options):
        del options
        raise AssertionError("capture should not run without a required Grantex grant")

    config = _config()
    config.grantex = ServerGrantexConfig(
        jwksUri="https://auth.grantex.dev/.well-known/jwks.json",
        enforceGrant=True,
        hosted=HostedGrantexConfig(apiKey="gx_test"),
    )

    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CredentialVerifier.verify", _verify)
    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CaptureClient.capture", _capture)

    decision = decide_payment(
        credential_header="Payment dummy-credential",
        config=config,
        charge_options=ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke"),
    )

    assert GRANTEX_TOKEN_HEADER == "X-Grantex-Token"
    assert decision.action == "grant_required"
    assert decision.status == 403
    assert decision.grant_result is not None
    assert decision.grant_result.valid is False
    assert decision.problem_details["detail"].endswith(f"{GRANTEX_TOKEN_HEADER} header.")


def test_decide_payment_verifies_grantex_grant_before_capture(monkeypatch) -> None:
    budget_calls: list[object] = []

    def _verify(self, credential_header):
        del credential_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                    token="tok_123",
                    payment_method=PaymentMethod.RESERVE_PAY,
                    customer_reference="9876543210",
                    mobile_number="9876543210",
                ),
                challenge=SimpleNamespace(id="ch_grant_valid"),
            ),
        )

    def _capture(self, options):
        assert options.challengeId == "ch_grant_valid"
        return CaptureResult(
            capture_id="cap_123",
            order_id="ord_123",
            merchant_order_reference=options.merchantOrderReference,
            amount=options.amount,
            settled_at="2030-01-01T00:00:00Z",
            payment_gateway=PaymentGateway.PineLabsOnline,
            payment_method=PaymentMethod.RESERVE_PAY,
        )

    grant = SimpleNamespace(grant_id="grnt_123", agent_did="did:web:agent.example", scopes=["mpp:*"])
    verifier = _GrantVerifier(GrantexVerificationResult(valid=True, grant=grant))

    class _Budgets:
        def debit(self, body):
            budget_calls.append(body)
            return SimpleNamespace(grantId=body.grant_id, remaining=900, transactionId="txn_budget")

    config = _config()
    config.grantex = ServerGrantexConfig(
        agentId="did:web:agent.example",
        requiredScopes=["mpp:payment:capture"],
        enforceGrant=True,
        hosted=HostedGrantexConfig(apiKey="gx_test", client_factory=lambda: SimpleNamespace(budgets=_Budgets())),
        verifier=verifier,
    )

    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CredentialVerifier.verify", _verify)
    monkeypatch.setattr("pinelabs_p3p_server.server.middleware.generic.CaptureClient.capture", _capture)

    decision = decide_payment(
        credential_header="Payment dummy-credential",
        grantex_token_header="grant_token_123",
        config=config,
        charge_options=ChargeOptions(
            amount=Amount(value=100, currency="INR"),
            resource="/api/joke",
            merchantOrderReference="order-123",
        ),
    )

    assert decision.action == "proceed"
    assert verifier.tokens == ["grant_token_123"]
    assert decision.grant_result is not None
    assert decision.grant_result.valid is True
    assert decision.grant_result.grant is grant
    assert len(budget_calls) == 1
    assert budget_calls[0].grant_id == "grnt_123"
    assert budget_calls[0].amount == 1


def test_hosted_grantex_authorization_exchange_and_budgets() -> None:
    calls: list[tuple[str, object]] = []

    class _Tokens:
        def exchange(self, body):
            calls.append(("exchange", body))
            return SimpleNamespace(
                grantToken="grant.jwt",
                grantId="grnt_123",
                refreshToken="rt_123",
                scopes=["mpp:payment:initiate"],
                expiresAt="2030-01-01T00:00:00Z",
            )

    class _Budgets:
        def allocate(self, body):
            calls.append(("allocate", body))
            return SimpleNamespace(
                id="bdg_1",
                grantId=body.grant_id,
                initialBudget=body.initial_budget,
                remainingBudget=body.initial_budget,
                currency=body.currency,
            )

        def debit(self, body):
            calls.append(("debit", body))
            return SimpleNamespace(grantId=body.grant_id, remaining=9.5, transactionId="txn_1")

        def balance(self, grant_id):
            calls.append(("balance", grant_id))
            return SimpleNamespace(id="bdg_1", grantId=grant_id, initialBudget=10, remainingBudget=9.5, currency="INR")

        def transactions(self, grant_id, options):
            calls.append(("transactions", (grant_id, options)))
            return {
                "total": 1,
                "transactions": [
                    {"id": "txn_1", "grantId": grant_id, "amount": 0.5, "description": "P3P debit", "balanceAfter": 9.5}
                ],
            }

    class _Hosted:
        tokens = _Tokens()
        budgets = _Budgets()

        def authorize(self, body):
            calls.append(("authorize", body))
            return SimpleNamespace(
                authRequestId="areq_123",
                consentUrl="https://consent.grantex.dev/authorize?req=123",
                agentId=body.agent_id,
                principalId=body.user_id,
                scopes=body.scopes,
                expiresAt="2030-01-01T00:00:00Z",
                status="pending",
            )

    hosted = create_hosted_grantex_client(
        HostedGrantexConfig(apiKey="gx_test", client_factory=lambda: _Hosted())
    )

    auth = hosted.create_authorization(
        GrantexAuthorizationOptions(
            userId="user_123",
            agentId="ag_123",
            scopes=["mpp:payment:initiate", "mpp:payment:max_txn_paise:25000"],
            redirectUri="https://merchant.example/grantex/callback",
            expiresIn="30d",
        )
    )
    token = hosted.exchange_code(GrantexExchangeCodeOptions(code="code_123", agentId="ag_123"))
    allocation = hosted.allocate_budget(GrantexBudgetAllocationOptions(grantId="grnt_123", initialBudget=1000))
    debit = hosted.debit_budget(GrantexBudgetDebitOptions(grantId="grnt_123", amount=100, description="P3P debit"))
    balance = hosted.get_budget_balance("grnt_123")
    transactions = hosted.list_budget_transactions("grnt_123")

    assert "consent.grantex.dev" in auth.consentUrl
    assert token.grantId == "grnt_123"
    assert allocation.remainingBudget == 1000
    assert debit.remaining == 9.5
    assert balance.remainingBudget == 9.5
    assert transactions.transactions[0].amount == 0.5
    assert transactions.total == 1
    assert [call[0] for call in calls] == ["authorize", "exchange", "allocate", "debit", "balance", "transactions"]


def test_decide_payment_checks_grantex_budget_before_challenge() -> None:
    budget_calls: list[object] = []

    class _Budgets:
        def balance(self, grant_id):
            budget_calls.append(("balance", grant_id))
            return SimpleNamespace(id="bdg_1", grantId=grant_id, initialBudget=10, remainingBudget=9, currency="INR")

        def debit(self, body):
            budget_calls.append(("debit", body))
            return SimpleNamespace(grantId=body.grant_id, remaining=8, transactionId="txn_budget")

    grant = SimpleNamespace(grant_id="grnt_123", agent_did="did:web:agent.example", scopes=["mpp:payment:initiate", "mpp:payment:max_txn_paise:1000"])
    config = _config()
    config.grantex = ServerGrantexConfig(
        agentId="did:web:agent.example",
        requiredScopes=["mpp:payment:initiate"],
        enforceGrant=True,
        hosted=HostedGrantexConfig(apiKey="gx_test", client_factory=lambda: SimpleNamespace(budgets=_Budgets())),
        verifier=_GrantVerifier(GrantexVerificationResult(valid=True, grant=grant)),
    )

    decision = decide_payment(
        grantex_token_header="grant_token_123",
        config=config,
        charge_options=ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke"),
    )

    assert decision.action == "challenge"
    assert decision.status == 402
    assert len(budget_calls) == 1
    assert budget_calls[0] == ("balance", "grnt_123")


def test_decide_payment_rejects_over_cap_grantex_grant_before_challenge() -> None:
    grant = SimpleNamespace(grant_id="grnt_123", agent_did="did:web:agent.example", scopes=["mpp:payment:initiate", "mpp:payment:max_txn_paise:99"])
    config = _config()
    config.grantex = ServerGrantexConfig(
        agentId="did:web:agent.example",
        requiredScopes=["mpp:payment:initiate"],
        enforceGrant=True,
        hosted=HostedGrantexConfig(apiKey="gx_test"),
        verifier=_GrantVerifier(GrantexVerificationResult(valid=True, grant=grant)),
    )

    decision = decide_payment(
        grantex_token_header="grant_token_123",
        config=config,
        charge_options=ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke"),
    )

    assert decision.action == "grant_invalid"
    assert decision.status == 403
    assert "exceeds" in decision.problem_details["detail"]
    assert "WWW-Authenticate" not in decision.headers


def test_decide_payment_rejects_exhausted_hosted_grantex_budget_before_challenge() -> None:
    class _Budgets:
        def balance(self, grant_id):
            return SimpleNamespace(id="bdg_1", grantId=grant_id, initialBudget=10, remainingBudget=0.99, currency="INR")

    grant = SimpleNamespace(grant_id="grnt_123", agent_did="did:web:agent.example", scopes=["mpp:payment:initiate"])
    config = _config()
    config.grantex = ServerGrantexConfig(
        agentId="did:web:agent.example",
        requiredScopes=["mpp:payment:initiate"],
        enforceGrant=True,
        hosted=HostedGrantexConfig(apiKey="gx_test", client_factory=lambda: SimpleNamespace(budgets=_Budgets())),
        verifier=_GrantVerifier(GrantexVerificationResult(valid=True, grant=grant)),
    )

    decision = decide_payment(
        grantex_token_header="grant_token_123",
        config=config,
        charge_options=ChargeOptions(amount=Amount(value=100, currency="INR"), resource="/api/joke"),
    )

    assert decision.action == "grant_invalid"
    assert decision.status == 403
    assert decision.problem_details["type"] == "urn:ietf:rfc:9725:error:budget-exceeded"
    assert "WWW-Authenticate" not in decision.headers


def test_decide_payment_returns_202_when_capture_remains_pending(monkeypatch) -> None:
    def _verify(self, credential_header):
        del credential_header
        return SimpleNamespace(
            valid=True,
            error=None,
            credential=SimpleNamespace(
                payload=SimpleNamespace(
                    token="tok_123",
                    payment_method=PaymentMethod.RESERVE_PAY,
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


def test_fastapi_middleware_does_not_postpone_annotations() -> None:
    source = (SERVER_ROOT / "src/pinelabs_p3p_server/fastapi_mw.py").read_text()

    assert "from __future__ import annotations" not in source


def test_credential_verifier_uses_reserve_pay_alias_branch() -> None:
    source = Path(
        SERVER_ROOT / "src/pinelabs_p3p_server/server/credential_verifier.py"
    ).read_text()

    assert "if value == PaymentMethod.RESERVE_PAY.value:" in source
    assert "return PaymentMethod.RESERVE_PAY" in source


def test_build_receipt_header_falls_back_to_raw_debit_fields() -> None:
    import time

    before = time.time()
    header = build_receipt_header(
        CaptureResult(
            amount={"value": 300, "currency": "INR"},
            settled_at="",
            created_at="2030-01-02T00:00:00Z",
            payment_gateway=PaymentGateway.PineLabsOnline,
            payment_method=PaymentMethod.RESERVE_PAY,
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

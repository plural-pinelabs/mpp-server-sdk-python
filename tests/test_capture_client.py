from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import pinelabs_p3p_server.server.capture_client as capture_client_module
from pinelabs_p3p_server.server.capture_client import CaptureClient
from pinelabs_p3p_server.types.capture import CaptureOptions
from pinelabs_p3p_server.types.challenge import PaymentGateway, PaymentMethod
from pinelabs_p3p_server.types.config import Amount, PineLabsOnlineServerConfig
from pinelabs_p3p_server.utils.errors import P3PCaptureError


class _RecordingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/api/auth/v1/token"):
            return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "type": "RESERVE_PAY",
                    "payment_method_reference_id": "v1-sub-260422154824-aa-M3qU2m",
                    "payment_id": "088d3a01-5b05-43c7-9e1b-ddb11d2db0e4",
                    "merchant_order_reference": "order-123",
                    "amount": {"value": 100, "currency": "INR"},
                    "status": "CONFIRMED",
                    "oms_order_id": "v1-260430172729-aa-V9OITr",
                    "oms_payment_id": "v1-260430172729-aa-V9OITr-up-a",
                    "metadata": {
                        "external_capture_id": "v1-260430172729-aa-V9OITr-up-a",
                        "external_payment_id": "v1-260430172729-aa-V9OITr-up-a",
                        "upstream_payment_status": "PROCESSED",
                        "upstream_order_status": "PROCESSED",
                        "sbmd_data": {
                            "settled_at": "2026-04-30T17:27:36.586Z",
                            "upi_txn_id": "929542019913",
                        },
                    },
                }
            },
        )


def test_capture_client_uses_local_sbmd_route_for_localhost_base() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
            metadata={"mandate_id": "mnd_local_123"},
        )
    )

    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    body = json.loads(debit_request.content.decode() or "{}")
    assert body == {
        "payment_method": "RESERVE_PAY",
        "customer": {"mobile_number": "9876543210"},
        "payment_amount": {"value": 100, "currency": "INR"},
        "payment_token": "ppt_local_123",
        "challenge_id": "ch_test",
    }
    assert "Request-Hash" not in debit_request.headers
    assert debit_request.headers["Merchant-ID"] == "merchant-test"
    assert result.type == "RESERVE_PAY"
    assert result.payment_method_reference_id == "v1-sub-260422154824-aa-M3qU2m"
    assert result.payment_id == "088d3a01-5b05-43c7-9e1b-ddb11d2db0e4"
    assert result.merchant_order_reference == "order-123"
    assert result.amount == {"value": 100, "currency": "INR"}
    assert result.status == "CONFIRMED"
    assert result.payment_gateway == PaymentGateway.PineLabsOnline
    assert "payment_method" not in result


def test_capture_client_sends_card_debit_with_pre_authorization_reference() -> None:
    class _CardDebitTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.requests: list[httpx.Request] = []

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.path.endswith("/api/auth/v1/token"):
                return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})

            body = json.loads(request.content.decode() or "{}")
            assert request.headers["Authorization"] == "Bearer server-access-token"
            assert request.headers["Idempotency-Key"] == "debit-card-key-123"
            assert body == {
                "payment_method": "CARD",
                "customer": {"mobile_number": "9876543210"},
                "payment_amount": {"value": 300, "currency": "INR"},
                "payment_token": "P3P_TOK_CARD_123",
                "challenge_id": "ch_card_123",
                "payment_method_reference_id": "auth_card_123",
            }
            return httpx.Response(
                200,
                json={
                    "data": {
                        "type": "CARD",
                        "payment_method": "CARD",
                        "payment_method_reference_id": "auth_card_123",
                        "merchant_payment_debit_reference": "debit-card-key-123",
                        "amount": {"value": 300, "currency": "INR"},
                        "status": "PROCESSED",
                        "payment_data": {
                            "order_id": "ord_card_123",
                            "order_status": "PROCESSED",
                        },
                    }
                },
            )

    transport = _CardDebitTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.CARD],
            env="http://localhost:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="P3P_TOK_CARD_123",
            amount=Amount(value=300, currency="INR"),
            paymentMethod=PaymentMethod.CARD,
            paymentMethodReferenceId="auth_card_123",
            mobileNumber="9876543210",
            challengeId="ch_card_123",
            idempotencyKey="debit-card-key-123",
        )
    )

    assert result.payment_method == "CARD"
    assert result.payment_method_reference_id == "auth_card_123"
    assert result.merchant_payment_debit_reference == "debit-card-key-123"
    assert result.status == "PROCESSED"
    assert [request.url.path for request in transport.requests] == ["/api/auth/v1/token", "/mpp/v1/debit"]


def test_capture_client_sends_credit_emi_debit_with_pre_authorization_reference() -> None:
    class _CreditEmiDebitTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.requests: list[httpx.Request] = []

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.path.endswith("/api/auth/v1/token"):
                return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})
            body = json.loads(request.content.decode() or "{}")
            assert body["payment_method"] == "CREDIT_EMI"
            assert body["payment_method_reference_id"] == "auth_credit_emi_123"
            return httpx.Response(200, json={"data": {
                "status": "PROCESSED",
                "payment_method": "CREDIT_EMI",
                "payment_method_reference_id": "auth_credit_emi_123",
                "amount": {"value": 14897000, "currency": "INR"},
            }})

    transport = _CreditEmiDebitTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.CREDIT_EMI],
            env="http://localhost:8081",
        ),
        http_client=client,
    )
    result = capture.capture(CaptureOptions(
        token="P3P_TOK_CREDIT_EMI_123",
        amount=Amount(value=14897000, currency="INR"),
        paymentMethod=PaymentMethod.CREDIT_EMI,
        paymentMethodReferenceId="auth_credit_emi_123",
        mobileNumber="9390012811",
        challengeId="ch_credit_emi_123",
        idempotencyKey="debit-credit-emi-123",
    ))

    assert result.payment_method == "CREDIT_EMI"
    assert result.payment_method_reference_id == "auth_credit_emi_123"
    assert [request.url.path for request in transport.requests] == ["/api/auth/v1/token", "/mpp/v1/debit"]


def test_capture_client_rejects_credit_emi_without_pre_authorization_reference_before_network() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.CREDIT_EMI],
            env="http://localhost:8081",
        ),
        http_client=client,
    )
    with pytest.raises(P3PCaptureError, match="paymentMethodReferenceId is required for CREDIT_EMI"):
        capture.capture(CaptureOptions(
            token="P3P_TOK_CREDIT_EMI_123",
            amount=Amount(value=1000, currency="INR"),
            paymentMethod=PaymentMethod.CREDIT_EMI,
            mobileNumber="9390012811",
            challengeId="ch_credit_emi_123",
        ))
    assert transport.requests == []


def test_capture_client_keeps_payment_method_from_upstream_response() -> None:
    class _PaymentMethodTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth/v1/token"):
                return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "payment_method": "RESERVE_PAY",
                        "payment_method_reference_id": "v1-sub-upstream",
                        "payment_id": "pay_upstream",
                        "merchant_order_reference": "order-123",
                        "amount": {"value": 100, "currency": "INR"},
                        "status": "CONFIRMED",
                    }
                },
            )

    client = httpx.Client(transport=_PaymentMethodTransport())
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
            env="http://localhost:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.OTM,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
        )
    )

    assert result["payment_method"] == "RESERVE_PAY"


def test_capture_client_exchanges_server_token_for_debit() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
        )
    )

    assert "/api/auth/v1/token" in [request.url.path for request in transport.requests]
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    assert debit_request.headers["Authorization"] == "Bearer server-access-token"
    assert debit_request.headers["Merchant-ID"] == "merchant-test"


def test_capture_client_requires_mobile_number_for_v2_debit() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    with pytest.raises(P3PCaptureError, match="mobileNumber"):
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=100, currency="INR"),
                paymentMethod=PaymentMethod.RESERVE_PAY,
                merchantOrderReference="order-123",
                challengeId="ch_test",
                metadata={"mandate_id": "mnd_local_123"},
            )
        )

    assert transport.requests == []


def test_capture_client_requires_challenge_id_for_v2_debit() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    with pytest.raises(P3PCaptureError, match="challengeId"):
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=100, currency="INR"),
                paymentMethod=PaymentMethod.RESERVE_PAY,
                merchantOrderReference="order-123",
                customerReference="cust-ref-123",
                mobileNumber="9876543210",
                metadata={"mandate_id": "mnd_local_123"},
            )
        )

    assert transport.requests == []


def test_capture_client_uses_local_sbmd_route_for_host_docker_internal_base() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
                env="http://host.docker.internal:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
            metadata={"mandate_id": "mnd_local_123"},
        )
    )

    assert result.type == "RESERVE_PAY"
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    assert debit_request.headers["Merchant-ID"] == "merchant-test"


class _ActualOnlyTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/api/auth/v1/token"):
            return httpx.Response(200, json={"data": {"access_token": "real-token", "expires_in": 300}})
        if request.url.path.endswith("/mpp/v1/auth/token"):
            return httpx.Response(500, json={"error": {"message": "legacy auth path must not be used"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "payment_method_reference_id": "mnd_real_123",
                    "payment_token": "ppt_real_123",
                    "customer": {"merchant_customer_reference": "cust-real-ref", "customer_id": "cust_real_123"},
                    "merchant_id": "118284",
                    "oms_order_id": "ord_real_123",
                    "oms_payment_id": "ord_real_123-up-a",
                    "metadata": {"external_capture_id": "cap_real_123", "upstream_payment_status": "PROCESSED"},
                    "payment_id": "pay_real_123",
                    "status": "CONFIRMED",
                    "amount": {"value": 100, "currency": "INR"},
                    "created_at": "2026-04-22T19:00:00Z",
                }
            },
        )


def test_capture_client_does_not_use_internal_mpp_mock_route() -> None:
    transport = _ActualOnlyTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
                env="http://api:8000/api/v1/internal-mpp",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_real_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
            metadata={"mandate_id": "mnd_real_123"},
        )
    )

    assert result.metadata["external_capture_id"] == "cap_real_123"
    assert result.status == "CONFIRMED"
    attempted_paths = [request.url.path for request in transport.requests]
    assert "/api/v1/internal-mpp/mpp/v1/sbmd-mandate/debit" not in attempted_paths
    assert "/api/v1/internal-mpp/mpp/v1/capture" not in attempted_paths
    assert attempted_paths[-1] == "/api/v1/internal-mpp/mpp/v1/debit"


class _TopLevelErrorTransport(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/auth/v1/token"):
            return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})
        return httpx.Response(
            500,
            json={
                "code": "INTERNAL_ERROR",
                "message": "Unknown error",
                "additional_error_details": {
                    "reason": "SOMETHING_WENT_WRONG",
                    "metadata": {"rootCause": "subscription row conflict"},
                },
            },
        )


def test_capture_client_preserves_top_level_error_details() -> None:
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
                env="http://localhost:8081",
        ),
        http_client=httpx.Client(transport=_TopLevelErrorTransport()),
    )

    with pytest.raises(P3PCaptureError) as exc:
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=25000, currency="INR"),
                paymentMethod=PaymentMethod.RESERVE_PAY,
                merchantOrderReference="quote_123",
                customerReference="cust-ref-123",
                mobileNumber="9876543210",
                challengeId="ch_test",
                metadata={"mandate_id": "mnd_local_123"},
            )
        )

    assert exc.value.capture_error is not None
    assert exc.value.capture_error.code == "INTERNAL_ERROR"
    assert str(exc.value.capture_error) == "Unknown error"
    assert exc.value.capture_error.details == {
        "reason": "SOMETHING_WENT_WRONG",
        "metadata": {"rootCause": "subscription row conflict"},
    }


def test_capture_client_polls_debit_status_after_pending_debit_and_resolves(monkeypatch) -> None:
    sleep_calls: list[float] = []
    debit_post_keys: list[str] = []
    status_poll_paths: list[str] = []

    class _PendingThenResolvedTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth/v1/token"):
                return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})
            # The debit is POSTed exactly once; the async result is resolved by
            # polling the read-only GET /mpp/v1/debit/{id} endpoint.
            if request.url.path == "/mpp/v1/debit":
                assert request.method == "POST"
                debit_post_keys.append(request.headers["Idempotency-Key"])
                return httpx.Response(
                    202,
                    headers={"Retry-After": "0"},
                    json={
                        "data": {
                            "merchant_payment_debit_reference": "pay_ref_pending",
                            "amount": {"value": 25000, "currency": "INR"},
                            "status": "PROCESSING",
                        }
                    },
                )
            if request.url.path == "/mpp/v1/debit/idem_key_20260601_001":
                assert request.method == "GET"
                status_poll_paths.append(request.url.path)
                # First poll still processing; second poll resolves.
                if len(status_poll_paths) == 1:
                    return httpx.Response(
                        200,
                        json={
                            "data": {
                                "merchant_payment_debit_reference": "pay_ref_pending",
                                "amount": {"value": 25000, "currency": "INR"},
                                "status": "PROCESSING",
                            }
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "merchant_payment_debit_reference": "pay_ref_processed",
                            "amount": {"value": 25000, "currency": "INR"},
                            "status": "PROCESSED",
                            "payment_data": {"order_id": "ord_123", "order_status": "PROCESSED"},
                        }
                    },
                )
            raise AssertionError(f"unexpected request path {request.url.path}")

    monkeypatch.setattr(capture_client_module, "time", SimpleNamespace(sleep=sleep_calls.append), raising=False)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
            env="http://localhost:8081",
            maxRetries=2,
            initialRetryDelayMs=50,
        ),
        http_client=httpx.Client(transport=_PendingThenResolvedTransport()),
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=25000, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
            idempotencyKey="idem_key_20260601_001",
        )
    )

    assert result.status == "PROCESSED"
    assert result.idempotencyKey == "idem_key_20260601_001"
    # Debit POSTed exactly once; resolution came from GET-polling the status.
    assert debit_post_keys == ["idem_key_20260601_001"]
    assert status_poll_paths == [
        "/mpp/v1/debit/idem_key_20260601_001",
        "/mpp/v1/debit/idem_key_20260601_001",
    ]
    # Retry-After: 0 on the 202 drives a 0ms wait before each poll.
    assert sleep_calls == [0.0, 0.0]


def test_capture_client_returns_pending_after_poll_budget_exhausted_using_fallback_delay(monkeypatch) -> None:
    sleep_calls: list[float] = []
    debit_post_calls = 0
    status_poll_calls = 0

    class _PendingFallbackTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal debit_post_calls, status_poll_calls
            if request.url.path.endswith("/api/auth/v1/token"):
                return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})
            if request.url.path == "/mpp/v1/debit":
                debit_post_calls += 1
                return httpx.Response(
                    202,
                    json={
                        "data": {
                            "merchant_payment_debit_reference": "pay_ref_pending",
                            "amount": {"value": 25000, "currency": "INR"},
                            "status": "PENDING",
                        }
                    },
                )
            # The status poll keeps reporting PENDING, so the debit stays pending.
            if request.url.path == "/mpp/v1/debit/idem_key_20260601_002":
                assert request.method == "GET"
                status_poll_calls += 1
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "merchant_payment_debit_reference": "pay_ref_pending",
                            "amount": {"value": 25000, "currency": "INR"},
                            "status": "PENDING",
                        }
                    },
                )
            raise AssertionError(f"unexpected request path {request.url.path}")

    transport = _PendingFallbackTransport()
    monkeypatch.setattr(capture_client_module, "time", SimpleNamespace(sleep=sleep_calls.append), raising=False)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
            env="http://localhost:8081",
            maxRetries=1,
            initialRetryDelayMs=321,
        ),
        http_client=httpx.Client(transport=transport),
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=25000, currency="INR"),
            paymentMethod=PaymentMethod.RESERVE_PAY,
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
            idempotencyKey="idem_key_20260601_002",
        )
    )

    assert result.status == "PENDING"
    assert result.retryAfter == 321
    # Debit POSTed once, then polled once (maxRetries == 1) before giving up.
    assert debit_post_calls == 1
    assert status_poll_calls == 1
    # No Retry-After header, so polling falls back to initialRetryDelayMs (321ms).
    assert sleep_calls == [0.321]


def test_capture_client_gets_debit_status_by_idempotency_key() -> None:
    class _DebitStatusTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.requests: list[httpx.Request] = []

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.path.endswith("/api/auth/v1/token"):
                return httpx.Response(200, json={"data": {"access_token": "server-access-token", "expires_in": 300}})
            if request.url.path == "/mpp/v1/debit/idem_key_20260601_003":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "merchant_payment_debit_reference": "pay_ref_processed",
                            "amount": {"value": 25000, "currency": "INR"},
                            "status": "PROCESSED",
                            "payment_data": {"order_id": "ord_123", "order_status": "PROCESSED"},
                        }
                    },
                )
            raise AssertionError(f"unexpected request path {request.url.path}")

    transport = _DebitStatusTransport()
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            merchantId="merchant-test",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.RESERVE_PAY, PaymentMethod.OTM],
            env="http://localhost:8081",
        ),
        http_client=httpx.Client(transport=transport),
    )

    result = capture.get_debit_status("idem_key_20260601_003")

    assert result.status == "PROCESSED"
    assert result.merchant_payment_debit_reference == "pay_ref_processed"
    assert result.idempotencyKey == "idem_key_20260601_003"
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit/idem_key_20260601_003")
    assert debit_request.method == "GET"
    assert debit_request.headers["Authorization"] == "Bearer server-access-token"

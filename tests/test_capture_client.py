from __future__ import annotations

import json

import httpx
import pytest

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
                    "type": "SBMD",
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
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
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
        "payment_method": "SBMD",
        "customer": {"mobile_number": "9876543210"},
        "payment_amount": {"value": 100, "currency": "INR"},
        "payment_token": "ppt_local_123",
        "challenge_id": "ch_test",
    }
    assert "Request-Hash" not in debit_request.headers
    assert "Merchant-ID" not in debit_request.headers
    assert result.capture_id == "v1-260430172729-aa-V9OITr-up-a"
    assert result.mandate_id == "v1-sub-260422154824-aa-M3qU2m"
    assert result.payment_id == "v1-260430172729-aa-V9OITr-up-a"
    assert result.order_id == "v1-260430172729-aa-V9OITr"
    assert result.order_status == "CONFIRMED"
    assert result.payment_status == "PROCESSED"
    assert result.upi_txn_id == "929542019913"
    assert result.receipt["oms_payment_id"] == "v1-260430172729-aa-V9OITr-up-a"


def test_capture_client_exchanges_server_token_for_debit() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
        )
    )

    assert "/api/auth/v1/token" in [request.url.path for request in transport.requests]
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    assert debit_request.headers["Authorization"] == "Bearer server-access-token"
    assert "Merchant-ID" not in debit_request.headers


def test_capture_client_requires_customer_reference_for_v2_debit() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PineLabsOnlineServerConfig(
            clientId="server-client",
            clientSecret="server-secret",
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    with pytest.raises(P3PCaptureError, match="customerReference"):
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=100, currency="INR"),
                paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
                merchantOrderReference="order-123",
                challengeId="ch_test",
                mobileNumber="9876543210",
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
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
                env="http://localhost:8081",
        ),
        http_client=client,
    )

    with pytest.raises(P3PCaptureError, match="challengeId"):
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=100, currency="INR"),
                paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
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
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
                env="http://host.docker.internal:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
            metadata={"mandate_id": "mnd_local_123"},
        )
    )

    assert result.capture_id == "v1-260430172729-aa-V9OITr-up-a"
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    assert "Merchant-ID" not in debit_request.headers


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
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
                env="http://api:8000/api/v1/internal-mpp",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_real_123",
            amount=Amount(value=100, currency="INR"),
            paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            mobileNumber="9876543210",
            challengeId="ch_test",
            metadata={"mandate_id": "mnd_real_123"},
        )
    )

    assert result.capture_id == "cap_real_123"
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
            paymentGateway=PaymentGateway.PineLabsOnline,
            availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
                env="http://localhost:8081",
        ),
        http_client=httpx.Client(transport=_TopLevelErrorTransport()),
    )

    with pytest.raises(P3PCaptureError) as exc:
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=25000, currency="INR"),
                paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
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

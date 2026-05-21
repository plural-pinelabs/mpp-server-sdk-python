from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from plural_mpp_seller.server.capture_client import CaptureClient
from plural_mpp_seller.types.capture import CaptureOptions
from plural_mpp_seller.types.config import Amount, PluralSellerConfig
from plural_mpp_seller.utils.errors import MppCaptureError


class _RecordingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/api/auth/v1/token"):
            return httpx.Response(200, json={"data": {"access_token": "seller-access-token", "expires_in": 300}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "type": "SBMD",
                    "authorization_id": "v1-sub-260422154824-aa-M3qU2m",
                    "payment_id": "088d3a01-5b05-43c7-9e1b-ddb11d2db0e4",
                    "merchant_order_reference": "order-123",
                    "amount": "100",
                    "currency": "INR",
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
        PluralSellerConfig(
            clientId="seller-client",
            clientSecret="seller-secret",
            challengeSecretKey="challenge-key",
            baseUrl="http://localhost:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
            metadata={"mandate_id": "mnd_local_123"},
        )
    )

    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    body = json.loads(debit_request.content.decode() or "{}")
    assert body == {
        "type": "SBMD",
        "customer_reference": "cust-ref-123",
        "merchant_order_reference": "order-123",
        "amount": "100",
        "currency": "INR",
        "payment_token": "ppt_local_123",
    }
    expected_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert debit_request.headers["Request-Hash"] == expected_hash
    assert "Merchant-ID" not in debit_request.headers
    assert result.capture_id == "v1-260430172729-aa-V9OITr-up-a"
    assert result.mandate_id == "v1-sub-260422154824-aa-M3qU2m"
    assert result.payment_id == "088d3a01-5b05-43c7-9e1b-ddb11d2db0e4"
    assert result.order_id == "v1-260430172729-aa-V9OITr"
    assert result.order_status == "CONFIRMED"
    assert result.payment_status == "PROCESSED"
    assert result.upi_txn_id == "929542019913"
    assert result.receipt["oms_payment_id"] == "v1-260430172729-aa-V9OITr-up-a"


def test_capture_client_uses_configured_bearer_token_without_auth_exchange() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PluralSellerConfig(
            clientId="seller-client",
            clientSecret="seller-secret",
            challengeSecretKey="challenge-key",
            baseUrl="http://localhost:8081",
            accessToken="Bearer configured-seller-token",
        ),
        http_client=client,
    )

    capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
        )
    )

    assert "/api/auth/v1/token" not in [request.url.path for request in transport.requests]
    debit_request = next(req for req in transport.requests if req.url.path == "/mpp/v1/debit")
    assert debit_request.headers["Authorization"] == "Bearer configured-seller-token"
    assert "Merchant-ID" not in debit_request.headers


def test_capture_client_requires_customer_reference_for_v2_debit() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PluralSellerConfig(
            clientId="seller-client",
            clientSecret="seller-secret",
            challengeSecretKey="challenge-key",
            baseUrl="http://localhost:8081",
        ),
        http_client=client,
    )

    with pytest.raises(MppCaptureError, match="customerReference"):
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=100, currency="INR"),
                merchantOrderReference="order-123",
                metadata={"mandate_id": "mnd_local_123"},
            )
        )

    assert transport.requests == []


def test_capture_client_uses_local_sbmd_route_for_host_docker_internal_base() -> None:
    transport = _RecordingTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PluralSellerConfig(
            clientId="seller-client",
            clientSecret="seller-secret",
            challengeSecretKey="challenge-key",
            baseUrl="http://host.docker.internal:8081",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_local_123",
            amount=Amount(value=100, currency="INR"),
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
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
                    "authorization_id": "mnd_real_123",
                    "payment_token": "ppt_real_123",
                    "customer_id": "cust_real_123",
                    "merchant_id": "118284",
                    "oms_order_id": "ord_real_123",
                    "oms_payment_id": "ord_real_123-up-a",
                    "metadata": {"external_capture_id": "cap_real_123", "upstream_payment_status": "PROCESSED"},
                    "payment_id": "pay_real_123",
                    "status": "CONFIRMED",
                    "amount": "100",
                    "currency": "INR",
                    "created_at": "2026-04-22T19:00:00Z",
                }
            },
        )


def test_capture_client_does_not_use_internal_mpp_mock_route() -> None:
    transport = _ActualOnlyTransport()
    client = httpx.Client(transport=transport)
    capture = CaptureClient(
        PluralSellerConfig(
            clientId="seller-client",
            clientSecret="seller-secret",
            challengeSecretKey="challenge-key",
            baseUrl="http://api:8000/api/v1/internal-mpp",
        ),
        http_client=client,
    )

    result = capture.capture(
        CaptureOptions(
            token="ppt_real_123",
            amount=Amount(value=100, currency="INR"),
            merchantOrderReference="order-123",
            customerReference="cust-ref-123",
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
            return httpx.Response(200, json={"data": {"access_token": "seller-access-token", "expires_in": 300}})
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
        PluralSellerConfig(
            clientId="seller-client",
            clientSecret="seller-secret",
            challengeSecretKey="challenge-key",
            baseUrl="http://localhost:8081",
        ),
        http_client=httpx.Client(transport=_TopLevelErrorTransport()),
    )

    with pytest.raises(MppCaptureError) as exc:
        capture.capture(
            CaptureOptions(
                token="ppt_local_123",
                amount=Amount(value=25000, currency="INR"),
                merchantOrderReference="quote_123",
                customerReference="cust-ref-123",
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

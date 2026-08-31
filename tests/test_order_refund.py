from __future__ import annotations

import json

import httpx
import pytest

from pinelabs_p3p_server import (
    Amount,
    CreateRefundOptions,
    P3PEnvironment,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineP3P,
    PineLabsOnlineServerConfig,
)


class _OrderRefundTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/auth/v1/token":
            return httpx.Response(200, json={"data": {"access_token": "access", "expires_in": 3600}})
        if request.url.path == "/api/pay/v1/orders/parent-order-1":
            assert request.method == "GET"
            assert request.headers["Authorization"] == "Bearer access"
            return httpx.Response(200, json={"data": {
                "order_id": "parent-order-1",
                "merchant_order_reference": "merchant-order-1",
                "type": "CHARGE",
                "status": "PROCESSED",
                "merchant_id": "111643",
                "order_amount": {"value": 14897000, "currency": "INR"},
                "pre_auth": True,
                "purchase_details": {
                    "customer": {
                        "mobile_number": "9390012811",
                        "billing_address": {"city": "MUMBAI", "country": "INDIA"},
                    },
                    "merchant_metadata": {"source": "merchant"},
                },
                "payments": [{
                    "id": "payment-1",
                    "status": "PROCESSED",
                    "payment_amount": {"value": 14897000, "currency": "INR"},
                    "payment_method": "CARD",
                    "payment_option": {"card_data": {"network_name": "VISA"}},
                    "acquirer_data": {"rrn": "420123000239"},
                }],
                "future_field": "retained",
            }})
        if request.url.path == "/api/pay/v1/refunds/parent-order-1":
            assert request.method == "POST"
            assert request.headers.get("Request-ID")
            assert request.headers.get("Request-Timestamp", "").endswith("Z")
            assert json.loads(request.content.decode()) == {
                "merchant_order_reference": "refund-reference-123",
                "order_amount": {"value": 1100, "currency": "INR"},
                "merchant_metadata": {"reason": "customer_request"},
            }
            return httpx.Response(200, json={"data": {
                "order_id": "refund-order-1",
                "parent_order_id": "parent-order-1",
                "merchant_order_reference": "refund-reference-123",
                "type": "REFUND",
                "status": "PROCESSED",
                "merchant_id": "111643",
                "order_amount": {"value": 1100, "currency": "INR"},
                "payments": [{
                    "id": "refund-payment-1",
                    "status": "PROCESSED",
                    "payment_amount": {"value": 1100, "currency": "INR"},
                    "payment_method": "CARD",
                    "acquirer_data": {"acquirer_reference": "7285447904236780703954", "is_aggregator": True},
                }],
            }})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": request.url.path})


def _config() -> PineLabsOnlineServerConfig:
    return PineLabsOnlineServerConfig(
        clientId="client-id",
        clientSecret="client-secret",
        merchantId="111643",
        env=P3PEnvironment.SANDBOX,
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.CARD],
        maxRetries=0,
    )


def test_get_order_and_create_refund_are_typed_and_use_pay_api(monkeypatch) -> None:
    transport = _OrderRefundTransport()
    real_client = httpx.Client

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("httpx.Client", client)
    sdk = PineLabsOnlineP3P.create(_config())

    order = sdk.get_order("  parent-order-1  ")
    refund = sdk.create_refund("  parent-order-1  ", CreateRefundOptions(
        merchantOrderReference=" refund-reference-123 ",
        orderAmount=Amount(value=1100, currency=" INR "),
        merchantMetadata={"reason": "customer_request"},
    ))

    assert order.order_id == "parent-order-1"
    assert order.order_amount.value == 14897000
    assert order.purchase_details.customer.billing_address.city == "MUMBAI"
    assert order.payments[0].payment_option.card_data.network_name == "VISA"
    assert order.raw["future_field"] == "retained"
    assert refund.parent_order_id == "parent-order-1"
    assert refund.order_id == "refund-order-1"
    assert refund.payments[0].acquirer_data.is_aggregator is True
    assert [request.url.path for request in transport.requests] == [
        "/api/auth/v1/token",
        "/api/pay/v1/orders/parent-order-1",
        "/api/pay/v1/refunds/parent-order-1",
    ]


def test_order_and_refund_validate_before_network(monkeypatch) -> None:
    class _FailingTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise AssertionError("network must not be called")

    real_client = httpx.Client
    monkeypatch.setattr("httpx.Client", lambda *args, **kwargs: real_client(transport=_FailingTransport()))
    sdk = PineLabsOnlineP3P.create(_config())

    with pytest.raises(ValueError, match="order_id is required"):
        sdk.get_order("   ")
    with pytest.raises(ValueError, match="merchantOrderReference is required"):
        sdk.create_refund("order-1", CreateRefundOptions("", Amount(100, "INR")))
    with pytest.raises(ValueError, match="positive integer"):
        sdk.create_refund("order-1", CreateRefundOptions("refund-1", Amount(0, "INR")))

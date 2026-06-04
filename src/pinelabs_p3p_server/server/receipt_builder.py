from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..types.capture import CaptureResult, ReceiptData, Settlement
from ..types.config import Amount
from ..types.payment import PaymentGateway, PaymentMethod
from ..utils.base64url import encode_json

PAYMENT_RECEIPT_PREFIX = "Payment "


def build_receipt_data(
    capture_result: CaptureResult,
    challenge_id: str,
    payment_gateway: Optional[PaymentGateway] = None,
    payment_method: Optional[PaymentMethod] = None,
) -> ReceiptData:
    """Build structured receipt data from a successful capture result."""
    amount = _as_amount(_value(capture_result, "amount"))
    timestamp = str(_value(capture_result, "settled_at") or "") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    reference = str(_value(capture_result, "capture_id") or _value(capture_result, "merchant_payment_debit_reference") or "")
    merchant_order_reference = str(
        _value(capture_result, "merchant_order_reference")
        or _value(capture_result, "merchant_payment_debit_reference")
        or ""
    ) or None
    resolved_gateway = payment_gateway or getattr(capture_result, "payment_gateway", None)
    resolved_method = payment_method or getattr(capture_result, "payment_method", None)
    return ReceiptData(
        status="success",
        timestamp=timestamp,
        reference=reference,
        challengeId=challenge_id,
        settlement=Settlement(amount=f"{amount.value / 100:.2f}", currency=amount.currency) if amount else None,
        paymentGateway=resolved_gateway,
        paymentMethod=resolved_method,
        orderId=str(_value(capture_result, "order_id") or "") or None,
        merchantOrderReference=merchant_order_reference or None,
    )


def build_receipt_header(
    capture_result: CaptureResult,
    challenge_id: str,
    payment_gateway: Optional[PaymentGateway] = None,
    payment_method: Optional[PaymentMethod] = None,
) -> str:
    """Encode capture receipt data as `Payment <base64url>`."""
    receipt = build_receipt_data(capture_result, challenge_id, payment_gateway, payment_method)
    payload = {
        "status": receipt.status,
        "timestamp": receipt.timestamp,
        "reference": receipt.reference,
        "challengeId": receipt.challengeId,
        "orderId": receipt.orderId,
        "merchantOrderReference": receipt.merchantOrderReference,
    }
    if receipt.settlement:
        payload["settlement"] = {"amount": receipt.settlement.amount, "currency": receipt.settlement.currency}
    if receipt.paymentGateway:
        payload["paymentGateway"] = _enum_value(receipt.paymentGateway)
    if receipt.paymentMethod:
        payload["paymentMethod"] = _enum_value(receipt.paymentMethod)
    return f"{PAYMENT_RECEIPT_PREFIX}{encode_json(payload)}"


def build_failure_receipt_data(
    challenge_id: str,
    error: str,
    payment_gateway: Optional[PaymentGateway] = None,
    payment_method: Optional[PaymentMethod] = None,
) -> ReceiptData:
    """Build a failure receipt object for adapters that need explicit failure data."""
    del error
    return ReceiptData(
        status="failure",
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        reference="",
        challengeId=challenge_id,
        settlement=Settlement(amount="0.00", currency="INR"),
        paymentGateway=payment_gateway,
        paymentMethod=payment_method,
    )


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _as_amount(value: Any) -> Optional[Amount]:
    if isinstance(value, Amount):
        return value
    if isinstance(value, dict):
        amount_value = value.get("value")
        currency = value.get("currency")
        if isinstance(currency, str):
            return Amount(value=int(amount_value or 0), currency=currency)
    return None


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)

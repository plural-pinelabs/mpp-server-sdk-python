from __future__ import annotations

from datetime import datetime, timezone

from ..types.capture import CaptureResult, ReceiptData, Settlement
from ..utils.base64url import encode_json

PAYMENT_RECEIPT_PREFIX = "Payment "


def build_receipt_data(capture_result: CaptureResult, challenge_id: str) -> ReceiptData:
    """Build structured receipt data from a successful capture result."""
    amount_major = f"{capture_result.amount.value / 100:.2f}"
    timestamp = capture_result.settled_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return ReceiptData(
        status="success",
        method="plural",
        timestamp=timestamp,
        reference=capture_result.capture_id,
        challengeId=challenge_id,
        settlement=Settlement(amount=amount_major, currency=capture_result.amount.currency),
    )


def build_receipt_header(capture_result: CaptureResult, challenge_id: str) -> str:
    """Encode capture receipt data as `Payment <base64url>`."""
    receipt = build_receipt_data(capture_result, challenge_id)
    payload = {
        "status": receipt.status,
        "method": receipt.method,
        "timestamp": receipt.timestamp,
        "reference": receipt.reference,
        "challengeId": receipt.challengeId,
        "settlement": {"amount": receipt.settlement.amount, "currency": receipt.settlement.currency},
    }
    return f"{PAYMENT_RECEIPT_PREFIX}{encode_json(payload)}"


def build_failure_receipt_data(challenge_id: str, error: str) -> ReceiptData:
    """Build a failure receipt object for adapters that need explicit failure data."""
    return ReceiptData(
        status="failure",
        method="plural",
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        reference="",
        challengeId=challenge_id,
        settlement=Settlement(amount="0.00", currency="INR"),
    )

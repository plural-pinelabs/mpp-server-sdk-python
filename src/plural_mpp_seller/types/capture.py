from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from .config import Amount


@dataclass
class CaptureOptions:
    """Input for seller debit/capture via `POST /mpp/v1/debit`."""

    token: str
    amount: Amount
    description: Optional[str] = None
    merchantOrderReference: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    idempotencyKey: Optional[str] = None
    paymentType: str = "SBMD"
    customerReference: Optional[str] = None


@dataclass
class CaptureReceipt:
    """Legacy receipt summary returned by older capture APIs."""

    mandate_amount: int
    total_debited: int
    remaining: int
    token_remaining: Dict[str, Any]


@dataclass
class CaptureResult:
    """Normalized debit/capture response from the MPP service."""

    capture_id: str
    object: str
    mandate_id: str
    token_id: str
    customer_id: str
    merchant_id: str
    order_id: str
    order_status: str
    payment_id: str
    payment_status: str
    amount: Amount
    upi_txn_id: str
    receipt: Dict[str, Any]
    description: Optional[str]
    merchant_order_reference: Optional[str]
    metadata: Optional[Dict[str, str]]
    settled_at: str
    created_at: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Settlement:
    """Settlement amount encoded in a `Payment-Receipt` header."""

    amount: str
    currency: str


@dataclass
class ReceiptData:
    """Decoded/structured seller payment receipt data."""

    status: Literal["success", "failure"]
    method: str
    timestamp: str
    reference: str
    challengeId: str
    settlement: Settlement

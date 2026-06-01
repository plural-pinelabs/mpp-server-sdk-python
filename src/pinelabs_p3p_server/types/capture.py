from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from .config import Amount
from .payment import PaymentGateway, PaymentMethod


@dataclass
class CaptureOptions:
    """Input for server debit/capture via `POST /mpp/v1/debit`.

    `merchantOrderReference` is retained for compatibility and is used as the
    idempotency key when `idempotencyKey` is absent; current debit requests do
    not send `merchant_order_reference` in the body.
    """

    token: str
    amount: Amount
    paymentMethod: PaymentMethod
    description: Optional[str] = None
    merchantOrderReference: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    idempotencyKey: Optional[str] = None
    customerReference: Optional[str] = None
    mobileNumber: Optional[str] = None
    challengeId: Optional[str] = None


@dataclass
class CaptureReceipt:
    """Legacy receipt summary returned by older capture APIs."""

    mandate_amount: int
    total_debited: int
    remaining: int
    token_remaining: Dict[str, Any]


@dataclass
class CaptureResult:
    """Normalized debit/capture response from the P3P service."""

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
    payment_gateway: Optional[PaymentGateway] = None
    payment_method: Optional[PaymentMethod] = None


@dataclass
class Settlement:
    """Settlement amount encoded in a `Payment-Receipt` header."""

    amount: str
    currency: str


@dataclass
class ReceiptData:
    """Decoded/structured server payment receipt data."""

    status: Literal["success", "failure"]
    timestamp: str
    reference: str
    challengeId: str
    settlement: Settlement
    paymentGateway: Optional[PaymentGateway] = None
    paymentMethod: Optional[PaymentMethod] = None
    orderId: Optional[str] = None
    merchantOrderReference: Optional[str] = None

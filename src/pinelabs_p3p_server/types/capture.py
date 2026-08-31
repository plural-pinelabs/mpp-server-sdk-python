from dataclasses import dataclass
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
    paymentMethodReferenceId: Optional[str] = None
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


class CaptureResult(dict[str, Any]):
    """Raw debit/capture response with SDK context fields attached.

    The dict may include SDK-added context such as `payment_gateway`,
    `idempotencyKey`, `pending`, `message`, and `retryAfter`.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - mirrors normal attribute access failure
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


PENDING_DEBIT_STATUSES = frozenset({
    "PENDING",
    "CREATED",
    "OMS_PAYMENT_SUBMITTED",
    "PROCESSING",
})


def is_pending_debit_status(status: Any) -> bool:
    return str(status or "").strip().upper() in PENDING_DEBIT_STATUSES


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
    settlement: Optional[Settlement]
    paymentGateway: Optional[PaymentGateway] = None
    paymentMethod: Optional[PaymentMethod] = None
    orderId: Optional[str] = None
    merchantOrderReference: Optional[str] = None

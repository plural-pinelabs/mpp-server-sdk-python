from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from ..config.environments import P3PEnvironment
from .payment import PaymentGateway, PaymentMethod


@dataclass
class Amount:
    """Money amount expressed in the smallest unit for the currency."""

    value: int
    currency: str


class P3PLogger(Protocol):
    def debug(self, message: str, context: Optional[dict] = None) -> None: ...
    def info(self, message: str, context: Optional[dict] = None) -> None: ...
    def error(self, message: str, context: Optional[dict] = None) -> None: ...


@dataclass
class PineLabsOnlineServerConfig:
    """Configuration required to construct a server SDK instance.

    `clientSecret` is used for service auth before calling `/mpp/v1/debit`
    and derives the local HMAC key used to sign 402 challenges.
    """

    clientId: str
    clientSecret: str
    paymentGateway: PaymentGateway
    availablePaymentMethods: List[PaymentMethod]
    env: str = P3PEnvironment.PRODUCTION
    realm: Optional[str] = None
    defaultChallengeExpirySeconds: Optional[int] = None
    requestTimeoutMs: Optional[int] = None
    maxRetries: Optional[int] = None
    initialRetryDelayMs: Optional[int] = None
    logger: Optional[P3PLogger] = None


@dataclass
class ChargeOptions:
    """Payment challenge/capture context for a server-protected resource."""

    amount: Amount
    resource: str
    description: Optional[str] = None
    merchantOrderReference: Optional[str] = None
    metadata: Optional[dict] = None
    challengeExpirySeconds: Optional[int] = None


@dataclass
class CreateMandateOptions:
    """Input for server/server-side mandate creation via `POST /mpp/v1/pre-authorize`."""

    amount: Amount
    mobileNumber: Optional[str] = None
    customerReference: Optional[str] = None
    customerId: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    expiry: Optional[str] = None
    idempotencyKey: Optional[str] = None
    paymentMethod: Optional[PaymentMethod] = None
    validityInDays: Optional[int] = None


@dataclass
class MandateChallenge:
    type: str
    qr_url: str
    deep_link: str
    expires_at: str


@dataclass
class Mandate:
    """Normalized mandate/pre-authorization response returned by the P3P service."""

    mandate_id: str
    object: str
    order_id: str
    order_status: str
    payment_status: str
    customer_reference: str
    customer_id: str
    agent_id: str
    amount: Amount
    amount_blocked: int
    amount_debited: int
    amount_held: int
    amount_available: int
    mobile_number: str
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    expires_at: str = ""
    created_at: str = ""
    challenge: Optional[MandateChallenge] = None
    raw: Dict[str, Any] = field(default_factory=dict)

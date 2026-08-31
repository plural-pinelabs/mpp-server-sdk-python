from dataclasses import dataclass
from typing import Literal, Optional

from .challenge import ChallengeRequest
from .payment import PaymentGateway, PaymentMethod


@dataclass
class CredentialChallenge:
    """Challenge copy embedded inside a client Payment credential."""

    id: str
    realm: str
    intent: str
    request: ChallengeRequest
    expires: str
    paymentGateway: Optional[PaymentGateway] = None


@dataclass
class CredentialPayload:
    """Client token payload embedded inside a Payment credential."""

    type: Literal["token"]
    token: str
    payment_method: PaymentMethod
    payment_method_reference_id: Optional[str] = None
    customer_reference: Optional[str] = None
    mobile_number: Optional[str] = None


@dataclass
class Credential:
    """Decoded client credential from `P3P-Credential: Payment <payload>`."""

    challenge: CredentialChallenge
    source: str
    payload: CredentialPayload


@dataclass
class VerificationResult:
    """Result of local Payment credential verification."""

    valid: bool
    credential: Optional[Credential] = None
    error: Optional[str] = None

from dataclasses import dataclass
from typing import List, Literal, Optional

from .payment import PaymentGateway, PaymentMethod


@dataclass
class ChallengeRequest:
    """Payment request embedded in the server 402 challenge."""

    scheme: str
    amount: str
    currency: str
    resource: str
    availablePaymentMethods: List[PaymentMethod]


@dataclass
class Challenge:
    """Signed server payment challenge encoded in `WWW-Authenticate`."""

    id: str
    realm: str
    intent: str
    request: ChallengeRequest
    expires: str
    paymentGateway: Optional[PaymentGateway] = None


@dataclass
class ProblemDetails:
    """Problem Details response body returned with a 402 challenge."""

    type: str
    title: str
    status: Literal[402]
    detail: str
    challengeId: str


@dataclass
class ChallengeResult:
    """Generated challenge plus its encoded header payload and problem body."""

    challenge: Challenge
    encoded: str
    problemDetails: ProblemDetails

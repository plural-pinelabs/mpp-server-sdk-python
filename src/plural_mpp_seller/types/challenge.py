from dataclasses import dataclass
from typing import Literal


@dataclass
class ChallengeRequest:
    """Payment request embedded in the seller 402 challenge."""

    scheme: str
    amount: str
    currency: str
    resource: str


@dataclass
class Challenge:
    """Signed seller payment challenge encoded in `WWW-Authenticate`."""

    id: str
    realm: str
    method: str
    intent: str
    request: ChallengeRequest
    expires: str


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

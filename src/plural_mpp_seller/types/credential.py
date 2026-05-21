from dataclasses import dataclass
from typing import Literal, Optional

from .challenge import ChallengeRequest


@dataclass
class CredentialChallenge:
    """Challenge copy embedded inside a buyer Payment credential."""

    id: str
    realm: str
    method: str
    intent: str
    request: ChallengeRequest
    expires: str


@dataclass
class CredentialPayload:
    """Buyer token payload embedded inside a Payment credential."""

    type: Literal["token"]
    token: str
    customer_reference: Optional[str] = None


@dataclass
class Credential:
    """Decoded buyer credential from `Authorization: Payment <payload>`."""

    challenge: CredentialChallenge
    source: str
    payload: CredentialPayload


@dataclass
class VerificationResult:
    """Result of local Payment credential verification."""

    valid: bool
    credential: Optional[Credential] = None
    error: Optional[str] = None

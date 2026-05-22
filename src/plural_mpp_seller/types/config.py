from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class Amount:
    """Money amount expressed in the smallest unit for the currency."""

    value: int
    currency: str


class MppLogger(Protocol):
    def debug(self, message: str, context: Optional[dict] = None) -> None: ...
    def info(self, message: str, context: Optional[dict] = None) -> None: ...
    def error(self, message: str, context: Optional[dict] = None) -> None: ...


@dataclass
class PluralSellerConfig:
    """Configuration required to construct a seller SDK instance.

    `challengeSecretKey` signs 402 challenges. `clientId` and `clientSecret`
    are used for service auth before calling `/mpp/v1/debit`.
    """

    clientId: str
    clientSecret: str
    challengeSecretKey: str
    realm: Optional[str] = None
    baseUrl: Optional[str] = None
    defaultChallengeExpirySeconds: Optional[int] = None
    requestTimeoutMs: Optional[int] = None
    maxRetries: Optional[int] = None
    initialRetryDelayMs: Optional[int] = None
    logger: Optional[MppLogger] = None
    accessToken: Optional[str] = None


@dataclass
class ChargeOptions:
    """Payment challenge/capture context for a seller-protected resource."""

    amount: Amount
    resource: str
    description: Optional[str] = None
    merchantOrderReference: Optional[str] = None
    metadata: Optional[dict] = None
    challengeExpirySeconds: Optional[int] = None

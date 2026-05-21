from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GrantTokenClaims:
    """Verified Grantex JWT claims seen by the seller SDK."""

    iss: str
    sub: str
    agt: str
    scp: List[str]
    grnt: str
    iat: int
    exp: int
    dev: Optional[str] = None
    nbf: Optional[int] = None
    parentAgt: Optional[str] = None
    parentGrnt: Optional[str] = None
    delegationDepth: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrantVerificationResult:
    """Result of seller-side Grantex token verification."""

    valid: bool
    claims: Optional[GrantTokenClaims] = None
    error: Optional[str] = None


@dataclass
class SellerGrantexConfig:
    """Seller-side Grantex verification settings.

    `enforceGrant=True` makes `decide_payment` reject missing or invalid
    `X-Grantex-Token` headers before attempting debit.
    """

    jwksUrl: str
    jwksCacheTtlMs: Optional[int] = None
    requiredScopes: Optional[List[str]] = None
    enforceGrant: bool = False

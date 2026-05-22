"""Plural MPP Seller SDK — Python port of `@plural/mpp-seller-sdk`.

Issues HTTP 402 challenges, verifies UPI SBMD credentials, captures
payments, and returns receipts — works standalone or as Flask / FastAPI
middleware.
"""
from .config.environments import DEFAULT_BASE_URL, DEFAULT_REALM, MppEnvironment
from .server import (
    AuthManager,
    CaptureClient,
    ChallengeGenerator,
    CredentialVerifier,
    PluralMPP,
    PluralMPPInstance,
    build_failure_receipt_data,
    build_receipt_data,
    build_receipt_header,
)
from .server.middleware import PaymentDecision, decide_payment
from .types import (
    Amount,
    CaptureOptions,
    CaptureResult,
    Challenge,
    ChallengeRequest,
    ChallengeResult,
    ChargeOptions,
    Credential,
    CredentialChallenge,
    CredentialPayload,
    MppErrorCode,
    PluralSellerConfig,
    ProblemDetails,
    ReceiptData,
    VerificationResult,
)
from .utils.errors import MppCaptureError, MppError, MppVerificationError

__all__ = [
    "Amount",
    "AuthManager",
    "CaptureClient",
    "CaptureOptions",
    "CaptureResult",
    "Challenge",
    "ChallengeGenerator",
    "ChallengeRequest",
    "ChallengeResult",
    "ChargeOptions",
    "Credential",
    "CredentialChallenge",
    "CredentialPayload",
    "CredentialVerifier",
    "DEFAULT_BASE_URL",
    "DEFAULT_REALM",
    "MppCaptureError",
    "MppEnvironment",
    "MppError",
    "MppErrorCode",
    "MppVerificationError",
    "PaymentDecision",
    "PluralMPP",
    "PluralMPPInstance",
    "PluralSellerConfig",
    "ProblemDetails",
    "ReceiptData",
    "VerificationResult",
    "build_failure_receipt_data",
    "build_receipt_data",
    "build_receipt_header",
    "decide_payment",
]

__version__ = "0.1.0"

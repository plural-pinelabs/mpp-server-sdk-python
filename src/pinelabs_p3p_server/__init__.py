"""Pine Labs Online P3P Server SDK — Python port of `@pine-labs-online/p3p-server-sdk`.

Issues HTTP 402 challenges, verifies P3P payment credentials, captures
payments, and returns receipts — works standalone or as Flask / FastAPI
middleware.
"""
from .config.environments import DEFAULT_BASE_URL, DEFAULT_REALM, P3PEnvironment
from .server import (
    ApiClient,
    AuthManager,
    CaptureClient,
    ChallengeGenerator,
    CredentialVerifier,
    PineLabsOnlineP3P,
    PineLabsOnlineP3PInstance,
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
    CreateMandateOptions,
    Credential,
    CredentialChallenge,
    CredentialPayload,
    Mandate,
    MandateChallenge,
    P3PErrorCode,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineServerConfig,
    ProblemDetails,
    ReceiptData,
    VerificationResult,
)
from .utils.errors import P3PCaptureError, P3PError, P3PVerificationError

__all__ = [
    "Amount",
    "ApiClient",
    "AuthManager",
    "CaptureClient",
    "CaptureOptions",
    "CaptureResult",
    "Challenge",
    "ChallengeGenerator",
    "ChallengeRequest",
    "ChallengeResult",
    "ChargeOptions",
    "CreateMandateOptions",
    "Credential",
    "CredentialChallenge",
    "CredentialPayload",
    "CredentialVerifier",
    "DEFAULT_BASE_URL",
    "DEFAULT_REALM",
    "Mandate",
    "MandateChallenge",
    "P3PCaptureError",
    "P3PEnvironment",
    "P3PError",
    "P3PErrorCode",
    "P3PVerificationError",
    "PaymentGateway",
    "PaymentMethod",
    "PaymentDecision",
    "PineLabsOnlineP3P",
    "PineLabsOnlineP3PInstance",
    "PineLabsOnlineServerConfig",
    "ProblemDetails",
    "ReceiptData",
    "VerificationResult",
    "build_failure_receipt_data",
    "build_receipt_data",
    "build_receipt_header",
    "decide_payment",
]

__version__ = "0.1.0"

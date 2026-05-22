"""Framework-agnostic payment decision helper.

Given an incoming request's `Authorization` header, this function returns a
:class:`PaymentDecision` describing what to do next — serve a challenge,
reject the credential, or proceed with the handler (after capturing the
payment).

This is used by the Flask and FastAPI adapters, but can also be used
directly in any other framework (aiohttp, Django, Bottle, ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ...types.capture import CaptureResult
from ...types.challenge import ChallengeResult
from ...types.config import ChargeOptions, PluralSellerConfig
from ...types.credential import Credential
from ...utils.errors import MppCaptureError
from ..capture_client import CaptureClient
from ..challenge_generator import ChallengeGenerator
from ..credential_verifier import CredentialVerifier
from ..receipt_builder import build_receipt_header


@dataclass
class PaymentDecision:
    """The next step the framework adapter should take.

    One of:
      - action="challenge"  : return 402 with problem_details + headers
      - action="invalid"    : return 402 (invalid credential) with problem_details + headers
      - action="failed"     : return 402 (capture failed) with problem_details + headers
      - action="proceed"    : call the downstream handler; set response_headers
    """
    action: str
    status: int = 200
    headers: Dict[str, str] = None  # type: ignore[assignment]
    problem_details: Optional[Dict[str, Any]] = None
    capture_result: Optional[CaptureResult] = None
    credential: Optional[Credential] = None
    receipt_header: Optional[str] = None
    challenge_result: Optional[ChallengeResult] = None


def decide_payment(
    *,
    authorization_header: Optional[str],
    config: PluralSellerConfig,
    charge_options: ChargeOptions,
) -> PaymentDecision:
    """Return the next seller action for an incoming paid-resource request.

    This helper is framework-agnostic. It either creates a fresh 402 challenge,
    rejects invalid payment credentials, captures the payment, or returns
    headers that allow the application handler to proceed.
    """
    challenge_generator = ChallengeGenerator(config)
    credential_verifier = CredentialVerifier(config)

    if not authorization_header or not authorization_header.startswith("Payment "):
        result = challenge_generator.generate(charge_options)
        return PaymentDecision(
            action="challenge",
            status=402,
            headers={
                "WWW-Authenticate": f"Payment {result.encoded}",
                "Content-Type": "application/problem+json",
                "Cache-Control": "no-store",
            },
            problem_details={
                "type": result.problemDetails.type,
                "title": result.problemDetails.title,
                "status": result.problemDetails.status,
                "detail": result.problemDetails.detail,
                "challengeId": result.problemDetails.challengeId,
            },
            challenge_result=result,
        )

    verification = credential_verifier.verify(authorization_header)
    if not verification.valid:
        result = challenge_generator.generate(charge_options)
        return PaymentDecision(
            action="invalid",
            status=402,
            headers={
                "WWW-Authenticate": f"Payment {result.encoded}",
                "Content-Type": "application/problem+json",
                "Cache-Control": "no-store",
            },
            problem_details={
                "type": result.problemDetails.type.replace("payment-required", "payment-invalid"),
                "title": "Invalid Payment Credential",
                "status": 402,
                "detail": verification.error or "The payment credential could not be verified.",
                "challengeId": result.challenge.id,
            },
            challenge_result=result,
        )

    credential = verification.credential
    assert credential is not None
    capture_client = CaptureClient(config)
    try:
        from ...types.capture import CaptureOptions
        capture_result = capture_client.capture(
            CaptureOptions(
                token=credential.payload.token,
                amount=charge_options.amount,
                description=charge_options.description,
                merchantOrderReference=charge_options.merchantOrderReference,
                metadata=charge_options.metadata,
            )
        )
    except MppCaptureError as exc:
        capture_error = exc.capture_error
        if capture_error is not None and capture_error.http_status >= 500:
            return PaymentDecision(
                action="error",
                status=502,
                headers={"Content-Type": "application/problem+json"},
                problem_details={
                    "type": "urn:plural:error:payment-capture-failed",
                    "title": "Payment Capture Failed",
                    "status": 502,
                    "detail": str(exc),
                    "upstream": {
                        "code": capture_error.code,
                        "http_status": capture_error.http_status,
                        "details": capture_error.details,
                    },
                },
            )
        result = challenge_generator.generate(charge_options)
        return PaymentDecision(
            action="failed",
            status=402,
            headers={
                "WWW-Authenticate": f"Payment {result.encoded}",
                "Content-Type": "application/problem+json",
                "Cache-Control": "no-store",
            },
            problem_details={
                "type": result.problemDetails.type.replace("payment-required", "payment-failed"),
                "title": "Payment Failed",
                "status": 402,
                "detail": "Previous payment token was invalid or expired. New challenge issued.",
                "challengeId": result.challenge.id,
            },
            challenge_result=result,
        )

    receipt_header = build_receipt_header(capture_result, credential.challenge.id)
    return PaymentDecision(
        action="proceed",
        status=200,
        headers={"Payment-Receipt": receipt_header},
        capture_result=capture_result,
        credential=credential,
        receipt_header=receipt_header,
    )

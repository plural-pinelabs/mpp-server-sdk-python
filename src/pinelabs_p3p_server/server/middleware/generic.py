"""Framework-agnostic payment decision helper.

Given an incoming request's `P3P-Credential` header, this function returns a
:class:`PaymentDecision` describing what to do next — serve a challenge,
reject the credential, or proceed with the handler (after capturing the
payment).

This is used by the Flask and FastAPI adapters, but can also be used
directly in any other framework (aiohttp, Django, Bottle, ...).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from ...types.capture import CaptureResult, is_pending_debit_status
from ...types.challenge import ChallengeResult
from ...grantex import GrantTokenVerifier
from ...grantex_hosted import HostedGrantexError, create_hosted_grantex_client
from ...types.config import (
    GRANTEX_TOKEN_HEADER,
    ChargeOptions,
    GrantexBudgetDebitOptions,
    GrantexVerificationResult,
    PineLabsOnlineServerConfig,
)
from ...types.credential import Credential
from ...utils.errors import P3PCaptureError
from ..capture_client import CaptureClient
from ..challenge_generator import ChallengeGenerator
from ..credential_verifier import CredentialVerifier
from ..receipt_builder import build_receipt_header

MAX_TRANSACTION_SCOPE_PREFIX = "mpp:payment:max_txn_paise:"


@dataclass
class PaymentDecision:
    """The next step the framework adapter should take.

    One of:
      - action="challenge"  : return 402 with problem_details + headers
      - action="invalid"    : return 402 (invalid credential) with problem_details + headers
      - action="failed"     : return upstream payment failure with problem_details + headers
      - action="pending"    : return 202 with pending body + headers
      - action="proceed"    : call the downstream handler; set response_headers
    """
    action: str
    status: int = 200
    headers: Dict[str, str] = None  # type: ignore[assignment]
    problem_details: Optional[Dict[str, Any]] = None
    pending_body: Optional[Dict[str, Any]] = None
    capture_result: Optional[CaptureResult] = None
    credential: Optional[Credential] = None
    receipt_header: Optional[str] = None
    challenge_result: Optional[ChallengeResult] = None
    grant_result: Optional[GrantexVerificationResult] = None


def decide_payment(
    *,
    credential_header: Optional[str] = None,
    authorization_header: Optional[str] = None,
    grantex_token_header: Optional[str] = None,
    config: PineLabsOnlineServerConfig,
    charge_options: ChargeOptions,
) -> PaymentDecision:
    """Return the next server action for an incoming paid-resource request.

    This helper is framework-agnostic. It either creates a fresh 402 challenge,
    rejects invalid payment credentials, captures the payment, or returns
    headers that allow the application handler to proceed.
    """
    challenge_generator = ChallengeGenerator(config)
    credential_verifier = CredentialVerifier(config)

    grant_result = _verify_grantex_if_present(config, grantex_token_header)
    grant_decision = _decide_grant(config, grantex_token_header, grant_result)
    if grant_decision is not None:
        return grant_decision
    transaction_cap_decision = _decide_transaction_cap(config, charge_options, grant_result)
    if transaction_cap_decision is not None:
        return transaction_cap_decision

    header_value = credential_header if credential_header is not None else authorization_header
    if not header_value or not header_value.startswith("Payment "):
        budget_decision = _check_hosted_budget_before_challenge(config, charge_options, grant_result)
        if budget_decision is not None:
            return budget_decision
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

    verification = credential_verifier.verify(header_value)
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
                paymentMethod=credential.payload.payment_method,
                paymentMethodReferenceId=getattr(credential.payload, "payment_method_reference_id", None),
                mobileNumber=getattr(credential.payload, "mobile_number", None),
                challengeId=credential.challenge.id,
            )
        )
    except Exception as exc:
        capture_error = exc.capture_error if isinstance(exc, P3PCaptureError) else None
        if capture_error is not None:
            is_gateway_error = capture_error.http_status >= 500
            return PaymentDecision(
                action="error" if is_gateway_error else "failed",
                status=502 if is_gateway_error else capture_error.http_status,
                headers={"Content-Type": "application/json"},
                problem_details={
                    "code": capture_error.code,
                    "message": str(capture_error),
                },
            )
        return PaymentDecision(
            action="error",
            status=502,
            headers={"Content-Type": "application/json"},
            problem_details={
                "code": "CAPTURE_FAILED",
                "message": str(exc) if isinstance(exc, P3PCaptureError) else "Capture failed",
            },
        )

    if _is_pending_capture_result(capture_result):
        pending_body = _pending_capture_body(capture_result)
        return PaymentDecision(
            action="pending",
            status=202,
            headers={"Content-Type": "application/json"},
            problem_details=pending_body,
            pending_body=pending_body,
            capture_result=capture_result,
            credential=credential,
            grant_result=grant_result,
        )

    _debit_hosted_budget_after_capture(config, charge_options, grant_result)
    receipt_header = build_receipt_header(
        capture_result,
        credential.challenge.id,
        config.paymentGateway,
        credential.payload.payment_method,
    )
    return PaymentDecision(
        action="proceed",
        status=200,
        headers={"Payment-Receipt": receipt_header},
        capture_result=capture_result,
        credential=credential,
        receipt_header=receipt_header,
        grant_result=grant_result,
    )


def _decide_grant(
    config: PineLabsOnlineServerConfig,
    grant_token_header: Optional[str],
    result: Optional[GrantexVerificationResult],
) -> Optional[PaymentDecision]:
    if config.grantex is None:
        return None

    token = (grant_token_header or "").strip()
    enforce_grant = (
        config.grantex.enforce_grant
        if config.grantex.enforce_grant is not None
        else config.grantex.enforceGrant
    )

    if not token:
        if enforce_grant:
            grant_result = GrantexVerificationResult(valid=False, error="Missing grant token")
            return PaymentDecision(
                action="grant_required",
                status=403,
                headers={"Content-Type": "application/problem+json", "Cache-Control": "no-store"},
                problem_details={
                    "type": "urn:ietf:rfc:9725:error:grant-required",
                    "title": "Grant Token Required",
                    "status": 403,
                    "detail": f"A valid Grantex grant token is required in the {GRANTEX_TOKEN_HEADER} header.",
                },
                grant_result=grant_result,
            )
        return None

    if result is None or result.valid:
        return None

    if config.logger is not None:
        config.logger.error("Grantex grant verification failed", {"error": result.error})
    if enforce_grant:
        return PaymentDecision(
            action="grant_invalid",
            status=403,
            headers={"Content-Type": "application/problem+json", "Cache-Control": "no-store"},
            problem_details={
                "type": "urn:ietf:rfc:9725:error:grant-invalid",
                "title": "Invalid Grant Token",
                "status": 403,
                "detail": "The grant token could not be verified.",
            },
            grant_result=result,
        )
    return None


def _decide_transaction_cap(
    config: PineLabsOnlineServerConfig,
    charge_options: ChargeOptions,
    result: Optional[GrantexVerificationResult],
) -> Optional[PaymentDecision]:
    if not _is_grant_enforced(config) or result is None or not result.valid or result.grant is None:
        return None
    max_transaction_paise = _extract_max_transaction_paise(_grant_scopes(result.grant))
    if max_transaction_paise is None or charge_options.amount.value <= max_transaction_paise:
        return None
    return PaymentDecision(
        action="grant_invalid",
        status=403,
        headers={"Content-Type": "application/problem+json", "Cache-Control": "no-store"},
        problem_details={
            "type": "urn:ietf:rfc:9725:error:transaction-limit-exceeded",
            "title": "Transaction Limit Exceeded",
            "status": 403,
            "detail": f"The charge amount {charge_options.amount.value} exceeds the Grantex per-transaction cap {max_transaction_paise}.",
        },
        grant_result=GrantexVerificationResult(
            valid=False,
            grant=result.grant,
            error="Grantex per-transaction cap exceeded",
        ),
    )


def _check_hosted_budget_before_challenge(
    config: PineLabsOnlineServerConfig,
    charge_options: ChargeOptions,
    result: Optional[GrantexVerificationResult],
) -> Optional[PaymentDecision]:
    if config.grantex is None or not _is_grant_enforced(config) or config.grantex.hosted is None:
        return None
    debit_before_challenge = (
        config.grantex.debit_budget_before_challenge
        if config.grantex.debit_budget_before_challenge is not None
        else config.grantex.debitBudgetBeforeChallenge
    )
    # Match TypeScript: skip only when explicitly False, not when None/unset
    if debit_before_challenge is False or result is None or not result.valid or result.grant is None:
        return None
    grant_id = _grant_value(result.grant, "grantId", "grant_id") or _grant_value(result.grant, "id")
    try:
        balance = create_hosted_grantex_client(config.grantex.hosted).get_budget_balance(grant_id)
        remaining_paise = _grantex_major_to_paise(balance.remainingBudget)
        if remaining_paise < charge_options.amount.value:
            return PaymentDecision(
                action="grant_invalid",
                status=403,
                headers={"Content-Type": "application/problem+json", "Cache-Control": "no-store"},
                problem_details={
                    "type": "urn:ietf:rfc:9725:error:budget-exceeded",
                    "title": "Grant Budget Exceeded",
                    "status": 403,
                    "detail": (
                        f"The Grantex grant budget has {remaining_paise} paise remaining, "
                        f"which is less than the charge amount {charge_options.amount.value} paise."
                    ),
                },
                grant_result=GrantexVerificationResult(
                    valid=False,
                    grant=result.grant,
                    error="Grantex grant budget exceeded",
                ),
            )
        return None
    except Exception as exc:
        hosted_error = exc if isinstance(exc, HostedGrantexError) else HostedGrantexError(str(exc))
        if config.logger is not None:
            config.logger.error(
                "Grantex budget check failed",
                {"error": str(hosted_error), "status": hosted_error.status, "code": hosted_error.code},
            )
        return PaymentDecision(
            action="grant_invalid",
            status=403,
            headers={"Content-Type": "application/problem+json", "Cache-Control": "no-store"},
            problem_details={
                "type": "urn:ietf:rfc:9725:error:budget-exceeded",
                "title": "Grant Budget Exceeded",
                "status": 403,
                "detail": "The Grantex grant budget could not be checked.",
            },
            grant_result=GrantexVerificationResult(
                valid=False,
                grant=result.grant,
                error=str(hosted_error) or "The Grantex grant budget could not be checked.",
            ),
        )


def _debit_hosted_budget_after_capture(
    config: PineLabsOnlineServerConfig,
    charge_options: ChargeOptions,
    result: Optional[GrantexVerificationResult],
) -> None:
    if config.grantex is None or not _is_grant_enforced(config) or config.grantex.hosted is None:
        return
    debit_before_challenge = (
        config.grantex.debit_budget_before_challenge
        if config.grantex.debit_budget_before_challenge is not None
        else config.grantex.debitBudgetBeforeChallenge
    )
    # Match TypeScript: skip only when explicitly False, not when None/unset
    if debit_before_challenge is False or result is None or not result.valid or result.grant is None:
        return
    grant_id = _grant_value(result.grant, "grantId", "grant_id") or _grant_value(result.grant, "id")
    try:
        create_hosted_grantex_client(config.grantex.hosted).debit_budget(
            GrantexBudgetDebitOptions(
                grantId=grant_id,
                amount=_paise_to_grantex_major(charge_options.amount.value),
                description=charge_options.description or "P3P payment capture",
                metadata={
                    "resource": charge_options.resource,
                    "currency": charge_options.amount.currency,
                    **(charge_options.metadata or {}),
                },
            )
        )
    except Exception as exc:
        hosted_error = exc if isinstance(exc, HostedGrantexError) else HostedGrantexError(str(exc))
        if config.logger is not None:
            config.logger.error(
                "Grantex budget debit failed after successful capture",
                {"error": str(hosted_error), "status": hosted_error.status, "code": hosted_error.code},
            )


def _verify_grantex_if_present(
    config: PineLabsOnlineServerConfig,
    grant_token_header: Optional[str],
) -> Optional[GrantexVerificationResult]:
    if config.grantex is None or not (grant_token_header or "").strip():
        return None
    return GrantTokenVerifier(config.grantex).verify(grant_token_header or "")


def _is_grant_enforced(config: PineLabsOnlineServerConfig) -> bool:
    if config.grantex is None:
        return False
    return bool(
        config.grantex.enforce_grant
        if config.grantex.enforce_grant is not None
        else config.grantex.enforceGrant
    )


def _extract_max_transaction_paise(scopes: list[str]) -> Optional[int]:
    max_transaction_paise: Optional[int] = None
    for scope in scopes:
        if not scope.startswith(MAX_TRANSACTION_SCOPE_PREFIX):
            continue
        try:
            value = int(scope[len(MAX_TRANSACTION_SCOPE_PREFIX):])
        except ValueError:
            continue
        if value < 0:
            continue
        max_transaction_paise = value if max_transaction_paise is None else min(max_transaction_paise, value)
    return max_transaction_paise


def _grant_scopes(grant: Any) -> list[str]:
    scopes = _grant_value(grant, "scopes") or []
    return [str(scope) for scope in scopes] if isinstance(scopes, list) else []


def _paise_to_grantex_major(amount_paise: int) -> float:
    return float(Decimal(amount_paise) / Decimal("100"))


def _grantex_major_to_paise(amount: Any) -> int:
    return int((Decimal(str(amount)) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _grant_value(grant: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(grant, dict) and key in grant:
            return grant[key]
        if hasattr(grant, key):
            return getattr(grant, key)
    return None


def _is_pending_capture_result(capture_result: CaptureResult) -> bool:
    if bool(_capture_value(capture_result, "pending")):
        return True
    return is_pending_debit_status(_capture_value(capture_result, "status"))


def _pending_capture_body(capture_result: CaptureResult) -> Dict[str, Any]:
    status = str(_capture_value(capture_result, "status") or "PENDING")
    body: Dict[str, Any] = {
        "status": "PENDING",
        "idempotencyKey": str(
            _capture_value(capture_result, "idempotencyKey")
            or _capture_value(capture_result, "idempotency_key")
            or ""
        ),
        "message": str(
            _capture_value(capture_result, "message")
            or "Payment accepted and still processing"
        ),
        "debitStatus": status,
    }
    retry_after = _capture_value(capture_result, "retryAfter")
    if retry_after is not None:
        body["retryAfter"] = retry_after
    return body


def _capture_value(capture_result: CaptureResult, key: str) -> Any:
    if isinstance(capture_result, dict):
        return capture_result.get(key)
    return getattr(capture_result, key, None)

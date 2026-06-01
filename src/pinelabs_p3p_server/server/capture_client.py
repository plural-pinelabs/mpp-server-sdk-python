from __future__ import annotations

import uuid
from typing import Any, Optional

import httpx

from ..config.environments import resolve_p3p_base_url
from ..types.capture import CaptureOptions, CaptureResult
from ..types.config import Amount, P3PLogger, PineLabsOnlineServerConfig
from ..utils.errors import P3PCaptureError, P3PError
from ..utils.fetch_helpers import request_with_retry
from ..utils.validation import normalize_mobile_number
from .auth_manager import AuthManager


class CaptureClient:
    """HTTP client that executes server debits through the P3P service."""

    def __init__(self, config: PineLabsOnlineServerConfig, http_client: Optional[httpx.Client] = None) -> None:
        self._base_url = resolve_p3p_base_url(config.env).rstrip("/")
        self._payment_gateway = config.paymentGateway
        self._timeout_ms = config.requestTimeoutMs
        self._max_retries = config.maxRetries
        self._initial_retry_delay_ms = config.initialRetryDelayMs
        self._logger: Optional[P3PLogger] = config.logger
        self._http = http_client or httpx.Client()
        self._auth = AuthManager(
            config.clientId,
            config.clientSecret,
            self._base_url,
            self._http,
            self._timeout_ms,
            self._logger,
            self._max_retries,
            self._initial_retry_delay_ms,
        )

    def capture(self, options: CaptureOptions) -> CaptureResult:
        """Call `/mpp/v1/debit` with idempotency headers."""
        idempotency_key = options.idempotencyKey or options.merchantOrderReference or str(uuid.uuid4())
        _resolve_customer_reference(options)
        mobile_number = _resolve_mobile_number(options)
        challenge_id = _resolve_challenge_id(options)
        auth_token = self._auth.get_access_token()
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        payload = {
            "payment_method": _payment_method_value(options.paymentMethod),
            "customer": {"mobile_number": mobile_number},
            "payment_amount": {"value": int(options.amount.value), "currency": options.amount.currency},
            "payment_token": options.token,
            "challenge_id": challenge_id,
        }

        response = request_with_retry(
            self._http,
            "POST",
            f"{self._base_url}/mpp/v1/debit",
            headers=headers,
            json=payload,
            timeout_ms=self._timeout_ms,
            logger=self._logger,
            max_retries=self._max_retries,
            initial_retry_delay_ms=self._initial_retry_delay_ms,
        )

        if response.status_code >= 400:
            try:
                err_body = response.json()
            except Exception as exc:
                raise P3PCaptureError(f"Capture failed with status {response.status_code}") from exc
            raise P3PCaptureError(
                f"Capture failed: {err_body.get('error', {}).get('message', 'unknown error')}",
                P3PError.from_response(response.status_code, err_body),
            )

        payload = response.json()
        data = (payload.get("data", payload) if isinstance(payload, dict) else {}) or {}
        capture_result = _dict_to_capture_result(data)
        capture_result.payment_gateway = self._payment_gateway
        capture_result.payment_method = options.paymentMethod
        return capture_result


def _resolve_customer_reference(options: CaptureOptions) -> str:
    metadata = options.metadata or {}
    customer_reference = str(
        options.customerReference
        or metadata.get("customer_reference")
        or metadata.get("customerReference")
        or ""
    ).strip()
    if not customer_reference:
        raise P3PCaptureError("CaptureOptions: customerReference is required for P3P V2 debit")
    return customer_reference


def _resolve_mobile_number(options: CaptureOptions) -> str:
    metadata = options.metadata or {}
    mobile_number = normalize_mobile_number(
        options.mobileNumber
        or metadata.get("mobile_number", "")
        or metadata.get("mobileNumber", "")
    )
    if not mobile_number:
        raise P3PCaptureError("CaptureOptions: mobileNumber is required for P3P V2 debit")
    return mobile_number


def _resolve_challenge_id(options: CaptureOptions) -> str:
    challenge_id = str(options.challengeId or "").strip()
    if not challenge_id:
        raise P3PCaptureError("CaptureOptions: challengeId is required for P3P V2 debit")
    return challenge_id


def _payment_method_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _dict_to_capture_result(data: dict[str, Any]) -> CaptureResult:
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    amt = data.get("amount") or data.get("payment_amount") or data.get("paymentAmount") or {}
    if not isinstance(amt, dict):
        amt = {"value": amt, "currency": data.get("currency", "INR")}
    payment_data = data.get("payment_data") if isinstance(data.get("payment_data"), dict) else {}
    payment_sbmd_data = payment_data.get("sbmd_data") if isinstance(payment_data.get("sbmd_data"), dict) else {}
    metadata = data.get("metadata") or {}
    if payment_data:
        metadata = {**metadata, "payment_data": payment_data}
    sbmd_data = metadata.get("sbmd_data") or {}
    capture_id = (
        data.get("merchant_payment_debit_reference")
        or metadata.get("external_capture_id")
        or data.get("capture_id")
        or data.get("debit_id")
        or data.get("payment_id", "")
    )
    external_payment_id = (
        payment_sbmd_data.get("upstream_payment_id")
        or metadata.get("external_payment_id")
        or data.get("payment_id")
        or data.get("oms_payment_id")
        or ""
    )
    return CaptureResult(
        capture_id=capture_id,
        object=data.get("object", "debit"),
        mandate_id=data.get("payment_method_reference_id") or data.get("authorization_id") or data.get("mandate_id") or data.get("pre_authorization_id", ""),
        token_id=data.get("token_id") or data.get("payment_token", ""),
        customer_id=customer.get("customer_id") or data.get("customer_id") or customer.get("merchant_customer_reference") or data.get("customer_reference", ""),
        merchant_id=data.get("merchant_id", ""),
        order_id=payment_data.get("order_id") or data.get("oms_order_id") or data.get("order_id") or data.get("merchant_order_reference", ""),
        order_status=payment_data.get("order_status") or data.get("order_status") or data.get("status", ""),
        payment_id=external_payment_id or data.get("debit_id", ""),
        payment_status=payment_sbmd_data.get("upstream_payment_status") or metadata.get("upstream_payment_status") or payment_data.get("payment_status") or payment_data.get("order_status") or data.get("payment_status") or data.get("status", ""),
        amount=Amount(value=int(amt.get("value", 0) or 0), currency=amt.get("currency", data.get("currency", "INR"))),
        upi_txn_id=sbmd_data.get("upi_txn_id", data.get("upi_txn_id", "")),
        receipt=data.get("receipt") or {
            "reference": capture_id,
            "oms_payment_id": data.get("oms_payment_id", ""),
            "external_payment_id": external_payment_id,
        },
        description=data.get("description"),
        merchant_order_reference=data.get("merchant_order_reference") or data.get("merchant_payment_debit_reference"),
        metadata=metadata,
        settled_at=sbmd_data.get("settled_at", data.get("settled_at", "")),
        created_at=data.get("created_at", ""),
        raw=data,
    )

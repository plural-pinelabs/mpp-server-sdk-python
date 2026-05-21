from __future__ import annotations

import uuid
from typing import Any, Optional

import httpx

from ..config.environments import DEFAULT_BASE_URL
from ..types.capture import CaptureOptions, CaptureResult
from ..types.config import Amount, MppLogger, PluralSellerConfig
from ..utils.errors import MppCaptureError, MppError
from ..utils.fetch_helpers import request_with_retry
from ..utils.request_hash import build_request_hash
from .auth_manager import AuthManager


class CaptureClient:
    """HTTP client that executes seller debits through the MPP service."""

    def __init__(self, config: PluralSellerConfig, http_client: Optional[httpx.Client] = None) -> None:
        self._base_url = (config.baseUrl or DEFAULT_BASE_URL).rstrip("/")
        self._timeout_ms = config.requestTimeoutMs
        self._max_retries = config.maxRetries
        self._initial_retry_delay_ms = config.initialRetryDelayMs
        self._logger: Optional[MppLogger] = config.logger
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
            config.accessToken,
        )

    def capture(self, options: CaptureOptions) -> CaptureResult:
        """Call `/mpp/v1/debit` with idempotency and request-hash headers."""
        idempotency_key = options.idempotencyKey or str(uuid.uuid4())
        customer_reference = _resolve_customer_reference(options)
        auth_token = self._auth.get_access_token()
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        payload = {
            "type": options.paymentType,
            "customer_reference": customer_reference,
            "merchant_order_reference": options.merchantOrderReference or f"mpr-{uuid.uuid4().hex[:12]}",
            "amount": str(options.amount.value),
            "currency": options.amount.currency,
            "payment_token": options.token,
        }
        headers["Request-Hash"] = build_request_hash(payload)

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
                raise MppCaptureError(f"Capture failed with status {response.status_code}") from exc
            raise MppCaptureError(
                f"Capture failed: {err_body.get('error', {}).get('message', 'unknown error')}",
                MppError.from_response(response.status_code, err_body),
            )

        payload = response.json()
        data = (payload.get("data", payload) if isinstance(payload, dict) else {}) or {}
        return _dict_to_capture_result(data)


def _resolve_customer_reference(options: CaptureOptions) -> str:
    metadata = options.metadata or {}
    customer_reference = str(
        options.customerReference
        or metadata.get("customer_reference")
        or metadata.get("customerReference")
        or ""
    ).strip()
    if not customer_reference:
        raise MppCaptureError("CaptureOptions: customerReference is required for MPP V2 debit")
    return customer_reference


def _dict_to_capture_result(data: dict[str, Any]) -> CaptureResult:
    amt = data.get("amount") or {}
    if not isinstance(amt, dict):
        amt = {"value": amt, "currency": data.get("currency", "INR")}
    metadata = data.get("metadata") or {}
    sbmd_data = metadata.get("sbmd_data") or {}
    capture_id = (
        metadata.get("external_capture_id")
        or data.get("capture_id")
        or data.get("debit_id")
        or data.get("payment_id", "")
    )
    return CaptureResult(
        capture_id=capture_id,
        object=data.get("object", "debit"),
        mandate_id=data.get("authorization_id") or data.get("mandate_id") or data.get("pre_authorization_id", ""),
        token_id=data.get("token_id") or data.get("payment_token", ""),
        customer_id=data.get("customer_id") or data.get("customer_reference", ""),
        merchant_id=data.get("merchant_id", ""),
        order_id=data.get("oms_order_id") or data.get("order_id") or data.get("merchant_order_reference", ""),
        order_status=data.get("order_status") or data.get("status", ""),
        payment_id=data.get("payment_id") or data.get("oms_payment_id") or data.get("debit_id", ""),
        payment_status=metadata.get("upstream_payment_status") or data.get("payment_status") or data.get("status", ""),
        amount=Amount(value=int(amt.get("value", 0) or 0), currency=amt.get("currency", data.get("currency", "INR"))),
        upi_txn_id=sbmd_data.get("upi_txn_id", data.get("upi_txn_id", "")),
        receipt=data.get("receipt") or {
            "reference": data.get("payment_id", ""),
            "oms_payment_id": data.get("oms_payment_id", ""),
            "external_payment_id": metadata.get("external_payment_id", ""),
        },
        description=data.get("description"),
        merchant_order_reference=data.get("merchant_order_reference"),
        metadata=data.get("metadata"),
        settled_at=sbmd_data.get("settled_at", data.get("settled_at", "")),
        created_at=data.get("created_at", ""),
        raw=data,
    )

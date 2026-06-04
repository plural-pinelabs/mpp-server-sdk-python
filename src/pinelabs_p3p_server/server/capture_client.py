from __future__ import annotations

import time
import uuid
from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..config.environments import resolve_p3p_base_url
from ..types.capture import CaptureOptions, CaptureResult
from ..types.config import Amount, P3PLogger, PineLabsOnlineServerConfig
from ..utils.errors import P3PCaptureError, P3PError
from ..utils.fetch_helpers import (
    DEFAULT_INITIAL_RETRY_DELAY_MS,
    DEFAULT_MAX_RETRIES,
    request_with_retry,
)
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

        pending_attempts = 0
        while True:
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

            if response.status_code == 202:
                retry_after_ms = _resolve_pending_retry_after_ms(
                    response.headers.get("Retry-After"),
                    self._initial_retry_delay_ms,
                )
                result = _capture_result_from_response(
                    response,
                    self._payment_gateway,
                    idempotency_key,
                    pending=True,
                    retry_after_ms=retry_after_ms,
                )
                if pending_attempts >= _effective_max_retries(self._max_retries):
                    return result
                pending_attempts += 1
                time.sleep(retry_after_ms / 1000.0)
                continue

            if response.status_code >= 400:
                _raise_capture_error(response)

            return _capture_result_from_response(response, self._payment_gateway, idempotency_key)

    def get_debit_status(self, idempotency_key: str) -> CaptureResult:
        """Fetch the latest debit status via `GET /mpp/v1/debit/{id}`."""
        if not str(idempotency_key or "").strip():
            raise ValueError("idempotency_key is required")

        auth_token = self._auth.get_access_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {auth_token}",
        }
        response = request_with_retry(
            self._http,
            "GET",
            f"{self._base_url}/mpp/v1/debit/{quote(str(idempotency_key), safe='')}",
            headers=headers,
            timeout_ms=self._timeout_ms,
            logger=self._logger,
            max_retries=self._max_retries,
            initial_retry_delay_ms=self._initial_retry_delay_ms,
        )
        if response.status_code >= 400:
            _raise_capture_error(response)
        return _capture_result_from_response(response, self._payment_gateway, str(idempotency_key))


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


def _effective_max_retries(value: Optional[int]) -> int:
    return DEFAULT_MAX_RETRIES if value is None else value


def _resolve_pending_retry_after_ms(retry_after: Optional[str], configured_delay_ms: Optional[int]) -> int:
    if retry_after is not None:
        try:
            seconds = float(retry_after)
        except (TypeError, ValueError):
            seconds = None
        if seconds is not None and seconds >= 0:
            return int(seconds * 1000)
    return configured_delay_ms or DEFAULT_INITIAL_RETRY_DELAY_MS


def _raise_capture_error(response: httpx.Response) -> None:
    try:
        err_body = response.json()
    except Exception as exc:
        raise P3PCaptureError(f"Capture failed with status {response.status_code}") from exc
    raise P3PCaptureError(
        f"Capture failed: {err_body.get('error', {}).get('message', 'unknown error')}",
        P3PError.from_response(response.status_code, err_body),
    )


def _capture_result_from_response(
    response: httpx.Response,
    payment_gateway: Any,
    idempotency_key: str,
    *,
    pending: bool = False,
    retry_after_ms: Optional[int] = None,
) -> CaptureResult:
    payload = response.json()
    data = (payload.get("data", payload) if isinstance(payload, dict) else {}) or {}
    result = CaptureResult(
        **data,
        payment_gateway=payment_gateway,
        idempotencyKey=idempotency_key,
        idempotency_key=idempotency_key,
    )
    if pending:
        result.pending = True
        result.message = "Payment accepted and still processing"
        if retry_after_ms is not None:
            result.retryAfter = retry_after_ms
    return result

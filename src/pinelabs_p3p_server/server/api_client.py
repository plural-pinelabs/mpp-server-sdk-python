from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from ..config.environments import resolve_p3p_base_url
from ..types.config import Amount, CreateMandateOptions, Mandate, MandateChallenge, P3PLogger, PineLabsOnlineServerConfig
from ..utils.errors import P3PError
from ..utils.fetch_helpers import request_with_retry
from ..utils.validation import normalize_mobile_number, validate_create_mandate_options
from .auth_manager import AuthManager


class ApiClient:
    """Low-level server P3P service client for mandate/pre-authorization APIs."""

    def __init__(self, config: PineLabsOnlineServerConfig, http_client: Optional[httpx.Client] = None) -> None:
        self._config = config
        self._base_url = resolve_p3p_base_url(config.env).rstrip("/")
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

    def create_mandate(self, options: CreateMandateOptions) -> Mandate:
        """Create a mandate/pre-authorization via `POST /mpp/v1/pre-authorize`."""
        validate_create_mandate_options(options)
        mobile_number = normalize_mobile_number(options.mobileNumber or "")
        customer_reference = options.customerReference or options.customerId or mobile_number
        payment_method = options.paymentMethod or self._config.availablePaymentMethods[0]
        body: Dict[str, Any] = {
            "payment_method": _payment_method_value(payment_method),
            "customer": _customer_payload(customer_reference, mobile_number),
            "amount": _amount_payload(options.amount),
            "validity_in_days": options.validityInDays or 7,
        }
        if options.description:
            body["description"] = options.description

        data = self._request(
            "POST",
            "/mpp/v1/pre-authorize",
            body,
            {"Idempotency-Key": options.idempotencyKey or str(uuid.uuid4())},
        )
        return _parse_mandate(data)

    def get_mandate(self, mandate_id: str) -> Mandate:
        """Fetch mandate/pre-authorization status through `GET /mpp/v1/authorization/{id}`."""
        if not mandate_id:
            raise ValueError("mandate_id is required")
        data = self._request("GET", f"/mpp/v1/authorization/{quote(mandate_id, safe='')}")
        return _parse_mandate(data)

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        token = self._auth.get_access_token()
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if extra_headers:
            headers.update(extra_headers)
        json_body = None
        if body is not None and method != "GET":
            headers["Content-Type"] = "application/json"
            json_body = body

        response = request_with_retry(
            self._http,
            method,
            f"{self._base_url}{path}",
            headers=headers,
            json=json_body,
            timeout_ms=self._timeout_ms,
            logger=self._logger,
            max_retries=self._max_retries,
            initial_retry_delay_ms=self._initial_retry_delay_ms,
        )
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {"error": {"code": "MPP_INTERNAL_ERROR", "message": f"HTTP {response.status_code}"}}
            raise P3PError.from_response(response.status_code, body)

        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload


def _customer_payload(customer_reference: str, mobile_number: str) -> Dict[str, str]:
    if mobile_number:
        return {"mobile_number": mobile_number}
    return {"merchant_customer_reference": customer_reference}


def _amount_payload(amount: Amount) -> Dict[str, Any]:
    return {"value": int(amount.value), "currency": amount.currency}


def _payment_method_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _amount_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(float(value or 0))


def _parse_mandate(data: Dict[str, Any]) -> Mandate:
    metadata = data.get("metadata") or {}
    sbmd_data = metadata.get("sbmd_data") or metadata.get("sbmdData") or {}
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    challenge = data.get("challenge")
    challenge_url = data.get("challenge_url") or data.get("challengeUrl")
    mandate_challenge = None
    if challenge or challenge_url:
        challenge = challenge or {}
        mandate_challenge = MandateChallenge(
            type=challenge.get("type", sbmd_data.get("challenge_type", "")),
            qr_url=challenge.get("qr_url", challenge_url or ""),
            deep_link=challenge.get("deep_link", challenge_url or ""),
            expires_at=challenge.get("expires_at", data.get("expiry_at", sbmd_data.get("expires_at", ""))),
        )

    amt = data.get("payment_amount") or data.get("paymentAmount") or data.get("amount") or {}
    amount_value = amt.get("value", data.get("amount_value", metadata.get("amount", 0))) if isinstance(amt, dict) else data.get("amount_value", metadata.get("amount", 0))
    amount_currency = amt.get("currency", data.get("amount_currency", metadata.get("currency", "INR"))) if isinstance(amt, dict) else data.get("amount_currency", metadata.get("currency", "INR"))
    status = data.get("payment_status") or data.get("order_status") or data.get("status", "")
    return Mandate(
        mandate_id=data.get("payment_method_reference_id") or data.get("authorization_id") or data.get("authorizationId") or data.get("mandate_id") or data.get("mandateId") or metadata.get("external_subscription_id") or "",
        object=data.get("object", "mandate"),
        order_id=data.get("order_id", sbmd_data.get("order_id", "")),
        order_status=data.get("order_status", status),
        payment_status=data.get("payment_status", status),
        customer_reference=customer.get("merchant_customer_reference", data.get("merchant_customer_reference", data.get("customer_reference", data.get("customer_id", "")))),
        customer_id=customer.get("customer_id", data.get("customer_id", data.get("customer_reference", ""))),
        agent_id=data.get("agent_id", ""),
        amount=Amount(value=_amount_int(amount_value), currency=amount_currency),
        amount_blocked=data.get("amount_blocked", sbmd_data.get("amount_blocked", 0)),
        amount_debited=data.get("amount_debited", sbmd_data.get("amount_debited", 0)),
        amount_held=data.get("amount_held", sbmd_data.get("amount_held", 0)),
        amount_available=data.get("amount_available", sbmd_data.get("amount_available", 0)),
        mobile_number=customer.get("mobile_number", data.get("mobile_number", "")),
        description=data.get("description", metadata.get("description")),
        metadata=metadata,
        expires_at=data.get("expiry_at", data.get("expires_at", sbmd_data.get("expires_at", ""))),
        created_at=data.get("created_at", sbmd_data.get("created_at", "")),
        challenge=mandate_challenge,
        raw=data,
    )

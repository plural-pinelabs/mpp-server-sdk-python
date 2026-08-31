from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from ..config.environments import resolve_p3p_base_url
from ..types.config import (
    Amount,
    CreateMandateOptions,
    CreateMandateRevokeOptions,
    CreatePreAuthorizationOptions,
    Mandate,
    MandateBalanceCustomer,
    MandateBalanceDetails,
    MandateBalanceLookupOptions,
    MandateBalanceResult,
    MandateChallenge,
    MandateRevokeResult,
    P3PLogger,
    PineLabsOnlineServerConfig,
    PreAuthorization,
    PreAuthorizationCustomer,
)
from ..utils.errors import P3PError
from ..utils.fetch_helpers import request_with_retry
from ..utils.validation import (
    normalize_mobile_number,
    validate_create_mandate_options,
    validate_create_mandate_revoke_options,
    validate_mandate_balance_lookup_options,
)
from ..types.payment import PaymentMethod
from ..types.orders import CreateRefundOptions, Order, Refund
from .auth_manager import AuthManager
from .order_parsers import parse_order, parse_refund


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
        data = self._create_pre_authorization_request(options)
        return _parse_mandate(data)

    def create_pre_authorization(self, options: CreatePreAuthorizationOptions) -> PreAuthorization:
        """Create a card/mandate pre-authorization and return the service contract shape."""
        data = self._create_pre_authorization_request(options)
        return _parse_pre_authorization(data)

    def _create_pre_authorization_request(self, options: CreateMandateOptions) -> Any:
        validate_create_mandate_options(options)
        mobile_number = normalize_mobile_number(options.mobileNumber or "")
        payment_method = options.paymentMethod or self._config.availablePaymentMethods[0]
        body: Dict[str, Any] = {
            "payment_method": _payment_method_value(payment_method).upper(),
            "customer": _customer_payload(mobile_number),
            "amount": _amount_payload(options.amount),
            "validity_in_days": options.validityInDays or 7,
        }
        if options.description:
            body["description"] = options.description
        payment_method_options = (
            options.paymentMethodOptions
            if options.paymentMethodOptions is not None
            else options.payment_method_options
        )
        if payment_method_options is not None:
            body["payment_method_options"] = payment_method_options
        merchant_metadata = (
            options.merchantMetadata
            if options.merchantMetadata is not None
            else options.merchant_metadata
        )
        if merchant_metadata is not None:
            body["merchant_metadata"] = _merchant_metadata_payload(merchant_metadata)

        data = self._request(
            "POST",
            "/mpp/v1/pre-authorize",
            body,
            {"Idempotency-Key": options.idempotencyKey or str(uuid.uuid4())},
        )
        return _with_checkout_redirect_url(data, self._base_url) if _is_redirect_payment_method(payment_method) else data

    def get_mandate(self, mandate_id: str) -> Mandate:
        """Fetch mandate/pre-authorization status through `GET /mpp/v1/authorization/{id}`."""
        if not mandate_id:
            raise ValueError("mandate_id is required")
        data = self._request("GET", f"/mpp/v1/authorization/{quote(mandate_id, safe='')}")
        return _parse_mandate(data)

    def get_order(self, order_id: str) -> Order:
        """Retrieve an order through `GET /api/pay/v1/orders/{order_id}`."""
        normalized_order_id = order_id.strip()
        if not normalized_order_id:
            raise ValueError("order_id is required")
        data = self._request("GET", f"/api/pay/v1/orders/{quote(normalized_order_id, safe='')}")
        return parse_order(data)

    def create_refund(self, order_id: str, options: CreateRefundOptions) -> Refund:
        """Initiate a refund through `POST /api/pay/v1/refunds/{order_id}`."""
        normalized_order_id = order_id.strip()
        merchant_order_reference = options.merchantOrderReference.strip()
        currency = options.orderAmount.currency.strip()
        if not normalized_order_id:
            raise ValueError("order_id is required")
        if not merchant_order_reference:
            raise ValueError("CreateRefundOptions: merchantOrderReference is required")
        if not isinstance(options.orderAmount.value, int) or isinstance(options.orderAmount.value, bool) or options.orderAmount.value <= 0:
            raise ValueError("CreateRefundOptions: orderAmount.value must be a positive integer (paise)")
        if not currency:
            raise ValueError("CreateRefundOptions: orderAmount.currency is required")

        body: Dict[str, Any] = {
            "merchant_order_reference": merchant_order_reference,
            "order_amount": {"value": options.orderAmount.value, "currency": currency},
        }
        if options.merchantMetadata is not None:
            body["merchant_metadata"] = options.merchantMetadata
        data = self._request(
            "POST",
            f"/api/pay/v1/refunds/{quote(normalized_order_id, safe='')}",
            body,
            {
                "Request-ID": str(uuid.uuid4()),
                "Request-Timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        return parse_refund(data)

    def get_mandate_balance(self, options: MandateBalanceLookupOptions) -> MandateBalanceResult:
        """Fetch mandate balance / authorization status through `GET /mpp/v1/balance`."""
        validate_mandate_balance_lookup_options(options)
        params: Dict[str, str] = {}
        if options.authorizationId:
            params["authorization_id"] = options.authorizationId
            if options.phoneNumber:
                params["phone_number"] = normalize_mobile_number(options.phoneNumber)
        else:
            params["phone_number"] = normalize_mobile_number(options.phoneNumber or "")
            params["type"] = _payment_method_value(options.paymentMethod)
        data = self._request("GET", f"/mpp/v1/balance?{httpx.QueryParams(params)}")
        return _parse_mandate_balance_result(data)

    def revoke_mandate(self, options: CreateMandateRevokeOptions) -> MandateRevokeResult:
        """Create a mandate revoke request through `POST /mpp/v1/revoke`."""
        validate_create_mandate_revoke_options(options)
        customer = options.customer or {}
        if hasattr(customer, "__dict__"):
            customer = customer.__dict__
        body: Dict[str, Any] = {
            "payment_method": _payment_method_value(options.paymentMethod),
        }
        if options.paymentMethodReferenceId:
            body["payment_method_reference_id"] = options.paymentMethodReferenceId
        if customer:
            customer_payload: Dict[str, str] = {}
            if customer.get("merchantCustomerReference"):
                customer_payload["merchant_customer_reference"] = str(customer["merchantCustomerReference"])
            if customer.get("mobileNumber"):
                customer_payload["mobile_number"] = normalize_mobile_number(str(customer["mobileNumber"]))
            if customer_payload:
                body["customer"] = customer_payload
        data = self._request("POST", "/mpp/v1/revoke", body)
        return _parse_mandate_revoke_result(data)

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
        headers["Merchant-ID"] = self._config.merchantId
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


def _customer_payload(mobile_number: str) -> Dict[str, str]:
    return {"mobile_number": mobile_number}


def _amount_payload(amount: Amount) -> Dict[str, Any]:
    return {"value": int(amount.value), "currency": amount.currency}


def _with_checkout_redirect_url(data: Any, base_url: str) -> Any:
    if not isinstance(data, dict) or data.get("redirect_url") or data.get("redirectUrl"):
        return data
    token = str(data.get("token") or "").strip()
    if not token:
        return data
    return {
        **data,
        "redirect_url": f"{base_url}/api/v3/checkout-bff/redirect/checkout?token={_encode_checkout_token(token)}",
    }


def _encode_checkout_token(token: str) -> str:
    try:
        return quote(bytes(token, "utf-8").decode("utf-8"), safe="") if "%" not in token else quote(bytes(token, "utf-8").decode("utf-8"), safe="%")
    except Exception:
        return quote(token, safe="")


def _payment_method_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _merchant_metadata_payload(metadata: Dict[str, Any]) -> Dict[str, str]:
    """Serialize structured SDK metadata into Pine's string-valued wire map."""
    return {
        str(key): value if isinstance(value, str) else json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        for key, value in metadata.items()
    }


def _is_redirect_payment_method(value: Any) -> bool:
    return _payment_method_value(value).upper() in ("CARD", "CREDIT_EMI")


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
    challenge_url = data.get("challenge_url") or data.get("challengeUrl") or data.get("redirect_url") or data.get("redirectUrl")
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
        mandate_id=data.get("payment_method_reference_id") or data.get("authorization_id") or data.get("authorizationId") or data.get("mandate_id") or data.get("mandateId") or data.get("order_id") or data.get("orderId") or metadata.get("external_subscription_id") or "",
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


def _parse_pre_authorization(data: Dict[str, Any]) -> PreAuthorization:
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    amount = data.get("amount") or data.get("payment_amount") or data.get("paymentAmount") or {}
    amount_value = amount.get("value", data.get("amount_value", 0)) if isinstance(amount, dict) else data.get("amount_value", 0)
    amount_currency = amount.get("currency", data.get("amount_currency", "INR")) if isinstance(amount, dict) else data.get("amount_currency", "INR")
    redirect_url = data.get("redirect_url") or data.get("redirectUrl")
    challenge_url = data.get("challenge_url") or data.get("challengeUrl") or redirect_url
    return PreAuthorization(
        payment_method=_payment_method_enum(data.get("payment_method") or data.get("type")),
        payment_method_reference_id=str(data.get("payment_method_reference_id") or data.get("authorization_id") or data.get("mandate_id") or data.get("order_id") or data.get("orderId") or ""),
        customer=PreAuthorizationCustomer(
            customer_id=customer.get("customer_id"),
            merchant_customer_reference=customer.get("merchant_customer_reference"),
            mobile_number=str(customer.get("mobile_number") or data.get("mobile_number") or ""),
        ),
        challenge_url=challenge_url,
        redirect_url=redirect_url,
        status=str(data.get("status") or data.get("payment_status") or data.get("order_status") or ""),
        amount=Amount(value=_amount_int(amount_value), currency=str(amount_currency)),
        validity_in_days=data.get("validity_in_days") if isinstance(data.get("validity_in_days"), int) else None,
        expiry_at=data.get("expiry_at") or data.get("expires_at"),
        raw=data,
    )


def _parse_mandate_balance_result(data: Dict[str, Any]) -> MandateBalanceResult:
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    amount = data.get("amount") if isinstance(data.get("amount"), dict) else None
    balance_details = data.get("balance_details") if isinstance(data.get("balance_details"), dict) else None
    return MandateBalanceResult(
        payment_method=_payment_method_enum(data.get("payment_method")),
        payment_method_reference_id=str(data.get("payment_method_reference_id") or ""),
        merchant_id=str(data.get("merchant_id") or ""),
        customer=MandateBalanceCustomer(
            mobile_number=str(customer.get("mobile_number") or ""),
            merchant_customer_reference=customer.get("merchant_customer_reference"),
            bank_account_number=customer.get("bank_account_number"),
        ),
        status=str(data.get("status") or ""),
        amount=Amount(value=_amount_int(amount.get("value")), currency=str(amount.get("currency") or "INR")) if amount else None,
        description=data.get("description"),
        validity_in_days=data.get("validity_in_days"),
        expiry_at=data.get("expiry_at"),
        challenge_url=data.get("challenge_url"),
        external_reference_id=data.get("external_reference_id"),
        created_at=data.get("created_at"),
        balance_details=MandateBalanceDetails(
            amount_debited=Amount(
                value=_amount_int((balance_details.get("amount_debited") or {}).get("value")),
                currency=str((balance_details.get("amount_debited") or {}).get("currency") or "INR"),
            ),
            amount_remaining=Amount(
                value=_amount_int((balance_details.get("amount_remaining") or {}).get("value")),
                currency=str((balance_details.get("amount_remaining") or {}).get("currency") or "INR"),
            ),
        ) if balance_details else None,
        raw=data,
    )


def _parse_mandate_revoke_result(data: Dict[str, Any]) -> MandateRevokeResult:
    return MandateRevokeResult(
        payment_method=_payment_method_enum(data.get("payment_method")),
        payment_method_reference_id=str(data.get("payment_method_reference_id") or ""),
        revoke_reference_id=str(data.get("revoke_reference_id") or ""),
        status=str(data.get("status") or ""),
        raw=data,
    )


def _payment_method_enum(value: Any) -> PaymentMethod:
    if value == PaymentMethod.CARD.value:
        return PaymentMethod.CARD
    if value == PaymentMethod.OTM.value:
        return PaymentMethod.OTM
    if value == PaymentMethod.CREDIT_EMI.value:
        return PaymentMethod.CREDIT_EMI
    return PaymentMethod.Crypto if value == PaymentMethod.Crypto.value else PaymentMethod.RESERVE_PAY

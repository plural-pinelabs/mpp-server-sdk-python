from __future__ import annotations

from ..config.environments import is_p3p_environment
from ..types.config import CreateMandateOptions, CreateMandateRevokeOptions, MandateBalanceLookupOptions, PineLabsOnlineServerConfig
from ..types.payment import PaymentGateway, PaymentMethod


def normalize_mobile_number(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) > 10:
        raise ValueError(f"mobileNumber must be at most 10 digits, got {len(digits)}")
    return digits


def validate_config(config: PineLabsOnlineServerConfig) -> None:
    if not config.clientId or not isinstance(config.clientId, str):
        raise ValueError("PineLabsOnlineServerConfig: clientId is required and must be a non-empty string")
    if not config.clientSecret or not isinstance(config.clientSecret, str):
        raise ValueError("PineLabsOnlineServerConfig: clientSecret is required and must be a non-empty string")
    if not config.merchantId or not isinstance(config.merchantId, str) or not config.merchantId.strip():
        raise ValueError("PineLabsOnlineServerConfig: merchantId is required and must be a non-empty string")
    if config.paymentGateway != PaymentGateway.PineLabsOnline:
        raise ValueError("PineLabsOnlineServerConfig: paymentGateway must be PaymentGateway.PineLabsOnline")
    if not isinstance(config.availablePaymentMethods, list) or not config.availablePaymentMethods:
        raise ValueError("PineLabsOnlineServerConfig: availablePaymentMethods must contain at least one payment method")
    for payment_method in config.availablePaymentMethods:
        if not is_supported_payment_method(payment_method):
            raise _unsupported_payment_method_error("PineLabsOnlineServerConfig: availablePaymentMethods", payment_method)
    if not is_p3p_environment(config.env):
        raise ValueError("PineLabsOnlineServerConfig: env must be P3PEnvironment.SANDBOX, P3PEnvironment.PRODUCTION, or an HTTP URL")
    if config.requestTimeoutMs is not None and (
        not isinstance(config.requestTimeoutMs, int) or config.requestTimeoutMs <= 0
    ):
        raise ValueError("PineLabsOnlineServerConfig: requestTimeoutMs must be a positive integer")
    if config.maxRetries is not None and (
        not isinstance(config.maxRetries, int) or config.maxRetries < 0
    ):
        raise ValueError("PineLabsOnlineServerConfig: maxRetries must be a non-negative integer")
    if config.initialRetryDelayMs is not None and (
        not isinstance(config.initialRetryDelayMs, int) or config.initialRetryDelayMs <= 0
    ):
        raise ValueError("PineLabsOnlineServerConfig: initialRetryDelayMs must be a positive integer")
    if config.grantex is not None:
        enforce_grant = (
            config.grantex.enforce_grant
            if config.grantex.enforce_grant is not None
            else config.grantex.enforceGrant
        )
        hosted = config.grantex.hosted
        api_key = ""
        if hosted is not None:
            api_key = str(hosted.apiKey or hosted.api_key or "").strip()
        if enforce_grant and not api_key:
            raise ValueError("PineLabsOnlineServerConfig: grantex.hosted.apiKey is required when grantex.enforceGrant is true")


def is_supported_payment_method(value: object) -> bool:
    return value in (PaymentMethod.RESERVE_PAY, PaymentMethod.OTM, PaymentMethod.CARD, PaymentMethod.CREDIT_EMI)


def validate_create_mandate_options(options: CreateMandateOptions) -> None:
    mobile_number = str(options.mobileNumber or "").strip()
    normalized_mobile = normalize_mobile_number(mobile_number)
    if not mobile_number:
        raise ValueError("CreateMandateOptions: mobileNumber is required")
    if len(normalized_mobile) != 10:
        raise ValueError("CreateMandateOptions: mobileNumber must be 10 digits or E.164 format")
    if not options.amount:
        raise ValueError("CreateMandateOptions: amount is required")
    if not isinstance(options.amount.value, int) or options.amount.value < 100:
        raise ValueError("CreateMandateOptions: amount.value must be at least 100 paise")
    if options.amount.currency != "INR":
        raise ValueError("CreateMandateOptions: only INR currency is supported")
    if options.validityInDays is not None and options.validityInDays <= 0:
        raise ValueError("CreateMandateOptions: validityInDays must be a positive integer")
    if options.paymentMethod is not None and not is_supported_payment_method(options.paymentMethod):
        raise _unsupported_payment_method_error("CreateMandateOptions: paymentMethod", options.paymentMethod)


def validate_mandate_balance_lookup_options(options: MandateBalanceLookupOptions) -> None:
    authorization_id = str(options.authorizationId or "").strip()
    phone_number = normalize_mobile_number(str(options.phoneNumber or "").strip())

    if options.paymentMethod is None:
        raise ValueError("MandateBalanceLookupOptions: paymentMethod is required")
    if not is_supported_payment_method(options.paymentMethod):
        raise _unsupported_payment_method_error("MandateBalanceLookupOptions: paymentMethod", options.paymentMethod)
    if options.paymentMethod == PaymentMethod.OTM:
        raise ValueError("MandateBalanceLookupOptions: OTM is not supported for mandate balance lookup")

    if not authorization_id and not phone_number:
        raise ValueError("MandateBalanceLookupOptions: phoneNumber is required when authorizationId is absent")
    if len(phone_number) != 10:
        raise ValueError("MandateBalanceLookupOptions: phoneNumber must be 10 digits")


def validate_create_mandate_revoke_options(options: CreateMandateRevokeOptions) -> None:
    if not is_supported_payment_method(options.paymentMethod):
        raise _unsupported_payment_method_error("CreateMandateRevokeOptions: paymentMethod", options.paymentMethod)

    customer = options.customer or {}
    if hasattr(customer, "__dict__"):
        customer = customer.__dict__

    payment_method_reference_id = str(options.paymentMethodReferenceId or "").strip()
    merchant_customer_reference = str(customer.get("merchantCustomerReference") or "").strip()
    mobile_number = normalize_mobile_number(str(customer.get("mobileNumber") or "").strip())

    if not payment_method_reference_id and not merchant_customer_reference and not mobile_number:
        raise ValueError("CreateMandateRevokeOptions: paymentMethodReferenceId or customer lookup is required")
    if mobile_number and len(mobile_number) != 10:
        raise ValueError("CreateMandateRevokeOptions: customer.mobileNumber must be 10 digits")


def _unsupported_payment_method_error(context: str, value: object) -> ValueError:
    if value == PaymentMethod.Crypto:
        return ValueError(f"{context}: PaymentMethod.Crypto is currently not supported in SDKs")
    return ValueError(f"{context}: payment method must be RESERVE_PAY, OTM, CARD, or CREDIT_EMI")

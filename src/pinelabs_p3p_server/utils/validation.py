from __future__ import annotations

from ..config.environments import is_p3p_environment
from ..types.config import CreateMandateOptions, PineLabsOnlineServerConfig
from ..types.payment import PaymentGateway, PaymentMethod


def normalize_mobile_number(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def validate_config(config: PineLabsOnlineServerConfig) -> None:
    if not config.clientId or not isinstance(config.clientId, str):
        raise ValueError("PineLabsOnlineServerConfig: clientId is required and must be a non-empty string")
    if not config.clientSecret or not isinstance(config.clientSecret, str):
        raise ValueError("PineLabsOnlineServerConfig: clientSecret is required and must be a non-empty string")
    if config.paymentGateway != PaymentGateway.PineLabsOnline:
        raise ValueError("PineLabsOnlineServerConfig: paymentGateway must be PaymentGateway.PineLabsOnline")
    if not isinstance(config.availablePaymentMethods, list) or not config.availablePaymentMethods:
        raise ValueError("PineLabsOnlineServerConfig: availablePaymentMethods must contain at least one payment method")
    for payment_method in config.availablePaymentMethods:
        if not is_supported_payment_method(payment_method):
            raise ValueError(f'PineLabsOnlineServerConfig: unsupported payment method "{payment_method}"')
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


def is_supported_payment_method(value: object) -> bool:
    return value in (PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto)


def validate_create_mandate_options(options: CreateMandateOptions) -> None:
    customer_reference = str(options.customerReference or options.customerId or "").strip()
    mobile_number = str(options.mobileNumber or "").strip()
    normalized_mobile = normalize_mobile_number(mobile_number)
    if not customer_reference and not mobile_number:
        raise ValueError("CreateMandateOptions: customerReference or mobileNumber is required")
    if mobile_number and len(normalized_mobile) != 10:
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
        raise ValueError("CreateMandateOptions: paymentMethod must be a supported payment method")

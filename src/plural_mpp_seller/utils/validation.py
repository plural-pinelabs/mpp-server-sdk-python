from __future__ import annotations

from ..types.config import PluralSellerConfig


def validate_config(config: PluralSellerConfig) -> None:
    if not config.clientId or not isinstance(config.clientId, str):
        raise ValueError("PluralSellerConfig: clientId is required and must be a non-empty string")
    if not config.clientSecret or not isinstance(config.clientSecret, str):
        raise ValueError("PluralSellerConfig: clientSecret is required and must be a non-empty string")
    if not config.challengeSecretKey or not isinstance(config.challengeSecretKey, str):
        raise ValueError(
            "PluralSellerConfig: challengeSecretKey is required and must be a non-empty string"
        )
    if config.baseUrl is not None and not isinstance(config.baseUrl, str):
        raise ValueError("PluralSellerConfig: baseUrl must be a string")
    if config.requestTimeoutMs is not None and (
        not isinstance(config.requestTimeoutMs, int) or config.requestTimeoutMs <= 0
    ):
        raise ValueError("PluralSellerConfig: requestTimeoutMs must be a positive integer")
    if config.maxRetries is not None and (
        not isinstance(config.maxRetries, int) or config.maxRetries < 0
    ):
        raise ValueError("PluralSellerConfig: maxRetries must be a non-negative integer")
    if config.initialRetryDelayMs is not None and (
        not isinstance(config.initialRetryDelayMs, int) or config.initialRetryDelayMs <= 0
    ):
        raise ValueError("PluralSellerConfig: initialRetryDelayMs must be a positive integer")

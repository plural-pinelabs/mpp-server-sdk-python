from __future__ import annotations

from typing import Any, Dict, Optional

from .types.config import (
    GrantexAuthorizationOptions,
    GrantexAuthorizationResult,
    GrantexBudgetAllocationOptions,
    GrantexBudgetAllocationResult,
    GrantexBudgetBalanceResult,
    GrantexBudgetDebitOptions,
    GrantexBudgetDebitResult,
    GrantexBudgetTransaction,
    GrantexBudgetTransactionsOptions,
    GrantexBudgetTransactionsResult,
    GrantexExchangeCodeOptions,
    GrantexExchangeCodeResult,
    HostedGrantexConfig,
)

DEFAULT_GRANTEX_BASE_URL = "https://api.grantex.dev"


class HostedGrantexError(Exception):
    def __init__(
        self,
        message: str,
        status: Optional[int] = None,
        code: Optional[str] = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class HostedGrantexClient:
    def __init__(self, config: HostedGrantexConfig) -> None:
        self._config = config
        self._client: Any = None
        if not _api_key(config):
            raise ValueError("HostedGrantexConfig: apiKey is required")

    def create_authorization(self, options: GrantexAuthorizationOptions) -> GrantexAuthorizationResult:
        client = self._get_client()
        raw = _call_hosted(lambda: client.authorize(_authorization_params(options)))
        return _normalize_authorization(raw)

    def exchange_code(self, options: GrantexExchangeCodeOptions) -> GrantexExchangeCodeResult:
        client = self._get_client()
        raw = _call_hosted(lambda: client.tokens.exchange(_exchange_params(options)))
        return _normalize_token(raw)

    def allocate_budget(self, options: GrantexBudgetAllocationOptions) -> GrantexBudgetAllocationResult:
        grant_id = _required(_first(options.grantId, options.grant_id), "GrantexBudgetAllocationOptions: grantId is required")
        initial_budget = _required_number(
            _first(options.initialBudget, options.initial_budget),
            "GrantexBudgetAllocationOptions: initialBudget is required",
        )
        client = self._get_client()
        raw = _call_hosted(lambda: client.budgets.allocate(_allocate_budget_params(grant_id, initial_budget, options.currency)))
        return _normalize_budget(raw, grant_id)

    def debit_budget(self, options: GrantexBudgetDebitOptions) -> GrantexBudgetDebitResult:
        grant_id = _required(_first(options.grantId, options.grant_id), "GrantexBudgetDebitOptions: grantId is required")
        client = self._get_client()
        raw = _call_hosted(lambda: client.budgets.debit(_debit_budget_params(grant_id, options)))
        return _normalize_debit(raw, grant_id)

    def get_budget_balance(self, grant_id: str) -> GrantexBudgetBalanceResult:
        raw = _call_hosted(lambda: self._get_client().budgets.balance(grant_id))
        return _normalize_budget(raw, grant_id)

    def list_budget_transactions(
        self,
        grant_id: str,
        options: Optional[GrantexBudgetTransactionsOptions] = None,
    ) -> GrantexBudgetTransactionsResult:
        raw = _call_hosted(lambda: self._get_client().budgets.transactions(grant_id, _options_dict(options)))
        return _normalize_transactions(raw, grant_id)

    def _get_client(self) -> Any:
        if self._client is None:
            if self._config.client_factory is not None:
                self._client = self._config.client_factory()
            else:
                from grantex import Grantex

                self._client = Grantex(
                    api_key=_api_key(self._config),
                    base_url=resolve_hosted_grantex_base_url(self._config),
                    timeout=_first(self._config.timeoutMs, self._config.timeout_ms) or 30000,
                    max_retries=_first(self._config.maxRetries, self._config.max_retries) or 3,
                )
        return self._client


def create_hosted_grantex_client(config: HostedGrantexConfig) -> HostedGrantexClient:
    return HostedGrantexClient(config)


def resolve_hosted_grantex_base_url(config: Optional[HostedGrantexConfig] = None) -> str:
    url = str(_first(getattr(config, "baseUrl", None), getattr(config, "base_url", None), DEFAULT_GRANTEX_BASE_URL)).rstrip("/")
    if not _is_https_url(url):
        raise ValueError(f"HostedGrantexConfig: baseUrl must use HTTPS (got: {url})")
    return url


def _is_https_url(url: str) -> bool:
    return url.startswith("https://") or _is_localhost_url(url)


def _is_localhost_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        return (
            hostname in ("localhost", "127.0.0.1", "::1", "host.docker.internal")
            or "." not in hostname
        )
    except Exception:
        return False


def _authorization_params(options: GrantexAuthorizationOptions) -> Any:
    from grantex import AuthorizeParams

    return AuthorizeParams(
        agent_id=_required(_first(options.agentId, options.agent_id), "GrantexAuthorizationOptions: agentId is required"),
        user_id=_required(_first(options.userId, options.user_id), "GrantexAuthorizationOptions: userId is required"),
        scopes=options.scopes,
        expires_in=_first(options.expiresIn, options.expires_in),
        redirect_uri=_first(options.redirectUri, options.redirect_uri),
        code_challenge=_first(options.codeChallenge, options.code_challenge),
        code_challenge_method=_first(options.codeChallengeMethod, options.code_challenge_method),
    )


def _exchange_params(options: GrantexExchangeCodeOptions) -> Any:
    from grantex import ExchangeTokenParams

    return ExchangeTokenParams(
        code=options.code,
        agent_id=_required(_first(options.agentId, options.agent_id), "GrantexExchangeCodeOptions: agentId is required"),
        code_verifier=_first(options.codeVerifier, options.code_verifier),
        credential_format=_first(options.credentialFormat, options.credential_format),
    )


def _allocate_budget_params(grant_id: str, initial_budget: float, currency: str) -> Any:
    from grantex import AllocateBudgetParams

    return AllocateBudgetParams(
        grant_id=grant_id,
        initial_budget=initial_budget,
        currency=currency,
    )


def _debit_budget_params(grant_id: str, options: GrantexBudgetDebitOptions) -> Any:
    from grantex import DebitBudgetParams

    return DebitBudgetParams(
        grant_id=grant_id,
        amount=options.amount,
        description=options.description,
        metadata=options.metadata,
    )


def _normalize_authorization(raw: Any) -> GrantexAuthorizationResult:
    return GrantexAuthorizationResult(
        authRequestId=_string_value(raw, "authRequestId", "auth_request_id", "id"),
        consentUrl=_string_value(raw, "consentUrl", "consent_url", "redirectUrl", "redirect_url", "url"),
        agentId=_string_value(raw, "agentId", "agent_id"),
        principalId=_string_value(raw, "principalId", "principal_id", "userId", "user_id"),
        scopes=_list_value(raw, "scopes"),
        expiresAt=_optional_string_value(raw, "expiresAt", "expires_at"),
        status=_optional_string_value(raw, "status"),
        raw=_raw_dict(raw),
    )


def _normalize_token(raw: Any) -> GrantexExchangeCodeResult:
    return GrantexExchangeCodeResult(
        grantToken=_string_value(raw, "grantToken", "grant_token", "accessToken", "access_token", "token"),
        grantId=_string_value(raw, "grantId", "grant_id", "id"),
        refreshToken=_optional_string_value(raw, "refreshToken", "refresh_token"),
        scopes=_list_value(raw, "scopes"),
        expiresAt=_optional_string_value(raw, "expiresAt", "expires_at"),
        raw=_raw_dict(raw),
    )


def _normalize_budget(raw: Any, grant_id: str) -> GrantexBudgetAllocationResult:
    return GrantexBudgetAllocationResult(
        id=_string_value(raw, "id", "budgetId", "budget_id"),
        grantId=_string_value(raw, "grantId", "grant_id") or grant_id,
        initialBudget=_number_value(raw, "initialBudget", "initial_budget"),
        remainingBudget=_number_value(raw, "remainingBudget", "remaining_budget"),
        currency=_string_value(raw, "currency") or "INR",
        createdAt=_optional_string_value(raw, "createdAt", "created_at"),
        raw=_raw_dict(raw),
    )


def _normalize_debit(raw: Any, grant_id: str) -> GrantexBudgetDebitResult:
    return GrantexBudgetDebitResult(
        grantId=_string_value(raw, "grantId", "grant_id") or grant_id,
        remaining=_number_value(raw, "remaining", "remainingBudget", "remaining_budget"),
        transactionId=_optional_string_value(raw, "transactionId", "transaction_id", "id"),
        raw=_raw_dict(raw),
    )


def _normalize_transactions(raw: Any, grant_id: str) -> GrantexBudgetTransactionsResult:
    transactions = _value(raw, "transactions") or []
    if not isinstance(transactions, list):
        transactions = []
    return GrantexBudgetTransactionsResult(
        total=_optional_int_value(raw, "total"),
        transactions=[
            GrantexBudgetTransaction(
                id=_string_value(item, "id", "transactionId", "transaction_id"),
                grantId=_string_value(item, "grantId", "grant_id") or grant_id,
                amount=_number_value(item, "amount"),
                description=_optional_string_value(item, "description"),
                balanceAfter=_optional_number_value(item, "balanceAfter", "balance_after"),
                createdAt=_optional_string_value(item, "createdAt", "created_at"),
                raw=_raw_dict(item),
            )
            for item in transactions
        ],
        raw=_raw_dict(raw),
    )


def _call_hosted(operation: Any) -> Any:
    try:
        return operation()
    except HostedGrantexError:
        raise
    except Exception as exc:
        raise _normalize_error(exc) from exc


def _normalize_error(exc: Exception) -> HostedGrantexError:
    status = _optional_int_from_value(_first(getattr(exc, "status", None), getattr(exc, "http_status", None)))
    code = _optional_string(_first(getattr(exc, "code", None), getattr(exc, "error", None)))
    message = str(exc) or "Hosted Grantex request failed"
    return HostedGrantexError(message, status=status, code=code, details=exc)


def _api_key(config: HostedGrantexConfig) -> str:
    return str(_first(config.apiKey, config.api_key, "") or "").strip()


def _options_dict(options: Optional[GrantexBudgetTransactionsOptions]) -> Dict[str, Any]:
    if options is None:
        return {}
    return {key: value for key, value in {"limit": options.limit, "cursor": options.cursor}.items() if value is not None}


def _raw_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if hasattr(raw, "__dict__"):
        return dict(raw.__dict__)
    return {}


def _value(raw: Any, key: str) -> Any:
    if isinstance(raw, dict):
        return raw.get(key)
    return getattr(raw, key, None)


def _string_value(raw: Any, *keys: str) -> str:
    return _optional_string_value(raw, *keys) or ""


def _optional_string_value(raw: Any, *keys: str) -> Optional[str]:
    for key in keys:
        value = _optional_string(_value(raw, key))
        if value is not None:
            return value
    return None


def _optional_string(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _list_value(raw: Any, key: str) -> list[str]:
    value = _value(raw, key)
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _int_value(raw: Any, *keys: str) -> int:
    return _optional_int_value(raw, *keys) or 0


def _number_value(raw: Any, *keys: str) -> float:
    return _optional_number_value(raw, *keys) or 0


def _optional_int_value(raw: Any, *keys: str) -> Optional[int]:
    for key in keys:
        value = _optional_int_from_value(_value(raw, key))
        if value is not None:
            return value
    return None


def _optional_int_from_value(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _optional_number_value(raw: Any, *keys: str) -> Optional[float]:
    for key in keys:
        value = _optional_number_from_value(_value(raw, key))
        if value is not None:
            return value
    return None


def _optional_number_from_value(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _required(value: Any, message: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(message)
    return normalized


def _required_number(value: Any, message: str) -> float:
    normalized = _optional_number_from_value(value)
    if normalized is None:
        raise ValueError(message)
    return normalized


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None

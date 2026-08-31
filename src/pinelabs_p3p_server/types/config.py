from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Union

from ..config.environments import P3PEnvironment
from .payment import PaymentGateway, PaymentMethod

GRANTEX_TOKEN_HEADER = "X-Grantex-Token"


@dataclass
class Amount:
    """Money amount expressed in the smallest unit for the currency."""

    value: int
    currency: str


class P3PLogger(Protocol):
    def debug(self, message: str, context: Optional[dict] = None) -> None: ...
    def info(self, message: str, context: Optional[dict] = None) -> None: ...
    def error(self, message: str, context: Optional[dict] = None) -> None: ...


@dataclass
class GrantexVerificationResult:
    valid: bool
    grant: Optional[Any] = None
    error: Optional[str] = None


class GrantexVerifierLike(Protocol):
    def verify(self, token: str) -> GrantexVerificationResult: ...


class HostedGrantexSdkFactory(Protocol):
    def __call__(self) -> Any: ...


@dataclass
class HostedGrantexConfig:
    """Hosted Grantex API config used only by the server SDK."""

    apiKey: Optional[str] = None
    api_key: Optional[str] = None
    baseUrl: Optional[str] = None
    base_url: Optional[str] = None
    timeoutMs: Optional[int] = None
    timeout_ms: Optional[int] = None
    maxRetries: Optional[int] = None
    max_retries: Optional[int] = None
    client_factory: Optional[HostedGrantexSdkFactory] = None


@dataclass
class ServerGrantexConfig:
    """Optional delegated authorization verification using the published Grantex SDK."""

    jwksUri: Optional[str] = None
    jwksUrl: Optional[str] = None
    jwks_uri: Optional[str] = None
    jwks_url: Optional[str] = None
    requiredScopes: Optional[List[str]] = None
    required_scopes: Optional[List[str]] = None
    issuer: Optional[str] = None
    issuerDid: Optional[str] = None
    issuer_did: Optional[str] = None
    audience: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    clockTolerance: int = 0
    clock_tolerance: Optional[int] = None
    enforceGrant: bool = False
    enforce_grant: Optional[bool] = None
    hosted: Optional[HostedGrantexConfig] = None
    debitBudgetBeforeChallenge: bool = True
    debit_budget_before_challenge: Optional[bool] = None
    verifier: Optional[GrantexVerifierLike] = None


@dataclass
class GrantexAuthorizationOptions:
    userId: Optional[str] = None
    user_id: Optional[str] = None
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    redirectUri: Optional[str] = None
    redirect_uri: Optional[str] = None
    expiresIn: Optional[Union[str, int]] = None
    expires_in: Optional[Union[str, int]] = None
    codeChallenge: Optional[str] = None
    code_challenge: Optional[str] = None
    codeChallengeMethod: Optional[str] = None
    code_challenge_method: Optional[str] = None


@dataclass
class GrantexAuthorizationResult:
    authRequestId: str
    consentUrl: str
    agentId: str
    principalId: str
    scopes: List[str]
    expiresAt: Optional[str] = None
    status: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrantexExchangeCodeOptions:
    code: str
    agentId: Optional[str] = None
    agent_id: Optional[str] = None
    codeVerifier: Optional[str] = None
    code_verifier: Optional[str] = None
    credentialFormat: Optional[str] = None
    credential_format: Optional[str] = None


@dataclass
class GrantexExchangeCodeResult:
    grantToken: str
    grantId: str
    refreshToken: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    expiresAt: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrantexBudgetAllocationOptions:
    grantId: Optional[str] = None
    grant_id: Optional[str] = None
    initialBudget: Optional[float] = None
    initial_budget: Optional[float] = None
    currency: str = "INR"


@dataclass
class GrantexBudgetAllocationResult:
    id: str
    grantId: str
    initialBudget: float
    remainingBudget: float
    currency: str
    createdAt: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrantexBudgetDebitOptions:
    grantId: Optional[str] = None
    grant_id: Optional[str] = None
    amount: float = 0
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class GrantexBudgetDebitResult:
    grantId: str
    remaining: float
    transactionId: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrantexBudgetBalanceResult:
    id: str
    grantId: str
    initialBudget: float
    remainingBudget: float
    currency: str
    createdAt: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrantexBudgetTransaction:
    id: str
    grantId: str
    amount: float
    description: Optional[str] = None
    balanceAfter: Optional[float] = None
    createdAt: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrantexBudgetTransactionsOptions:
    limit: Optional[int] = None
    cursor: Optional[str] = None


@dataclass
class GrantexBudgetTransactionsResult:
    transactions: List[GrantexBudgetTransaction]
    total: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PineLabsOnlineServerConfig:
    """Configuration required to construct a server SDK instance.

    `clientSecret` is used for service auth and derives the local HMAC key used
    to sign 402 challenges. `merchantId` is mandatory and is sent as
    `Merchant-ID` on all Pine Labs MPP calls.
    """

    clientId: str
    clientSecret: str
    paymentGateway: PaymentGateway
    availablePaymentMethods: List[PaymentMethod]
    env: str = P3PEnvironment.PRODUCTION
    realm: Optional[str] = None
    merchantId: str = ""
    defaultChallengeExpirySeconds: Optional[int] = None
    requestTimeoutMs: Optional[int] = None
    maxRetries: Optional[int] = None
    initialRetryDelayMs: Optional[int] = None
    logger: Optional[P3PLogger] = None
    grantex: Optional[ServerGrantexConfig] = None


@dataclass
class ChargeOptions:
    """Payment challenge/capture context for a server-protected resource."""

    amount: Amount
    resource: str
    description: Optional[str] = None
    merchantOrderReference: Optional[str] = None
    metadata: Optional[dict] = None
    challengeExpirySeconds: Optional[int] = None


@dataclass
class CreateMandateOptions:
    """Input for server/server-side mandate creation via `POST /mpp/v1/pre-authorize`."""

    amount: Amount
    mobileNumber: Optional[str] = None
    customerReference: Optional[str] = None
    customerId: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    expiry: Optional[str] = None
    idempotencyKey: Optional[str] = None
    paymentMethod: Optional[PaymentMethod] = None
    paymentMethodOptions: Optional[Dict[str, Any]] = None
    payment_method_options: Optional[Dict[str, Any]] = None
    validityInDays: Optional[int] = None
    merchantMetadata: Optional[Dict[str, Any]] = None
    merchant_metadata: Optional[Dict[str, Any]] = None


@dataclass
class CreatePreAuthorizationOptions(CreateMandateOptions):
    """Input for card/mandate pre-authorization via `POST /mpp/v1/pre-authorize`."""


@dataclass
class PreAuthorizationCustomer:
    customer_id: Optional[str] = None
    merchant_customer_reference: Optional[str] = None
    mobile_number: str = ""


@dataclass
class PreAuthorization:
    """Contract-shaped pre-authorization response returned by `POST /mpp/v1/pre-authorize`."""

    payment_method: PaymentMethod
    payment_method_reference_id: str
    customer: PreAuthorizationCustomer
    status: str
    amount: Amount
    challenge_url: Optional[str] = None
    redirect_url: Optional[str] = None
    validity_in_days: Optional[int] = None
    expiry_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MandateChallenge:
    type: str
    qr_url: str
    deep_link: str
    expires_at: str


@dataclass
class Mandate:
    """Normalized mandate/pre-authorization response returned by the P3P service."""

    mandate_id: str
    object: str
    order_id: str
    order_status: str
    payment_status: str
    customer_reference: str
    customer_id: str
    agent_id: str
    amount: Amount
    amount_blocked: int
    amount_debited: int
    amount_held: int
    amount_available: int
    mobile_number: str
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    expires_at: str = ""
    created_at: str = ""
    challenge: Optional[MandateChallenge] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MandateBalanceLookupOptions:
    authorizationId: Optional[str] = None
    phoneNumber: Optional[str] = None
    paymentMethod: Optional[PaymentMethod] = None


@dataclass
class MandateBalanceCustomer:
    mobile_number: str
    merchant_customer_reference: Optional[str] = None
    bank_account_number: Optional[str] = None


@dataclass
class MandateBalanceDetails:
    amount_debited: Amount
    amount_remaining: Amount


@dataclass
class MandateBalanceResult:
    payment_method: PaymentMethod
    payment_method_reference_id: str
    merchant_id: str
    customer: MandateBalanceCustomer
    status: str
    amount: Optional[Amount] = None
    description: Optional[str] = None
    validity_in_days: Optional[int] = None
    expiry_at: Optional[str] = None
    challenge_url: Optional[str] = None
    external_reference_id: Optional[str] = None
    created_at: Optional[str] = None
    balance_details: Optional[MandateBalanceDetails] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RevokeMandateCustomerLookup:
    merchantCustomerReference: Optional[str] = None
    mobileNumber: Optional[str] = None


@dataclass
class CreateMandateRevokeOptions:
    paymentMethod: PaymentMethod
    paymentMethodReferenceId: Optional[str] = None
    customer: Optional[Union[RevokeMandateCustomerLookup, Dict[str, str]]] = None


@dataclass
class MandateRevokeResult:
    payment_method: PaymentMethod
    payment_method_reference_id: str
    revoke_reference_id: str
    status: str
    raw: Dict[str, Any] = field(default_factory=dict)

from __future__ import annotations

from typing import Optional

from ..types.capture import CaptureOptions, CaptureResult, ReceiptData
from ..types.challenge import ChallengeResult
from ..types.config import (
    ChargeOptions,
    CreateMandateOptions,
    CreateMandateRevokeOptions,
    CreatePreAuthorizationOptions,
    GrantexAuthorizationOptions,
    GrantexAuthorizationResult,
    GrantexBudgetAllocationOptions,
    GrantexBudgetAllocationResult,
    GrantexBudgetBalanceResult,
    GrantexBudgetDebitOptions,
    GrantexBudgetDebitResult,
    GrantexBudgetTransactionsOptions,
    GrantexBudgetTransactionsResult,
    GrantexExchangeCodeOptions,
    GrantexExchangeCodeResult,
    Mandate,
    MandateBalanceLookupOptions,
    MandateBalanceResult,
    MandateRevokeResult,
    PineLabsOnlineServerConfig,
    PreAuthorization,
)
from ..types.credential import VerificationResult
from ..types.orders import CreateRefundOptions, Order, Refund
from ..types.payment import PaymentGateway, PaymentMethod
from ..grantex_hosted import HostedGrantexClient, create_hosted_grantex_client
from ..utils.validation import validate_config
from ..config.environments import with_p3p_environment_defaults
from .api_client import ApiClient
from .capture_client import CaptureClient
from .challenge_generator import ChallengeGenerator
from .credential_verifier import CredentialVerifier
from .receipt_builder import build_receipt_data, build_receipt_header


class PineLabsOnlineP3PInstance:
    """Server SDK instance used to generate challenges, verify credentials, and debit."""

    def __init__(
        self,
        challenge_generator: ChallengeGenerator,
        credential_verifier: CredentialVerifier,
        capture_client: CaptureClient,
        api_client: ApiClient,
        hosted_grantex_client: Optional[HostedGrantexClient] = None,
    ) -> None:
        self._challenge_generator = challenge_generator
        self._credential_verifier = credential_verifier
        self._capture_client = capture_client
        self._api_client = api_client
        self._hosted_grantex_client = hosted_grantex_client

    def generate_challenge(self, options: ChargeOptions) -> ChallengeResult:
        """Generate a signed 402 Payment challenge for a protected resource."""
        return self._challenge_generator.generate(options)

    def verify_credential(self, credential_header: Optional[str]) -> VerificationResult:
        """Verify `P3P-Credential: Payment <payload>` from the client."""
        return self._credential_verifier.verify(credential_header)

    def capture(self, options: CaptureOptions) -> CaptureResult:
        """Execute a debit against `/mpp/v1/debit` using a one-time payment token."""
        return self._capture_client.capture(options)

    def get_debit_status(self, idempotency_key: str) -> CaptureResult:
        """Fetch debit status through `GET /mpp/v1/debit/{id}`."""
        return self._capture_client.get_debit_status(idempotency_key)

    def create_mandate(self, options: CreateMandateOptions) -> Mandate:
        """Create a mandate/pre-authorization through `POST /mpp/v1/pre-authorize`."""
        return self._api_client.create_mandate(options)

    def create_pre_authorization(self, options: CreatePreAuthorizationOptions) -> PreAuthorization:
        """Create a card/mandate pre-authorization through `POST /mpp/v1/pre-authorize`."""
        return self._api_client.create_pre_authorization(options)

    def get_mandate(self, mandate_id: str) -> Mandate:
        """Fetch mandate/pre-authorization status through `GET /mpp/v1/authorization/{id}`."""
        return self._api_client.get_mandate(mandate_id)

    def get_order(self, order_id: str) -> Order:
        """Retrieve an order by its Pine Labs order ID."""
        return self._api_client.get_order(order_id)

    def create_refund(self, order_id: str, options: CreateRefundOptions) -> Refund:
        """Initiate a refund against a processed Pine Labs order."""
        return self._api_client.create_refund(order_id, options)

    def get_mandate_balance(self, options: MandateBalanceLookupOptions) -> MandateBalanceResult:
        """Fetch mandate balance / authorization status through `GET /mpp/v1/balance`."""
        return self._api_client.get_mandate_balance(options)

    def revoke_mandate(self, options: CreateMandateRevokeOptions) -> MandateRevokeResult:
        """Create a mandate revoke request through `POST /mpp/v1/revoke`."""
        return self._api_client.revoke_mandate(options)

    def create_grantex_authorization(self, options: GrantexAuthorizationOptions) -> GrantexAuthorizationResult:
        """Create a hosted Grantex authorization request and return its consent URL."""
        return self._require_hosted_grantex().create_authorization(options)

    def exchange_grantex_code(self, options: GrantexExchangeCodeOptions) -> GrantexExchangeCodeResult:
        """Exchange a hosted Grantex callback code for a user grant token."""
        return self._require_hosted_grantex().exchange_code(options)

    def allocate_grantex_budget(self, options: GrantexBudgetAllocationOptions) -> GrantexBudgetAllocationResult:
        """Allocate a hosted Grantex grant-level budget."""
        return self._require_hosted_grantex().allocate_budget(options)

    def debit_grantex_budget(self, options: GrantexBudgetDebitOptions) -> GrantexBudgetDebitResult:
        """Debit a hosted Grantex grant-level budget."""
        return self._require_hosted_grantex().debit_budget(options)

    def get_grantex_budget_balance(self, grant_id: str) -> GrantexBudgetBalanceResult:
        """Fetch hosted Grantex grant-level budget balance."""
        return self._require_hosted_grantex().get_budget_balance(grant_id)

    def list_grantex_budget_transactions(
        self,
        grant_id: str,
        options: Optional[GrantexBudgetTransactionsOptions] = None,
    ) -> GrantexBudgetTransactionsResult:
        """List hosted Grantex grant-level budget transactions."""
        return self._require_hosted_grantex().list_budget_transactions(grant_id, options)

    def build_receipt_header(
        self,
        capture_result: CaptureResult,
        challenge_id: str,
        payment_gateway: Optional[PaymentGateway] = None,
        payment_method: Optional[PaymentMethod] = None,
    ) -> str:
        """Build the `Payment-Receipt` response header for a successful capture."""
        return build_receipt_header(capture_result, challenge_id, payment_gateway, payment_method)

    def build_receipt_data(
        self,
        capture_result: CaptureResult,
        challenge_id: str,
        payment_gateway: Optional[PaymentGateway] = None,
        payment_method: Optional[PaymentMethod] = None,
    ) -> ReceiptData:
        """Build structured receipt data without encoding it as a header."""
        return build_receipt_data(capture_result, challenge_id, payment_gateway, payment_method)

    def _require_hosted_grantex(self) -> HostedGrantexClient:
        if self._hosted_grantex_client is None:
            raise ValueError("PineLabsOnlineServerConfig: grantex.hosted is required")
        return self._hosted_grantex_client


class PineLabsOnlineP3P:
    """Factory for server SDK instances."""

    @staticmethod
    def create(config: PineLabsOnlineServerConfig) -> PineLabsOnlineP3PInstance:
        """Create a server SDK instance from `PineLabsOnlineServerConfig`."""
        validate_config(config)
        resolved_config = with_p3p_environment_defaults(config)
        return PineLabsOnlineP3PInstance(
            ChallengeGenerator(resolved_config),
            CredentialVerifier(resolved_config),
            CaptureClient(resolved_config),
            ApiClient(resolved_config),
            create_hosted_grantex_client(resolved_config.grantex.hosted)
            if resolved_config.grantex is not None and resolved_config.grantex.hosted is not None
            else None,
        )

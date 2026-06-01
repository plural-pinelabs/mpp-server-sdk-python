from __future__ import annotations

from typing import Optional

from ..types.capture import CaptureOptions, CaptureResult, ReceiptData
from ..types.challenge import ChallengeResult
from ..types.config import ChargeOptions, CreateMandateOptions, Mandate, PineLabsOnlineServerConfig
from ..types.credential import VerificationResult
from ..types.payment import PaymentGateway, PaymentMethod
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
    ) -> None:
        self._challenge_generator = challenge_generator
        self._credential_verifier = credential_verifier
        self._capture_client = capture_client
        self._api_client = api_client

    def generate_challenge(self, options: ChargeOptions) -> ChallengeResult:
        """Generate a signed 402 Payment challenge for a protected resource."""
        return self._challenge_generator.generate(options)

    def verify_credential(self, credential_header: Optional[str]) -> VerificationResult:
        """Verify `P3P-Credential: Payment <payload>` from the client."""
        return self._credential_verifier.verify(credential_header)

    def capture(self, options: CaptureOptions) -> CaptureResult:
        """Execute a debit against `/mpp/v1/debit` using a one-time payment token."""
        return self._capture_client.capture(options)

    def create_mandate(self, options: CreateMandateOptions) -> Mandate:
        """Create a mandate/pre-authorization through `POST /mpp/v1/pre-authorize`."""
        return self._api_client.create_mandate(options)

    def get_mandate(self, mandate_id: str) -> Mandate:
        """Fetch mandate/pre-authorization status through `GET /mpp/v1/authorization/{id}`."""
        return self._api_client.get_mandate(mandate_id)

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
        )

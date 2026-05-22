from __future__ import annotations

from typing import Optional

from ..types.capture import CaptureOptions, CaptureResult, ReceiptData
from ..types.challenge import ChallengeResult
from ..types.config import ChargeOptions, PluralSellerConfig
from ..types.credential import VerificationResult
from ..utils.validation import validate_config
from .capture_client import CaptureClient
from .challenge_generator import ChallengeGenerator
from .credential_verifier import CredentialVerifier
from .receipt_builder import build_receipt_data, build_receipt_header


class PluralMPPInstance:
    """Seller SDK instance used to generate challenges, verify credentials, and debit."""

    def __init__(
        self,
        challenge_generator: ChallengeGenerator,
        credential_verifier: CredentialVerifier,
        capture_client: CaptureClient,
    ) -> None:
        self._challenge_generator = challenge_generator
        self._credential_verifier = credential_verifier
        self._capture_client = capture_client

    def generate_challenge(self, options: ChargeOptions) -> ChallengeResult:
        """Generate a signed 402 Payment challenge for a protected resource."""
        return self._challenge_generator.generate(options)

    def verify_credential(self, authorization_header: Optional[str]) -> VerificationResult:
        """Verify `Authorization: Payment <payload>` from the buyer."""
        return self._credential_verifier.verify(authorization_header)

    def capture(self, options: CaptureOptions) -> CaptureResult:
        """Execute a debit against `/mpp/v1/debit` using a one-time payment token."""
        return self._capture_client.capture(options)

    def build_receipt_header(self, capture_result: CaptureResult, challenge_id: str) -> str:
        """Build the `Payment-Receipt` response header for a successful capture."""
        return build_receipt_header(capture_result, challenge_id)

    def build_receipt_data(self, capture_result: CaptureResult, challenge_id: str) -> ReceiptData:
        """Build structured receipt data without encoding it as a header."""
        return build_receipt_data(capture_result, challenge_id)


class PluralMPP:
    """Factory for seller SDK instances."""

    @staticmethod
    def create(config: PluralSellerConfig) -> PluralMPPInstance:
        """Create a seller SDK instance from `PluralSellerConfig`."""
        validate_config(config)
        return PluralMPPInstance(
            ChallengeGenerator(config),
            CredentialVerifier(config),
            CaptureClient(config),
        )

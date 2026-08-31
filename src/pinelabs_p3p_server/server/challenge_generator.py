from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from ..types.challenge import Challenge, ChallengeRequest, ChallengeResult, ProblemDetails
from ..types.config import ChargeOptions, PineLabsOnlineServerConfig
from ..utils.base64url import encode_json
from ..utils.hmac_sig import compute_challenge_id, derive_challenge_hmac_key
from ..utils.validation import validate_config

DEFAULT_EXPIRY_SECONDS = 300
PAYMENT_INTENT = "charge"
PAYMENT_SCHEME = "exact"


class ChallengeGenerator:
    """Creates signed Payment challenges for server-protected resources."""

    def __init__(self, config: PineLabsOnlineServerConfig) -> None:
        validate_config(config)
        self._secret_key = derive_challenge_hmac_key(config.clientSecret)
        self._realm = config.realm or config.env
        self._default_expiry = config.defaultChallengeExpirySeconds or DEFAULT_EXPIRY_SECONDS
        self._available_payment_methods = list(config.availablePaymentMethods)

    def generate(self, options: ChargeOptions) -> ChallengeResult:
        """Generate a challenge and problem-details response for HTTP 402."""
        val = options.amount.value
        if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
            raise ValueError("ChargeOptions: amount.value must be a positive integer (paise)")
        expiry_seconds = options.challengeExpirySeconds or self._default_expiry
        expires_dt = datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)
        expires = expires_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expires_dt.microsecond // 1000:03d}Z"

        amount_major = f"{options.amount.value / 100:.2f}"

        request = ChallengeRequest(
            scheme=PAYMENT_SCHEME,
            amount=amount_major,
            currency=options.amount.currency,
            resource=options.resource,
            availablePaymentMethods=list(self._available_payment_methods),
        )

        request_base64 = encode_json(asdict(request))
        challenge_id = compute_challenge_id(
            self._secret_key,
            self._realm,
            PAYMENT_INTENT,
            request_base64,
            expires,
        )

        challenge = Challenge(
            id=challenge_id,
            realm=self._realm,
            intent=PAYMENT_INTENT,
            request=request,
            expires=expires,
        )

        encoded = encode_json(_challenge_to_wire(challenge))

        problem = ProblemDetails(
            type=f"{self._realm}/errors/payment-required",
            title="Payment Required",
            status=402,
            detail=f"This resource requires payment of {amount_major} {options.amount.currency}",
            challengeId=challenge_id,
        )

        return ChallengeResult(challenge=challenge, encoded=encoded, problemDetails=problem)

def _challenge_to_wire(challenge: Challenge) -> dict:
    payload = asdict(challenge)
    payload.pop("paymentGateway", None)
    return payload

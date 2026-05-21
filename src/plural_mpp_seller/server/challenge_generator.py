from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from ..config.environments import DEFAULT_REALM
from ..types.challenge import Challenge, ChallengeRequest, ChallengeResult, ProblemDetails
from ..types.config import ChargeOptions, PluralSellerConfig
from ..utils.base64url import encode_json
from ..utils.hmac_sig import compute_challenge_id

DEFAULT_EXPIRY_SECONDS = 300
PAYMENT_METHOD = "plural"
PAYMENT_INTENT = "charge"
PAYMENT_SCHEME = "exact"


class ChallengeGenerator:
    """Creates signed Payment challenges for seller-protected resources."""

    def __init__(self, config: PluralSellerConfig) -> None:
        self._secret_key = config.challengeSecretKey
        self._realm = config.realm or DEFAULT_REALM
        self._default_expiry = config.defaultChallengeExpirySeconds or DEFAULT_EXPIRY_SECONDS

    def generate(self, options: ChargeOptions) -> ChallengeResult:
        """Generate a challenge and problem-details response for HTTP 402."""
        expiry_seconds = options.challengeExpirySeconds or self._default_expiry
        expires_dt = datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)
        expires = expires_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expires_dt.microsecond // 1000:03d}Z"

        amount_major = f"{options.amount.value / 100:.2f}"

        request = ChallengeRequest(
            scheme=PAYMENT_SCHEME,
            amount=amount_major,
            currency=options.amount.currency,
            resource=options.resource,
        )

        request_base64 = encode_json(asdict(request))
        challenge_id = compute_challenge_id(
            self._secret_key,
            self._realm,
            PAYMENT_METHOD,
            PAYMENT_INTENT,
            request_base64,
            expires,
        )

        challenge = Challenge(
            id=challenge_id,
            realm=self._realm,
            method=PAYMENT_METHOD,
            intent=PAYMENT_INTENT,
            request=request,
            expires=expires,
        )

        encoded = encode_json({
            "id": challenge.id,
            "realm": challenge.realm,
            "method": challenge.method,
            "intent": challenge.intent,
            "request": asdict(request),
            "expires": challenge.expires,
        })

        problem = ProblemDetails(
            type=f"{self._realm}/errors/payment-required",
            title="Payment Required",
            status=402,
            detail=f"This resource requires payment of ₹{amount_major} {options.amount.currency}",
            challengeId=challenge_id,
        )

        return ChallengeResult(challenge=challenge, encoded=encoded, problemDetails=problem)

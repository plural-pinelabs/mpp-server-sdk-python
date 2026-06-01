from __future__ import annotations

import hashlib
import hmac

CHALLENGE_HMAC_KEY_PREFIX = "p3p-challenge-v1:"


def derive_challenge_hmac_key(client_secret: str) -> str:
    return f"{CHALLENGE_HMAC_KEY_PREFIX}{client_secret}"


def compute_hmac_sha256(key: str, data: str) -> str:
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_challenge_id(
    secret_key: str,
    realm: str,
    intent: str,
    request_base64: str,
    expires: str,
) -> str:
    payload = f"{realm}|{intent}|{request_base64}|{expires}"
    return f"ch_{compute_hmac_sha256(secret_key, payload)}"

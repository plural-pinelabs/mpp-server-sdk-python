from __future__ import annotations

import hashlib
import hmac


def compute_hmac_sha256(key: str, data: str) -> str:
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_challenge_id(
    secret_key: str,
    realm: str,
    method: str,
    intent: str,
    request_base64: str,
    expires: str,
) -> str:
    payload = f"{realm}|{method}|{intent}|{request_base64}|{expires}"
    return f"ch_{compute_hmac_sha256(secret_key, payload)}"

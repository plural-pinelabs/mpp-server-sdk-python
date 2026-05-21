from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import jwt
from jwt import PyJWKClient

from ..types.grantex import GrantTokenClaims, GrantVerificationResult, SellerGrantexConfig

GRANTEX_TOKEN_HEADER = "X-Grantex-Token"
DEFAULT_JWKS_CACHE_TTL_MS = 3_600_000


class GrantTokenVerifier:
    """Verifies seller-received Grantex grant tokens using RS256 JWKS."""

    def __init__(self, config: SellerGrantexConfig) -> None:
        self._jwks_url = config.jwksUrl
        self._cache_ttl_ms = config.jwksCacheTtlMs or DEFAULT_JWKS_CACHE_TTL_MS
        self._required_scopes: List[str] = list(config.requiredScopes or [])
        self._jwk_client: Optional[PyJWKClient] = None
        self._cache_expires_at: float = 0
        self._lock = threading.Lock()

    def verify(self, grant_token: str) -> GrantVerificationResult:
        """Verify signature, expiry, required claims, and configured required scopes."""
        try:
            header = jwt.get_unverified_header(grant_token)
            if header.get("alg") != "RS256":
                return GrantVerificationResult(
                    valid=False,
                    error=f"Unsupported algorithm: {header.get('alg')}. Expected RS256",
                )
            signing_key = self._get_signing_key(header.get("kid"))
            if signing_key is None:
                return GrantVerificationResult(
                    valid=False,
                    error=f"No matching key found for kid: {header.get('kid') or 'none'}",
                )
            decoded = jwt.decode(
                grant_token,
                signing_key,
                algorithms=["RS256"],
                options={
                    "verify_aud": False,
                    "verify_iss": False,
                    "verify_exp": True,
                    "verify_nbf": True,
                },
            )
        except jwt.ExpiredSignatureError:
            return GrantVerificationResult(valid=False, error="Grant token has expired")
        except jwt.ImmatureSignatureError:
            return GrantVerificationResult(valid=False, error="Grant token is not yet valid")
        except jwt.InvalidSignatureError:
            return GrantVerificationResult(valid=False, error="Invalid grant token signature")
        except Exception as exc:
            return GrantVerificationResult(
                valid=False, error=f"Grant token verification failed: {exc}"
            )

        claims = _dict_to_claims(decoded)
        err = self._validate_claims(claims)
        if err is not None:
            return GrantVerificationResult(valid=False, error=err)
        return GrantVerificationResult(valid=True, claims=claims)

    def _validate_claims(self, claims: GrantTokenClaims) -> Optional[str]:
        now = int(time.time())
        if not claims.grnt:
            return "Missing grant ID (grnt)"
        if not claims.sub:
            return "Missing subject (sub)"
        if not claims.agt:
            return "Missing agent ID (agt)"
        if not claims.iss:
            return "Missing issuer (iss)"
        if not claims.scp:
            return "Missing or empty scopes (scp)"

        if claims.exp and claims.exp < now:
            iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(claims.exp))
            return f"Grant expired at {iso}"
        if claims.nbf and claims.nbf > now:
            iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(claims.nbf))
            return f"Grant not yet valid until {iso}"

        for required in self._required_scopes:
            if not self._has_scope(claims.scp, required):
                return f"Missing required scope: {required}"
        return None

    @staticmethod
    def _has_scope(scopes: List[str], required: str) -> bool:
        if required in scopes:
            return True
        parts = required.split(":")
        for scope in scopes:
            scope_parts = scope.split(":")
            if len(scope_parts) >= 2 and len(parts) >= 2 and scope_parts[0] == parts[0] and scope_parts[1] == "*":
                return True
            if scope == f"{parts[0]}:*":
                return True
        return False

    def _get_signing_key(self, kid: Optional[str]):
        with self._lock:
            now = time.time() * 1000
            if self._jwk_client is None or now >= self._cache_expires_at:
                self._jwk_client = PyJWKClient(self._jwks_url, cache_keys=True)
                self._cache_expires_at = now + self._cache_ttl_ms

        if kid is None:
            try:
                jwk_set = self._jwk_client.get_jwk_set()
                if len(jwk_set.keys) == 1:
                    return jwk_set.keys[0].key
                return None
            except Exception:
                return None

        try:
            return self._jwk_client.get_signing_key(kid).key
        except Exception:
            return None


def _dict_to_claims(raw: Dict[str, Any]) -> GrantTokenClaims:
    return GrantTokenClaims(
        iss=raw.get("iss", ""),
        sub=raw.get("sub", ""),
        agt=raw.get("agt", ""),
        scp=list(raw.get("scp") or []),
        grnt=raw.get("grnt", ""),
        iat=int(raw.get("iat", 0)),
        exp=int(raw.get("exp", 0)),
        dev=raw.get("dev"),
        nbf=raw.get("nbf"),
        parentAgt=raw.get("parentAgt"),
        parentGrnt=raw.get("parentGrnt"),
        delegationDepth=raw.get("delegationDepth"),
        raw=raw,
    )

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Optional

import httpx

from ..types.auth import AuthState
from ..types.config import P3PLogger
from ..utils.errors import P3PError
from ..utils.fetch_helpers import request_with_retry

REFRESH_BUFFER_MS = 60_000


class AuthManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str,
        http_client: Optional[httpx.Client] = None,
        timeout_ms: Optional[int] = None,
        logger: Optional[P3PLogger] = None,
        max_retries: Optional[int] = None,
        initial_retry_delay_ms: Optional[int] = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client()
        self._timeout_ms = timeout_ms
        self._logger = logger
        self._max_retries = max_retries
        self._initial_retry_delay_ms = initial_retry_delay_ms
        self._state: Optional[AuthState] = None
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        with self._lock:
            if self._state and not self._is_expiring_soon():
                return self._state.access_token
            return self._exchange_token()

    def invalidate(self) -> None:
        with self._lock:
            self._state = None

    def _is_expiring_soon(self) -> bool:
        if self._state is None:
            return True
        return (time.time() * 1000) >= (self._state.expires_at - REFRESH_BUFFER_MS)

    def _exchange_token(self) -> str:
        response = request_with_retry(
            self._http,
            "POST",
            f"{self._base_url}/api/auth/v1/token",
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout_ms=self._timeout_ms,
            logger=self._logger,
            max_retries=self._max_retries,
            initial_retry_delay_ms=self._initial_retry_delay_ms,
        )

        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = None
            body = body or {"error": {"code": "MPP_AUTHENTICATION_FAILED", "message": "Merchant token exchange failed"}}
            raise P3PError.from_response(response.status_code, body)

        payload = response.json()
        data = payload.get("data", payload)
        expires_at_ms = None
        if data.get("expires_at"):
            try:
                expires_at_ms = (
                    datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    .timestamp()
                    * 1000
                )
            except Exception:
                expires_at_ms = None
        self._state = AuthState(
            access_token=data["access_token"],
            expires_at=expires_at_ms or (time.time() * 1000 + data["expires_in"] * 1000),
            scope=data.get("scope", ""),
        )
        return self._state.access_token

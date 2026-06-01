from __future__ import annotations

import httpx
import pytest

from pinelabs_p3p_server.server.auth_manager import AuthManager
from pinelabs_p3p_server.utils.errors import P3PError


class _MockTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path == "/api/auth/v1/token":
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "missing"}})
        if request.url.path == "/mpp/v1/auth/token":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "access_token": "server-token",
                        "expires_in": 3600,
                        "scope": "mpp:capture",
                    }
                },
            )
        return httpx.Response(500, json={"error": {"code": "UNEXPECTED", "message": request.url.path}})


def test_auth_manager_does_not_fall_back_to_mpp_auth_path() -> None:
    transport = _MockTransport()
    client = httpx.Client(transport=transport)
    manager = AuthManager("server-client", "server-secret", "http://localhost:8081", http_client=client)

    with pytest.raises(P3PError) as exc:
        manager.get_access_token()

    assert exc.value.http_status == 404
    assert transport.paths == ["/api/auth/v1/token"]

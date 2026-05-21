from __future__ import annotations

from typing import Any, Dict, Optional


class MppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.details = details

    @classmethod
    def from_response(cls, status: int, body: Dict[str, Any]) -> "MppError":
        err = body.get("error") or body
        return cls(
            err.get("code", "MPP_INTERNAL_ERROR"),
            err.get("message", f"HTTP {status}"),
            status,
            err.get("additional_error_details"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": str(self),
                "additional_error_details": self.details,
            }
        }


class MppCaptureError(Exception):
    def __init__(self, message: str, capture_error: Optional[MppError] = None) -> None:
        super().__init__(message)
        self.capture_error = capture_error


class MppVerificationError(Exception):
    pass

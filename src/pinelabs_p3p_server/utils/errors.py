from __future__ import annotations

from typing import Any, Dict, Optional


class P3PError(Exception):
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
    def from_response(cls, status: int, body: Dict[str, Any]) -> "P3PError":
        raw_error = body.get("error")
        if isinstance(raw_error, str):
            return cls(
                body.get("code", "MPP_ERROR"),
                raw_error,
                status,
                body.get("additional_error_details"),
            )
        err = raw_error if isinstance(raw_error, dict) else body
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


class P3PCaptureError(Exception):
    def __init__(self, message: str, capture_error: Optional[P3PError] = None) -> None:
        super().__init__(message)
        self.capture_error = capture_error


class P3PVerificationError(Exception):
    pass

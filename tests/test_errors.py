from __future__ import annotations

from pinelabs_p3p_server.utils.errors import P3PError


def test_mpp_error_parses_top_level_code_and_message() -> None:
    error = P3PError.from_response(
        400,
        {
            "status": 400,
            "code": "INVALID_REQUEST",
            "message": "customer_reference is required",
        },
    )

    assert error.code == "INVALID_REQUEST"
    assert str(error) == "customer_reference is required"
    assert error.http_status == 400


def test_mpp_error_parses_string_error_map() -> None:
    error = P3PError.from_response(400, {"error": "missing request header"})

    assert str(error) == "missing request header"
    assert error.http_status == 400

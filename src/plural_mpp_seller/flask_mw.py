"""Flask integration.

Usage::

    from flask import Flask, jsonify
    from plural_mpp_seller import MppEnvironment, PluralSellerConfig, ChargeOptions, Amount
    from plural_mpp_seller.flask_mw import payment_required

    app = Flask(__name__)
    config = PluralSellerConfig(
        clientId="…",
        clientSecret="…",
        challengeSecretKey="…",
        baseUrl=MppEnvironment.SANDBOX,
    )

    @app.get("/api/premium")
    @payment_required(config, ChargeOptions(
        amount=Amount(value=50000, currency="INR"),
        resource="/api/premium",
    ))
    def premium():
        return jsonify({"data": "premium content"})
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Union

try:
    from flask import Response, request
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Flask is required for plural_mpp_seller.flask_mw. Install with "
        "`pip install plural-mpp-seller-sdk[flask]`."
    ) from exc

from .types.config import ChargeOptions, PluralSellerConfig
from .server.middleware.generic import decide_payment


ChargeResolver = Callable[..., ChargeOptions]


def payment_required(
    config: PluralSellerConfig,
    charge: Union[ChargeOptions, ChargeResolver],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Flask view decorator enforcing MPP payment."""

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            charge_options = charge(request) if callable(charge) else charge
            authorization = request.headers.get("Authorization")

            decision = decide_payment(
                authorization_header=authorization,
                config=config,
                charge_options=charge_options,
            )

            if decision.action != "proceed":
                headers = decision.headers or {}
                import json
                body = json.dumps(decision.problem_details or {})
                return Response(
                    body,
                    status=decision.status,
                    headers=headers,
                    mimetype=headers.get("Content-Type", "application/json"),
                )

            response = view(*args, **kwargs)
            if not isinstance(response, Response):
                from flask import make_response
                response = make_response(response)
            for k, v in (decision.headers or {}).items():
                response.headers[k] = v
            return response

        return wrapper

    return decorator

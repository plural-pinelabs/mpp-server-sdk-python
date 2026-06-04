"""Flask integration.

Usage::

    from flask import Flask, jsonify
    from pinelabs_p3p_server import (
        Amount, ChargeOptions, P3PEnvironment, PaymentGateway,
        PaymentMethod, PineLabsOnlineServerConfig,
    )
    from pinelabs_p3p_server.flask_mw import payment_required

    app = Flask(__name__)
    config = PineLabsOnlineServerConfig(
        clientId="…",
        clientSecret="…",
        env=P3PEnvironment.SANDBOX,
        paymentGateway=PaymentGateway.PineLabsOnline,
        availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY],
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
        "Flask is required for pinelabs_p3p_server.flask_mw. Install with "
        "`pip install pinelabs-online-p3p-server-sdk[flask]`."
    ) from exc

from .types.config import ChargeOptions, PineLabsOnlineServerConfig
from .server.middleware.generic import decide_payment


ChargeResolver = Callable[..., ChargeOptions]


def payment_required(
    config: PineLabsOnlineServerConfig,
    charge: Union[ChargeOptions, ChargeResolver],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Flask view decorator enforcing P3P payment."""

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            charge_options = charge(request) if callable(charge) else charge
            credential_header = request.headers.get("P3P-Credential")

            decision = decide_payment(
                credential_header=credential_header,
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

"""FastAPI / Starlette integration.

Usage::

    from fastapi import FastAPI, Depends
    from plural_mpp_seller import MppEnvironment, PluralSellerConfig, ChargeOptions, Amount
    from plural_mpp_seller.fastapi_mw import PaymentRequired

    app = FastAPI()
    config = PluralSellerConfig(
        clientId="…", clientSecret="…", challengeSecretKey="…",
        baseUrl=MppEnvironment.SANDBOX,
    )

    require_payment = PaymentRequired(config, ChargeOptions(
        amount=Amount(value=50000, currency="INR"),
        resource="/api/premium",
    ))

    @app.get("/api/premium", dependencies=[Depends(require_payment)])
    async def premium(request: Request):
        # The `Payment-Receipt` header is attached to the response automatically
        return {"data": "premium content"}
"""
from __future__ import annotations

from typing import Any, Callable, Union

try:
    from fastapi import HTTPException, Request, Response
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "FastAPI is required for plural_mpp_seller.fastapi_mw. Install with "
        "`pip install plural-mpp-seller-sdk[fastapi]`."
    ) from exc

from ..types.config import ChargeOptions, PluralSellerConfig
from ..server.middleware.generic import decide_payment


ChargeResolver = Callable[[Request], ChargeOptions]


class PaymentRequired:
    """FastAPI dependency enforcing MPP payment on a route.

    Attaches the `Payment-Receipt` header to the response on success.
    Raises ``HTTPException(402)`` with the RFC7807 problem details when
    payment is required, invalid, or failed.
    """

    def __init__(
        self,
        config: PluralSellerConfig,
        charge: Union[ChargeOptions, ChargeResolver],
    ) -> None:
        self._config = config
        self._charge = charge

    async def __call__(self, request: Request, response: Response) -> None:
        charge_options = self._charge(request) if callable(self._charge) else self._charge
        authorization = request.headers.get("authorization")

        decision = decide_payment(
            authorization_header=authorization,
            config=self._config,
            charge_options=charge_options,
        )

        if decision.action == "proceed":
            for k, v in (decision.headers or {}).items():
                response.headers[k] = v
            return

        raise HTTPException(
            status_code=decision.status,
            detail=decision.problem_details or {},
            headers=decision.headers or {},
        )

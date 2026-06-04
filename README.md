# Pine Labs Online P3P Server SDK (Python)

Python SDK for Pine Labs Online P3P server integrations. It mirrors
`p3p-server-sdk`, creates mandates, generates HTTP 402
payment challenges, verifies client credentials, captures payments through P3P,
and builds `Payment-Receipt` headers.

## Installation

```bash
pip install pinelabs-online-p3p-server-sdk[flask]
pip install pinelabs-online-p3p-server-sdk[fastapi]
```

Import module: `pinelabs_p3p_server`. Requires Python 3.9 or newer.

## Config

```python
from pinelabs_p3p_server import (
    P3PEnvironment,
    PaymentGateway,
    PaymentMethod,
    PineLabsOnlineServerConfig,
)

config = PineLabsOnlineServerConfig(
    clientId="...",
    clientSecret="...",
    env=P3PEnvironment.SANDBOX,
    paymentGateway=PaymentGateway.PineLabsOnline,
    availablePaymentMethods=[PaymentMethod.UPI_RESERVE_PAY, PaymentMethod.Crypto],
)
```

`clientId` and `clientSecret` are used internally for `POST /api/auth/v1/token`.
The local challenge HMAC key is derived internally from `clientSecret` with a
stable SDK prefix, so there is no separate challenge-signing config field.
The SDK caches and refreshes bearer tokens before expiry. `env` selects the
Pine Labs host used for auth and `/mpp/v1/*` service calls.

Environment defaults:

| Env | URL | Timeout | Retries | Initial retry delay |
|---|---|---:|---:|---:|
| `P3PEnvironment.SANDBOX` | `https://pluraluat.v2.pinepg.in` | 60000 ms | 2 | 300 ms |
| `P3PEnvironment.PRODUCTION` | `https://api.pluralpay.in` | 45000 ms | 2 | 200 ms |

## Mandates

```python
from pinelabs_p3p_server import Amount, CreateMandateOptions, PineLabsOnlineP3P

p3p = PineLabsOnlineP3P.create(config)
mandate = p3p.create_mandate(CreateMandateOptions(
    mobileNumber="9876543210",
    customerReference="9876543210",
    amount=Amount(value=100000, currency="INR"),
    paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
    validityInDays=20,
))
```

This maps to `POST /mpp/v1/pre-authorize` and sends
`customer.mobile_number`.

## Paid Resource Flow

```python
from flask import Flask, jsonify
from pinelabs_p3p_server import Amount, ChargeOptions
from pinelabs_p3p_server.flask_mw import payment_required

app = Flask(__name__)

@app.get("/api/premium")
@payment_required(config, ChargeOptions(
    amount=Amount(value=50000, currency="INR"),
    resource="/api/premium",
))
def premium():
    return jsonify({"data": "premium content"})
```

The middleware reads `P3P-Credential: Payment <payload>`, not `Authorization`,
so it does not conflict with application bearer auth.

## Capture

```python
from pinelabs_p3p_server import CaptureOptions

result = p3p.capture(CaptureOptions(
    token="MPP_TOK_123",
    amount=Amount(value=50000, currency="INR"),
    paymentMethod=PaymentMethod.UPI_RESERVE_PAY,
    customerReference="9876543210",
    mobileNumber="9876543210",
    challengeId="ch_123",
    merchantOrderReference="order-123",
))
```

The debit body uses `customer.mobile_number`, `payment_amount`,
`payment_token`, and `challenge_id`. The SDK sends `Idempotency-Key` and does
not send `Merchant-ID`.

If `/mpp/v1/debit` returns `202 Accepted`, the SDK treats that as an
accepted-but-processing debit:

- retries the same debit with the same `Idempotency-Key`
- respects `Retry-After` when Pine Labs returns it
- falls back to `initialRetryDelayMs` otherwise
- counts those pending retries against `maxRetries`

If pending retries are exhausted and the debit is still non-terminal, the SDK
returns a pending result and the middleware should return `202` without serving
the protected resource.

## Generic Middleware Helper

```python
from pinelabs_p3p_server.server.middleware import decide_payment

decision = decide_payment(
    credential_header=request.headers.get("P3P-Credential"),
    config=config,
    charge_options=ChargeOptions(
        amount=Amount(value=50000, currency="INR"),
        resource="/api/premium-data",
    ),
)
```

To reconcile a pending debit later, use the status lookup helper:

```python
latest = p3p.get_debit_status("idem_key_123")
```

This calls `GET /mpp/v1/debit/{id}` and returns the same debit payload family
as the original debit call, so application code can resolve pending payments by
idempotency key.

## License

MIT

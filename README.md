# pinelabs-online-mpp-seller-sdk (Python)

Python port of [`@pinelabs-online/mpp-seller-sdk`](../mpp-seller-sdk). x402
Machine Payments Protocol server-side SDK for monetising API endpoints.

Issues HTTP 402 challenges, verifies UPI SBMD credentials, captures
payments, and returns receipts — works standalone or as **Flask** /
**FastAPI** middleware.

## Installation

```bash
pip install pinelabs-online-mpp-seller-sdk[flask]     # with Flask support
pip install pinelabs-online-mpp-seller-sdk[fastapi]   # with FastAPI support
# or from source
cd mpp-seller-sdk-python
pip install -e '.[flask,fastapi]'
```

Requires Python ≥ 3.9. Core deps: `httpx`, `PyJWT[crypto]`.

## Quick Start

### Flask

```python
from flask import Flask, jsonify
from pinelabs-online_mpp_seller import Amount, ChargeOptions, MppEnvironment, pinelabs-onlineSellerConfig
from pinelabs-online_mpp_seller.flask_mw import payment_required

app = Flask(__name__)
config = pinelabs-onlineSellerConfig(
    clientId="…", clientSecret="…", challengeSecretKey="…",
    baseUrl=MppEnvironment.SANDBOX,
)

@app.get("/api/premium")
@payment_required(config, ChargeOptions(
    amount=Amount(value=50000, currency="INR"),
    resource="/api/premium",
))
def premium():
    return jsonify({"data": "premium content"})
```

### FastAPI

```python
from fastapi import FastAPI, Depends
from pinelabs-online_mpp_seller import Amount, ChargeOptions, MppEnvironment, pinelabs-onlineSellerConfig
from pinelabs-online_mpp_seller.fastapi_mw import PaymentRequired

app = FastAPI()
config = pinelabs-onlineSellerConfig(
    clientId="…", clientSecret="…", challengeSecretKey="…",
    baseUrl=MppEnvironment.SANDBOX,
)

require_payment = PaymentRequired(config, ChargeOptions(
    amount=Amount(value=50000, currency="INR"),
    resource="/api/premium",
))

@app.get("/api/premium", dependencies=[Depends(require_payment)])
async def premium():
    return {"data": "premium content"}
```

### Generic (any framework)

```python
from pinelabs-online_mpp_seller import Amount, ChargeOptions, MppEnvironment, pinelabs-onlineSellerConfig
from pinelabs-online_mpp_seller.server.middleware import decide_payment

decision = decide_payment(
    authorization_header=request.headers.get("Authorization"),
    grantex_token_header=request.headers.get("X-Grantex-Token"),
    config=config,
    charge_options=ChargeOptions(
        amount=Amount(value=50000, currency="INR"),
        resource="/api/premium-data",
    ),
)

if decision.action != "proceed":
    # Build a 402/403 response from decision.problem_details + decision.headers
    ...
else:
    # Run business logic; attach decision.headers (Payment-Receipt) to your response
    ...
```

## Configuration

```python
pinelabs-onlineSellerConfig(
    clientId="…", clientSecret="…", challengeSecretKey="…",
    realm="pinelabs-online MPP",
    baseUrl=MppEnvironment.SANDBOX,
    defaultChallengeExpirySeconds=300,
    requestTimeoutMs=30_000,
    maxRetries=3,
    initialRetryDelayMs=500,
    grantex=SellerGrantexConfig(
        jwksUrl="https://grantex.dev/.well-known/jwks.json",
        requiredScopes=["mpp:payment:initiate"],
        enforceGrant=True,
    ),
)
```

## API

### `pinelabs-onlineMPP.create(config)` → `pinelabs-onlineMPPInstance`

| Method | Description |
|---|---|
| `generate_challenge(options)` | Create a signed 402 challenge |
| `verify_credential(auth_header)` | Verify a `Payment` credential |
| `capture(options)` | Capture a payment via pinelabs-online's API |
| `build_receipt_header(result, challenge_id)` | Build `Payment-Receipt` header value |
| `build_receipt_data(result, challenge_id)` | Build receipt data object |
| `verify_grant_token(token)` | Verify a Grantex grant token (`None` when not configured) |

Also exposed: `ChallengeGenerator`, `CredentialVerifier`, `CaptureClient`,
`GrantTokenVerifier`, `AuthManager`, `build_receipt_header`,
`build_receipt_data`, `build_failure_receipt_data`.

## Error handling

```python
from pinelabs-online_mpp_seller import MppError, MppCaptureError, MppVerificationError

try:
    result = mpp.capture(options)
except MppCaptureError as err:
    print(err, err.capture_error and err.capture_error.http_status)
except MppError as err:
    print(err.code, err.http_status)
```

## License

MIT

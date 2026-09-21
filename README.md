# gm-payments

Reusable GoodMorning payment module. Stripe is the first supported provider;
product code owns fulfillment after a payment becomes paid.

## Configuration

```dotenv
PAYMENT_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
```

`STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are backend-only managed
secrets. `STRIPE_PUBLISHABLE_KEY` is intentionally not required: Checkout
Sessions redirect the browser to Stripe and no card data reaches GoodMorning.

Use Stripe test-mode keys and a test webhook endpoint during development. The
module never stores or logs private keys, card numbers, CVCs, or other
card-sensitive data.

## API

- `GET /health`
- `POST /payments/checkout`
- `GET /payments/{payment_id}`
- `POST /payments/{payment_id}/refund`
- `POST /payments/webhooks/stripe`

The payment API records payment state and webhook idempotency. It does not
deliver products, activate subscriptions, or decide business fulfillment.

## Development

```bash
python -m pip install -e '.[dev]'
pytest -q
```

The package is designed to be embedded into a GoodMorning FastAPI application
or exposed as a standalone service through `gm_payments:create_app`.

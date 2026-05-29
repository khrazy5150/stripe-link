# stripe-link

JSON-first rebuild of Stripe Cart.

This repository is intentionally isolated from the original `stripe-cart` app. New AWS resources use the `jb-` prefix so development and migration can happen without touching existing production tables or buckets.

## First Infrastructure Slice

The initial SAM template creates:

- `jb-*-${Environment}` DynamoDB tables for core documents and operational records
- globally unique `jb-*-${Environment}-${AccountId}` S3 buckets
- a regional API Gateway
- a minimal health Lambda at `GET /health`

## Deploy

```bash
sam build
sam deploy --guided
```

Use `Environment=dev` for the first stack.

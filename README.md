# stripe-link

JSON-first rebuild of Stripe Cart.

This repository is intentionally isolated from the original `stripe-cart` app. New AWS resources use the `jb-` prefix so development and migration can happen without touching existing production tables or buckets.

## First Infrastructure Slice

The initial SAM template creates:

- `jb-*-${Environment}` DynamoDB tables for core documents and operational records
- globally unique `jb-*-${Environment}-${AccountId}` S3 buckets
- a regional API Gateway
- a minimal health Lambda at `GET /health`

The `ProjectPrefix` parameter is intentionally restricted to `jb` so this app cannot accidentally deploy over the original `stripe-cart` resources.

## Deploy

```bash
./deploy/validate-resource-names.sh
sam build
sam deploy --config-env dev
```

Use `Environment=dev` for the first stack.

You can also use the wrapper:

```bash
./deploy/deploy.sh dev
```

Deploy the isolated dashboard frontend after the stack has created the dashboard bucket and CloudFront distribution:

```bash
./deploy/deploy-dashboard.sh dev
```

The dashboard deploy script reads `DashboardBucketName`, `DashboardDistributionId`, and `DashboardUrl` from the CloudFormation stack, syncs `dashboard/` to S3, and invalidates CloudFront. A custom dashboard URL such as `dashboard.juniorbay.com` can be attached by deploying the stack with `DASHBOARD_CUSTOM_DOMAIN_NAME` and a CloudFront-compatible ACM certificate ARN from `us-east-1`.

## Local Checks

```bash
./deploy/validate-resource-names.sh
python3.12 -m compileall src
PYTHONPATH=src python3.12 -m unittest discover -s tests
sam validate --lint
sam build
```

## JSON-First Slice

The current application slice supports:

- Product JSON create/get/list
- Offer JSON create/get/list
- Page JSON create/get/list
- offer resolution with selectable prices
- page rendering from `{ page, offer, products, selected_prices }`
- tenant registration/profile setup
- Stripe Connect setup URL and status
- Stripe key metadata storage with read-response redaction
- tenant configuration
- user profile documents
- user preferences
- notifications and refund request records
- tenant shipping configuration
- customer management records
- service booking, fulfillers, availability, and appointments
- invoice records for Stripe-backed service/custom invoices

## Dashboard Shell

Open `dashboard/index.html` locally for the first dashboard shell, or deploy it with `./deploy/deploy-dashboard.sh dev`. Set the API Base URL to the deployed API stage URL or custom API URL, then use the menu forms to exercise registration, Stripe Connect, Stripe keys, services, notifications, invoices, shipping, customers, configuration, profile, and preferences.

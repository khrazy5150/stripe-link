# Stripe Link Dashboard Vue

Proof-of-concept Vue 3 + Vite + Pinia dashboard.

The existing `dashboard/` folder remains untouched and deployable. This app is a separate migration path for the headless dashboard.

## Commands

```bash
npm install
npm run dev
npm run build
```

In local development, Vite proxies `/api/*` to `https://dev.juniorbay.com/*`. This keeps the Vue dashboard connected to the backend without browser CORS issues from `localhost`.

## First Slice

`src/components/StripeKeys.vue` is the first parity component. It is based on `schemas/StripeKeys.schema.json` and uses the current headless API contract:

- `GET /stripe/keys`
- `PUT /stripe/keys`
- `POST /stripe/keys/verify`

The form saves both key modes in one request:

- `test` -> `jb-stripe-keys-dev`
- `live` -> `jb-stripe-keys-prod`

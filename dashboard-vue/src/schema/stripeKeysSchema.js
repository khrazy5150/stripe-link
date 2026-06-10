export const stripeKeysSchema = {
  schema_version: "2026-05-29",
  document_type: "stripe_keys",
  required: ["schema_version", "document_type", "tenant_id", "mode"],
  modes: ["test", "live"],
  fields: {
    publishable_key: {
      label: "Publishable key",
      placeholders: {
        test: "pk_test_...",
        live: "pk_live_...",
      },
      secret: false,
    },
    secret_key_ref: {
      label: "Secret key",
      placeholders: {
        test: "sk_test_...",
        live: "sk_live_...",
      },
      secret: true,
      description: "KMS-wrapped Stripe secret key. Plaintext inputs are encrypted before persistence and never exposed in read responses.",
    },
    webhook_secret_ref: {
      label: "Webhook signing secret",
      placeholders: {
        test: "whsec_...",
        live: "whsec_...",
      },
      secret: true,
      description: "KMS-wrapped Stripe webhook signing secret. Plaintext inputs are encrypted before persistence and never exposed in read responses.",
    },
  },
};

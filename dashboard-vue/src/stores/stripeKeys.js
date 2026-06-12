import { defineStore } from "pinia";
import { apiRequest, getTenantId, setTenantId } from "../api/client";
import { stripeKeysSchema } from "../schema/stripeKeysSchema";

function emptyMode(mode) {
  return {
    mode,
    publishable_key: "",
    secret_key_ref: "",
    webhook_secret_ref: "",
    saved_secret_key: false,
    saved_webhook_secret: false,
    connect_account_id: "",
    connect_status: "not_connected",
    connect_scope: "",
    connect_livemode: false,
    connected_at: null,
  };
}

function normalizeMode(mode, document) {
  const normalized = emptyMode(mode);
  if (!document) return normalized;
  normalized.publishable_key = document.publishable_key || "";
  normalized.saved_secret_key = Boolean(document.secret_key_ref);
  normalized.saved_webhook_secret = Boolean(document.webhook_secret_ref);
  normalized.connect_account_id = document.connect_account_id || "";
  normalized.connect_status = document.connect_status || "not_connected";
  normalized.connect_scope = document.connect_scope || "";
  normalized.connect_livemode = Boolean(document.connect_livemode);
  normalized.connected_at = document.connected_at || null;
  return normalized;
}

export const useStripeKeysStore = defineStore("stripeKeys", {
  state: () => ({
    tenantId: getTenantId(),
    verifyMode: "test",
    modes: {
      test: emptyMode("test"),
      live: emptyMode("live"),
    },
    loading: false,
    saving: false,
    verifying: false,
    connectLoading: false,
    connectStarting: false,
    connectCard: null,
    connectError: "",
    message: "Set API Base URL, then save new Stripe keys.",
    messageTone: "info",
    error: "",
    output: null,
  }),

  actions: {
    resetForCurrentTenant() {
      this.tenantId = getTenantId();
      this.verifyMode = "test";
      this.modes = {
        test: emptyMode("test"),
        live: emptyMode("live"),
      };
      this.loading = false;
      this.saving = false;
      this.verifying = false;
      this.connectLoading = false;
      this.connectStarting = false;
      this.connectCard = null;
      this.connectError = "";
      this.message = "Set API Base URL, then save new Stripe keys.";
      this.messageTone = "info";
      this.error = "";
      this.output = null;
    },

    async load() {
      this.loading = true;
      this.error = "";
      setTenantId(this.tenantId);
      try {
        const body = await apiRequest("/stripe/keys", {
          params: { tenant_id: this.tenantId },
        });
        this.applyLoadedKeys(body.stripe_keys);
        this.output = body;
        this.message = "Stripe keys loaded.";
        this.messageTone = "success";
        await this.loadConnectCard();
      } catch (error) {
        this.output = { error: error.message };
        this.message = "No Stripe keys saved yet. Re-enter keys for this tenant.";
        this.messageTone = "error";
        await this.loadConnectCard();
      } finally {
        this.loading = false;
      }
    },

    async loadConnectCard() {
      this.connectLoading = true;
      this.connectError = "";
      setTenantId(this.tenantId);
      try {
        this.connectCard = await this.loadConnectCardForMode(this.verifyMode);
      } catch (error) {
        this.connectError = error.message;
        this.connectCard = null;
      } finally {
        this.connectLoading = false;
      }
    },

    async loadConnectCardForMode(mode) {
      const body = await apiRequest("/billing/connect-card", {
        params: {
          tenant_id: this.tenantId,
          mode,
        },
      });
      return body.stripe_connect_card;
    },

    async startConnect({ chain = "", path = "existing" } = {}) {
      this.connectStarting = true;
      this.connectError = "";
      setTenantId(this.tenantId);
      const params = {
        tenant_id: this.tenantId,
        mode: this.verifyMode,
        path,
      };
      if (chain) params.chain = chain;
      try {
        const body = await apiRequest("/stripe/connect/start", {
          params,
        });
        if (body.connect_url) {
          window.location.assign(body.connect_url);
        }
      } catch (error) {
        this.connectError = error.message;
      } finally {
        this.connectStarting = false;
      }
    },

    async disconnectConnect() {
      this.connectStarting = true;
      this.connectError = "";
      setTenantId(this.tenantId);
      try {
        const body = await apiRequest("/stripe/connect/status", {
          method: "DELETE",
          params: {
            tenant_id: this.tenantId,
            mode: this.verifyMode,
          },
        });
        this.output = body;
        this.message = `${this.verifyMode === "live" ? "Live" : "Test"} Stripe account disconnected.`;
        this.messageTone = "success";
        await this.loadConnectCard();
      } catch (error) {
        this.connectError = error.message;
        this.messageTone = "error";
      } finally {
        this.connectStarting = false;
      }
    },

    async save() {
      this.saving = true;
      this.error = "";
      setTenantId(this.tenantId);
      try {
        const body = await apiRequest("/stripe/keys", {
          method: "PUT",
          body: this.buildPayload(),
        });
        this.applyLoadedKeys(body.stripe_keys);
        this.output = body;
        this.message = "Stripe keys saved. Secrets are encrypted before persistence.";
        this.messageTone = "success";
        await this.loadConnectCard();
      } catch (error) {
        this.error = error.message;
        this.messageTone = "error";
        this.output = { error: error.message };
      } finally {
        this.saving = false;
      }
    },

    async verify() {
      this.verifying = true;
      this.error = "";
      setTenantId(this.tenantId);
      try {
        const body = await apiRequest("/stripe/keys/verify", {
          method: "POST",
          body: {
            tenant_id: this.tenantId,
            mode: this.verifyMode,
          },
        });
        const result = body.stripe_keys_verification;
        this.output = body;
        this.message = `${this.verifyMode === "live" ? "Live" : "Test"} Stripe keys verified for account ${result.account_id || "unknown"}.`;
        this.messageTone = "success";
      } catch (error) {
        this.error = error.message;
        this.messageTone = "error";
        this.output = { error: error.message };
      } finally {
        this.verifying = false;
      }
    },

    applyLoadedKeys(keys) {
      if (!keys) return;
      if (keys.test || keys.live) {
        this.modes.test = normalizeMode("test", keys.test);
        this.modes.live = normalizeMode("live", keys.live);
        return;
      }
      const mode = keys.mode === "live" ? "live" : "test";
      this.modes[mode] = normalizeMode(mode, keys);
    },

    buildPayload() {
      const now = Math.floor(Date.now() / 1000);
      return {
        schema_version: stripeKeysSchema.schema_version,
        document_type: stripeKeysSchema.document_type,
        tenant_id: this.tenantId,
        modes: {
          test: this.modePayload("test", now),
          live: this.modePayload("live", now),
        },
        updated_at: now,
      };
    },

    modePayload(mode, now) {
      return {
        tenant_id: this.tenantId,
        mode,
        publishable_key: this.modes[mode].publishable_key,
        secret_key_ref: this.modes[mode].secret_key_ref,
        webhook_secret_ref: this.modes[mode].webhook_secret_ref,
        updated_at: now,
      };
    },
  },
});

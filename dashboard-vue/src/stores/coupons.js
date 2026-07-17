import { defineStore } from "pinia";
import { apiRequest, getApiEnvironment, getTenantId } from "../api/client";

function localId(prefix = "coupon") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

function cents(value) {
  return Math.max(0, Math.round(Number(value || 0) * 100));
}

function epochFromDate(value) {
  if (!value) return null;
  const date = new Date(`${value}T23:59:59`);
  return Number.isNaN(date.getTime()) ? null : Math.floor(date.getTime() / 1000);
}

export function formatCouponDiscount(coupon) {
  const discount = coupon?.discount || {};
  if (discount.type === "percent") return `${Number(discount.value || 0)}% off`;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: String(discount.currency || "usd").toUpperCase(),
  }).format(Number(discount.value || 0) / 100);
}

export function couponIsUsable(coupon) {
  if (coupon?.status !== "active") return false;
  const expiresAt = coupon?.restrictions?.expires_at;
  if (expiresAt && Number(expiresAt) <= Math.floor(Date.now() / 1000)) return false;
  const maxRedemptions = coupon?.restrictions?.max_redemptions;
  if (maxRedemptions && Number(coupon.redemption_count || 0) >= Number(maxRedemptions)) return false;
  return true;
}

export const useCouponsStore = defineStore("coupons", {
  state: () => ({
    coupons: [],
    loading: false,
    loaded: false,
    saving: false,
    error: "",
    message: "Click Load Coupons to see coupons.",
    filters: {
      search: "",
      status: "usable",
    },
  }),

  getters: {
    usableCoupons(state) {
      return state.coupons.filter(couponIsUsable);
    },

    filteredCoupons(state) {
      const search = state.filters.search.trim().toLowerCase();
      return state.coupons.filter((coupon) => {
        if (state.filters.status === "usable" && !couponIsUsable(coupon)) return false;
        if (state.filters.status !== "usable" && state.filters.status !== "all" && coupon.status !== state.filters.status) return false;
        if (!search) return true;
        return [
          coupon.coupon_id,
          coupon.stripe_coupon_id,
          coupon.stripe_promo_code_id,
          coupon.code,
          coupon.name,
          coupon.status,
          coupon.discount?.type,
        ].filter(Boolean).join(" ").toLowerCase().includes(search);
      });
    },

    // Live count, so the banner tracks the filter as you type — no Apply button needed.
    statusMessage() {
      if (!this.loaded) return this.message;
      return `${this.filteredCoupons.length} of ${this.coupons.length} coupon${this.coupons.length === 1 ? "" : "s"} shown.`;
    },
  },

  actions: {
    reset() {
      this.coupons = [];
      this.loading = false;
      this.loaded = false;
      this.saving = false;
      this.error = "";
      this.message = "Click Load Coupons to see coupons.";
      this.filters.search = "";
      this.filters.status = "usable";
    },

    // Load on first filter interaction so search works without clicking Load Coupons first (mirrors Products).
    ensureLoaded() {
      if (!this.loaded && !this.loading) this.load({ status: "all" });
    },

    async load({ status = "all" } = {}) {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/coupons", { params: { status } });
        this.coupons = Array.isArray(body.coupons) ? body.coupons : [];
        this.loaded = true;
        this.message = this.coupons.length
          ? `${this.filteredCoupons.length} of ${this.coupons.length} coupon${this.coupons.length === 1 ? "" : "s"} shown.`
          : "No coupons found. Create a coupon before attaching one to an offer.";
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.loading = false;
      }
    },

    async saveCoupon(form) {
      this.saving = true;
      this.error = "";
      try {
        const coupon = buildCouponDocument(form);
        const path = form.coupon_id ? `/coupons/${encodeURIComponent(form.coupon_id)}` : "/coupons";
        const method = form.coupon_id ? "PUT" : "POST";
        const body = await apiRequest(path, { method, body: coupon });
        this.upsertCoupon(body.coupon || coupon);
        this.loaded = true;
        this.message = `${coupon.name || coupon.code} was saved.`;
        return body.coupon || coupon;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },

    upsertCoupon(coupon) {
      const index = this.coupons.findIndex((item) => item.coupon_id === coupon.coupon_id);
      if (index >= 0) this.coupons.splice(index, 1, coupon);
      else this.coupons.unshift(coupon);
    },
  },
});

export function buildCouponDocument(form) {
  const now = Math.floor(Date.now() / 1000);
  const couponId = form.coupon_id || localId("coupon");
  const discount = {
    type: form.discount_type,
    value: form.discount_type === "fixed" ? cents(form.value) : Number(form.value || 0),
    duration: form.duration,
  };
  if (form.discount_type === "fixed") discount.currency = String(form.currency || "usd").toLowerCase();
  if (form.duration === "repeating") discount.duration_months = Math.max(1, Number(form.duration_months || 1));

  return {
    schema_version: "2026-05-29",
    document_type: "coupon",
    tenant_id: getTenantId(),
    coupon_id: couponId,
    canonical: true,
    stripe_mode: getApiEnvironment(),
    stripe_coupon_id: form.stripe_coupon_id || couponId,
    stripe_promo_code_id: form.stripe_promo_code_id || `promo_${couponId.replace(/^coupon_/, "")}`,
    code: String(form.code || "").trim().toUpperCase(),
    name: form.name || String(form.code || "").trim().toUpperCase(),
    status: form.status || "active",
    discount,
    restrictions: {
      expires_at: epochFromDate(form.expires_on),
      max_redemptions: form.max_redemptions ? Number(form.max_redemptions) : null,
      max_redemptions_per_customer: form.max_redemptions_per_customer ? Number(form.max_redemptions_per_customer) : null,
      first_time_only: Boolean(form.first_time_only),
      minimum_amount: form.minimum_amount ? cents(form.minimum_amount) : null,
      minimum_amount_currency: form.minimum_amount ? String(form.minimum_amount_currency || "usd").toLowerCase() : null,
    },
    applies_to_offer_ids: Array.isArray(form.applies_to_offer_ids) ? form.applies_to_offer_ids : [],
    redemption_count: Number(form.redemption_count || 0),
    sync: {
      status: "synced",
      last_synced_at: now,
      error: null,
    },
    created_at: form.created_at || now,
    updated_at: now,
  };
}

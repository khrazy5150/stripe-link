<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Billing</h1>
        <p>Your Junior Bay subscription — separate from the Stripe account you connect to get paid.</p>
      </div>
    </header>

    <div v-if="billing.loading && !billing.loaded" class="billing-muted">Loading…</div>

    <template v-else>
      <!-- Status card -->
      <section class="dashboard-card billing-status-card" :class="{ walled: billing.walled }">
        <div class="billing-status-main">
          <span class="billing-status-pill" :class="statusTone">{{ statusLabel }}</span>
          <p v-if="billing.current.billing_exempt" class="billing-status-note">
            Your account is comped — full access, no charge.
          </p>
          <p v-else-if="billing.walled" class="billing-status-note">
            {{ billing.trialExpired ? "Your free trial has ended." : "Your account is on hold." }}
            Subscribe to keep your pages live and take payments.
          </p>
          <p v-else-if="billing.onTrial" class="billing-status-note">
            <strong>{{ billing.trialDaysLeft }}</strong> {{ billing.trialDaysLeft === 1 ? "day" : "days" }} left in your free trial — full access, no card required yet.
          </p>
          <p v-else-if="billing.current.has_subscription" class="billing-status-note">
            You're subscribed{{ planLabel ? ` to ${planLabel}` : "" }}.
          </p>
        </div>
        <button
          v-if="billing.current.has_subscription"
          type="button" class="secondary-action" :disabled="billing.working"
          @click="billing.openPortal()"
        >
          {{ billing.working ? "Opening…" : "Manage subscription" }}
        </button>
      </section>

      <!-- Plans -->
      <section class="dashboard-card">
        <header class="dashboard-card-header">
          <div>
            <h2>{{ billing.current.has_subscription ? "Change plan" : "Choose a plan" }}</h2>
            <p>Card required to subscribe. Cancel anytime from Manage subscription.</p>
          </div>
        </header>

        <div class="billing-plan-grid">
          <div v-for="plan in billing.plans" :key="plan.plan_key"
               class="billing-plan" :class="{ current: plan.plan_key === billing.current.billing_plan_key }">
            <div class="billing-plan-head">
              <h3>{{ plan.label }}</h3>
              <span v-if="plan.plan_key === billing.current.billing_plan_key" class="billing-plan-current">Current</span>
            </div>
            <p class="billing-plan-price"><strong>{{ price(plan.monthly_amount) }}</strong><span>/mo</span></p>
            <p v-if="plan.tagline" class="billing-plan-tagline">{{ plan.tagline }}</p>
            <ul v-if="plan.features && plan.features.length" class="billing-plan-features">
              <li v-for="(f, i) in plan.features" :key="i">{{ f }}</li>
            </ul>
            <button
              type="button" class="primary-action"
              :disabled="billing.working || plan.plan_key === billing.current.billing_plan_key"
              @click="subscribe(plan.plan_key)"
            >
              {{ subscribeLabel(plan) }}
            </button>
          </div>
        </div>

        <div class="billing-promo">
          <label>
            Have a promo code?
            <input v-model.trim="promoCode" type="text" placeholder="e.g. TRIAL14" autocomplete="off" />
          </label>
        </div>

        <div v-if="billing.error" class="keys-status-banner error">{{ billing.error }}</div>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { usePlatformBillingStore } from "../stores/platformBilling";

const billing = usePlatformBillingStore();
const promoCode = ref("");

onMounted(() => {
  if (!billing.loaded) billing.load();
});

const planLabel = computed(() => {
  const p = billing.plans.find((x) => x.plan_key === billing.current.billing_plan_key);
  return p ? p.label : "";
});

const statusLabel = computed(() => {
  if (billing.current.billing_exempt) return "Comped";
  if (billing.trialExpired) return "Trial ended";
  if (billing.onTrial) return "Free trial";
  const s = billing.current.billing_status;
  return { active: "Active", past_due: "Payment due", suspended: "On hold", canceled: "Canceled" }[s] || "Trial";
});

const statusTone = computed(() => {
  if (billing.current.billing_exempt || billing.current.has_subscription) return "ok";
  if (billing.walled) return "danger";
  return "info";
});

function price(cents) {
  return `$${((Number(cents) || 0) / 100).toFixed(2)}`;
}

function subscribeLabel(plan) {
  if (plan.plan_key === billing.current.billing_plan_key) return "Current plan";
  return billing.current.has_subscription ? "Switch to this plan" : `Subscribe to ${plan.label}`;
}

function subscribe(planKey) {
  billing.subscribe({ planKey, promoCode: promoCode.value });
}
</script>

<style scoped>
.billing-muted { color: var(--muted); padding: 1rem 0; }
.billing-status-card { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.billing-status-card.walled { border: 1px solid #dc2626; }
.billing-status-main { display: flex; flex-direction: column; gap: 0.4rem; }
.billing-status-pill { align-self: flex-start; font-size: 1.1rem; font-weight: 700; padding: 0.2rem 0.7rem; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.03em; }
.billing-status-pill.ok { background: #dcfce7; color: #166534; }
.billing-status-pill.info { background: #dbeafe; color: #1e40af; }
.billing-status-pill.danger { background: #fee2e2; color: #991b1b; }
.billing-status-note { margin: 0; color: var(--muted); font-size: 1.4rem; }
.billing-plan-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(24rem, 1fr)); gap: 1.2rem; }
.billing-plan { border: 1px solid var(--line); border-radius: 12px; padding: 1.4rem; display: flex; flex-direction: column; gap: 0.6rem; }
.billing-plan.current { border-color: var(--brand, #4f46e5); }
.billing-plan-head { display: flex; align-items: center; justify-content: space-between; }
.billing-plan-head h3 { margin: 0; }
.billing-plan-current { font-size: 1.05rem; font-weight: 700; color: var(--brand, #4f46e5); }
.billing-plan-price strong { font-size: 2.4rem; }
.billing-plan-price span { color: var(--muted); }
.billing-plan-tagline { margin: 0; color: var(--muted); }
.billing-plan-features { margin: 0.4rem 0; padding-left: 1.2rem; color: var(--muted); font-size: 1.35rem; display: grid; gap: 0.3rem; }
.billing-plan .primary-action { margin-top: auto; }
.billing-promo { margin-top: 1.2rem; }
.billing-promo label { display: flex; flex-direction: column; gap: 0.4rem; max-width: 28rem; color: var(--muted); font-size: 1.3rem; }
.billing-promo input { padding: 0.7rem 1rem; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; }
</style>

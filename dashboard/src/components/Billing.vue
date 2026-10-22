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
            Your account is on hold. Contact support to continue.
          </p>
          <p v-else-if="billing.onFreePlan" class="billing-status-note">
            You're on the <strong>Free plan</strong> — your pages stay live and you keep selling at the standard
            fee. Upgrade to unlock premium features and lower transaction fees.
          </p>
          <p v-else-if="billing.onTrial" class="billing-status-note">
            <strong>{{ billing.trialDaysLeft }}</strong> {{ billing.trialDaysLeft === 1 ? "day" : "days" }} left in your free trial — full access, no card required yet.
          </p>
          <p v-else-if="billing.current.has_subscription && billing.current.billing_status === 'past_due'" class="billing-status-note">
            There's a payment issue with your subscription — premium stays active while Stripe retries.
            Update your card with the button on the right.
          </p>
          <p v-else-if="billing.current.has_subscription && billing.current.cancel_at_period_end" class="billing-status-note">
            Your subscription is set to cancel — premium stays active until
            <strong>{{ periodEndLabel }}</strong>, then you'll move to the Free plan (your pages stay live).
          </p>
          <p v-else-if="billing.current.has_subscription" class="billing-status-note">
            You're subscribed{{ planLabel ? ` to ${planLabel}` : "" }}.
          </p>
        </div>
        <div v-if="billing.current.has_subscription" class="billing-status-actions">
          <button
            v-if="billing.current.cancel_at_period_end"
            type="button" class="resume-action" :disabled="billing.working"
            @click="billing.setCancellation(false)"
          >
            {{ billing.working ? "Working…" : "Resume subscription" }}
          </button>
          <template v-else-if="confirmingCancel">
            <button type="button" class="secondary-action" :disabled="billing.working" @click="confirmingCancel = false">
              Keep premium
            </button>
            <button type="button" class="confirm-cancel-action" :disabled="billing.working" @click="confirmCancel">
              {{ billing.working ? "Canceling…" : "Yes, cancel at period end" }}
            </button>
          </template>
          <button
            v-else
            type="button" class="setup-action" :disabled="billing.working"
            @click="confirmingCancel = true"
          >
            Cancel subscription
          </button>
          <!-- The Stripe portal is the only place to fix a failing card — surface it as a button ONLY then. -->
          <button
            v-if="billing.current.billing_status === 'past_due'"
            type="button" class="setup-action" :disabled="billing.working"
            @click="billing.openPortal()"
          >
            {{ billing.working ? "Opening…" : "Update payment method" }}
          </button>
        </div>
      </section>

      <!-- Plans -->
      <section class="dashboard-card">
        <header class="dashboard-card-header">
          <div>
            <h2>{{ billing.current.has_subscription ? "Change plan" : "Choose a plan" }}</h2>
            <p>Card required to subscribe. Cancel anytime — right here.</p>
          </div>
        </header>

        <div class="billing-plan-grid billing-plan-grid--spaced">
          <div v-for="plan in billing.plans" :key="plan.plan_key || 'free'"
               class="billing-plan"
               :class="{ current: isCurrent(plan), free: plan.free }">
            <div class="billing-plan-head">
              <h3>{{ plan.label }}</h3>
              <span v-if="isCurrent(plan)" class="billing-plan-current">Current</span>
              <span v-else-if="plan.retired" class="billing-plan-retired">No longer offered</span>
            </div>
            <p class="billing-plan-price"><strong>{{ price(plan.monthly_amount) }}</strong><span>/mo</span></p>
            <p v-if="plan.tagline" class="billing-plan-tagline">{{ plan.tagline }}</p>
            <!-- Said plainly, because "my plan vanished from the page" is alarming and this is not. -->
            <p v-if="plan.retired" class="billing-plan-tagline">
              This plan is no longer offered to new customers. Yours continues until you cancel.
            </p>
            <ul v-if="plan.features && plan.features.length" class="billing-plan-features">
              <li v-for="(f, i) in plan.features" :key="i">{{ f }}</li>
            </ul>
            <!-- The free tier has no button: it is not something you buy, it is where you already are
                 when you buy nothing. A "Subscribe to Free" would be a control that does nothing. -->
            <p v-if="plan.free" class="billing-plan-foot">
              {{ isCurrent(plan) ? "You are on this plan." : "Always available — no card needed." }}
            </p>
            <button
              v-else
              type="button" class="primary-action"
              :disabled="billing.working || plan.plan_key === billing.current.billing_plan_key"
              @click="subscribe(plan.plan_key)"
            >
              {{ subscribeLabel(plan) }}
            </button>
          </div>
        </div>

        <!-- Only when a promo could actually work. There are none in production, so this was asking
             every tenant for a code that could not exist. -->
        <div v-if="billing.promosAvailable" class="billing-promo">
          <label>
            Have a promo code?
            <input v-model.trim="promoCode" type="text" placeholder="e.g. TRIAL14" autocomplete="off" />
          </label>
        </div>

        <!-- Low-key portal access: the Stripe portal is the only place to change cards / download invoices. -->
        <p v-if="billing.current.has_subscription" class="billing-portal-link">
          Need to update your card or download invoices?
          <a href="#" @click.prevent="billing.openPortal()">Open the secure Stripe portal</a>
        </p>

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

/* The free card has no plan_key, so "am I on this?" is a question about having no subscription at
   all -- not a key comparison that would match every tenant whose billing_plan_key is "". */
function isCurrent(plan) {
  if (plan.free) return !billing.current.has_subscription;
  return plan.plan_key === billing.current.billing_plan_key;
}
const confirmingCancel = ref(false);

async function confirmCancel() {
  await billing.setCancellation(true);
  confirmingCancel.value = false;
}

const periodEndLabel = computed(() => {
  const end = Number(billing.current.current_period_end || 0);
  return end ? new Date(end * 1000).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "the end of your billing period";
});

onMounted(() => {
  if (!billing.loaded) billing.load();
});

const planLabel = computed(() => {
  const p = billing.plans.find((x) => x.plan_key === billing.current.billing_plan_key);
  return p ? p.label : "";
});

const statusLabel = computed(() => {
  if (billing.current.billing_exempt) return "Comped";
  if (billing.onFreePlan) return "Free plan";
  if (billing.onTrial) return "Free trial";
  const s = billing.current.billing_status;
  return { active: "Active", past_due: "Payment due", suspended: "On hold", canceled: "Free plan" }[s] || "Trial";
});

const statusTone = computed(() => {
  if (billing.current.billing_status === "past_due") return "danger";  // payment problem — never a green pill
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
.billing-status-actions { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; justify-content: flex-end; }
/* Green mirror of the amber .setup-action — resuming is the happy path. */
.resume-action {
  min-height: 4rem;
  border: 0;
  border-radius: var(--radius-md);
  background: #16a34a;
  color: #fff;
  cursor: pointer;
  font-weight: 900;
  padding: 0.8rem 1.6rem;
  white-space: nowrap;
}
.resume-action:disabled { opacity: 0.6; cursor: default; }
/* Red mirror of .setup-action/.resume-action so the confirm step matches its siblings. */
.confirm-cancel-action {
  min-height: 4rem;
  border: 0;
  border-radius: var(--radius-md);
  background: #dc2626;
  color: #fff;
  cursor: pointer;
  font-weight: 900;
  padding: 0.8rem 1.6rem;
  white-space: nowrap;
}
.confirm-cancel-action:disabled { opacity: 0.6; cursor: default; }
.billing-portal-link { margin-top: 1rem; font-size: 1.2rem; color: var(--text-muted); }
.billing-portal-link a { color: inherit; text-decoration: underline; }
.billing-status-main { display: flex; flex-direction: column; gap: 0.4rem; }
.billing-status-pill { align-self: flex-start; font-size: 1.1rem; font-weight: 700; padding: 0.2rem 0.7rem; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.03em; }
.billing-status-pill.ok { background: #dcfce7; color: #166534; }
.billing-status-pill.info { background: #dbeafe; color: #1e40af; }
.billing-status-pill.danger { background: #fee2e2; color: #991b1b; }
.billing-status-note { margin: 0; color: var(--muted); font-size: 1.4rem; }
/* PLAN CARDS. They were a 1px outline on the same background as the panel behind them, so at a
   glance there was no card -- just a price floating in a box. They now sit on their own surface with
   a shadow, which is what makes a card read as a thing you can pick rather than a region of text. */
.billing-plan-grid--spaced { margin-top: 1.6rem; }
.billing-plan-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(26rem, 1fr));
  gap: 1.6rem; align-items: stretch;
}
.billing-plan {
  position: relative; border: 1px solid var(--line); border-radius: 14px;
  padding: 2rem 1.8rem 1.8rem; display: flex; flex-direction: column; gap: 0.8rem;
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05), 0 8px 20px rgba(15, 23, 42, 0.05);
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}
.billing-plan:hover {
  transform: translateY(-2px); border-color: var(--brand, #4f46e5);
  box-shadow: 0 2px 4px rgba(15, 23, 42, 0.06), 0 14px 32px rgba(15, 23, 42, 0.1);
}
@media (prefers-reduced-motion: reduce) { .billing-plan, .billing-plan:hover { transition: none; transform: none; } }
/* The plan you are on is stated by a RING and a label, not by colour alone. */
.billing-plan-retired {
  font-size: 1.05rem; font-weight: 700; color: var(--muted);
  background: var(--line); padding: 0.2rem 0.7rem; border-radius: 999px;
  text-transform: uppercase; letter-spacing: 0.03em;
}
/* The free card is quieter on purpose: it is the baseline the others are measured against, not an
   option competing with them. */
.billing-plan.free { background: var(--ground, var(--surface)); box-shadow: none; }
.billing-plan.free:hover { transform: none; border-color: var(--line); box-shadow: none; }
.billing-plan-foot { margin: auto 0 0; color: var(--muted); font-size: 1.25rem; }
.billing-plan.current {
  border-color: var(--brand, #4f46e5);
  box-shadow: 0 0 0 2px var(--brand, #4f46e5), 0 8px 20px rgba(79, 70, 229, 0.12);
}
.billing-plan-head { display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; }
.billing-plan-head h3 { margin: 0; font-size: 1.7rem; }
.billing-plan-current {
  font-size: 1.05rem; font-weight: 700; color: var(--brand, #4f46e5);
  background: rgba(79, 70, 229, 0.1); padding: 0.2rem 0.7rem; border-radius: 999px;
  text-transform: uppercase; letter-spacing: 0.03em;
}
.billing-plan-price { margin: 0; display: flex; align-items: baseline; gap: 0.3rem; }
.billing-plan-price strong { font-size: 3.2rem; line-height: 1.1; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.billing-plan-price span { color: var(--muted); font-size: 1.3rem; }
.billing-plan-tagline { margin: 0; color: var(--muted); }
/* A rule under the price separates "what it costs" from "what you get". */
.billing-plan-features {
  margin: 0.6rem 0 0.2rem; padding: 1rem 0 0 1.2rem; color: var(--text);
  font-size: 1.35rem; display: grid; gap: 0.5rem; border-top: 1px solid var(--line);
}
.billing-plan-features li::marker { color: var(--brand, #4f46e5); }
.billing-plan .primary-action { margin-top: auto; width: 100%; min-height: 4rem; }

/* PROMO CODE. It sat 1.2rem under the grid with nothing between them, so it read as part of the last
   card rather than as a separate step. A rule and real space say it belongs to the section. */
.billing-promo { margin-top: 2.4rem; padding-top: 2rem; border-top: 1px solid var(--line); }
.billing-promo label { display: flex; flex-direction: column; gap: 0.5rem; max-width: 28rem; color: var(--muted); font-size: 1.3rem; }
.billing-promo input { padding: 0.9rem 1.1rem; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; }
.billing-promo input:focus-visible { outline: 2px solid var(--brand, #4f46e5); outline-offset: 1px; border-color: var(--brand, #4f46e5); }
</style>

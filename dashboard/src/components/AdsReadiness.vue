<template>
  <section class="dashboard-card" aria-labelledby="readiness-heading">
    <header class="dashboard-card-header">
      <div>
        <h2 id="readiness-heading">{{ ready ? "Ready to advertise" : "Get ready to advertise" }}</h2>
        <p v-if="!ready">Finish these steps, in Google Ads or here. You can leave and come back: each one is checked again when you return, and your campaign drafts are kept.</p>
      </div>
      <button class="secondary-action" type="button" :disabled="checking" @click="check">
        {{ checking ? "Checking…" : "Check again" }}
      </button>
    </header>
    <div v-if="!ready || expanded" class="dashboard-card-body">
      <p v-if="error" class="readiness-error" role="alert">{{ error }}</p>
      <ol class="readiness-steps">
        <li v-for="step in steps" :key="step.key" :class="`readiness-${step.status}`">
          <span class="readiness-badge">{{ badges[step.status] }}</span>
          <div>
            <strong>{{ step.title }}</strong>
            <p>{{ step.detail }}</p>
            <a v-if="step.link && step.status === 'action'" :href="step.link" target="_blank" rel="noopener noreferrer">{{ step.linkText }}</a>
            <button v-if="step.view && step.status === 'action'" class="secondary-action" type="button" @click="$emit('navigate', step.view)">
              {{ step.viewText }}
            </button>
            <button v-if="step.manage && step.status === 'action'" class="secondary-action" type="button" @click="$emit('manage-accounts')">
              Connect Google Ads
            </button>
          </div>
        </li>
      </ol>
    </div>
    <div v-else class="dashboard-card-body">
      <button class="link-action" type="button" @click="expanded = true">Show the checklist</button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { fetchAdsDestinationOptions, fetchAdsReadiness } from "../api/attention";

// What a first-time advertiser has to finish before a campaign can run (plans/ADS_PRIMITIVE.md, Advertiser
// onboarding). Nothing is stored: every step is read again from Google and Junior Bay, so returning after
// finishing something in Google Ads is all "resuming" takes.
const props = defineProps({
  connections: { type: Array, required: true },
  accounts: { type: Array, required: true },
});
defineEmits(["manage-accounts", "navigate"]);

const badges = { done: "Done", action: "To do", pending: "In review", not_required: "Not needed", unknown: "Couldn’t check" };
const GOOGLE_ADS = "https://ads.google.com/";
const checking = ref(false);
const expanded = ref(false);
const error = ref("");
const readiness = ref({});
const pages = ref(null);

const connected = computed(() => props.accounts.filter((account) => account.connected));

const steps = computed(() => {
  const list = [
    {
      key: "account", title: "Have a Google Ads account",
      status: props.connections.length || props.accounts.length ? "done" : "action",
      detail: "Ads are paid to Google directly, from your own Google Ads account.",
      link: GOOGLE_ADS, linkText: "Create a Google Ads account",
    },
    {
      key: "connect", title: "Connect it to Junior Bay",
      status: connected.value.length ? "done" : "action", manage: true,
      detail: connected.value.length
        ? `Connected: advertiser ${connected.value.map((account) => account.account_id).join(", ")}.`
        : "Sign in with Google and choose the advertiser Junior Bay should manage.",
    },
  ];
  for (const account of connected.value) {
    const state = readiness.value[account.account_id];
    const suffix = connected.value.length > 1 ? ` (${account.account_id})` : "";
    const test = state?.test_account;
    list.push(
      {
        key: `status-${account.account_id}`, title: `Account in good standing${suffix}`,
        status: state ? state.account_status : "unknown",
        detail: test ? "Not needed for Google Ads test accounts."
          : state?.account_status === "done" ? "Google reports the account as enabled."
            : `Google reports the account as ${String(state?.google_status || "unknown").toLowerCase()}. Open Google Ads to see why.`,
        link: GOOGLE_ADS, linkText: "Open Google Ads",
      },
      {
        key: `billing-${account.account_id}`, title: `Set up billing in Google Ads${suffix}`,
        status: state ? state.billing : "unknown",
        detail: test ? "Not needed for Google Ads test accounts."
          : state?.billing === "pending" ? "Google is reviewing your payment method."
            : state?.billing === "done" ? "Google has an approved payment method."
              : "Add a payment method in Google Ads under Billing. Google charges you for clicks directly.",
        link: GOOGLE_ADS, linkText: "Open Google Ads billing",
      },
      {
        key: `verification-${account.account_id}`, title: `Complete advertiser verification${suffix}`,
        status: state ? (state.verification === "needs_billing" ? "action" : state.verification) : "unknown",
        detail: test ? "Not needed for Google Ads test accounts."
          : state?.verification === "needs_billing" ? "Google asks for verification once billing is set up. Do that first."
            : state?.verification === "pending" ? "Google is reviewing your verification."
              : state?.verification === "done" ? "Verified, or Google hasn't asked for it yet."
                : "Google needs to verify who is advertising. Follow Google's steps.",
        link: state?.verification_url || GOOGLE_ADS, linkText: "Start verification in Google Ads",
      },
    );
  }
  list.push({
    key: "page", title: "Publish a landing page linked to an offer",
    status: pages.value === null ? "unknown" : pages.value > 0 ? "done" : "action",
    detail: pages.value ? "Your ads send people to one of your published landing pages." : "An ad needs a published page to send people to.",
    view: "landingPages", viewText: "Go to Landing Pages",
  });
  return list;
});

const ready = computed(() => steps.value.every((step) => ["done", "not_required"].includes(step.status)));

async function check() {
  checking.value = true;
  error.value = "";
  try {
    const [destinations, ...states] = await Promise.all([
      fetchAdsDestinationOptions().catch(() => null),
      ...connected.value.map((account) => fetchAdsReadiness(account.account_id).catch(() => null)),
    ]);
    pages.value = destinations ? destinations.length : null;
    readiness.value = Object.fromEntries(connected.value.map((account, index) => [account.account_id, states[index]]).filter(([, state]) => state));
    if (states.some((state) => !state)) error.value = "Google Ads couldn’t be reached for every check. Try Check again shortly.";
  } finally {
    checking.value = false;
  }
}

watch(() => connected.value.map((account) => account.account_id).join(","), check);
onMounted(check);
</script>

<style scoped>
.readiness-steps { display: grid; gap: 1rem; margin: 0; padding: 0; list-style: none; }
.readiness-steps li { display: grid; grid-template-columns: 7rem 1fr; gap: 1rem; align-items: start; }
.readiness-steps p { margin: .2rem 0 .4rem; }
.readiness-badge { display: inline-block; padding: .15rem .55rem; border-radius: 999px; font-size: .8rem; text-align: center; border: 1px solid var(--border, #d0d5dd); }
.readiness-done .readiness-badge, .readiness-not_required .readiness-badge { color: var(--success, #067647); }
.readiness-action .readiness-badge { color: var(--danger, #b91c1c); }
.readiness-error { color: var(--danger, #b91c1c); }
</style>

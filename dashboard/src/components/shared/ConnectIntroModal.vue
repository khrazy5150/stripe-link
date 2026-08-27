<template>
  <div v-if="store.connectIntro" class="modal-backdrop" @click.self="store.dismissConnectIntro()">
    <section class="modal-card connect-intro-card" role="dialog" aria-modal="true" aria-labelledby="connect-intro-title">
      <div class="ci-brandline">
        <img :src="assetUrl('/icon/favicon.png')" alt="" width="34" height="34" />
        <span class="ci-handshake">🤝</span>
        <span class="ci-stripe">stripe</span>
      </div>

      <h2 id="connect-intro-title">Start selling &amp; get paid</h2>
      <p class="ci-sub">
        Junior Bay partners with <strong>Stripe</strong> for secure payment processing.
        {{ isTest ? "You're setting up a TEST sandbox — no real money moves." : "Payouts go straight to your bank account." }}
      </p>

      <div class="ci-checklist">
        <p class="ci-checklist-title">Have these ready — setup takes about 5 minutes:</p>
        <ul>
          <li>✓ Your legal name and date of birth</li>
          <li>✓ A bank account for payouts (routing &amp; account number)</li>
          <li>✓ A government ID, in case Stripe asks to verify you</li>
          <li>✓ Business details — optional if you're an individual</li>
        </ul>
      </div>

      <label class="ci-country">
        Home country
        <select v-model="country">
          <option v-for="c in COUNTRIES" :key="c.code" :value="c.code">{{ c.label }}</option>
        </select>
      </label>

      <p class="ci-reassure">
        You'll finish on Stripe's secure page and come right back to Junior Bay automatically.
      </p>

      <div v-if="store.connectError" class="keys-status-banner error">{{ store.connectError }}</div>

      <div class="ci-actions">
        <button type="button" class="secondary-action" :disabled="store.connectStarting" @click="store.dismissConnectIntro()">
          Not now
        </button>
        <button type="button" class="primary-action" :disabled="store.connectStarting" @click="go">
          {{ store.connectStarting ? "Opening Stripe…" : "Create my Stripe account" }}
        </button>
      </div>
    </section>
  </div>
</template>

<script setup>
// Branded interstitial shown before the Stripe Connect OAuth redirect (Standard accounts can't embed
// onboarding, so the win is a friendly, expectation-setting wrapper — plans/TODO.md "Branded Connect
// onboarding intro"). Mounted ONCE in App.vue; every startConnect() entry point opens it.
import { ref, computed } from "vue";
import { assetUrl } from "../../api/client";
import { useStripeKeysStore } from "../../stores/stripeKeys";

const store = useStripeKeysStore();
const country = ref("US");

const isTest = computed(() => store.verifyMode === "test");

// Stripe-supported countries (common set; the full list is on Stripe's own page if someone's isn't here —
// the picker only prefills, Stripe's flow remains the source of truth).
const COUNTRIES = [
  { code: "US", label: "United States" },
  { code: "CA", label: "Canada" },
  { code: "GB", label: "United Kingdom" },
  { code: "AU", label: "Australia" },
  { code: "NZ", label: "New Zealand" },
  { code: "IE", label: "Ireland" },
  { code: "DE", label: "Germany" },
  { code: "FR", label: "France" },
  { code: "ES", label: "Spain" },
  { code: "IT", label: "Italy" },
  { code: "NL", label: "Netherlands" },
  { code: "BE", label: "Belgium" },
  { code: "PT", label: "Portugal" },
  { code: "AT", label: "Austria" },
  { code: "CH", label: "Switzerland" },
  { code: "SE", label: "Sweden" },
  { code: "NO", label: "Norway" },
  { code: "DK", label: "Denmark" },
  { code: "FI", label: "Finland" },
  { code: "PL", label: "Poland" },
  { code: "MX", label: "Mexico" },
  { code: "BR", label: "Brazil" },
  { code: "JP", label: "Japan" },
  { code: "SG", label: "Singapore" },
  { code: "HK", label: "Hong Kong" },
  { code: "AE", label: "United Arab Emirates" },
];

function go() {
  const args = store.connectIntro || {};
  store.launchConnect({ ...args, country: country.value });
}
</script>

<style scoped>
.connect-intro-card { max-width: 56rem; text-align: left; padding: 3.2rem 3.6rem; box-sizing: border-box; }
.ci-brandline { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.2rem; }
.ci-handshake { font-size: 2rem; }
.ci-stripe { font-weight: 900; font-size: 2.2rem; color: #635bff; letter-spacing: -0.02em; }
.connect-intro-card h2 { margin: 0 0 0.6rem; }
.ci-sub { margin: 0 0 1.4rem; color: var(--text-muted); }
.ci-checklist { border: 1px solid var(--line-strong); border-radius: var(--radius-md); padding: 1.2rem 1.4rem; margin-bottom: 1.4rem; }
.ci-checklist-title { margin: 0 0 0.6rem; font-weight: 700; }
.ci-checklist ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 0.4rem; }
.ci-country { display: grid; gap: 0.4rem; font-weight: 600; margin-bottom: 1.4rem; max-width: 28rem; }
.ci-reassure { color: var(--text-muted); font-size: 1.25rem; margin: 0 0 1.4rem; }
.ci-actions { display: flex; justify-content: flex-end; gap: 0.8rem; flex-wrap: wrap; }
</style>

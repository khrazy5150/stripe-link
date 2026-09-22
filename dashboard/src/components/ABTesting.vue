<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>A/B Testing</h1>
        <p>
          Split traffic across versions of a page on its own URL, then pick a winner. Visitors never see a
          different address and the winner takes over the one you tested.
        </p>
      </div>
    </header>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Experiments</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
            {{ store.loading ? "Loading…" : "Reload" }}
          </button>
          <button class="primary-action" type="button" :disabled="!store.publishedPages.length" @click="openCreate">
            + New Experiment
          </button>
        </div>
      </header>

      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else class="keys-status-banner">{{ store.message }}</div>

      <div v-if="!store.publishedPages.length && store.loaded" class="product-empty-state">
        Publish at least one landing page before creating an experiment — variants must be published to receive traffic.
      </div>

      <div v-else-if="!store.experiments.length" class="product-empty-state">
        {{ store.loaded ? "No experiments yet. Create one to start split-testing your pages." : "Loading…" }}
      </div>

      <div v-else class="coupon-card-grid">
        <article v-for="experiment in store.experiments" :key="experiment.experiment_id" class="coupon-card">
          <header>
            <div>
              <h3>{{ experiment.name || "Untitled experiment" }}</h3>
              <!-- No short link: an experiment runs on the page's OWN url now (A1c). The address below is
                   that page's url, not a test-only one -- which is the point, and is why it is safe to
                   share. It is also the only way to go and look at a running test. -->
            </div>
            <span class="product-status" :class="experiment.status">{{ statusLabel(experiment.status) }}</span>
          </header>

          <dl class="coupon-detail-list">
            <div><dt>Control</dt><dd>{{ store.pageName(experiment.control_page_id) }}</dd></div>
            <div><dt>Variants</dt><dd>{{ (experiment.variants || []).length }}</dd></div>
            <div><dt>Weights</dt><dd>{{ weightsSummary(experiment) }}</dd></div>
            <div>
              <dt>Test URL</dt>
              <dd v-if="experiment.control_url" class="ab-test-url">
                <a :href="experiment.control_url" target="_blank" rel="noopener">{{ experiment.control_url }}</a>
                <button type="button" class="secondary-action ab-copy" @click="copy(experiment.control_url)">
                  {{ copied === experiment.control_url ? "Copied" : "Copy" }}
                </button>
              </dd>
              <dd v-else class="ab-test-url-missing">
                This page isn't published on a site yet, so it has no address to test on.
              </dd>
            </div>
          </dl>

          <div class="product-card-actions">
            <button type="button" class="secondary-action" @click="openResults(experiment)">Results</button>
            <button
              v-if="experiment.status === 'draft'"
              type="button" class="secondary-action" @click="openEdit(experiment)"
            >Edit</button>
            <button
              v-if="experiment.status === 'draft' || experiment.status === 'paused'"
              type="button" class="primary-action" :disabled="store.saving" @click="startExperiment(experiment)"
            >{{ experiment.status === "paused" ? "Resume" : "Start" }}</button>
            <button
              v-if="experiment.status === 'running'"
              type="button" class="secondary-action" :disabled="store.saving" @click="store.pause(experiment.experiment_id)"
            >Pause</button>
            <button
              v-if="experiment.status !== 'completed'"
              type="button" class="danger-action" :disabled="store.saving" @click="pendingDelete = experiment"
            >Delete</button>
          </div>
        </article>
      </div>
    </section>

    <!-- Create / edit modal -->
    <div v-if="showEditor" class="modal-backdrop" @click.self="closeEditor">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="abEditorTitle">
        <header class="modal-card-header">
          <h2 id="abEditorTitle">{{ form.experiment_id ? "Edit Experiment" : "New Experiment" }}</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="closeEditor">×</button>
        </header>

        <form class="offer-form" @submit.prevent="saveExperiment">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <section class="offer-form-section">
            <label class="offer-field">
              <span>Experiment Name <strong>*</strong></span>
              <input v-model.trim="form.name" type="text" placeholder="Hero CTA test" required />
            </label>
          </section>

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Control</h3>
                <p v-if="!shapeFrozen">The baseline page. Its weight is the share of traffic it keeps.</p>
                <p v-else>
                  This test has already run, so its pages and weights are fixed — the views and conversions
                  recorded so far were measured against them. To test a different control, start a new
                  experiment. You can still rename this one.
                </p>
              </div>
            </header>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Control Page <strong>*</strong></span>
                <select v-model="form.control_page_id" required :disabled="shapeFrozen">
                  <option value="" disabled>Select a published page…</option>
                  <option v-for="page in store.publishedPages" :key="page.page_id" :value="page.page_id">
                    {{ store.pageLabel(page.page_id) }}
                  </option>
                </select>
              </label>
              <label class="offer-field">
                <span>Label</span>
                <input v-model.trim="form.control_label" type="text" placeholder="Control" :disabled="shapeFrozen" />
              </label>
              <label class="offer-field">
                <span>Weight</span>
                <input v-model.number="form.control_weight" type="number" min="0" step="1" :disabled="shapeFrozen" />
              </label>
            </div>
          </section>

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Variants</h3>
                <p>
              Each variant is a published page that receives its share of traffic. A variant must not be on
              a site of its own while it's tested — it's served behind the control's URL.
            </p>
              </div>
              <button type="button" class="secondary-action" @click="addVariant" :disabled="shapeFrozen">+ Add variant</button>
            </header>

            <div v-for="(variant, index) in form.variants" :key="index" class="offer-three-column ab-variant-row">
              <label class="offer-field">
                <span>Variant Page <strong>*</strong></span>
                <select v-model="variant.page_id" required :disabled="shapeFrozen">
                  <option value="" disabled>Select a published page…</option>
                  <option v-for="page in store.publishedPages" :key="page.page_id" :value="page.page_id">
                    {{ store.pageLabel(page.page_id) }}
                  </option>
                </select>
              </label>
              <label class="offer-field">
                <span>Label</span>
                <input v-model.trim="variant.label" type="text" :placeholder="`Variant ${index + 1}`" :disabled="shapeFrozen" />
              </label>
              <div class="ab-variant-weight">
                <label class="offer-field">
                  <span>Weight</span>
                  <input v-model.number="variant.weight" type="number" min="0" step="1" :disabled="shapeFrozen" />
                </label>
                <button type="button" class="danger-action" aria-label="Remove variant" :disabled="shapeFrozen" @click="form.variants.splice(index, 1)">×</button>
              </div>
            </div>
          </section>

          <div class="ab-weight-total" :class="{ warn: assembledTotalWeight !== 100 }">
            Total weight: <strong>{{ assembledTotalWeight }}</strong>
            <span v-if="assembledTotalWeight !== 100"> — must equal 100 before the experiment can start.</span>
          </div>

          <footer class="modal-card-footer">
            <button type="button" class="secondary-action" @click="closeEditor">Cancel</button>
            <button type="submit" class="primary-action" :disabled="store.saving">
              {{ store.saving ? "Saving…" : (form.experiment_id ? "Save changes" : "Create experiment") }}
            </button>
          </footer>
        </form>
      </section>
    </div>

    <!-- Results modal -->
    <div v-if="resultsFor" class="modal-backdrop" @click.self="resultsFor = null">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="abResultsTitle">
        <header class="modal-card-header">
          <div>
            <h2 id="abResultsTitle">{{ resultsFor.name }} — Results</h2>
          </div>
          <button type="button" class="modal-close" aria-label="Close" @click="resultsFor = null">×</button>
        </header>

        <div class="ab-results">
          <table class="ab-results-table">
            <thead>
              <tr>
                <th>Variant</th><th>Weight</th><th>Views</th><th>Conversions</th><th>Revenue</th><th>Rate</th><th>vs control</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in currentResults" :key="row.page_id" :class="{ winner: row.is_winner }">
                <td>
                  {{ row.label || store.pageName(row.page_id) }}
                  <span v-if="row.key === 'control'" class="ab-tag">control</span>
                  <span v-if="row.is_winner" class="ab-tag winner">winner</span>
                </td>
                <td>{{ row.weight }}</td>
                <td>{{ row.views }}</td>
                <td>{{ row.conversions }}</td>
                <td>{{ formatCurrencyCents(row.revenue) }}</td>
                <td>{{ formatConversionRate(row.conversion_rate) }}</td>
                <td>
                  <template v-if="row.key === 'control'">—</template>
                  <template v-else>
                    <span class="ab-tag" :class="verdictClass(row.page_id)">{{ verdictLabel(row.page_id) }}</span>
                    <span v-if="liftOf(row.page_id) !== null" class="ab-lift">{{ formatLift(liftOf(row.page_id)) }}</span>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
          <!-- Stated as an estimate at the CURRENT rate, never as a deadline: the tenant decides when there
               is enough evidence, and nothing here pauses or gates the test. -->
          <p v-if="stillToRun" class="ab-results-note">{{ stillToRun }}</p>

          <section v-if="resultsFor.status !== 'completed'" class="ab-winner-picker">
            <label class="offer-field">
              <span>Pick a winner</span>
              <select v-model="winnerPageId">
                <option value="" disabled>Select the winning page…</option>
                <option v-for="row in currentResults" :key="row.page_id" :value="row.page_id">
                  {{ row.label || store.pageName(row.page_id) }}
                </option>
              </select>
            </label>
            <button
              type="button" class="primary-action"
              :disabled="!winnerPageId || store.saving"
              @click="completeExperiment"
            >Complete &amp; switch to winner</button>
          </section>
          <p v-else class="keys-status-banner">
            <template v-if="winnerIsControl">
              Completed — {{ store.pageName(resultsFor.winner_page_id) }} (the control) won, and is serving.
            </template>
            <template v-else-if="promotion.status === 'moved'">
              Completed — {{ store.pageName(resultsFor.winner_page_id) }} now serves at
              <strong>{{ promotion.slug }}</strong>.
            </template>
            <template v-else>
              Completed — {{ store.pageName(resultsFor.winner_page_id) }} won, but the tested page had no
              address on a site, so there was nothing to switch over.
            </template>
          </p>
        </div>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingDelete"
      danger
      title="Delete experiment?"
      confirm-label="Delete"
      :busy="store.saving"
      @cancel="pendingDelete = null"
      @confirm="confirmRemoveExperiment"
    >
      <template v-if="pendingDelete">
        Delete “{{ pendingDelete.name || pendingDelete.experiment_id }}”? Its results are deleted with it.
      </template>
    </ConfirmDialog>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { useAbTestingStore, statusLabel, formatCurrencyCents, formatConversionRate, totalWeight } from "../stores/abTesting";
import ConfirmDialog from "./shared/ConfirmDialog.vue";

function blankForm() {
  return {
    experiment_id: null,
    name: "",
    control_page_id: "",
    control_label: "Control",
    control_weight: 50,
    variants: [{ page_id: "", label: "", weight: 50 }],
  };
}

const store = useAbTestingStore();
store.load();

const copied = ref("");
// Same shape as the Sites screen's copy: a transient label rather than a toast, and silent when the
// clipboard is unavailable (insecure context, denied permission) -- the address is selectable either way.
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = text;
    setTimeout(() => { if (copied.value === text) copied.value = ""; }, 1500);
  } catch { /* clipboard unavailable */ }
}
const showEditor = ref(false);
// An experiment that has ever started is frozen server-side (control + variants), because its
// counters were gathered against that exact shape. Mirrored here so the form does not offer an
// edit the API will refuse.
const shapeFrozen = ref(false);
const form = reactive(blankForm());
const formError = ref("");
const resultsFor = ref(null);
const winnerPageId = ref("");
const pendingDelete = ref(null);

const assembledVariants = computed(() => {
  const control = { page_id: form.control_page_id, label: form.control_label, weight: form.control_weight };
  return [control, ...form.variants].filter((variant) => variant.page_id);
});
const assembledTotalWeight = computed(() => totalWeight(assembledVariants.value));
const currentResults = computed(() => (resultsFor.value ? store.results[resultsFor.value.experiment_id] || [] : []));
// Completing an experiment RECORDS a winner; it does not re-point anything. `winner_page_id` reaches the
// serving path only through the short-code resolver, which A1c disabled -- so once status is `completed`,
// `running_experiment_for` stops matching and the tested URL serves the CONTROL again. Saying "all traffic
// routes to the winner" was telling tenants they had received an improvement they had not (plans/AB_TESTING.md A5).
// What completing actually DID, read from the experiment rather than asserted by the screen: the route move
// can legitimately be a no-op when the tested page was never attached to a Site.
const currentComparisons = computed(
  () => (resultsFor.value ? store.comparisons[resultsFor.value.experiment_id] || [] : []),
);
function comparisonFor(pageId) {
  return currentComparisons.value.find((row) => row.page_id === pageId) || null;
}
function liftOf(pageId) {
  const row = comparisonFor(pageId);
  return row && row.lift !== null && row.lift !== undefined ? row.lift : null;
}
// Words, not a p-value. "Not enough data yet" is a real answer and says so rather than showing a number
// that invites reading a big lift on 50 views as a result.
const VERDICTS = {
  clear: "clear difference",
  likely: "likely difference",
  too_close: "too close to call",
  insufficient: "not enough data yet",
};
function verdictLabel(pageId) {
  const row = comparisonFor(pageId);
  return (row && VERDICTS[row.verdict]) || VERDICTS.insufficient;
}
function verdictClass(pageId) {
  const row = comparisonFor(pageId);
  return row ? `verdict-${row.verdict}` : "verdict-insufficient";
}
function formatLift(lift) {
  const pct = lift * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}
const stillToRun = computed(() => {
  const days = currentComparisons.value
    .map((row) => row.days_remaining)
    .filter((value) => typeof value === "number" && value > 0);
  if (!days.length) return "";
  const longest = Math.max(...days);
  const rounded = longest < 1 ? "less than a day" : `about ${Math.ceil(longest)} more day${Math.ceil(longest) === 1 ? "" : "s"}`;
  return `At the current rate of traffic, telling these apart would take ${rounded}. It is your call when there is enough evidence — nothing stops the test on its own.`;
});
const promotion = computed(() => (resultsFor.value && resultsFor.value.promotion) || { status: "", slug: "" });
const winnerIsControl = computed(
  () => !!resultsFor.value && resultsFor.value.winner_page_id === resultsFor.value.control_page_id,
);

function resetForm(next) {
  Object.assign(form, next);
}

function weightsSummary(experiment) {
  return (experiment.variants || []).map((variant) => variant.weight).join(" / ") || "—";
}

function openCreate() {
  shapeFrozen.value = false;
  resetForm(blankForm());
  formError.value = "";
  showEditor.value = true;
}

function openEdit(experiment) {
  const variants = (experiment.variants || []).map((variant) => ({ ...variant }));
  const control = variants.find((variant) => variant.page_id === experiment.control_page_id) || variants[0] || {};
  const additional = variants
    .filter((variant) => variant.page_id !== experiment.control_page_id)
    .map((variant) => ({ page_id: variant.page_id, label: variant.label || "", weight: Number(variant.weight || 0) }));
  resetForm({
    experiment_id: experiment.experiment_id,
    name: experiment.name || "",
    control_page_id: experiment.control_page_id || "",
    control_label: control.label || "Control",
    control_weight: Number(control.weight || 0),
    variants: additional.length ? additional : [{ page_id: "", label: "", weight: 0 }],
  });
  shapeFrozen.value = !!experiment.started_at;
  formError.value = "";
  showEditor.value = true;
}

function closeEditor() {
  showEditor.value = false;
}

function addVariant() {
  form.variants.push({ page_id: "", label: "", weight: 0 });
}

function validateForm() {
  if (!form.name.trim()) return "Give the experiment a name.";
  if (!form.control_page_id) return "Select a control page.";
  const variants = assembledVariants.value;
  if (variants.length < 2) return "Add at least one variant page besides the control.";
  const pageIds = variants.map((variant) => variant.page_id);
  if (new Set(pageIds).size !== pageIds.length) return "Each page can be used only once in an experiment.";
  return "";
}

async function saveExperiment() {
  formError.value = validateForm();
  if (formError.value) return;
  const payload = { name: form.name, control_page_id: form.control_page_id, variants: assembledVariants.value };
  try {
    if (form.experiment_id) await store.update(form.experiment_id, payload);
    else await store.create(payload);
    showEditor.value = false;
  } catch {
    formError.value = store.error;
  }
}

async function startExperiment(experiment) {
  try {
    await store.start(experiment.experiment_id);
  } catch {
    /* store surfaces the error banner (e.g. weights must total 100, pages must be published) */
  }
}

async function confirmRemoveExperiment() {
  const experiment = pendingDelete.value;
  if (!experiment) return;
  await store.remove(experiment.experiment_id);
  if (resultsFor.value?.experiment_id === experiment.experiment_id) resultsFor.value = null;
  pendingDelete.value = null;
}

async function openResults(experiment) {
  resultsFor.value = experiment;
  winnerPageId.value = "";
  try {
    await store.loadResults(experiment.experiment_id);
    resultsFor.value = store.experiments.find((item) => item.experiment_id === experiment.experiment_id) || experiment;
  } catch {
    /* error banner shown by store */
  }
}

async function completeExperiment() {
  if (!winnerPageId.value) return;
  try {
    await store.complete(resultsFor.value.experiment_id, winnerPageId.value);
    resultsFor.value = store.experiments.find((item) => item.experiment_id === resultsFor.value.experiment_id) || null;
  } catch {
    /* error banner shown by store */
  }
}
</script>

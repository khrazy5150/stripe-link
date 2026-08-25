<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Collections</h1>
        <p>
          Reusable, ordered groups of a Site's landing pages. A storefront or category page shows a collection as
          its product grid — edit the collection here and every page embedding it updates.
        </p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
          {{ store.loading ? "Loading…" : "Reload" }}
        </button>
        <button class="primary-action" type="button" :disabled="!sitesStore.sites.length" @click="openCreate">
          + New collection
        </button>
      </div>
    </header>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
    <div v-else-if="!sitesStore.sites.length && sitesStore.loaded" class="keys-status-banner">
      Create a Site first — a collection groups the pages of one Site.
    </div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Your collections</h2></header>
      <div class="dashboard-card-body">
        <div v-if="!store.collections.length" class="product-empty-state">
          {{ store.loaded ? "No collections yet. Create one, or build a storefront and one is made for you." : "Loading…" }}
        </div>
        <div v-else class="collections-grid">
          <article v-for="c in store.collections" :key="c.collection_id" class="collection-card">
            <header class="collection-card-head">
              <h3>{{ c.name || "Untitled collection" }}</h3>
              <span class="product-status" :class="ruleClass(c.rule)">{{ ruleLabel(c.rule) }}</span>
            </header>
            <p class="collection-meta">
              <span>{{ siteName(c.site_id) }}</span>
              <span>· {{ memberSummary(c) }}</span>
            </p>
            <p v-if="usageFor(c.collection_id).length" class="collection-usage">
              Used by {{ usageFor(c.collection_id).join(", ") }}
            </p>
            <p v-else class="collection-usage muted">Not embedded on any page yet</p>
            <div class="button-row">
              <button class="secondary-action compact" type="button" @click="openEdit(c)">Edit</button>
              <button class="link-danger compact" type="button" @click="askDelete(c)">Delete</button>
            </div>
          </article>
        </div>
      </div>
    </section>

    <!-- Create / edit modal -->
    <div v-if="editing" class="modal-backdrop" @click.self="closeEditor">
      <section class="modal-card" role="dialog" aria-modal="true">
        <header class="modal-card-header">
          <h2>{{ editing.collection_id ? "Edit collection" : "New collection" }}</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="closeEditor">×</button>
        </header>
        <div class="product-create-body">
          <label class="offer-field">
            <span>Name</span>
            <input v-model.trim="editing.name" type="text" placeholder="Shop all" />
          </label>

          <label class="offer-field">
            <span>Site</span>
            <select v-model="editing.site_id" :disabled="!!editing.collection_id">
              <option value="">Choose a Site…</option>
              <option v-for="s in sitesStore.sites" :key="s.site_id" :value="s.site_id">{{ s.name || s.site_id }}</option>
            </select>
            <small v-if="editing.collection_id" class="field-note">A collection's Site can't change — its members belong to it.</small>
          </label>

          <div class="offer-field">
            <span>Which pages</span>
            <div class="rule-modes">
              <button type="button" class="rule-mode" :class="{ active: editing.rule === 'all' }" @click="editing.rule = 'all'">All products</button>
              <button type="button" class="rule-mode" :class="{ active: editing.rule === 'manual' }" @click="editing.rule = 'manual'">Specific pages</button>
              <button type="button" class="rule-mode" :class="{ active: editing.rule === 'category' }" @click="editing.rule = 'category'">By category</button>
            </div>
          </div>

          <small v-if="editing.rule === 'all'" class="field-note">
            Fills with every offer page on this Site and stays current as you add more.
          </small>

          <label v-else-if="editing.rule === 'category'" class="offer-field">
            <span>Category</span>
            <select v-model="editing.category">
              <option value="">Choose a category…</option>
              <option v-for="cat in categories" :key="cat.key" :value="cat.key">{{ cat.label }}</option>
            </select>
            <small v-if="!categories.length" class="field-note">No product categories yet — set one on a product first.</small>
          </label>

          <template v-else>
            <div class="offer-field">
              <span>Members (in order)</span>
              <div v-if="!editing.members.length" class="product-empty-state compact">No pages yet — add one below.</div>
              <ol v-else class="member-list">
                <li v-for="(pid, i) in editing.members" :key="pid" class="member-row">
                  <span class="member-name">{{ pageName(pid) }}<em>/{{ pageSlug(pid) }} · <span class="page-picker-id">{{ pid }}</span></em></span>
                  <span class="member-controls">
                    <button type="button" class="icon-btn" :disabled="i === 0" title="Move up" @click="moveMember(i, -1)">↑</button>
                    <button type="button" class="icon-btn" :disabled="i === editing.members.length - 1" title="Move down" @click="moveMember(i, 1)">↓</button>
                    <button type="button" class="icon-btn danger" title="Remove" @click="removeMember(i)">×</button>
                  </span>
                </li>
              </ol>
            </div>
            <label class="offer-field">
              <span>Add a page</span>
              <select :value="''" @change="addMember($event.target.value)">
                <option value="">{{ addablePages.length ? "Choose a page to add…" : "No more pages on this Site" }}</option>
                <option v-for="p in addablePages" :key="p.page_id" :value="p.page_id">{{ p.name || p.page_id }} · /{{ p.route?.slug || '' }} · {{ p.page_id }}{{ p.status !== 'published' ? ' · draft' : '' }}</option>
              </select>
              <small v-if="!editing.site_id" class="field-note">Pick a Site first to choose its pages.</small>
            </label>
          </template>

          <label class="offer-field">
            <span>Grid heading (optional)</span>
            <input v-model.trim="editing.heading" type="text" placeholder="Shop all" />
          </label>

          <p v-if="editorError" class="keys-status-banner error">{{ editorError }}</p>
        </div>
        <footer class="modal-card-footer">
          <button type="button" class="secondary-action" @click="closeEditor">Cancel</button>
          <button type="button" class="primary-action" :disabled="!canSave || saving" @click="save">
            {{ saving ? "Saving…" : (editing.collection_id ? "Save changes" : "Create collection") }}
          </button>
        </footer>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingDelete"
      danger
      title="Delete collection?"
      confirm-label="Delete"
      :busy="saving"
      @cancel="pendingDelete = null"
      @confirm="confirmDelete"
    >
      <template v-if="pendingDelete && usageFor(pendingDelete.collection_id).length">
        “{{ pendingDelete.name || 'This collection' }}” is embedded on {{ usageFor(pendingDelete.collection_id).join(", ") }}.
        Deleting it will leave those grids empty until you point them at another collection. Continue?
      </template>
      <template v-else>
        Delete “{{ pendingDelete?.name || 'this collection' }}”? This can't be undone.
      </template>
    </ConfirmDialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, toRaw } from "vue";
import { apiRequest } from "../api/client";
import { useCollectionsStore } from "../stores/collections";
import { useSitesStore } from "../stores/sites";
import { useProductsStore } from "../stores/products";
import ConfirmDialog from "./shared/ConfirmDialog.vue";

const store = useCollectionsStore();
const sitesStore = useSitesStore();
const productsStore = useProductsStore();

const pages = ref([]);           // all landing pages (GET /pages) — for member names/slugs + candidate lists
const editing = ref(null);       // working copy of the collection in the modal, or null when closed
const editorError = ref("");
const saving = ref(false);
const pendingDelete = ref(null);

// --- lookups -------------------------------------------------------------
const pageById = computed(() => {
  const map = new Map();
  for (const p of pages.value) map.set(p.page_id, p);
  return map;
});
function pageName(pid) { return pageById.value.get(pid)?.name || pid; }
function pageSlug(pid) { return pageById.value.get(pid)?.route?.slug || ""; }
function siteName(siteId) { return sitesStore.sites.find((s) => s.site_id === siteId)?.name || "Unknown Site"; }

// page_ids attached to a given Site (its route map), so members are drawn only from that Site's pages.
function pageIdsForSite(siteId) {
  const site = sitesStore.sites.find((s) => s.site_id === siteId);
  return new Set(Object.values(site?.pages || {}).map((e) => e.page_id).filter(Boolean));
}
// Candidate member pages: offer pages on the chosen Site not already in the members list.
const addablePages = computed(() => {
  if (!editing.value?.site_id) return [];
  const onSite = pageIdsForSite(editing.value.site_id);
  const chosen = new Set(editing.value.members || []);
  return pages.value.filter((p) => p.offer_id && onSite.has(p.page_id) && !chosen.has(p.page_id));
});

// Distinct product categories the tenant actually uses (matches the storefront/category builder source).
function categoryLabel(key) {
  return String(key).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
const categories = computed(() => {
  const seen = new Map();
  for (const p of productsStore.products) {
    const key = String(p.product_category || "").trim();
    if (key && !seen.has(key)) seen.set(key, categoryLabel(key));
  }
  return [...seen.entries()].map(([key, label]) => ({ key, label })).sort((a, b) => a.label.localeCompare(b.label));
});

// collection_id -> [page names embedding it], for the usage note + delete guard.
const usageByCollection = computed(() => {
  const map = new Map();
  for (const p of pages.value) {
    for (const s of p.sections || []) {
      const id = s && s.type === "catalog_grid" ? s.collection_id : null;
      if (!id) continue;
      if (!map.has(id)) map.set(id, []);
      map.get(id).push(p.name || p.page_id);
    }
  }
  return map;
});
function usageFor(collectionId) { return usageByCollection.value.get(collectionId) || []; }

// --- list display --------------------------------------------------------
const RULE_LABELS = { all: "All products", manual: "Curated", category: "By category" };
function ruleLabel(rule) { return RULE_LABELS[rule] || rule || "Curated"; }
function ruleClass(rule) { return rule === "all" ? "active" : rule === "category" ? "pending" : ""; }
function memberSummary(c) {
  if (c.rule === "all") return "every product on the Site";
  if (c.rule === "category") return `category: ${categoryLabel(c.category || "—")}`;
  const n = (c.members || []).length;
  return `${n} page${n === 1 ? "" : "s"}`;
}

// --- editor --------------------------------------------------------------
function blankEditing() {
  const onlySite = sitesStore.sites.length === 1 ? sitesStore.sites[0].site_id : "";
  return reactive({ collection_id: "", site_id: onlySite, name: "", rule: "all", members: [], category: "", heading: "" });
}
function openCreate() {
  editorError.value = "";
  editing.value = blankEditing();
}
function openEdit(c) {
  editorError.value = "";
  editing.value = reactive({
    collection_id: c.collection_id,
    site_id: c.site_id || "",
    name: c.name || "",
    rule: c.rule || "manual",
    members: [...(c.members || [])],
    category: c.category || "",
    heading: (c.presentation || {}).heading || "",
  });
}
function closeEditor() { editing.value = null; }

function addMember(pid) {
  if (pid && !editing.value.members.includes(pid)) editing.value.members.push(pid);
}
function removeMember(i) { editing.value.members.splice(i, 1); }
function moveMember(i, delta) {
  const j = i + delta;
  const m = editing.value.members;
  if (j < 0 || j >= m.length) return;
  [m[i], m[j]] = [m[j], m[i]];
}

const canSave = computed(() => {
  const e = editing.value;
  if (!e) return false;
  if (!e.name || !e.site_id) return false;
  if (e.rule === "category" && !e.category) return false;
  return true;
});

async function save() {
  if (!canSave.value) return;
  const e = editing.value;
  const doc = {
    document_type: "collection",
    site_id: e.site_id,
    name: e.name,
    rule: e.rule,
  };
  if (e.collection_id) doc.collection_id = e.collection_id;
  if (e.rule === "manual") doc.members = [...toRaw(e.members)];
  if (e.rule === "category") doc.category = e.category;
  const heading = (e.heading || "").trim();
  if (heading) doc.presentation = { heading };
  editorError.value = "";
  saving.value = true;
  try {
    await store.save(doc);
    editing.value = null;
  } catch (err) {
    editorError.value = err.message || "Failed to save collection.";
  } finally {
    saving.value = false;
  }
}

function askDelete(c) { pendingDelete.value = c; }
async function confirmDelete() {
  const c = pendingDelete.value;
  pendingDelete.value = null;
  if (!c) return;
  saving.value = true;
  try {
    await store.remove(c.collection_id);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  store.ensureLoaded();
  sitesStore.ensureLoaded();
  productsStore.ensureLoaded();
  try {
    const body = await apiRequest("/pages");
    pages.value = Array.isArray(body.pages) ? body.pages : [];
  } catch {
    pages.value = [];
  }
});
</script>

<style scoped>
.collections-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(28rem, 1fr)); gap: 1.2rem; }
.collection-card { border: 1px solid var(--line); border-radius: 10px; padding: 1.2rem 1.4rem; display: flex; flex-direction: column; gap: 0.5rem; }
.collection-card-head { display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; }
.collection-card-head h3 { margin: 0; font-size: 1.6rem; }
.collection-meta { margin: 0; color: var(--muted); display: flex; gap: 0.4rem; flex-wrap: wrap; }
.collection-usage { margin: 0.2rem 0 0; font-size: 1.3rem; color: var(--muted); }
.collection-usage.muted { font-style: italic; opacity: 0.8; }
.collection-card .button-row { margin-top: 0.4rem; }

.rule-modes { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.rule-mode { flex: 1; min-width: 9rem; padding: 0.7rem 1rem; border: 1px solid var(--line); border-radius: 8px; background: var(--surface, #fff); cursor: pointer; font: inherit; }
.rule-mode.active { border-color: var(--brand, #4f46e5); background: var(--brand, #4f46e5); color: #fff; font-weight: 600; }

.member-list { list-style: decimal; margin: 0; padding-left: 2rem; display: grid; gap: 0.4rem; }
.member-row { display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; }
.member-name { display: flex; flex-direction: column; }
.member-name em { color: var(--muted); font-style: normal; font-size: 1.2rem; }
.member-controls { display: flex; gap: 0.3rem; }
.icon-btn { width: 2.6rem; height: 2.6rem; border: 1px solid var(--line); border-radius: 6px; background: var(--surface, #fff); cursor: pointer; font-size: 1.4rem; line-height: 1; }
.icon-btn:disabled { opacity: 0.4; cursor: default; }
.icon-btn.danger { color: #dc2626; }
.product-empty-state.compact { padding: 0.8rem; font-size: 1.3rem; }

.link-danger { background: none; border: none; color: #dc2626; cursor: pointer; font: inherit; }
.link-danger:hover { text-decoration: underline; }
</style>

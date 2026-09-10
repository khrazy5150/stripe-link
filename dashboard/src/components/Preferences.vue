<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Preferences</h1>
        <p>Personal dashboard settings for your account</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
        <button class="primary-action" type="button" :disabled="saving || loading || !userId" @click="save">
          {{ saving ? "Saving..." : "Save Preferences" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error">{{ error }}</div>
    <div v-else-if="message" class="keys-status-banner">{{ message }}</div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Appearance & Defaults</h2></header>
      <div class="dashboard-card-body">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Theme</span>
            <select v-model="form.theme">
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
          <label class="offer-field">
            <span>Default Stripe Mode</span>
            <select v-model="form.default_stripe_mode">
              <option value="test">Test</option>
              <option value="live">Live</option>
            </select>
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Default Home View</span>
            <select v-model="form.dashboard_home">
              <option value="dashboard">Dashboard</option>
              <option value="products">Products</option>
              <option value="offers">Offers</option>
              <option value="landingPages">Landing Pages</option>
              <option value="orders">Orders</option>
              <option value="customers">Customers</option>
            </select>
          </label>
        </div>
        <label class="checkbox-row">
          <input v-model="form.sidebar_collapsed" type="checkbox" />
          <span>Collapse the side menu by default</span>
        </label>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Store Avatar</h2>
      </header>
      <!-- Same reasoning as Store Fonts below: this is what CUSTOMERS see, so it belongs to the store and
           not to a login. Two people editing one store must not put different faces on its pages. -->
      <div class="dashboard-card-body">
      <p class="field-note">
        Shown on every page that has not overridden it — checkout pages and link pages alike. Pages reference
        this image rather than copying it, so updating it here updates them all. A square image works best;
        it is shown as a circle.
      </p>
      <div class="builder-avatar-row">
        <img v-if="storeAvatarUrl" :src="storeAvatarUrl" class="builder-avatar-preview" alt="" />
        <input ref="storeAvatarInput" type="file" accept="image/*" hidden @change="onStoreAvatarPicked" />
        <button class="secondary-action compact" type="button" :disabled="storeAvatarBusy" @click="storeAvatarInput?.click()">
          {{ storeAvatarBusy ? "Uploading..." : (storeAvatarUrl ? "Replace avatar" : "Upload avatar") }}
        </button>
        <button v-if="storeAvatarUrl" class="secondary-action compact" type="button" :disabled="storeAvatarBusy" @click="clearStoreAvatar">Remove</button>
      </div>
      <small v-if="storeAvatarError" class="builder-upload-error">{{ storeAvatarError }}</small>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Store Fonts</h2>
        <!-- Said plainly, because this card sits on a screen headed "personal dashboard settings": these
             apply to the STORE, so a second login sees the same type. Deliberate — a font is what customers
             see, not a per-user choice (plans/FONT_SERVICE.md §9). -->
        <p>Used by every page on this store, for everyone who signs in. A page can still override them.</p>
      </header>
      <div class="dashboard-card-body">
        <ul v-if="fonts.length" class="font-list">
          <li v-for="font in fonts" :key="font.url">
            <span :style="{ fontFamily: `'${font.family}', sans-serif` }">{{ font.family }}</span>
            <small>
              {{ font.variable ? "variable" : "static" }} · weight {{ font.weight }}
              · {{ Math.round((font.bytes || 0) / 1024) }} KB
            </small>
            <button class="danger-action compact" type="button" :disabled="importing"
                    @click="fontToRemove = font">Remove</button>
          </li>
        </ul>
        <p v-else><small>No fonts imported. Your pages use the fonts built into each preset.</small></p>

        <div>
          <label class="offer-field">
            <span>Font family name</span>
            <input v-model.trim="fontForm.family" type="text" placeholder="e.g. Acme Display" />
            <small>Leave blank to use the name inside the font. Use one name for every weight of a family.</small>
          </label>
        </div>

        <!-- The honest constraint, BEFORE they upload. A static TTF cannot become a variable WOFF2: WOFF2
             compresses, it does not add axes. Saying nothing is the cruelty — they upload Regular, see it
             work, and cannot understand why bold comes out synthetically smeared. -->
        <p><small>
          A <strong>variable</strong> font covers every weight in one file. A <strong>static</strong> font is
          one weight per file — upload each weight you want, using the same family name.
        </small></p>

        <label class="checkbox-row">
          <input v-model="fontForm.licence" type="checkbox" />
          <span>
            I hold a licence permitting <strong>web embedding</strong> of this font. A desktop licence is
            usually not enough — this font will be served publicly from our CDN.
          </span>
        </label>

        <input ref="fontFile" type="file" accept=".ttf,.otf" hidden @change="importFont" />
        <div class="button-row">
          <button class="secondary-action" type="button"
                  :disabled="importing || !fontForm.licence"
                  @click="fontFile?.click()">
            {{ importing ? "Converting..." : "Upload font file" }}
          </button>
        </div>
        <small v-if="!fontForm.licence">Confirm the licence to enable upload.</small>
        <p v-if="fontError" class="field-error">{{ fontError }}</p>
        <p v-else-if="fontMessage"><small>{{ fontMessage }}</small></p>
      </div>
    </section>

    <div v-if="fontToRemove" class="modal-backdrop" @click.self="fontToRemove = null">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="removeFontTitle">
        <header class="modal-card-header">
          <h2 id="removeFontTitle" class="danger-title">Remove font</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="fontToRemove = null">×</button>
        </header>
        <div class="dashboard-card-body">
          <p>
            Remove <strong>{{ fontToRemove.family }}</strong>
            (weight {{ fontToRemove.weight }}{{ fontToRemove.style === "italic" ? ", italic" : "" }})?
          </p>
          <!-- Said rather than left to be discovered: removal is safe, and knowing that is what makes the
               decision easy. Nothing emits the @font-face any more, so a page naming it falls through to
               its preset font — the same result as a font that fails to load. -->
          <p class="field-note">
            Pages using it fall back to their preset font. Nothing else changes, and you can upload it again.
          </p>
          <p v-if="fontError" class="field-error">{{ fontError }}</p>
        </div>
        <footer class="config-save-bar">
          <button class="secondary-action" type="button" :disabled="importing" @click="fontToRemove = null">Cancel</button>
          <button class="danger-action" type="button" :disabled="importing" @click="confirmRemoveFont">
            {{ importing ? "Removing…" : "Remove font" }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<script setup>
import { reactive, ref } from "vue";
import { apiRequest, getAuthSession, getTenantId } from "../api/client";
import { uploadImage } from "../api/uploads";

const session = getAuthSession() || {};
const userId = session.user_id || "";
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const rawDoc = ref({});

// Store fonts live on the TENANT PROFILE, not in this screen's user-scoped document, so they have their own
// endpoint rather than riding the Save Preferences button (plans/FONT_SERVICE.md §9).
const fonts = ref([]);
const fontFile = ref(null);
const importing = ref(false);
const fontError = ref("");
const fontMessage = ref("");
const fontForm = reactive({ family: "", weight: "400", licence: false });
const fontToRemove = ref(null);

const storeAvatarInput = ref(null);
const storeAvatarUrl = ref("");
const storeAvatarBusy = ref(false);
const storeAvatarError = ref("");

async function loadStoreAvatar() {
  try {
    const body = await apiRequest("/tenant/avatar");
    storeAvatarUrl.value = body.avatar_url || "";
  } catch {
    storeAvatarUrl.value = "";   // no avatar set, or unreadable -- either way there is nothing to show
  }
}

async function saveStoreAvatar(url) {
  storeAvatarError.value = "";
  storeAvatarBusy.value = true;
  try {
    const body = await apiRequest("/tenant/avatar", { method: "PUT", body: { avatar_url: url } });
    storeAvatarUrl.value = body.avatar_url || "";
  } catch (err) {
    storeAvatarError.value = err.message || "Could not save the store avatar.";
  } finally {
    storeAvatarBusy.value = false;
  }
}

async function onStoreAvatarPicked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  storeAvatarError.value = "";
  storeAvatarBusy.value = true;
  try {
    const { url } = await uploadImage(file);
    await saveStoreAvatar(url);
  } catch (err) {
    storeAvatarError.value = err.message || "Avatar upload failed.";
  } finally {
    storeAvatarBusy.value = false;
  }
}

const clearStoreAvatar = () => saveStoreAvatar("");

async function loadFonts() {
  // Store fonts live on the tenant profile, not in this screen's user-scoped document, so they load
  // separately. Failing here must not break the rest of the screen — the fonts list is not the reason the
  // tenant opened Preferences.
  try {
    const body = await apiRequest("/fonts/import");
    fonts.value = body.fonts || [];
  } catch {
    fonts.value = [];
  }
}

async function confirmRemoveFont() {
  const font = fontToRemove.value;
  if (!font) return;
  fontError.value = "";
  fontMessage.value = "";
  importing.value = true;
  try {
    const body = await apiRequest("/fonts/import", {
      method: "DELETE",
      body: { family: font.family, weight: font.weight, style: font.style || "normal" },
    });
    fonts.value = body.fonts || [];
    fontMessage.value = `${font.family} removed.`;
    fontToRemove.value = null;
  } catch (err) {
    fontError.value = err?.message || "That font could not be removed.";
  } finally {
    importing.value = false;
  }
}

async function importFont(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  fontError.value = "";
  fontMessage.value = "";
  importing.value = true;
  try {
    // Base64 because the API speaks JSON; the endpoint decodes and streams the bytes to the converter.
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.onerror = () => reject(new Error("That file could not be read."));
      reader.readAsDataURL(file);
    });
    const body = await apiRequest("/fonts/import", {
      method: "POST",
      body: {
        family: fontForm.family,
        weight: fontForm.weight,
        filename: file.name,
        licence_affirmed: fontForm.licence,
        data,
      },
    });
    fonts.value = body.fonts || [];
    const font = body.font || {};
    // Tell them WHICH they got, because it decides whether they still need to upload more files.
    // Report what was READ from the file, not what was submitted — the whole point is that the tenant
    // does not have to know this.
    const called = font.detected_family
      ? ` The file calls itself “${font.detected_family}${font.detected_style ? " " + font.detected_style : ""}”.`
      : "";
    fontMessage.value = font.variable
      ? `${font.family} imported — variable, covering weights ${font.weight}. One file covers them all.${called}`
      : `${font.family} imported at weight ${font.weight}, read from the font.${called}`
        + " Upload each other weight you want, using the same family name.";
  } catch (err) {
    fontError.value = err?.message || "That font could not be imported.";
  } finally {
    importing.value = false;
  }
}
const form = reactive(defaultForm());

function defaultForm() {
  return { theme: "system", default_stripe_mode: "test", dashboard_home: "dashboard", sidebar_collapsed: false };
}

function applyPreferences(preferences) {
  rawDoc.value = preferences || {};
  form.theme = preferences.theme || "system";
  form.default_stripe_mode = preferences.default_stripe_mode || "test";
  form.dashboard_home = preferences.dashboard_home || "dashboard";
  form.sidebar_collapsed = Boolean(preferences.sidebar_collapsed);
}

async function load() {
  if (!userId) {
    error.value = "Could not determine your user account. Sign out and back in.";
    return;
  }
  loading.value = true;
  error.value = "";
  message.value = "";
  // Store fonts are a DIFFERENT document on a different table, so they load independently. Chaining them
  // after the preferences call meant a tenant who had never saved preferences got a 404, the catch handled
  // it, and the font list silently stayed empty — reading "No fonts imported" for fonts that existed.
  loadFonts();
  loadStoreAvatar();
  try {
    const body = await apiRequest("/preferences", { params: { user_id: userId } });
    applyPreferences(body.preferences || {});
  } catch (err) {
    if (/not found/i.test(err.message)) {
      applyPreferences({});
      message.value = "No preferences saved yet. Choose your settings and save.";
    } else {
      error.value = err.message || "Failed to load preferences.";
    }
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!userId) {
    error.value = "Could not determine your user account. Sign out and back in.";
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    // Preserve unmanaged sections (landing_pages.custom_color_themes, authoring_defaults).
    const doc = { ...rawDoc.value };
    doc.schema_version = "2026-05-29";
    doc.document_type = "user_preferences";
    doc.tenant_id = getTenantId();
    doc.user_id = userId;
    doc.theme = form.theme;
    doc.default_stripe_mode = form.default_stripe_mode;
    doc.dashboard_home = form.dashboard_home;
    doc.sidebar_collapsed = form.sidebar_collapsed;
    doc.updated_at = Math.floor(Date.now() / 1000);
    const body = await apiRequest("/preferences", { method: "PUT", body: doc });
    applyPreferences(body.preferences || doc);
    message.value = "Preferences saved.";
  } catch (err) {
    error.value = err.message || "Failed to save preferences.";
  } finally {
    saving.value = false;
  }
}

load();
</script>

<style scoped>
/* Matches Configuration.vue's Danger Zone. Those styles are scoped to that component, so a destructive
   control here has to restate them rather than inherit. */
.danger-action {
  border: 0;
  border-radius: 8px;
  background: #dc2626;
  color: #fff;
  font-weight: 700;
  padding: 0.9rem 1.6rem;
  cursor: pointer;
}
.danger-action:hover { background: #b91c1c; }
.danger-action:disabled { opacity: 0.6; cursor: default; }
.danger-action.compact { padding: 0.35rem 0.8rem; font-size: 0.8rem; font-weight: 600; }
.danger-title { color: #dc2626; }
.font-list { list-style: none; margin: 0 0 1rem; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.font-list li { display: flex; align-items: center; gap: 0.75rem; }
.font-list li span:first-child { font-size: 1.1rem; }
.font-list li small { color: #64748b; flex: 1; }
</style>

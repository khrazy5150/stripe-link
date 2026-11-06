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
        this image rather than copying it, so updating it here updates them all. Crop it to the circle here —
        any shape of photo will do.
      </p>
      <!-- The SAME field onboarding uses. This was a bare file input that centre-cropped whatever it
           was given and told the tenant "a square image works best" — asking them to do the cropping in
           their head, while the cropper sat unused one directory away. -->
      <StoreAvatarField
        :model-value="storeAvatarUrl"
        :uploader="uploadImage"
        :busy="storeAvatarBusy"
        :error="storeAvatarError"
        @update:model-value="saveStoreAvatar"
      />
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

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Sabbath Mode</h2>
        <!-- Said here for the same reason the two cards above say it: this screen is headed "personal
             dashboard settings", and this one is not personal. Observing the Sabbath is a fact about the
             person who runs the shops, so it closes every Site on the account and every login sees it. -->
        <p>
          Closes your store from Friday sundown to Saturday sundown. This belongs to the <strong>store</strong>,
          not to your login — it applies to every Site on this account, for everyone who signs in.
        </p>
      </header>
      <div class="dashboard-card-body">
        <label class="checkbox-row">
          <input v-model="sabbath.enabled" type="checkbox" />
          <span>Close my store for the Sabbath</span>
        </label>
        <p class="field-note">
          Checkout, the cart, upsells and bookings all stop taking money during the window, and the shopper is
          told when you reopen. Sundown is worked out from each Site's own location, so it moves with the season
          instead of sitting at a fixed hour.
        </p>

        <template v-if="sabbath.enabled">
          <div class="offer-two-column">
            <label class="offer-field">
              <span>Close this many minutes <strong>before</strong> Friday sundown</span>
              <input v-model.number="sabbath.before_minutes" type="number"
                     :min="sabbathLimits.min_minutes" :max="sabbathLimits.max_minutes" step="1" />
            </label>
            <label class="offer-field">
              <span>Reopen this many minutes <strong>after</strong> Saturday sundown</span>
              <input v-model.number="sabbath.after_minutes" type="number"
                     :min="sabbathLimits.min_minutes" :max="sabbathLimits.max_minutes" step="1" />
            </label>
          </div>
          <p class="field-note">
            {{ sabbathLimits.min_minutes }}–{{ sabbathLimits.max_minutes }} minutes each, and they need not
            match: {{ sabbathLimits.before_minutes }} and {{ sabbathLimits.after_minutes }} are the common
            choices (candle-lighting, and nightfall). Zero on both closes exactly at sundown and reopens
            exactly at sundown.
          </p>
        </template>

        <!-- THE PART THAT KEEPS THE TOGGLE HONEST. The gate fails open at every missing input, so a tenant
             who switches this on without coordinates on their Site gets a store that never closes, no error,
             and nothing to say why. The server resolves the real window per Site and this reports it. -->
        <div v-if="sabbathLoaded">
          <div v-if="sabbath.enabled && !sabbathStatus.effective" class="keys-status-banner error">
            This is switched on, but <strong>no store will close</strong> yet — see each Site below.
          </div>
          <ul v-if="sabbathStatus.sites.length" class="sabbath-sites">
            <li v-for="site in sabbathStatus.sites" :key="site.site_id">
              <span class="sabbath-site-name">
                <strong>{{ site.name }}</strong>
                <small>{{ site.timezone }}</small>
              </span>
              <span :class="['sabbath-chip', siteState(site).tone]">{{ siteState(site).label }}</span>
              <small class="sabbath-detail">{{ siteState(site).detail }}</small>
            </li>
          </ul>
          <p v-else>
            <small>
              No Sites yet. A Sabbath closure needs one, because a Site is what says where your store is.
            </small>
          </p>
        </div>

        <!-- Open on its own when a Site actually needs it. Above the Arctic circle the sun does not set for
             weeks, so there is no sundown to compute and a manual window is the only thing that can close the
             store. It is NOT a second way to configure an ordinary store: where the sun does set, the real
             sundown wins, because that is the thing being observed. -->
        <details v-if="sabbathLoaded && sabbath.enabled" :open="needsManualWindow">
          <summary>Manual window — for a store where the sun does not set</summary>
          <p class="field-note">
            Used only when sundown cannot be computed for a Site. Everywhere else your real sundown applies and
            this is ignored.
          </p>
          <label class="checkbox-row">
            <input v-model="manual.enabled" type="checkbox" />
            <span>Use a manual window where there is no sundown</span>
          </label>
          <div v-if="manual.enabled" class="offer-two-column">
            <label class="offer-field">
              <span>Starts on</span>
              <select v-model.number="manual.weekday">
                <option v-for="(day, index) in WEEKDAYS" :key="index" :value="index">{{ day }}</option>
              </select>
            </label>
            <label class="offer-field">
              <span>At</span>
              <input v-model="manual.at" type="time" step="60" />
            </label>
            <label class="offer-field">
              <span>For this many hours</span>
              <input v-model.number="manual.duration_hours" type="number"
                     :min="sabbathLimits.min_manual_hours" :max="sabbathLimits.max_manual_hours" step="0.25" />
            </label>
          </div>
          <p v-if="manual.enabled" class="field-note">
            {{ sabbathLimits.min_manual_hours }}–{{ sabbathLimits.max_manual_hours }} hours — the Sabbath it
            stands in for is about a day, sundown to sundown.
          </p>
        </details>

        <p v-if="sabbathError" class="field-error">{{ sabbathError }}</p>
        <p v-else-if="sabbathMessage"><small>{{ sabbathMessage }}</small></p>
        <div class="button-row">
          <button class="secondary-action" type="button" :disabled="sabbathSaving" @click="saveSabbath">
            {{ sabbathSaving ? "Saving…" : "Save Sabbath setting" }}
          </button>
        </div>
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
import { computed, reactive, ref } from "vue";
import { apiRequest, getAuthSession, getTenantId } from "../api/client";
import StoreAvatarField from "./shared/StoreAvatarField.vue";
import { uploadImage } from "../api/uploads";
import { useProfileStore } from "../stores/profile";

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

const profileStore = useProfileStore();
// Read THROUGH the store, not into a local ref. The topbar pill renders profileStore.storeAvatarUrl, so a
// card holding its own copy meant removing the avatar cleared the card and left the pill showing it until
// the page was reloaded -- the same stale-second-copy shape as every other drift bug here.
const storeAvatarUrl = computed(() => profileStore.storeAvatarUrl);
const storeAvatarBusy = ref(false);
const storeAvatarError = ref("");

async function loadStoreAvatar() {
  try {
    const body = await apiRequest("/tenant/avatar");
    profileStore.storeAvatarUrl = body.avatar_url || "";
  } catch {
    profileStore.storeAvatarUrl = "";   // no avatar set, or unreadable -- nothing to show either way
  }
}

async function saveStoreAvatar(url) {
  storeAvatarError.value = "";
  storeAvatarBusy.value = true;
  try {
    const body = await apiRequest("/tenant/avatar", { method: "PUT", body: { avatar_url: url } });
    // One place holds it, so the topbar pill updates with the card instead of after a refresh.
    profileStore.storeAvatarUrl = body.avatar_url || "";
  } catch (err) {
    storeAvatarError.value = err.message || "Could not save the store avatar.";
  } finally {
    storeAvatarBusy.value = false;
  }
}



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
// --- Sabbath mode -----------------------------------------------------------------------------------
// Its OWN endpoint, not the Save Preferences button. The setting lives on the tenant config document,
// which the Configuration screen saves WHOLE — so a load-mutate-put from this screen would restore its
// own stale copy of the refund policies and legal links over whatever Configuration had just saved, and
// would look like it worked. `PUT /sabbath` writes one attribute (plans/TODO.md "Sabbath mode").
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const SABBATH_LIMITS = {
  before_minutes: 18, after_minutes: 40, min_minutes: 0, max_minutes: 60,
  min_manual_hours: 24, max_manual_hours: 25,
};
const sabbath = reactive({ enabled: false, before_minutes: 18, after_minutes: 40 });
// From the server, so the bounds the inputs enforce are the bounds the server keeps. A hardcoded 60 here
// is how a screen comes to refuse a value the API accepts, or accept one it silently clamps.
const sabbathLimits = ref({ ...SABBATH_LIMITS });
const sabbathStatus = reactive({ sites: [], effective: false, closed_now: false });
const manual = reactive({ enabled: false, weekday: 4, at: "18:00", duration_hours: 24 });
const sabbathLoaded = ref(false);
const sabbathSaving = ref(false);
const sabbathError = ref("");
const sabbathMessage = ref("");

const needsManualWindow = computed(
  // Only where it is the ONLY thing that can work: a Site whose sun does not set. `sun_sets` is null when
  // there were no coordinates to ask about, which is a different problem with a different fix.
  () => sabbathStatus.sites.some((site) => site.sun_sets === false) || manual.enabled,
);

function applySabbath(body) {
  const stored = body.sabbath || {};
  sabbath.enabled = Boolean(stored.enabled);
  sabbath.before_minutes = Number(stored.before_minutes ?? SABBATH_LIMITS.before_minutes);
  sabbath.after_minutes = Number(stored.after_minutes ?? SABBATH_LIMITS.after_minutes);
  manual.enabled = Boolean(stored.manual);
  if (stored.manual) {
    manual.weekday = Number(stored.manual.weekday ?? 4);
    manual.at = `${String(stored.manual.hour ?? 18).padStart(2, "0")}:${String(stored.manual.minute ?? 0).padStart(2, "0")}`;
    manual.duration_hours = Number(stored.manual.duration_hours ?? 24);
  }
  sabbathLimits.value = body.limits || sabbathLimits.value;
  sabbathStatus.sites = body.sites || [];
  sabbathStatus.effective = Boolean(body.effective);
  sabbathStatus.closed_now = Boolean(body.closed_now);
  sabbathLoaded.value = true;
}

function sabbathMoment(iso, zone) {
  // Rendered in the STORE's zone, not the viewer's, and with the abbreviation. A tenant checking a Site in
  // another country must read the time their shoppers will experience, not the one their laptop is in.
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
      timeZone: zone || undefined, timeZoneName: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function siteState(site) {
  // Every branch here is a state the server actually reports, and the two warnings name the fix. A Site
  // that cannot close is the thing this preview exists to say out loud.
  if (!sabbath.enabled) return { tone: "off", label: "Off", detail: "" };
  if (site.source === "none") {
    if (!site.has_coordinates) {
      return {
        tone: "warn",
        label: "No location",
        detail: "This Site has no latitude or longitude, so sundown cannot be worked out and the store stays"
          + " open. Add them in Sites → edit this Site → Local business (Google & local SEO).",
      };
    }
    if (site.sun_sets === false) {
      return {
        tone: "warn",
        label: "No sundown",
        detail: "The sun does not set here at this time of year. Set a manual window below, or this Site"
          + " stays open.",
      };
    }
    return { tone: "warn", label: "Not closing", detail: "No window could be worked out for this Site." };
  }
  const via = site.source === "manual" ? " (manual window)" : "";
  if (site.closed_now) {
    return { tone: "closed", label: "Closed now", detail: `Reopens ${sabbathMoment(site.ends_at, site.timezone)}${via}` };
  }
  return {
    tone: "open",
    label: "Open",
    detail: `Next closes ${sabbathMoment(site.starts_at, site.timezone)}, reopens `
      + `${sabbathMoment(site.ends_at, site.timezone)}${via}`,
  };
}

async function loadSabbath() {
  // Independent of the preferences call, like the fonts and the avatar: a tenant who has never saved
  // preferences must still be able to read and change this one.
  try {
    applySabbath(await apiRequest("/sabbath"));
  } catch (err) {
    sabbathError.value = err?.message || "Could not read the Sabbath setting.";
  }
}

async function saveSabbath() {
  sabbathError.value = "";
  sabbathMessage.value = "";
  sabbathSaving.value = true;
  try {
    const [hour, minute] = String(manual.at || "18:00").split(":");
    const payload = {
      enabled: sabbath.enabled,
      before_minutes: sabbath.before_minutes,
      after_minutes: sabbath.after_minutes,
      // `null` CLEARS it. Sending the window while the checkbox is off would store a setting the tenant
      // just switched off, and it would fire the moment they moved somewhere the sun stops setting.
      manual: manual.enabled
        ? {
          weekday: manual.weekday,
          hour: Number(hour),
          minute: Number(minute || 0),
          duration_hours: manual.duration_hours,
        }
        : null,
    };
    // Answered with the resolved preview, so the confirmation is the window itself rather than "saved".
    applySabbath(await apiRequest("/sabbath", { method: "PUT", body: payload }));
    sabbathMessage.value = sabbath.enabled
      ? "Saved. The window above is what your stores will do."
      : "Saved. Your stores stay open.";
  } catch (err) {
    sabbathError.value = err?.message || "Could not save the Sabbath setting.";
  } finally {
    sabbathSaving.value = false;
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
  loadSabbath();
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
.sabbath-sites { list-style: none; margin: 0.75rem 0 1rem; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.sabbath-sites li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.25rem 0.75rem;
  align-items: center;
  border-left: 3px solid #e2e8f0;
  padding-left: 0.75rem;
}
.sabbath-site-name { display: flex; flex-direction: column; min-width: 0; }
.sabbath-site-name small { color: #64748b; }
/* The detail spans both columns so a two-line explanation never squeezes the chip off the row. */
.sabbath-detail { grid-column: 1 / -1; color: #475569; }
.sabbath-chip {
  justify-self: end;
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
  font-size: 0.75rem;
  font-weight: 700;
  white-space: nowrap;
}
.sabbath-chip.off { background: #f1f5f9; color: #64748b; }
.sabbath-chip.open { background: #dcfce7; color: #166534; }
.sabbath-chip.closed { background: #e0e7ff; color: #3730a3; }
/* Amber, not red: nothing is broken — the tenant has asked for something we cannot do yet, and the
   detail beside it names the one field that fixes it. */
.sabbath-chip.warn { background: #fef3c7; color: #92400e; }
</style>

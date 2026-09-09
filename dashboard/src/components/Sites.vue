<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Sites</h1>
        <p>Your public website — the domain, identity, and SEO that every landing page inherits.</p>
      </div>
      <div class="button-row">
        <button v-if="store.sites.length && !creating" class="primary-action" type="button" @click="startCreate">Add New Site</button>
        <button class="secondary-action" type="button" :disabled="store.loading" @click="reload">
          {{ store.loading ? "Loading..." : "Reload" }}
        </button>
      </div>
    </header>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
    <div v-else-if="store.message" class="keys-status-banner">{{ store.message }}</div>

    <div v-if="creating || (store.loaded && !store.sites.length)" class="dashboard-card">
      <div class="dashboard-card-body">
        <h2>{{ store.sites.length ? "Add a new Site" : "Create your Site" }}</h2>
        <p class="field-note">
          A Site is a public website — it owns a hostname and business identity, and the landing pages you choose
          live under it. The identity is seeded from your Profile → Business details. It starts on a free
          <strong>{{ hostingDomainHint }}</strong> address and stays private to search engines until you connect
          a custom domain. A landing page belongs to one Site at a time.
        </p>
        <label class="offer-field">
          <span>Site name</span>
          <input :value="createName" type="text" placeholder="My Shop" autocapitalize="words"
                 @input="applyTitleCaseInput((value) => { createName = value; }, $event)" />
        </label>
        <StoreAddressField
          v-model="createSubdomain"
          v-model:available="createAvailable"
          v-model:normalized="createNormalized"
          :name="createName"
          :hosting-domain="hostingDomainHint"
          label="Choose your store address"
          placeholder="axel-mart"
        />
        <small class="field-note store-address-note">This address is permanent and unique to you — pick it deliberately. You can add a custom domain later.</small>
        <div class="offer-field">
          <span>Pages to include</span>
          <ul v-if="pages.length" class="site-page-list">
            <li v-for="p in pages" :key="p.page_id">
              <label class="checkbox-row" :class="{ 'is-disabled': !!claimedBy(p.page_id) }">
                <input type="checkbox" :value="p.page_id" v-model="createPageIds" :disabled="!!claimedBy(p.page_id)" />
                {{ p.name || p.page_id }}
                <em v-if="claimedBy(p.page_id)">— on {{ claimedBy(p.page_id) }}</em>
              </label>
            </li>
          </ul>
          <p v-else class="field-note">You don't have any landing pages yet — that's fine. Create the Site now and add pages to it later.</p>
          <small class="field-note">Pick which pages this Site serves. A page already on another Site is locked — remove it there first to move it here.</small>
        </div>
        <p v-if="formError" class="field-error">{{ formError }}</p>
        <div class="button-row">
          <button v-if="store.sites.length" class="secondary-action" type="button" @click="cancelCreate">Cancel</button>
          <button class="primary-action" type="button" :disabled="!canCreate" @click="createSite">
            {{ store.saving ? "Creating..." : (store.sites.length ? "Create Site" : "Create my Site") }}
          </button>
        </div>
      </div>
    </div>

    <div v-for="site in store.sites" :key="site.site_id" class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>{{ site.name }}</h2>
        <div class="button-row">
          <span class="product-status" :class="indexClass(site)">{{ indexLabel(site) }}</span>
          <a v-if="siteStoreUrl(site)" class="secondary-action" :href="siteStoreUrl(site)" target="_blank" rel="noopener noreferrer">Visit store ↗</a>
          <button class="secondary-action" type="button" :disabled="copyBusy" @click="copySiteToEnvironment(site)">
            {{ copyBusy ? "Preparing…" : `Copy to ${targetEnvLabel}` }}
          </button>
          <button class="secondary-action" type="button" @click="openEdit(site)">Edit</button>
        </div>
      </header>
      <div class="dashboard-card-body">
        <dl class="product-details-grid">
          <div><dt>Canonical hostname</dt><dd class="font-mono"><a v-if="siteStoreUrl(site)" :href="siteStoreUrl(site)" target="_blank" rel="noopener noreferrer">{{ canonicalHost(site) }}</a><template v-else>{{ canonicalHost(site) }}</template></dd></div>
          <div><dt>Platform host</dt><dd class="font-mono">{{ site.hosting?.platform_hostname }}</dd></div>
          <div><dt>Custom domain</dt><dd>{{ customDomainLabel(site) }}</dd></div>
          <div><dt>Organization</dt><dd>{{ site.organization?.name || "—" }}</dd></div>
          <div><dt>Pages</dt><dd>{{ Object.keys(site.pages || {}).length }}</dd></div>
          <div><dt>Status</dt><dd>{{ site.status }}</dd></div>
        </dl>
        <p class="field-note">{{ indexReason(site) }}</p>
      </div>
    </div>

    <div v-if="editing" class="modal-backdrop" @click.self="editing = null">
      <section class="modal-card" role="dialog" aria-modal="true">
        <header class="modal-card-header">
          <h2>Edit Site</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="editing = null">×</button>
        </header>
        <div class="product-create-body">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>
          <label class="offer-field">
            <span>Site Name</span>
            <input :value="form.name" type="text" placeholder="My Store"
                   @input="applyTitleCaseInput((value) => { form.name = value; }, $event)" />
          </label>
          <label class="offer-field">
            <span>Free address (subdomain)</span>
            <div class="subdomain-input">
              <input
                v-model.trim="form.subdomain"
                type="text"
                placeholder="axel-mart"
                autocapitalize="off"
                autocorrect="off"
                spellcheck="false"
                @input="editCheck.check(form.subdomain, editing.site_id)"
              />
              <span class="subdomain-suffix">.{{ hostingDomainHint }}</span>
            </div>
            <small :class="availabilityClass(editCheck.state)">{{ availabilityText(editCheck.state) }}</small>
            <div v-if="editCheck.state.suggestions.length" class="subdomain-suggestions">
              <span class="field-note">Try:</span>
              <button v-for="s in editCheck.state.suggestions" :key="s" type="button" class="subdomain-chip" @click="pickEdit(s)">{{ s }}</button>
            </div>
            <small class="field-note">Changing this claims a new address; your old one stays reserved to you, so existing links keep working. Not indexed by search engines.</small>
          </label>

          <fieldset class="product-identifiers">
            <legend>Business identity (Organization)</legend>
            <p class="field-note">The single source of truth for your business's structured data — every page's Organization, seller, and local-business markup derives from here.</p>
            <div class="offer-two-column">
              <label class="offer-field"><span>Business name</span><input v-model.trim="form.org.name" type="text" placeholder="Axel Mart" /></label>
              <label class="offer-field"><span>Legal name</span><input v-model.trim="form.org.legal_name" type="text" placeholder="Axel Mart LLC" /></label>
            </div>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Business type</span>
                <select v-model="form.org.entity_type">
                  <option v-for="t in entityTypes" :key="t" :value="t">{{ t }}</option>
                </select>
              </label>
              <label class="offer-field" v-if="specificTypes.length">
                <span>Specific type <small class="field-note">(sharper local SEO)</small></span>
                <select v-model="form.org.business_type">
                  <option value="">General ({{ form.org.entity_type }})</option>
                  <option v-for="t in specificTypes" :key="t" :value="t">{{ t }}</option>
                </select>
              </label>
            </div>
            <label class="offer-field"><span>Description</span><textarea v-model.trim="form.org.description" rows="2" /></label>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Phone</span>
                <PhoneInput v-model="form.org.telephone" />
                <small v-if="orgPhoneError" class="field-error">{{ orgPhoneError }}</small>
              </label>
              <label class="offer-field"><span>Email</span><input v-model.trim="form.org.email" type="email" /></label>
            </div>
            <label class="offer-field"><span>Street</span><input v-model.trim="form.org.address.street" type="text" placeholder="1493 Osage St" /></label>
            <div class="offer-two-column">
              <label class="offer-field"><span>City</span><input v-model.trim="form.org.address.locality" type="text" /></label>
              <label class="offer-field"><span>Region</span><input v-model.trim="form.org.address.region" type="text" /></label>
            </div>
            <div class="offer-two-column">
              <label class="offer-field"><span>Postal code</span><input v-model.trim="form.org.address.postal_code" type="text" /></label>
              <label class="offer-field"><span>Country</span><input v-model.trim="form.org.address.country" type="text" placeholder="US" /></label>
            </div>
          </fieldset>

          <fieldset class="product-identifiers">
            <legend>Local business (Google &amp; local SEO)</legend>
            <p class="field-note">For service/local businesses: hours, map location, and your Google listing power the LocalBusiness structured data and a “View on Google” link. All optional.</p>
            <label class="offer-field"><span>Google Business Profile URL</span><input v-model.trim="form.org.gbp_url" type="url" placeholder="https://maps.google.com/… or https://g.page/…" /></label>
            <label class="offer-field">
              <span>Post-purchase review invites go to</span>
              <select v-model="form.org.review_destination">
                <option value="">Auto — {{ derivedDestinationLabel }} (based on business type)</option>
                <option value="junior_bay">Junior Bay — on-page reviews (product star snippets)</option>
                <option value="google">Google — your Maps/local listing</option>
              </select>
              <small class="field-note">Each buyer gets one review link. Product stores default to Junior Bay (earns on-page star snippets); service/local businesses default to Google (their stars live on Maps). Google needs the Place ID above, or it falls back to Junior Bay.</small>
            </label>
            <div class="offer-two-column">
              <label class="offer-field"><span>Google place ID</span><input v-model.trim="form.org.place_id" type="text" placeholder="ChIJ…" /></label>
              <div></div>
            </div>
            <div class="offer-two-column">
              <label class="offer-field"><span>Latitude</span><input v-model.trim="form.org.geo.latitude" type="number" step="any" placeholder="39.7392" /></label>
              <label class="offer-field"><span>Longitude</span><input v-model.trim="form.org.geo.longitude" type="number" step="any" placeholder="-104.9903" /></label>
            </div>
            <div class="offer-field">
              <span>Opening hours</span>
              <div v-for="(row, i) in form.org.opening_hours" :key="i" class="hours-row">
                <div class="hours-days">
                  <button
                    v-for="[day, short] in WEEK_DAYS"
                    :key="day"
                    type="button"
                    class="day-chip"
                    :class="{ on: row.days.includes(day) }"
                    @click="toggleHoursDay(row, day)"
                  >{{ short }}</button>
                </div>
                <input v-model="row.opens" type="time" class="hours-time" />
                <span class="hours-dash">–</span>
                <input v-model="row.closes" type="time" class="hours-time" />
                <button type="button" class="link-danger-btn hours-remove" @click="removeHoursRow(i)">Remove</button>
              </div>
              <button type="button" class="secondary-action compact" @click="addHoursRow">+ Add hours</button>
              <small class="field-note">Group days that share the same hours (e.g. Mon–Fri 9:00–17:00, then a separate Sat row).</small>
            </div>
            <div class="offer-field">
              <span>Social profiles</span>
              <div v-for="(row, i) in form.org.same_as" :key="i" class="social-row">
                <input
                  v-model.trim="row.url"
                  type="url"
                  class="social-url"
                  placeholder="https://instagram.com/yourname"
                  @blur="onSocialUrlChange(row)"
                />
                <span class="social-status" :class="socialStatus(row).tone">{{ socialStatus(row).label }}</span>
                <button type="button" class="link-danger-btn hours-remove" @click="removeSocialRow(i)">Remove</button>
              </div>
              <p v-if="socialHostError" class="social-error">{{ socialHostError }}</p>
              <div class="button-row">
                <button
                  type="button"
                  class="secondary-action compact"
                  :disabled="form.org.same_as.length >= SAME_AS_MAX"
                  @click="addSocialRow"
                >+ Add profile</button>
                <button
                  type="button"
                  class="secondary-action compact"
                  :disabled="socialBusy || !anyCheckableSocial"
                  @click="checkSocialLinks"
                >{{ socialBusy ? "Checking…" : "Check links now" }}</button>
              </div>
              <p v-if="socialCheckNote" class="field-note">{{ socialCheckNote }}</p>
              <small class="field-note">
                Up to {{ SAME_AS_MAX }} profiles. These tell search engines which accounts are yours, so we confirm
                each one before making that claim — add a link back to this site on the profile, then use
                <em>Check links now</em>.
              </small>
              <small class="field-note">
                <strong>Networks we accept:</strong> {{ acceptedNetworks }}.
              </small>
              <small class="field-note">
                {{ unconfirmableNetworks }} can be listed and are shown to visitors, but cannot be confirmed
                automatically — so they are left out of the search-engine claim.
              </small>
            </div>
          </fieldset>

          <fieldset class="product-identifiers">
            <legend>Search visibility</legend>
            <label class="builder-toggle"><input v-model="form.seo_enabled" type="checkbox" /><span>Let search engines find this site</span></label>
            <p class="field-note">
              When off, every page tells search engines <strong>noindex</strong> and the storefront header switches to its plain form (no breadcrumb, centered brand) — a visible cue that SEO is off. Navigation stays. Applies once your custom domain is verified; on the free {{ hostingDomainHint }} address a Site is never indexed regardless.
            </p>
          </fieldset>

          <fieldset class="product-identifiers">
            <legend>Search engine verification</legend>
            <p class="field-note">Verify your Site in Google/Bing Search Console so you can submit sitemaps. Paste the token from each provider's "HTML tag" verification method (just the content value).</p>
            <label class="offer-field"><span>Google verification token</span><input v-model.trim="form.seo.google_site_verification" type="text" placeholder="google-site-verification content…" /></label>
            <label class="offer-field"><span>Bing verification token</span><input v-model.trim="form.seo.bing_site_verification" type="text" placeholder="msvalidate.01 content…" /></label>
          </fieldset>

          <fieldset class="product-identifiers">
            <legend>Custom domain</legend>
            <p v-if="!customDomainsEnabled" class="field-note">
              Custom domains connect on your <strong>Live</strong> Site only. A sandbox Site is for testing, and
              pointing a real domain at it would show test pages as your real business — something search engines
              cannot tell apart, and a reputation that is hard to win back. Switch to Live to connect your domain.
            </p>
            <template v-else>
            <p class="field-note">Connect your own domain to serve this Site's homepage and become eligible for search indexing. On the free {{ hostingDomainHint }} address a Site is never indexed.</p>
            <div v-if="domainError" class="keys-status-banner error">{{ domainError }}</div>

            <template v-if="!editing.hosting?.custom_domain">
              <label class="offer-field">
                <span>Your domain</span>
                <input v-model.trim="domainForm.domain" type="text" placeholder="shop.yourbrand.com" autocapitalize="off" spellcheck="false" />
              </label>
              <label v-if="!siteHasHomepage" class="offer-field">
                <span>Which page should the domain show?</span>
                <select v-model="domainForm.homepage">
                  <option value="">Choose a homepage…</option>
                  <option v-for="p in pages" :key="p.page_id" :value="p.page_id">
                    {{ p.name || p.page_id }}{{ p.status === 'published' ? '' : ' — draft, publish to go live' }}
                  </option>
                </select>
                <small v-if="!pages.length" class="field-note">This Site has no landing pages yet. Create and publish a landing page first, then connect your domain.</small>
                <small v-else class="field-note">The homepage must be published for the domain to serve it.</small>
              </label>
              <div class="button-row">
                <button type="button" class="primary-action" :disabled="domainBusy || !domainForm.domain || (!siteHasHomepage && !domainForm.homepage)" @click="connectDomain">
                  {{ domainBusy ? "Connecting…" : "Connect domain" }}
                </button>
              </div>
            </template>

            <template v-else>
              <dl class="product-details-grid">
                <div><dt>Domain</dt><dd class="font-mono">{{ editing.hosting.custom_domain }}</dd></div>
                <div><dt>Status</dt><dd>{{ domainStatusLabel }}</dd></div>
              </dl>
              <div v-if="!editing.hosting.verification?.verified" class="domain-dns">
                <div class="dns-provider-row">
                  <label for="dns-provider">Add these at your DNS provider:</label>
                  <select id="dns-provider" v-model="dnsProvider">
                    <option v-for="p in dnsProviders" :key="p.id" :value="p.id">{{ p.label }}</option>
                  </select>
                </div>
                <p v-if="apexHint" class="field-note apex-hint">{{ apexHint }}</p>
                <div class="dns-accordion">
                  <div v-for="(rec, i) in displayRecords" :key="i" class="dns-step" :class="{ open: openStep === i }">
                    <button type="button" class="dns-step-header" @click="openStep = openStep === i ? -1 : i">
                      <span class="dns-badge" :class="rec.badgeClass">{{ rec.badgeIcon }}</span>
                      <span class="dns-step-title">{{ rec.stepLabel }}</span>
                      <span class="dns-step-status" :class="rec.badgeClass">{{ rec.statusText }}</span>
                      <span class="dns-chevron">{{ openStep === i ? '▾' : '▸' }}</span>
                    </button>
                    <div class="dns-step-body">
                      <p v-if="providerTip" class="field-note">{{ providerTip }}</p>
                      <div class="dns-field"><span class="dns-field-label">Type</span><code>{{ rec.type }}</code></div>
                      <div class="dns-field">
                        <span class="dns-field-label">Name</span><code>{{ rec.displayName }}</code>
                        <button type="button" class="copy-btn" @click="copy(rec.displayName)">{{ copied === rec.displayName ? 'Copied!' : 'Copy' }}</button>
                      </div>
                      <div class="dns-field">
                        <span class="dns-field-label">Value</span><code class="dns-value">{{ rec.value }}</code>
                        <button type="button" class="copy-btn" @click="copy(rec.value)">{{ copied === rec.value ? 'Copied!' : 'Copy' }}</button>
                      </div>
                      <p v-if="rec.note" class="field-note">{{ rec.note }}</p>
                    </div>
                  </div>
                </div>
              </div>
              <div class="button-row">
                <button v-if="!editing.hosting.verification?.verified" type="button" class="primary-action" :disabled="domainBusy" @click="checkDomain">
                  {{ domainBusy ? "Checking…" : "Verify domain" }}
                </button>
                <button type="button" class="secondary-action" :disabled="domainBusy" @click="disconnectDomain">Disconnect</button>
              </div>
            </template>
            </template>
          </fieldset>

          <div class="offer-field">
            <span>Homepage</span>
            <div class="homepage-picker">
              <select v-model="homepagePick">
                <option value="">Choose a page…</option>
                <option v-for="p in assignablePages" :key="p.page_id" :value="p.page_id">{{ p.name || p.page_id }}</option>
              </select>
              <button type="button" class="secondary-action" :disabled="!homepagePick || homepageBusy" @click="setAsHomepage">
                {{ homepageBusy ? "Setting…" : "Set as homepage" }}
              </button>
            </div>
            <small>The page served at your domain root (/). Your current homepage moves to its own slug so it stays live.</small>
            <p v-if="homepageError" class="field-error">{{ homepageError }}</p>
          </div>

          <div class="offer-field">
            <span>Attach a page</span>
            <div class="homepage-picker">
              <select v-model="attachForm.pageId">
                <option value="">Choose a page…</option>
                <option v-for="p in assignablePages" :key="p.page_id" :value="p.page_id">{{ p.name || p.page_id }}</option>
              </select>
              <input v-model.trim="attachForm.slug" type="text" placeholder="/slug" class="attach-slug" />
              <button type="button" class="secondary-action" :disabled="!attachForm.pageId || !attachForm.slug || attachBusy" @click="attachPage">
                {{ attachBusy ? "Attaching…" : "Attach" }}
              </button>
            </div>
            <small>Places a page at a slug so it serves on your domain. A category page is detected automatically; other pages attach as landing pages (which is what lets category pages find them).</small>
            <p v-if="attachError" class="field-error">{{ attachError }}</p>
          </div>

          <div class="offer-field">
            <span>Pages in this Site</span>
            <ul class="site-page-list">
              <li v-for="(entry, slug) in editing.pages" :key="slug">
                <span>
                  <span class="font-mono">{{ slug }}</span> — {{ entry.label || entry.page_id }}
                  <em>({{ entry.page_type || 'landing' }}{{ entry.category ? ', ' + entry.category : '' }}{{ entry.enabled === false ? ', disabled' : '' }})</em>
                </span>
                <button type="button" class="link-danger" :disabled="removeBusy === entry.page_id" @click="removePage(entry.page_id)">
                  {{ removeBusy === entry.page_id ? "Removing…" : "Remove" }}
                </button>
              </li>
            </ul>
            <p v-if="removeError" class="field-error">{{ removeError }}</p>
            <small>Removing a page frees it to join another Site. Page routing, slugs, and navigation get a full editor in a later phase.</small>
          </div>
        </div>
        <p v-if="archiveError" class="field-error">{{ archiveError }}</p>
        <footer class="modal-card-footer">
          <button
            v-if="editing.status === 'archived'"
            type="button"
            class="secondary-action"
            :disabled="archiveBusy"
            @click="pendingArchive = 'unarchive'"
          >
            {{ archiveBusy ? "Working…" : "Reactivate Site" }}
          </button>
          <button
            v-else
            type="button"
            class="secondary-action link-danger-btn"
            :disabled="archiveBusy"
            @click="pendingArchive = 'archive'"
          >
            {{ archiveBusy ? "Working…" : "Archive Site" }}
          </button>
          <span class="footer-spacer"></span>
          <button type="button" class="secondary-action" @click="editing = null">Cancel</button>
          <button type="button" class="primary-action" :disabled="!canSaveEdit" @click="saveEdit">
            {{ store.saving ? "Saving..." : "Save Site" }}
          </button>
        </footer>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingArchive"
      :danger="pendingArchive === 'archive'"
      :title="pendingArchive === 'archive' ? 'Archive this Site?' : 'Reactivate this Site?'"
      :confirm-label="pendingArchive === 'archive' ? 'Archive' : 'Reactivate'"
      :busy="archiveBusy"
      @cancel="pendingArchive = ''"
      @confirm="confirmArchive"
    >
      <template v-if="pendingArchive === 'archive'">
        Archiving <strong>{{ editing?.name }}</strong> tells search engines to drop all its pages (noindex, nofollow, noarchive). Its published pages are re-rendered now so it takes effect immediately. The Site keeps serving — reactivate anytime.
      </template>
      <template v-else>
        Reactivating <strong>{{ editing?.name }}</strong> restores normal indexing and re-renders its published pages.
      </template>
    </ConfirmDialog>

    <ConfirmDialog
      :open="!!copyPlan"
      :danger="!!copyPlan?.existingSite"
      :title="(copyPlan?.existingSite ? 'Replace in ' : 'Copy to ') + targetEnvLabel + '?'"
      :confirm-label="copyBusy ? 'Copying…' : ((copyPlan?.existingSite ? 'Replace in ' : 'Copy to ') + targetEnvLabel)"
      :busy="copyBusy"
      @cancel="copyPlan = null"
      @confirm="executeSiteCopy"
    >
      <template v-if="copyPlan">
        Copies <strong>{{ copyPlan.site.name }}</strong> — {{ copyPlan.pages.length }} page{{ copyPlan.pages.length === 1 ? '' : 's' }}, {{ copyPlan.offerDocs.length }} offer{{ copyPlan.offerDocs.length === 1 ? '' : 's' }}, {{ copyPlan.productDocs.length }} product{{ copyPlan.productDocs.length === 1 ? '' : 's' }} — to {{ targetEnvLabel }} (same IDs).
        <br>The custom domain is <strong>not</strong> copied; the {{ targetEnvLabel }} Site is navigable on its own free platform host.
        <template v-if="copyPlan.existingSite">
          <br><strong class="copy-replace-warning">⚠ This overwrites the existing {{ targetEnvLabel }} Site and its pages/catalog, and cannot be undone.</strong>
        </template>
        <template v-if="copyPlan.subdomainConflict"><br><strong class="copy-replace-warning">⚠ The subdomain “{{ copyPlan.label }}” is already taken in {{ targetEnvLabel }} by another Site. Rename this Site's store address before copying.</strong></template>
        <template v-if="copyPlan.hasServices"><br>Note: offers that include services aren't fully copied — set services up in {{ targetEnvLabel }}.</template>
        <template v-if="copyError"><br><strong class="copy-replace-warning">{{ copyError }}</strong></template>
      </template>
    </ConfirmDialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { apiRequest, getStripeMode, getOtherEnvironment } from "../api/client";
import { useSitesStore, organizationFromBusiness } from "../stores/sites";
import { useProfileStore } from "../stores/profile";
import { useSubdomainCheck } from "../composables/useSubdomainCheck";
import { resolvePageDoc, resolvePageDeps, copyCatalogToEnv, pageForTarget, siteForTarget } from "../composables/environmentCopy";
import { normalizeE164, phoneError } from "../utils/phone";
import PhoneInput from "./PhoneInput.vue";
import ConfirmDialog from "./shared/ConfirmDialog.vue";
import StoreAddressField from "./StoreAddressField.vue";
import { applyTitleCaseInput } from "../utils/titleCase.js";

const store = useSitesStore();
const profileStore = useProfileStore();
const pages = ref([]);
const editing = ref(null);
const formError = ref("");
const hostingDomainHint = computed(() => store.hostingDomain || "jbay.uk");
const entityTypes = ["OnlineStore", "Organization", "LocalBusiness", "HomeAndConstructionBusiness", "HealthAndBeautyBusiness", "FoodEstablishment", "ProfessionalService", "Store"];

const creating = ref(false);
const createName = ref("");
const createSubdomain = ref("");
const createPageIds = ref([]);
const editCheck = useSubdomainCheck();
// Store-address availability + canonical value are owned by the StoreAddressField component and surfaced here.
const createAvailable = ref(false);
const createNormalized = ref("");

const removeBusy = ref("");
const removeError = ref("");

// Cross-environment Site copy (plans/PLATFORM_HOSTNAME_SERVING.md P2): clone a whole Site — its pages, their
// offers + products, and the Site doc itself (route map, org, SEO) — to the opposite environment, same IDs. The
// custom domain is NOT copied; the target Site is immediately navigable on its own free platform host.
const targetEnv = computed(() => getOtherEnvironment());
const targetEnvLabel = computed(() => (targetEnv.value === "live" ? "Live" : "Test"));
const copyBusy = ref(false);
const copyError = ref("");
const copyPlan = ref(null);  // { site, pages:[{page,existingTarget}], offerDocs, productDocs, existingSite, hasServices }

async function copySiteToEnvironment(site) {
  copyError.value = "";
  copyBusy.value = true;
  try {
    const env = targetEnv.value;
    const pageIds = [...new Set(Object.values(site.pages || {}).map((e) => e && e.page_id).filter(Boolean))];
    const pageDocs = (await Promise.all(pageIds.map((id) => resolvePageDoc(id)))).filter(Boolean);
    // Aggregate the whole catalog across every page, deduped by id.
    const offerById = new Map();
    const productById = new Map();
    let hasServices = false;
    const pages = [];
    for (const page of pageDocs) {
      const deps = await resolvePageDeps(page);
      deps.offerDocs.forEach((o) => offerById.set(o.offer_id, o));
      deps.productDocs.forEach((p) => productById.set(p.product_id, p));
      hasServices = hasServices || deps.hasServices;
      // Per-page pre-flight so each page keeps the draft-vs-published rule on the target.
      const existingTarget = await apiRequest(`/pages/${encodeURIComponent(page.page_id)}`, { mode: env })
        .then((b) => b.page).catch(() => null);
      pages.push({ page, existingTarget });
    }
    const existingSite = await apiRequest(`/sites/${encodeURIComponent(site.site_id)}`, { mode: env })
      .then((b) => b.site).catch(() => null);
    // If this Site is new to the target, its platform subdomain must not be owned by a DIFFERENT Site there.
    // The copy preserves this Site's id, so pass site_id: the subdomain reservation is global and already owned by
    // THIS site_id — without it the check reports the Site's own address as "taken" (a false conflict).
    const label = String(site.hosting?.platform_hostname || "").split(".")[0];
    let subdomainConflict = false;
    if (!existingSite && label) {
      const check = await apiRequest(
        `/sites/subdomain?name=${encodeURIComponent(label)}&site_id=${encodeURIComponent(site.site_id)}`,
        { mode: env },
      ).catch(() => null);
      subdomainConflict = !!check && check.available === false;
    }
    copyPlan.value = {
      site, pages, existingSite, hasServices, label, subdomainConflict,
      offerDocs: [...offerById.values()], productDocs: [...productById.values()],
    };
  } catch (err) {
    copyError.value = err.message || "Couldn't prepare the copy.";
  } finally {
    copyBusy.value = false;
  }
}

async function executeSiteCopy() {
  const plan = copyPlan.value;
  if (!plan) return;
  if (plan.subdomainConflict) {
    copyError.value = `The subdomain “${plan.label}” is already taken in ${targetEnvLabel.value}. Rename this Site's store address first.`;
    return;
  }
  const env = targetEnv.value;
  copyError.value = "";
  copyBusy.value = true;
  try {
    // Bottom-up so references resolve in the target: products -> offers -> pages -> Site.
    await copyCatalogToEnv(plan.productDocs, plan.offerDocs, env);
    for (const { page, existingTarget } of plan.pages) {
      await apiRequest("/pages", { method: "POST", body: pageForTarget(page, existingTarget, env), mode: env });
    }
    await apiRequest("/sites", { method: "POST", body: siteForTarget(plan.site, plan.existingSite, env), mode: env });
    store.message = `Copied “${plan.site.name}” (${plan.pages.length} page${plan.pages.length === 1 ? "" : "s"}) to ${targetEnvLabel.value}.`;
    copyPlan.value = null;
  } catch (err) {
    copyError.value = err.message || "Copy failed partway. Re-run to finish — it's idempotent.";
  } finally {
    copyBusy.value = false;
  }
}

// A page belongs to at most one Site. For the create form, a page on ANY existing Site is locked.
// In the Site editor, a page on a DIFFERENT Site is locked (its own pages stay assignable).
function claimedByOther(pageId, exceptSiteId) {
  for (const s of store.sites) {
    if (exceptSiteId && s.site_id === exceptSiteId) continue;
    if (Object.values(s.pages || {}).some((e) => e && e.page_id === pageId)) return s.name || s.site_id;
  }
  return "";
}
const claimedBy = (pageId) => claimedByOther(pageId, "");
const assignablePages = computed(() => pages.value.filter((p) => !claimedByOther(p.page_id, editing.value?.site_id)));

// Specific schema.org LocalBusiness subtypes, grouped by the broad entity_type bucket they show under.
// Mirrors src/stripe_link/domain/business_types.py — keep in sync.
const BUSINESS_TYPE_GROUPS = [
  { parent: "HealthAndBeautyBusiness", label: "Health & beauty", types: ["BeautySalon", "DaySpa", "HairSalon", "NailSalon", "HealthClub", "TattooParlor", "Dentist", "MedicalClinic", "Optician", "Physician"] },
  { parent: "HomeAndConstructionBusiness", label: "Home & construction", types: ["Plumber", "Electrician", "HVACBusiness", "RoofingContractor", "HousePainter", "Locksmith", "MovingCompany", "GeneralContractor"] },
  { parent: "FoodEstablishment", label: "Food & drink", types: ["Restaurant", "CafeOrCoffeeShop", "Bakery", "BarOrPub", "IceCreamShop", "Winery"] },
  { parent: "ProfessionalService", label: "Professional services", types: ["AccountingService", "LegalService", "Attorney", "Notary", "RealEstateAgent", "InsuranceAgency", "AutoRepair", "TravelAgency"] },
  { parent: "Store", label: "Stores & retail", types: ["ClothingStore", "GroceryStore", "JewelryStore", "PetStore", "HardwareStore", "BookStore", "FurnitureStore", "ShoeStore", "ToyStore", "Florist", "ConvenienceStore"] },
  { parent: "LocalBusiness", label: "Other local", types: ["ChildCare", "DryCleaningOrLaundry", "SelfStorage", "EntertainmentBusiness"] },
];

const socialHostError = ref("");
const socialBusy = ref(false);
const socialCheckNote = ref("");
const form = reactive({ name: "", subdomain: "", org: { name: "", legal_name: "", entity_type: "OnlineStore", business_type: "", description: "", telephone: "", email: "", address: { locality: "", region: "" }, place_id: "", gbp_url: "", geo: { latitude: "", longitude: "" }, opening_hours: [], same_as: [], review_destination: "" }, seo: { google_site_verification: "", bing_site_verification: "" }, seo_enabled: true });

// The specific-type options for the chosen broad entity_type (empty for OnlineStore/Organization).
const specificTypes = computed(() => (BUSINESS_TYPE_GROUPS.find((g) => g.parent === form.org.entity_type)?.types) || []);
// Drop a specific type that no longer fits the selected bucket.
watch(() => form.org.entity_type, () => {
  if (form.org.business_type && !specificTypes.value.includes(form.org.business_type)) form.org.business_type = "";
});

const LOCAL_ENTITY_TYPES = ["LocalBusiness", "HomeAndConstructionBusiness", "HealthAndBeautyBusiness", "FoodEstablishment", "ProfessionalService"];
const derivedDestinationLabel = computed(() =>
  LOCAL_ENTITY_TYPES.includes(form.org.entity_type) ? "Google" : "Junior Bay");

const WEEK_DAYS = [
  ["Monday", "Mon"], ["Tuesday", "Tue"], ["Wednesday", "Wed"], ["Thursday", "Thu"],
  ["Friday", "Fri"], ["Saturday", "Sat"], ["Sunday", "Sun"],
];
// Mirrors SAME_AS_HOSTS and SAME_AS_MAX in src/stripe_link/domain/social_links.py. The dashboard cannot
// import Python, so tests/test_social_link_picker.py pins the two together — adding a host on one side only
// is the failure that test exists to catch.
const SAME_AS_HOSTS = [
  "bbb.org", "crunchbase.com", "facebook.com", "github.com", "instagram.com", "linkedin.com",
  "pinterest.com", "threads.net", "tiktok.com", "trustpilot.com", "twitter.com", "wikidata.org",
  "wikipedia.org", "x.com", "yelp.com", "youtube.com",
];
const SAME_AS_MAX = 6;
// Mirrors NETWORK_LABELS. Pinned to the Python side by tests/test_social_link_picker.py, which also
// asserts every allowlisted host has a label -- so a host can never appear here as a bare domain.
const NETWORK_LABELS = {
  "bbb.org": "Better Business Bureau",
  "crunchbase.com": "Crunchbase",
  "facebook.com": "Facebook",
  "github.com": "GitHub",
  "instagram.com": "Instagram",
  "linkedin.com": "LinkedIn",
  "pinterest.com": "Pinterest",
  "threads.net": "Threads",
  "tiktok.com": "TikTok",
  "trustpilot.com": "Trustpilot",
  "twitter.com": "Twitter",
  "wikidata.org": "Wikidata",
  "wikipedia.org": "Wikipedia",
  "x.com": "X",
  "yelp.com": "Yelp",
  "youtube.com": "YouTube",
};
// Cannot be confirmed by fetching: both serve a login wall or a JS shell to any unauthenticated request.
// They are shown to visitors like any other link; they just never enter the identity claim.
const UNVERIFIABLE_HOSTS = ["instagram.com", "tiktok.com"];
// Anyone can edit these, so finding our link there would prove nothing about who runs the profile.
const SELF_EDITABLE_HOSTS = ["wikipedia.org", "wikidata.org"];

function sameAsHost(url) {
  const text = String(url || "").trim().toLowerCase().replace(/^https?:\/\//, "");
  const host = text.split("/")[0].split("?")[0].split("#")[0].split(":")[0];
  return host.startsWith("www.") ? host.slice(4) : host;
}
function hostIn(host, group) {
  return group.some((h) => host === h || host.endsWith("." + h));
}
function addSocialRow() {
  if (form.org.same_as.length >= SAME_AS_MAX) return;
  form.org.same_as.push({ url: "", verification: null });
}
function removeSocialRow(index) {
  form.org.same_as.splice(index, 1);
  socialHostError.value = "";
}
function onSocialUrlChange(row) {
  // Editing the URL invalidates whatever we had proven about the old one, and the server enforces exactly
  // that on save. Clearing it here so the badge does not keep claiming "Confirmed" for a link we have not
  // checked — a stale badge would be a lie in the one place the tenant is deciding whether to trust it.
  row.verification = null;
  const host = sameAsHost(row.url);
  socialHostError.value = (!row.url || hostIn(host, SAME_AS_HOSTS))
    ? ""
    : `“${host}” is not a network we can list. Accepted: ${acceptedNetworks.value}.`;
}
const acceptedNetworks = computed(() =>
  [...new Set(SAME_AS_HOSTS.map((h) => NETWORK_LABELS[h] || h))].sort((a, b) => a.localeCompare(b)).join(", "));
const unconfirmableNetworks = computed(() =>
  [...new Set([...UNVERIFIABLE_HOSTS, ...SELF_EDITABLE_HOSTS].map((h) => NETWORK_LABELS[h] || h))]
    .sort((a, b) => a.localeCompare(b)).join(", "));

const anyCheckableSocial = computed(() =>
  form.org.same_as.some((r) => r.url && hostIn(sameAsHost(r.url), SAME_AS_HOSTS)
    && !hostIn(sameAsHost(r.url), UNVERIFIABLE_HOSTS) && !hostIn(sameAsHost(r.url), SELF_EDITABLE_HOSTS)));

async function checkSocialLinks() {
  // Save first: the check runs against what is STORED, so an unsaved row would be checked as it was
  // before the edit -- and the tenant would read the badge as being about what is on screen.
  socialBusy.value = true;
  socialCheckNote.value = "";
  try {
    await saveEdit({ keepOpen: true });
    const { site, checked, backlinkHost } = await store.checkSocialLinks(editing.value.site_id);
    editing.value = site;
    const entries = site.organization?.same_as || [];
    form.org.same_as = entries.map((e) => ({ url: e.url || "", verification: e.verification || null }));
    const confirmed = entries.filter((e) => e.verification?.state === "verified").length;
    socialCheckNote.value = checked
      ? `Checked ${checked} profile${checked === 1 ? "" : "s"} for a link back to ${backlinkHost}. ${confirmed} confirmed.`
      : "None of these profiles can be checked automatically.";
  } catch (error) {
    socialCheckNote.value = error.message || "Could not check the links just now.";
  } finally {
    socialBusy.value = false;
  }
}

function socialStatus(row) {
  const host = sameAsHost(row.url);
  if (!row.url) return { label: "", tone: "" };
  if (!hostIn(host, SAME_AS_HOSTS)) return { label: "Not a known network", tone: "bad" };
  if (hostIn(host, UNVERIFIABLE_HOSTS)) return { label: "Shown, not confirmable", tone: "muted" };
  if (hostIn(host, SELF_EDITABLE_HOSTS)) return { label: "Shown, not confirmable", tone: "muted" };
  const state = row.verification?.state || "unverified";
  if (state === "verified") return { label: "Confirmed", tone: "good" };
  if (state === "pending") return { label: "Checking…", tone: "muted" };
  if (state === "failed") return { label: "Link back not found", tone: "bad" };
  return { label: "Not yet confirmed", tone: "muted" };
}

function addHoursRow() {
  form.org.opening_hours.push({ days: [], opens: "09:00", closes: "17:00" });
}
function removeHoursRow(index) {
  form.org.opening_hours.splice(index, 1);
}
function toggleHoursDay(row, day) {
  const i = row.days.indexOf(day);
  if (i >= 0) row.days.splice(i, 1);
  else row.days.push(day);
}
function sameAsForSave(rows) {
  // URL only. Verification state is server-owned: the backend restores it by URL and discards anything the
  // client sends, so posting the badge back would be noise at best and an attempted forgery at worst.
  const urls = rows.map((r) => String(r.url || "").trim()).filter(Boolean);
  return urls.length ? urls.slice(0, SAME_AS_MAX).map((url) => ({ url })) : undefined;
}
function geoForSave(geo) {
  const lat = Number(geo.latitude), lng = Number(geo.longitude);
  if (geo.latitude === "" || geo.longitude === "" || Number.isNaN(lat) || Number.isNaN(lng)) return undefined;
  return { latitude: lat, longitude: lng };
}
function hoursForSave(rows) {
  const clean = (rows || [])
    .filter((r) => r.days.length && r.opens && r.closes)
    .map((r) => ({ days: [...r.days], opens: r.opens, closes: r.closes }));
  return clean.length ? clean : undefined;
}

const domainForm = reactive({ domain: "", homepage: "" });
const domainBusy = ref(false);
const domainError = ref("");

const homepagePick = ref("");
const homepageBusy = ref(false);
const homepageError = ref("");
async function setAsHomepage() {
  if (!homepagePick.value || !editing.value) return;
  homepageBusy.value = true;
  homepageError.value = "";
  try {
    const site = await store.setHomepage(editing.value.site_id, homepagePick.value, editing.value.tenant_id);
    editing.value = { ...site };
    homepagePick.value = "";
  } catch (error) {
    homepageError.value = error.message || "Failed to set homepage.";
  } finally {
    homepageBusy.value = false;
  }
}

const attachForm = reactive({ pageId: "", slug: "" });
const attachBusy = ref(false);
const attachError = ref("");
// A category page carries a catalog_grid section with a category key; attach it as page_type=category so the
// renderer/breadcrumbs treat it right. Everything else attaches as a landing page.
function categoryOfPage(page) {
  const grid = (page?.sections || []).find((s) => s && s.type === "catalog_grid" && s.category);
  return grid ? String(grid.category) : "";
}
async function attachPage() {
  if (!attachForm.pageId || !attachForm.slug || !editing.value) return;
  attachBusy.value = true;
  attachError.value = "";
  try {
    const page = pages.value.find((p) => p.page_id === attachForm.pageId) || {};
    const category = categoryOfPage(page);
    const site = await store.attachPage(
      editing.value.site_id,
      { pageId: attachForm.pageId, slug: attachForm.slug, pageType: category ? "category" : "landing", category, label: page.name },
      editing.value.tenant_id,
    );
    editing.value = { ...site };
    attachForm.pageId = "";
    attachForm.slug = "";
  } catch (error) {
    attachError.value = error.message || "Failed to attach the page.";
  } finally {
    attachBusy.value = false;
  }
}
const domainDiagnostics = ref({});

const dnsProviders = [
  { id: "route53", label: "AWS Route 53", fqdn: false },
  { id: "cloudflare", label: "Cloudflare", fqdn: false },
  { id: "godaddy", label: "GoDaddy", fqdn: false },
  { id: "namecheap", label: "Namecheap", fqdn: false },
  { id: "cpanel", label: "cPanel", fqdn: true },
  { id: "other", label: "Other / full name", fqdn: true },
];
// Custom-domain serving is production/Live-only (single prod edge Worker) — hide it in Test to avoid a dead end.
const customDomainsEnabled = computed(() => getStripeMode() === "live");
function customDomainLabel(site) {
  // "Not connected" is only true-and-useful on a Live Site. On a sandbox Site it reads as an invitation to
  // connect something the server refuses (custom_domains_live_only), so say why instead.
  if (site.hosting?.custom_domain) return site.hosting.custom_domain;
  return customDomainsEnabled.value ? "Not connected" : "Live environment only";
}
const dnsProvider = ref("route53");
const openStep = ref(0);
const copied = ref("");
const providerFqdn = computed(() => (dnsProviders.find((p) => p.id === dnsProvider.value) || {}).fqdn);
const providerLabel = computed(() => (dnsProviders.find((p) => p.id === dnsProvider.value) || {}).label);
const providerTip = computed(() =>
  providerFqdn.value
    ? "Enter the full Name exactly as shown (including your domain)."
    : `${providerLabel.value} adds your domain automatically — enter only the Name shown (the part before your domain).`,
);

function rootDomain(domain) {
  const parts = String(domain || "").split(".");
  return parts.length > 2 ? parts.slice(-2).join(".") : domain;
}
function hostPrefix(fullName, domain) {
  const root = rootDomain(domain);
  if (fullName === root) return "@";
  return fullName.endsWith("." + root) ? fullName.slice(0, -(root.length + 1)) : fullName;
}

const displayRecords = computed(() => {
  const domain = editing.value?.hosting?.custom_domain || "";
  return (editing.value?.domain_provisioning?.dns_records || []).map((rec) => {
    const diag = domainDiagnostics.value[rec.name];
    const resolved = diag ? diag.resolved : null;
    const isSsl = rec.name.startsWith("_acme-challenge");
    return {
      type: rec.type,
      value: rec.value,
      note: rec.note || "",
      displayName: providerFqdn.value ? rec.name : hostPrefix(rec.name, domain),
      stepLabel: isSsl ? "SSL certificate" : "Point your domain",
      badgeClass: resolved === true ? "ok" : resolved === false ? "bad" : "idle",
      badgeIcon: resolved === true ? "✓" : resolved === false ? "!" : "•",
      statusText: resolved === true ? "Detected" : resolved === false ? (diag.note || "Not found yet") : "",
    };
  });
});

// An apex domain (example.com) can't hold a plain CNAME. Guidance depends on the provider (§2.6b).
const isApexDomain = computed(() =>
  (editing.value?.domain_provisioning?.dns_records || []).some((rec) => rec.apex),
);
const apexHint = computed(() => {
  if (!isApexDomain.value) return "";
  const usingA = (editing.value?.domain_provisioning?.dns_records || []).some((rec) => rec.apex && (rec.type === "A" || rec.type === "AAAA"));
  if (usingA) return "Your root domain uses plain A/AAAA records below — these work on any provider, including Route 53.";
  const byProvider = {
    cloudflare: "At the root (@), add a CNAME to the target below — Cloudflare flattens it automatically at the apex.",
    route53: "Route 53 can't point a root domain at an external host like ours. Use a subdomain (e.g. www) for now, or move DNS to a provider with ANAME/ALIAS support — full Route 53 apex support is coming.",
    godaddy: "Use GoDaddy's forwarding/root options or a provider with ANAME/ALIAS. A plain CNAME won't work at the root.",
    namecheap: "Namecheap doesn't support ALIAS at the root — use a subdomain (e.g. www) for now, or a provider with ANAME/ALIAS.",
  };
  return byProvider[dnsProvider.value] || "At the root (@), add an ALIAS or ANAME record to the target below. A plain CNAME won't work at the apex.";
});

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = text;
    setTimeout(() => { if (copied.value === text) copied.value = ""; }, 1500);
  } catch { /* clipboard unavailable */ }
}
const DOMAIN_STATUS_LABELS = { active: "Connected & verified", pending_dns: "Waiting for DNS", pending_ssl: "Issuing certificate", failed: "Verification failed" };
const siteHasHomepage = computed(() => !!(editing.value?.pages || {})["/"]);
const domainStatusLabel = computed(() => {
  if (editing.value?.hosting?.verification?.verified) return "Connected & verified";
  return DOMAIN_STATUS_LABELS[editing.value?.domain_provisioning?.status] || "Pending verification";
});

async function connectDomain() {
  domainError.value = "";
  domainBusy.value = true;
  try {
    editing.value = await store.connectDomain(editing.value.site_id, domainForm.domain, domainForm.homepage);
    domainForm.domain = "";
    domainForm.homepage = "";
  } catch (error) {
    domainError.value = error.message || "Failed to connect domain.";
  } finally {
    domainBusy.value = false;
  }
}

async function checkDomain() {
  domainError.value = "";
  domainBusy.value = true;
  try {
    const { site, status, hint, diagnostics } = await store.checkDomain(editing.value.site_id);
    editing.value = site;
    domainDiagnostics.value = Object.fromEntries((diagnostics || []).map((d) => [d.name, d]));
    if (status !== "active") domainError.value = hint || "Not verified yet — DNS changes can take a while to propagate. Try again shortly.";
  } catch (error) {
    domainError.value = error.message || "Failed to verify domain.";
  } finally {
    domainBusy.value = false;
  }
}

async function disconnectDomain() {
  domainError.value = "";
  domainBusy.value = true;
  try {
    editing.value = await store.disconnectDomain(editing.value.site_id);
  } catch (error) {
    domainError.value = error.message || "Failed to disconnect domain.";
  } finally {
    domainBusy.value = false;
  }
}

const orgPhoneError = computed(() => phoneError(form.org.telephone));
const canCreate = computed(() => !store.saving && createAvailable.value);
const canSaveEdit = computed(() => !store.saving && editCheck.state.available && !orgPhoneError.value);

async function loadPages() {
  try {
    const body = await apiRequest("/pages");
    pages.value = Array.isArray(body.pages) ? body.pages : [];
  } catch {
    pages.value = [];
  }
}

async function reload() {
  await Promise.all([store.load(), loadPages()]);
}

function pickEdit(value) {
  form.subdomain = value;
  editCheck.check(value, editing.value?.site_id);
}

function defaultCreateSelection() {
  // First-ever Site sweeps in every page (unchanged one-click onboarding); an additional Site starts empty
  // so the tenant deliberately picks — the natural path to a one-page Site.
  return store.sites.length ? [] : pages.value.filter((p) => !claimedBy(p.page_id)).map((p) => p.page_id);
}

function startCreate() {
  creating.value = true;
  formError.value = "";
  createName.value = "";
  createSubdomain.value = "";
  createAvailable.value = false;
  createNormalized.value = "";
  createPageIds.value = defaultCreateSelection();
}

function cancelCreate() {
  creating.value = false;
  formError.value = "";
}

async function createSite() {
  formError.value = "";
  const chosen = new Set(createPageIds.value);
  const selectedPages = pages.value.filter((p) => chosen.has(p.page_id) && !claimedBy(p.page_id));
  const business = { ...profileStore.business, name: createName.value || profileStore.business.name };
  try {
    await store.createDefault(selectedPages, business, createNormalized.value || createSubdomain.value);
    creating.value = false;
  } catch (error) {
    formError.value = error.message || "Failed to create site.";
  }
}

async function removePage(pageId) {
  removeError.value = "";
  removeBusy.value = pageId;
  try {
    editing.value = await store.detachPage(editing.value.site_id, pageId, editing.value.tenant_id);
  } catch (error) {
    removeError.value = error.message || "Failed to remove page.";
  } finally {
    removeBusy.value = "";
  }
}

function openEdit(site) {
  editing.value = site;
  domainError.value = "";
  domainDiagnostics.value = {};
  domainForm.domain = "";
  domainForm.homepage = "";
  const org = site.organization || {};
  const address = org.address || {};
  form.name = site.name || "";
  form.subdomain = (site.hosting?.platform_hostname || "").split(".")[0] || "";
  form.org = {
    name: org.name || "", legal_name: org.legal_name || "", entity_type: org.entity_type || "OnlineStore",
    business_type: org.business_type || "",
    description: org.description || "", telephone: org.telephone || "", email: org.email || "",
    address: { locality: address.locality || "", region: address.region || "", street: address.street || "", postal_code: address.postal_code || "", country: address.country || "US" },
    place_id: org.place_id || "", gbp_url: org.gbp_url || "", review_destination: org.review_destination || "",
    geo: { latitude: org.geo?.latitude ?? "", longitude: org.geo?.longitude ?? "" },
    opening_hours: (org.opening_hours || []).map((h) => ({ days: [...(h.days || [])], opens: h.opens || "", closes: h.closes || "" })),
    // verification is read-only here: it is server-owned, and the badge reports it rather than setting it.
    same_as: (org.same_as || []).map((e) => ({ url: e.url || "", verification: e.verification || null })),
  };
  socialHostError.value = "";
  const seo = site.seo || {};
  form.seo = { google_site_verification: seo.google_site_verification || "", bing_site_verification: seo.bing_site_verification || "" };
  form.seo_enabled = site.indexing?.seo_enabled !== false;  // default on
  editCheck.check(form.subdomain, site.site_id);
}

async function saveEdit({ keepOpen = false } = {}) {
  formError.value = "";
  const organization = {
    ...editing.value.organization,
    name: form.org.name || undefined,
    legal_name: form.org.legal_name || undefined,
    entity_type: form.org.entity_type || undefined,
    business_type: form.org.business_type || undefined,
    description: form.org.description || undefined,
    telephone: form.org.telephone ? normalizeE164(form.org.telephone) : undefined,
    email: form.org.email || undefined,
    address: Object.fromEntries(Object.entries(form.org.address).filter(([, v]) => v)),
    place_id: form.org.place_id || undefined,
    gbp_url: form.org.gbp_url || undefined,
    review_destination: form.org.review_destination || undefined,
    geo: geoForSave(form.org.geo),
    opening_hours: hoursForSave(form.org.opening_hours),
    same_as: sameAsForSave(form.org.same_as),
  };
  // Preserve any existing seo fields (title_suffix, indexnow_key) and overlay the editable verification tokens.
  const seo = Object.fromEntries(Object.entries({
    ...editing.value.seo,
    google_site_verification: form.seo.google_site_verification || undefined,
    bing_site_verification: form.seo.bing_site_verification || undefined,
  }).filter(([, v]) => v !== undefined && v !== ""));
  const doc = {
    ...editing.value,
    name: form.name || editing.value.name,
    hosting: { ...editing.value.hosting, platform_subdomain: form.subdomain || undefined },
    organization: Object.fromEntries(Object.entries(organization).filter(([, v]) => v !== undefined && !(typeof v === "object" && !Object.keys(v).length))),
    seo: Object.keys(seo).length ? seo : undefined,
    // Search visibility toggle (default on). Persisted on indexing alongside the computed eligibility; the
    // backend re-renders the pages when it flips (robots + storefront chrome are baked into each artifact).
    indexing: { ...editing.value.indexing, seo_enabled: form.seo_enabled },
  };
  if (!doc.seo) delete doc.seo;
  try {
    const saved = await store.save(doc);
    // keepOpen: the link check saves first so it runs against stored data, then keeps editing so the
    // tenant sees the badges update in place rather than being thrown back to the list.
    if (keepOpen) editing.value = saved || editing.value;
    else editing.value = null;
  } catch (error) {
    formError.value = error.message || "Failed to save site.";
    if (keepOpen) throw error;
  }
}

function availabilityText(state) {
  if (!state.input) return "";
  if (state.checking) return "Checking availability…";
  if (!state.checked) return "";
  if (state.available) return `✓ ${state.hostname} is available`;
  return `✗ ${state.reason}`;
}
function availabilityClass(state) {
  if (state.checking || !state.checked || !state.input) return "field-note";
  return state.available ? "subdomain-ok" : "subdomain-bad";
}

function canonicalHost(site) {
  return site.hosting?.type === "custom" && site.hosting?.custom_domain ? site.hosting.custom_domain : site.hosting?.platform_hostname;
}
// The Site's live, navigable store URL: a verified custom domain if connected, else its free platform host
// ({label}.jbay.uk / .jbay.be), which now serves in both environments (plans/PLATFORM_HOSTNAME_SERVING.md P3).
function siteStoreUrl(site) {
  const h = site.hosting || {};
  const host = (h.custom_domain && h.verification?.verified) ? h.custom_domain : h.platform_hostname;
  return host ? `https://${host}/` : "";
}
const ELIGIBILITY_LABELS = { eligible: "Indexed", pending: "Indexing pending", blocked: "Not indexed", revoked: "Indexing revoked" };
function indexLabel(site) {
  if (site.status === "archived") return "Archived";
  return ELIGIBILITY_LABELS[site.indexing?.eligibility] || "Not indexed";
}
function indexClass(site) {
  return site.status !== "archived" && site.indexing?.eligibility === "eligible" ? "active" : "archived";
}
function indexReason(site) {
  if (site.status === "archived") return "This Site is archived — its pages tell search engines noindex, nofollow, noarchive and are dropped from results. It keeps serving; reactivate anytime to restore indexing.";
  const state = site.indexing?.eligibility;
  if (state === "eligible") return "This Site is eligible for search indexing.";
  if (state === "revoked") return "Indexing was revoked because your Stripe account is restricted. Resolve it in Stripe to restore eligibility.";
  if (state === "pending") return "Almost there — search indexing needs both a verified custom domain and a verified Stripe Connect account.";
  return "Search indexing requires a verified custom domain and a verified Stripe Connect account. On the free address a Site is never indexed.";
}

// Archiving a Site de-indexes all its pages (noindex,nofollow,noarchive in prod). Robots are baked into each
// published artifact at publish time, so flipping the status must ALSO re-render the Site's published pages —
// orchestrated here (same pattern as attach/detach), reusing the publish endpoint.
const pendingArchive = ref("");   // "archive" | "unarchive" while the confirm dialog is open
const archiveBusy = ref(false);
const archiveError = ref("");

async function republishSitePages(site) {
  const pageIds = new Set(Object.values(site.pages || {}).map((e) => e && e.page_id).filter(Boolean));
  if (!pageIds.size) return 0;
  const body = await apiRequest("/pages");
  const targets = (Array.isArray(body.pages) ? body.pages : []).filter((p) => pageIds.has(p.page_id) && p.status === "published");
  let count = 0;
  for (const page of targets) {
    try {
      await apiRequest("/pages", { method: "POST", body: page });  // re-render with the fresh Site status
      count += 1;
    } catch { /* best-effort per page — one failure shouldn't abort the rest */ }
  }
  return count;
}

async function confirmArchive() {
  const archived = pendingArchive.value === "archive";
  const site = editing.value;
  archiveError.value = "";
  archiveBusy.value = true;
  try {
    const saved = await store.setStatus(site, archived ? "archived" : "active");  // flip status first
    editing.value = saved;
    const n = await republishSitePages(saved);                                    // then re-render its live pages
    store.message = archived
      ? `${saved.name} archived — ${n} published page${n === 1 ? "" : "s"} de-indexed.`
      : `${saved.name} reactivated — ${n} page${n === 1 ? "" : "s"} re-published.`;
    pendingArchive.value = "";
    editing.value = null;
  } catch (err) {
    archiveError.value = err.message || "Failed to update the Site.";
    pendingArchive.value = "";
  } finally {
    archiveBusy.value = false;
  }
}

onMounted(async () => {
  await profileStore.ensureLoaded();
  await reload();
  if (store.loaded && !store.sites.length) {
    createPageIds.value = defaultCreateSelection();
    // Seed the Site name from the business profile; StoreAddressField derives + checks the address from it.
    if (!createName.value && profileStore.business?.name) createName.value = profileStore.business.name;
  }
});
</script>

<style scoped>
/* All colors come from the app's theme tokens (--panel/--bg/--text/--line/--accent) — never hardcode a
   surface color. (The old .theme-live dark theme was retired 2026-08-27; the Live/Test pill is the env signal.) */
.copy-replace-warning {
  color: var(--danger, #c0392b);
}
.homepage-picker {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.homepage-picker select {
  flex: 1 1 12rem;
}
.homepage-picker .attach-slug {
  flex: 0 1 10rem;
}
.subdomain-input {
  display: flex;
  align-items: stretch;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  overflow: hidden;
}
.subdomain-input input {
  border: none;
  border-radius: 0;
  flex: 1 1 auto;
  min-width: 0;
}
.subdomain-input input:focus {
  outline: none;
}
.subdomain-input:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.subdomain-suffix {
  display: flex;
  align-items: center;
  padding: 0 0.75rem;
  background: var(--bg);
  color: var(--muted);
  font-family: ui-monospace, monospace;
  white-space: nowrap;
}
.subdomain-suggestions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.35rem;
}
.subdomain-chip {
  border: 1px solid var(--line-strong);
  background: var(--bg);
  color: var(--text);
  border-radius: 999px;
  padding: 0.15rem 0.7rem;
  font-family: ui-monospace, monospace;
  font-size: 0.85em;
  cursor: pointer;
}
.subdomain-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.dns-provider-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0.3rem 0 0.6rem;
  font-size: 1.3rem;
  font-weight: 600;
}
.dns-provider-row select {
  flex: 0 0 auto;
  width: auto;
  padding: 0.3rem 0.6rem;
}
.dns-accordion {
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  overflow: hidden;
}
.dns-step + .dns-step {
  border-top: 1px solid var(--line-strong);
}
.dns-step-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.7rem 0.9rem;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  font-size: 1.35rem;
  color: var(--text);
}
.dns-step-header:hover { background: var(--accent-soft); }
.dns-step-title { font-weight: 600; flex: 1 1 auto; }
.dns-step-status { font-size: 1.2rem; color: var(--muted); }
.dns-chevron { color: var(--muted); }
.dns-badge {
  width: 1.7rem; height: 1.7rem; border-radius: 999px; flex: 0 0 auto;
  display: inline-flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 700;
}
.dns-badge.ok { background: #dcfce7; color: #15803d; }
.dns-badge.bad { background: #fee2e2; color: #b91c1c; }
.dns-badge.idle { background: var(--line); color: var(--muted); }
.dns-step-status.ok { color: #22c55e; }
.dns-step-status.bad { color: #f87171; }
.dns-step-body {
  display: none;
  padding: 0.2rem 0.9rem 0.9rem;
  background: var(--bg);
}
.dns-step.open .dns-step-body { display: block; }
.dns-field {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.4rem;
}
.dns-field-label {
  flex: 0 0 3.6rem;
  font-size: 1.1rem;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--muted);
}
.dns-field code {
  flex: 1 1 auto;
  font-family: ui-monospace, monospace;
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  padding: 0.35rem 0.6rem;
  word-break: break-all;
  font-size: 1.25rem;
}
.copy-btn {
  flex: 0 0 auto;
  background: none;
  border: none;
  color: var(--accent);
  font-weight: 600;
  cursor: pointer;
  font-size: 1.2rem;
}
.copy-btn:hover { text-decoration: underline; }
.subdomain-ok {
  color: #22c55e;
  font-weight: 600;
}
.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 400;
}
.checkbox-row input { width: auto; margin: 0; }
.checkbox-row.is-disabled { color: var(--muted); }
.checkbox-row em { color: var(--muted); font-style: normal; }
.site-page-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  max-height: 240px;
  overflow-y: auto;
}
.site-page-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  font-weight: 400;
  font-size: 1.3rem;
}
.site-page-list li + li { border-top: 1px solid var(--line); }
.link-danger {
  background: none;
  border: none;
  color: #dc2626;
  cursor: pointer;
  font: inherit;
  padding: 0;
}
.link-danger:hover:not(:disabled) { text-decoration: underline; }
.link-danger:disabled { color: var(--muted); cursor: default; }
.subdomain-bad {
  color: #f87171;
  font-weight: 600;
}
.footer-spacer {
  flex: 1 1 auto;
}
.hours-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.social-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.social-url {
  flex: 1 1 18rem;
  min-width: 0;
}
/* The status is the whole point of the row: it says whether we are willing to vouch for this link.
   Muted is the honest default -- "not confirmed" must not look like a failure, because for Instagram
   and TikTok it never can be. */
.social-status {
  font-size: 0.82rem;
  white-space: nowrap;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--sl-border, #d7d7dc);
  color: var(--sl-muted, #6a6a72);
}
.social-status.good {
  color: #146c43;
  border-color: #a9d5bd;
  background: #eaf6f0;
}
.social-status.bad {
  color: #a12a2a;
  border-color: #e2b4b4;
  background: #fbeeee;
}
.social-error {
  margin: 4px 0 8px;
  font-size: 0.85rem;
  color: #a12a2a;
}
.hours-days {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.day-chip {
  min-width: 3.4rem;
  padding: 4px 6px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--muted);
  font: inherit;
  font-size: 1.2rem;
  cursor: pointer;
}
.day-chip.on {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: var(--accent);
  font-weight: 700;
}
.hours-time {
  width: auto;
  min-width: 9rem;
}
.hours-dash {
  color: var(--muted);
}
.hours-remove {
  font-size: 1.2rem;
}
.link-danger-btn {
  color: #dc2626;
  border-color: #f3c0c0;
}
</style>

<template>
  <section class="page landing-pages-page">
    <header class="page-header">
      <div>
        <h1>Landing Pages</h1>
        <p>Create and manage landing pages</p>
      </div>
      <button v-if="builderOpen" class="secondary-action" type="button" @click="backToList">‹ Back to List</button>
    </header>

    <section v-if="!builderOpen" class="dashboard-card landing-pages-card">
      <header class="dashboard-card-header landing-pages-toolbar">
        <h2>Landing Pages</h2>
        <div class="landing-pages-actions">
          <select v-if="sitesStore.sites.length" v-model="siteFilter" class="landing-site-filter" aria-label="Filter by Site">
            <option value="">All Sites</option>
            <option v-for="s in sitesStore.sites" :key="s.site_id" :value="s.site_id">{{ s.name || s.site_id }}</option>
            <option value="__none__">No Site</option>
          </select>
          <input
            v-model.trim="search"
            class="landing-search"
            type="search"
            placeholder="Name, slug, offer, product..."
            aria-label="Search landing pages"
            @focus="ensurePagesLoaded()"
          />
          <button class="secondary-action" type="button" :disabled="loading" @click="loadPages">
            {{ loading ? "Loading..." : "Load Pages" }}
          </button>
          <button class="primary-action" type="button" @click="openWizard">+ Create New Page</button>
        </div>
      </header>

      <div class="landing-pages-body">
        <div v-if="error" class="keys-status-banner error">{{ error }}</div>
        <div v-else-if="message" class="keys-status-banner">{{ message }}</div>

        <div v-if="loading" class="landing-empty-state">Loading landing pages...</div>
        <div v-else-if="!filteredPages.length" class="landing-empty-state">
          {{ emptyStateText }}
        </div>

        <div v-else class="landing-page-list">
          <article
            v-for="page in filteredPages"
            :key="page.page_id"
            class="landing-page-card"
            :class="{ 'is-menu-open': openMenuId === page.page_id }"
          >
            <div class="landing-page-image">
              <!-- Storefront pages show a circular brand mark: the logo (contained, never distorted) or a
                   product-style deterministic colored tile with a house glyph when there's no logo. -->
              <div v-if="isStorefrontPage(page)" class="landing-page-mark">
                <div class="landing-page-mark-inner" :class="{ faux: !pageImage(page) }" :style="pageImage(page) ? null : idColorStyle(page.page_id || page.name)">
                  <img v-if="pageImage(page)" :src="pageImage(page)" :alt="page.name || 'Store logo'" />
                  <svg v-else viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z" />
                  </svg>
                </div>
              </div>
              <img v-else-if="pageImage(page)" :src="pageImage(page)" :alt="page.name || 'Landing page image'" />
              <div v-else class="landing-page-placeholder" aria-hidden="true">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5.25 18.75c4.75-.25 8.75-2.5 12-6.75m0 0 1.5 1.5m-1.5-1.5-1.5-1.5M6.75 14.25 4.5 19.5l5.25-2.25M12 3.75c3.5 1.25 6.25 4 7.5 7.5-4.75.5-8.25-1-10.5-4.5A10 10 0 0 1 12 3.75Z" />
                </svg>
              </div>
            </div>

            <div class="landing-page-copy">
              <div class="landing-page-title-row">
                <div>
                  <h3>{{ page.name || "Untitled Landing Page" }}</h3>
                  <p>
                    {{ templateLabel(page) }} <span>{{ page.page_id }}</span>
                    <span v-if="siteNameForPage(page)" class="landing-page-site">{{ siteNameForPage(page) }}</span>
                    <span v-else class="landing-page-site is-unassigned">No Site</span>
                  </p>
                </div>
              </div>

              <div class="landing-page-url-row">
                <!-- Context cards (test env, page enables /sale or /flash-sale) lead with the pricing-view
                     picker in place of the long URL; Copy + Preview then act on the selected view. Other
                     cards keep the URL text. -->
                <div v-if="cardViewOptions(page).length > 1" class="landing-page-view-picker" aria-label="Preview pricing view">
                  <button
                    v-for="opt in cardViewOptions(page)"
                    :key="opt.value"
                    type="button"
                    :class="{ active: cardView(page) === opt.value }"
                    @click="setCardView(page, opt.value)"
                  >{{ opt.label }}</button>
                </div>
                <span v-else class="landing-page-url">{{ pageUrl(page) }}</span>
                <button class="copy-icon-button" type="button" aria-label="Copy landing page URL" @click="copyPageUrl(page)">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9h9.75A1.25 1.25 0 0 1 20 10.25V20a1.25 1.25 0 0 1-1.25 1.25H9A1.25 1.25 0 0 1 7.75 20v-9.75A1.25 1.25 0 0 1 9 9Zm-5-5h9.75A1.25 1.25 0 0 1 15 5.25V7.5M4 4h9.75M4 4v9.75A1.25 1.25 0 0 0 5.25 15H7.5" />
                  </svg>
                </button>
                <button class="secondary-action compact" type="button" @click="previewPage(page)">Preview</button>
              </div>

              <!-- An attached draft isn't served at its Site URL yet (that would 404), so the URL row above keeps the
                   working preview link; this muted line shows where the page WILL live once published. -->
              <p v-if="pendingSiteUrl(page)" class="landing-page-pending-url" :title="pendingSiteUrl(page)">
                <span class="field-note">Will publish to</span>
                <span>{{ pendingSiteUrl(page) }}</span>
              </p>

              <div class="landing-page-meta">
                <span><strong>{{ itemCount(page) }}</strong> item(s)</span>
                <!-- Views appear only when the rail has actually measured this page: the tracker exists in
                     the PUBLISHED artifact alone, so an unpublished page has no number rather than a zero
                     standing in for traffic nobody counted. -->
                <span v-if="page.analytics_summary?.views !== undefined"><strong>{{ Number(page.analytics_summary.views) }}</strong> views</span>
                <span><strong>{{ Number(page.analytics_summary?.conversions || 0) }}</strong> conversions</span>
                <strong>{{ formatMoney(page.analytics_summary?.revenue_cents || 0) }}</strong>
                <span>revenue</span>
                <span v-if="page.route?.slug" class="landing-page-slug" :title="'/' + page.route.slug">Slug: {{ displaySlug(page) }}</span>
              </div>
            </div>

            <div class="landing-page-badges">
              <span class="page-status-badge" :class="page.status || 'draft'">{{ statusLabel(page.status) }}</span>
              <span class="page-source-badge">{{ pageIntentLabel(page) }}</span>
              <div class="offer-card-menu" @click.stop>
                <button
                  type="button"
                  class="offer-kebab-button"
                  aria-label="Page actions"
                  :aria-expanded="openMenuId === page.page_id"
                  @click="toggleMenu(page.page_id)"
                >
                  ⋮
                </button>
                <div v-if="openMenuId === page.page_id" class="offer-action-menu" role="menu">
                  <button type="button" role="menuitem" @click="viewPage(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.25 12s3.5-6 9.75-6 9.75 6 9.75 6-3.5 6-9.75 6-9.75-6-9.75-6Z" />
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                    </svg>
                    <span>View JSON</span>
                  </button>
                  <button type="button" role="menuitem" @click="editPage(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m16.862 4.487 1.688-1.688a1.875 1.875 0 1 1 2.652 2.652L8.625 18.028 3.75 19.5l1.472-4.875L16.862 4.487Z" />
                    </svg>
                    <span>Edit</span>
                  </button>
                  <button type="button" role="menuitem" @click="duplicatePage(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 8h10.5A1.5 1.5 0 0 1 20 9.5V20a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 20V9.5A1.5 1.5 0 0 1 8 8Z" />
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16V5.5A1.5 1.5 0 0 1 5.5 4H16" />
                    </svg>
                    <span>Duplicate</span>
                  </button>
                  <button type="button" role="menuitem" :disabled="copyBusy" @click="copyPageToEnvironment(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                    </svg>
                    <span>Copy to {{ targetEnvLabel }}</span>
                  </button>
                  <button type="button" role="menuitem" @click="copyPageUrl(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 8h10.5A1.5 1.5 0 0 1 20 9.5V20a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 20V9.5A1.5 1.5 0 0 1 8 8Z" />
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16V5.5A1.5 1.5 0 0 1 5.5 4H16" />
                    </svg>
                    <span>Copy URL</span>
                  </button>
                  <button type="button" role="menuitem" @click="previewPage(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h10v10H7V7Z" />
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 10h4v4h-4v-4Zm8-8h4v4m0-4-5 5M6 22H2v-4m0 4 5-5" />
                    </svg>
                    <span>Preview</span>
                  </button>
                  <button v-if="page.status !== 'archived'" type="button" role="menuitem" @click="togglePagePublished(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path v-if="page.status === 'published'" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM6.6 17.4 17.4 6.6" />
                      <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5.25 18.75c4.75-.25 8.75-2.5 12-6.75m0 0 1.5 1.5m-1.5-1.5-1.5-1.5M6.75 14.25 4.5 19.5l5.25-2.25M12 3.75c3.5 1.25 6.25 4 7.5 7.5-4.75.5-8.25-1-10.5-4.5A10 10 0 0 1 12 3.75Z" />
                    </svg>
                    <span>{{ page.status === "published" ? "Unpublish" : "Publish" }}</span>
                  </button>
                  <button v-if="siteForPage(page)" type="button" role="menuitem" @click="requestDetachSite(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.5 6H18a3 3 0 0 1 0 6h-1.5m-9 0H6a3 3 0 0 1 0-6h1.5M8 9h5" />
                    </svg>
                    <span>Detach Site</span>
                  </button>
                  <button v-else type="button" role="menuitem" @click="openAttachSite(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.5 6H18a3 3 0 0 1 0 6h-1.5m-9 0H6a3 3 0 0 1 0-6h1.5M8 9h8" />
                    </svg>
                    <span>Attach Site</span>
                  </button>
                  <button type="button" class="danger" role="menuitem" @click="requestArchivePage(page)">
                    <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 7h12m-9 0V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7m-7 0 .75 12A2 2 0 0 0 10.75 21h2.5a2 2 0 0 0 2-2L16 7M10 11v6m4-6v6" />
                    </svg>
                    <span>{{ page.status === "published" ? "Archive" : "Delete" }}</span>
                  </button>
                </div>
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>


    <!-- Section editor. One editing surface: rows are a scannable, draggable map and every editor lives
         here (plans/BUILDER_SECTION_ORDER.md Phase 2). ADD opens on a draft and commits; EDIT writes
         through live so the preview keeps updating as the tenant types. -->

    <!-- Page Settings. Page-wide options with no position on the page — which is why this is NOT a row in
         Page Content (plans/BUILDER_SECTION_ORDER.md §2: settings are a separate group). Accordions in
         order of how often a tenant touches them, matching the Post-Checkout Flow pattern. -->
    <div v-if="pageSettingsOpen" class="modal-backdrop" @click.self="closePageSettings()">
      <section class="modal-card section-editor-modal" role="dialog" aria-modal="true" aria-labelledby="pageSettingsTitle">
        <header class="modal-card-header">
          <h2 id="pageSettingsTitle">Page Settings</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="closePageSettings()">✕</button>
        </header>
        <div class="section-editor-body">
            <SettingsAccordion label="Page Basics" hint="What this page is" :icon="SETTINGS_ICONS['Page Basics']" :open="openSetting === 'Page Basics'" @toggle="toggleSetting('Page Basics')">
                <label class="offer-field">
                  <span>Page Name</span>
                  <input v-model.trim="builder.name" type="text" />
                  <small>Internal name for organizing your pages.</small>
                </label>

                <div class="offer-two-column">
                  <label class="offer-field">
                    <span>Product Source</span>
                    <select disabled>
                      <option>From Offer</option>
                    </select>
                  </label>
                  <label class="offer-field">
                    <span>Select Offer</span>
                    <select v-model="builder.offer_id" @change="onBuilderOfferChange">
                      <option v-for="offer in offers" :key="offer.offer_id" :value="offer.offer_id">
                        {{ offer.name }} ({{ offerItemCount(offer) }} item{{ offerItemCount(offer) === 1 ? "" : "s" }})
                      </option>
                    </select>
                  </label>
                </div>
            </SettingsAccordion>
            <SettingsAccordion label="Page Goal" hint="Who is arriving, and from where" :icon="SETTINGS_ICONS['Page Goal']" :open="openSetting === 'Page Goal'" @toggle="toggleSetting('Page Goal')">
                <!-- The goal is set in the create wizard, but it must stay editable: it drives composition, so
                     a page frozen on its original goal could never gain (or drop) what a goal governs. -->
                <label class="offer-field">
                  <span>Page Goal</span>
                  <select v-model="builder.goal">
                    <option value="">Not set</option>
                    <option v-for="option in goalOptions" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </option>
                  </select>
                  <small>{{ builderGoalNote }}</small>
                </label>
            </SettingsAccordion>
                        <SettingsAccordion label="Appearance" hint="Theme preset and colour overrides" :icon="SETTINGS_ICONS['Appearance']" :open="openSetting === 'Appearance'" @toggle="toggleSetting('Appearance')">
                  <label class="offer-field">
                    <span>Preset</span>
                    <select v-model="builder.preset">
                      <option v-for="option in universalBundlePresets" :key="option.value" :value="option.value">
                        {{ option.label }}
                      </option>
                    </select>
                  </label>

                <label class="builder-switch-row">
                  <span class="builder-switch" @click.stop>
                    <input v-model="builder.advanced_appearance" type="checkbox" aria-label="Advanced appearance settings" />
                    <span aria-hidden="true"></span>
                  </span>
                  <span>Customize fonts and colors</span>
                </label>
                <div v-if="builder.advanced_appearance" class="advanced-colors">
                  <div class="advanced-colors-head">
                    <small>The preset already looks good — only tweak here if you need to. Empty = use the preset.</small>
                    <button class="secondary-action compact" type="button" @click="resetAppearanceOverrides">Reset to preset</button>
                  </div>
                  <div class="color-group">
                    <div class="color-group-title">Fonts</div>
                    <label v-for="role in builderFontRoles" :key="role.key" class="font-row">
                      <span class="color-label">{{ role.label }}</span>
                      <select :value="fontFamilyFor(role.key)" @change="setFontFamily(role.key, $event.target.value)">
                        <option value="">Use preset</option>
                        <option value="system">System fonts (no download)</option>
                        <optgroup v-if="tenantFontFamilies.length" label="Your fonts">
                <option v-for="family in tenantFontFamilies" :key="family" :value="family">{{ family }}</option>
              </optgroup>
              <optgroup label="Junior Bay fonts">
                <option v-for="family in builderFontFamilies" :key="family" :value="family">{{ family }}</option>
              </optgroup>
                      </select>
                    </label>
                  </div>
                  <div v-for="group in tokenGroups()" :key="group.name" class="color-group">
                    <div class="color-group-title">{{ group.name }}</div>
                    <label v-for="t in group.tokens" :key="t.token" class="color-row">
                      <input class="color-picker" type="color" :value="pickerColor(t.token)" :title="t.label" @input="setTokenColor(t.token, $event.target.value)" />
                      <span class="color-label">{{ t.label }}</span>
                      <input
                        :value="builder.theme_tokens[t.token] || ''"
                        type="text"
                        spellcheck="false"
                        :placeholder="effectiveColor(t.token) || 'preset'"
                        @input="setTokenColor(t.token, $event.target.value)"
                      />
                    </label>
                  </div>
                </div>
            </SettingsAccordion>
            <SettingsAccordion label="SEO" hint="Title and search snippet" :icon="SETTINGS_ICONS['SEO']" :open="openSetting === 'SEO'" @toggle="toggleSetting('SEO')">
                <label class="offer-field">
                  <span>SEO Title</span>
                  <input :value="builder.seo_title" :placeholder="seoTitlePlaceholder" type="text" @input="applyTitleCaseInput((value) => { builder.seo_title = value; }, $event)" />
                  <small>The browser tab / search-result title. Leave blank to use the smart default (shown above).</small>
                </label>
                <label class="offer-field">
                  <span>SEO Description</span>
                  <textarea v-model.trim="builder.seo_description" :placeholder="seoDescriptionPlaceholder" rows="3"></textarea>
                  <small>The search-result snippet. Leave blank to auto-generate from the product description.</small>
                </label>
            </SettingsAccordion>
            <SettingsAccordion label="Discoverability" hint="Structured data and machine readers" :icon="SETTINGS_ICONS['Discoverability']" :open="openSetting === 'Discoverability'" @toggle="toggleSetting('Discoverability')">
                <details v-if="discoverabilitySections.length" class="builder-section discoverability-drawer">
                  <summary>
                    <h3>Discoverability</h3>
                    <span class="discoverability-hint">
                      {{ isSectionEnabled("structured_data") ? "Structured data on" : "Nothing emitted" }}
                    </span>
                  </summary>
                  <small>
                    Not visible on the page — this is what search engines and AI crawlers read. It is generated from
                    your offer and the sections you have already added, so there is nothing to write here.
                  </small>
                  <div class="composition-list">
                    <label v-for="key in discoverabilitySections" :key="key" class="composition-row">
                      <input type="checkbox" :checked="isSectionEnabled(key)" @change="toggleSection(key, $event.target.checked)" />
                      <span class="composition-name">{{ sectionKeyLabel(key) }}</span>
                      <span class="composition-tag" :class="defaultVisible(builderOfferType, key, builderGoal) ? 'is-recommended' : 'is-optional'">
                        {{ defaultVisible(builderOfferType, key, builderGoal) ? "Recommended" : "Optional" }}
                      </span>
                    </label>
                  </div>
                  <div v-if="isSectionEnabled('structured_data')" class="discoverability-emits">
                    <span>Will emit</span>
                    <strong v-if="structuredDataTypes.length">{{ structuredDataTypes.join(", ") }}</strong>
                    <strong v-else>Nothing yet — add an offer price or an FAQ</strong>
                  </div>
                  <!-- Thin markup isn't invalid, it's ignored — which is the failure a tenant can't see. Nudge,
                       never block (plans/LANDING_PAGE_GOAL_COMPOSITION.md: warnings, not gates). -->
                  <div v-if="isSectionEnabled('structured_data') && structuredDataWarnings.length" class="discoverability-warnings">
                    <strong>To earn a rich result in search:</strong>
                    <ul>
                      <li v-for="(warning, i) in structuredDataWarnings" :key="i">{{ warning }}</li>
                    </ul>
                    <small>Your page still publishes normally — these only affect how search engines display it.</small>
                  </div>
                  <p v-if="!builderGoal" class="discoverability-note">
                    Set a Page Goal of "Search / SEO" above to turn this on by default.
                  </p>
                </details>
            </SettingsAccordion>
            <SettingsAccordion label="Analytics" hint="Google Tag and Meta Pixel" :icon="SETTINGS_ICONS['Analytics']" :open="openSetting === 'Analytics'" @toggle="toggleSetting('Analytics')">
                <div class="offer-two-column">
                  <label class="offer-field">
                    <span>Google Tag ID</span>
                    <input v-model.trim="builder.google_tag_id" type="text" />
                  </label>
                  <label class="offer-field">
                    <span>Meta Pixel ID</span>
                    <input v-model.trim="builder.pixel_id" type="text" />
                  </label>
                </div>
            </SettingsAccordion>
            <SettingsAccordion label="Favicon" hint="The browser-tab icon" :icon="SETTINGS_ICONS['Favicon']" :open="openSetting === 'Favicon'" @toggle="toggleSetting('Favicon')">
                <label class="offer-field">
                  <span>Favicon</span>
                  <div class="builder-inline-media">
                    <img :src="builder.favicon_url || defaultFaviconUrl" alt="" />
                    <div class="builder-upload-stack">
                      <input ref="faviconFileInput" type="file" accept="image/*" hidden @change="handleFaviconPicked" />
                      <button class="secondary-action compact" type="button" :disabled="faviconUploading" @click="faviconFileInput?.click()">
                        {{ faviconUploading ? "Uploading..." : "Upload favicon" }}
                      </button>
                      <input v-model.trim="builder.favicon_url" type="url" placeholder="Leave blank to use Junior Bay favicon" />
                    </div>
                  </div>
                  <small v-if="faviconUploadError" class="builder-upload-error">{{ faviconUploadError }}</small>
                </label>
            </SettingsAccordion>
        </div>
        <footer class="section-editor-footer">
          <button class="primary-action" type="button" @click="closePageSettings()">Done</button>
        </footer>
      </section>
    </div>
    <div v-if="sectionEditor" class="modal-backdrop" @click.self="cancelSectionEditor">
      <section class="modal-card section-editor-modal" role="dialog" aria-modal="true" aria-labelledby="sectionEditorTitle">
        <header class="modal-card-header">
          <h2 id="sectionEditorTitle">{{ sectionEditor.isNew ? `Add ${sectionEditor.row.label}` : sectionEditor.row.label }}</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="cancelSectionEditor">✕</button>
        </header>
        <div class="section-editor-body">
            <template v-if="sectionEditor.row.editor === 'countdown'">
                <p>Add urgency with a countdown timer at the top of the page.</p>
                <label class="builder-toggle">
                  <input v-model="builder.countdown.enabled" type="checkbox" />
                  <span>Enable Countdown Timer</span>
                </label>
                <div v-if="builder.countdown.enabled" class="builder-countdown-options">
                  <label class="offer-field">
                    <span>Duration Minutes</span>
                    <input v-model.number="builder.countdown.duration_minutes" type="number" min="1" />
                  </label>
                  <label class="builder-toggle">
                    <input v-model="builder.countdown.persistent" type="checkbox" />
                    <span>Persist Timer</span>
                  </label>
                  <label class="builder-toggle">
                    <input v-model="builder.countdown.transparent" type="checkbox" />
                    <span>Transparent Background</span>
                  </label>
                  <label class="builder-toggle">
                    <input v-model="builder.countdown.sticky" type="checkbox" />
                    <span>Sticky Banner</span>
                  </label>
                  <label class="builder-toggle">
                    <input v-model="builder.countdown.marquee" type="checkbox" />
                    <span>Marquee Scroll</span>
                  </label>
                  <label v-if="builder.countdown.marquee" class="offer-field">
                    <span>Scroll Speed</span>
                    <div class="builder-speed-row">
                      <span aria-hidden="true" title="Slower">🐢</span>
                      <input
                        v-model.number="marqueeSpeedSlider"
                        type="range"
                        :min="MARQUEE_MIN_SECONDS"
                        :max="MARQUEE_MAX_SECONDS"
                        step="1"
                        aria-label="Marquee scroll speed"
                      />
                      <span aria-hidden="true" title="Faster">🐇</span>
                    </div>
                  </label>
                  <div class="builder-countdown-row">
                    <label class="builder-toggle">
                      <input v-model="builder.countdown.start_enabled" type="checkbox" />
                      <span>Banner Start</span>
                    </label>
                    <button
                      type="button"
                      class="badge-icon-picker-btn"
                      aria-label="Start icon"
                      @click.stop="showIconPicker(builder.countdown.start_icon, (emoji) => { builder.countdown.start_icon = emoji; }, 'Choose an Icon')"
                    >{{ builder.countdown.start_icon || '—' }}</button>
                    <input v-model.trim="builder.countdown.start_text" type="text" aria-label="Start text" />
                    <input v-model="builder.countdown.start_color" type="color" aria-label="Start color" />
                  </div>
                  <div class="builder-countdown-row">
                    <label class="builder-toggle">
                      <input v-model="builder.countdown.end_enabled" type="checkbox" />
                      <span>Banner End</span>
                    </label>
                    <button
                      type="button"
                      class="badge-icon-picker-btn"
                      aria-label="End icon"
                      @click.stop="showIconPicker(builder.countdown.end_icon, (emoji) => { builder.countdown.end_icon = emoji; }, 'Choose an Icon')"
                    >{{ builder.countdown.end_icon || '—' }}</button>
                    <input v-model.trim="builder.countdown.end_text" type="text" aria-label="End text" />
                    <input v-model="builder.countdown.end_color" type="color" aria-label="End color" />
                  </div>
                </div>
            </template>
            <template v-else-if="sectionEditor.row.editor === 'hero'">
                <template v-if="isListicleOffer">
                  <small>This landing page shows several products in a carousel. The hero headline and subheadline follow the product you’re viewing — each product’s own name and description — so there’s nothing to set here.</small>
                </template>
                <template v-else-if="sectionVisible('hero')">
                  <label class="offer-field">
                    <span>Hero Headline</span>
                    <input :value="builder.headline" type="text" @input="applyTitleCaseInput((value) => { builder.headline = value; }, $event)" />
                  </label>
                  <label class="offer-field">
                    <span>Hero Subheadline</span>
                    <textarea v-model.trim="builder.subheadline" rows="3"></textarea>
                  </label>
                </template>
                <!-- Everything below belongs to hero_media, not hero: the carousel, the avatar that overlaps
                     it, and the brand chip that sits inside it. A bridge page has no hero_media, so offering
                     an avatar there would be offering a control with nothing to attach to. -->
                <template v-if="sectionVisible('hero_media')">
                <div class="offer-field">
                  <span>Hero Media</span>
                  <MediaListField
                    :model-value="heroMediaList"
                    hint="Add images and videos to your hero carousel"
                    empty-text="No media yet — upload an image or add a video URL."
                    :suggestions="builderProductImages"
                    :derived="builderDerivedHeroMedia"
                    derived-note="Auto — these come from your offer's products. Upload or add media to override."
                    :upload="uploadPageImage"
                    :upload-video="uploadPageVideo"
                    :crop-ratios="imageRatios.asset.hero_media"
                    :assets="builder.image_assets || {}"
                    :posters="builder.video_posters || {}"
                    allow-video-upload
                    @update:model-value="setHeroMedia"
                    @crop-applied="onHeroCropApplied"
                    @poster-set="onHeroPosterSet"
                  />
                </div>
                <label class="builder-switch-row">
                  <span class="builder-switch" @click.stop>
                    <input v-model="builder.autoplay" type="checkbox" aria-label="Autoplay hero videos muted" />
                    <span aria-hidden="true"></span>
                  </span>
                  <span>Autoplay video (muted)</span>
                </label>

                <label class="offer-field">
                  <span>Profile Avatar</span>
                  <small>Put a face on the page — the person behind the service. Overlaps the hero image.</small>
                  <div class="builder-avatar-row">
                    <img v-if="effectiveAvatarUrl" :src="effectiveAvatarUrl" class="builder-avatar-preview" alt="" />
                    <input ref="avatarFileInput" type="file" accept="image/*" hidden @change="handleAvatarPicked" />
                    <button class="secondary-action compact" type="button" :disabled="avatarUploading" @click="avatarFileInput?.click()">
                      {{ avatarUploading ? "Uploading..." : (builder.avatar_url ? "Replace avatar" : "Override for this page") }}
                    </button>
                    <button v-if="builder.avatar_url" class="secondary-action compact" type="button" @click="builder.avatar_url = ''">Use store avatar</button>
                  </div>
                  <small v-if="avatarUploadError" class="builder-upload-error">{{ avatarUploadError }}</small>
                  <small v-else-if="avatarIsFromProfile" class="field-note">Showing your store avatar. Change it in Preferences and every page that has not overridden it updates too.</small>
                  <!-- NOT gated on knowing the avatar's URL. The renderer already learned this lesson where
                       the section is written (see builderSectionCandidates): once the avatar became a
                       REFERENCE, a page inheriting the store image has an empty avatar_url, so any gate on it
                       silently withholds the control from exactly the pages most likely to want it. The gate
                       here was the same mistake in the editor -- and worse, it depended on an async profile
                       load, so the dropdown could vanish for a page that renders an avatar perfectly well.
                       Placement is a page-level preference about WHERE an avatar goes; it is answerable
                       before one exists, and "hidden" is a real answer. -->
                  <label class="offer-field">
                    <span>Avatar placement</span>
                    <select v-model="builder.avatar_placement">
                      <option value="overlay">Overlapping hero, bottom left</option>
                      <option value="overlay_bottom">Overlapping hero, bottom center</option>
                      <option value="overlay_top">Overlapping hero, top center</option>
                      <option value="inline">Below the hero, left</option>
                      <option value="centered">Below the hero, centered</option>
                      <option value="hidden">Don't show an avatar on this page</option>
                    </select>
                    <small class="field-note">Overlapping suits a page with a cover image. Without one, choose a position below the hero — an overlapping avatar with nothing behind it reads as a mistake.</small>
                  </label>
                </label>

                <!-- Not every tenant has a brand to promote; most creators are promoting themselves. Hiding it
                     writes a composition override, the SAME mechanism the Page Sections panel uses, rather than
                     a second way to switch a section off. -->
                <label class="builder-switch-row">
                  <span class="builder-switch" @click.stop>
                    <input v-model="brandLabelHidden" type="checkbox" aria-label="Hide the brand name" />
                    <span aria-hidden="true"></span>
                  </span>
                  <span>Hide brand name</span>
                </label>
                <small class="field-note">
                  Removes the <strong>● {{ brandLabelFallback || "brand" }}</strong> mark above the hero. Turn it off
                  if this page is about a person rather than a business — the name below can stand in for it.
                </small>

                <label class="builder-switch-row">
                  <span class="builder-switch" @click.stop>
                    <input v-model="builder.show_identity" type="checkbox" aria-label="Show name and slogan" />
                    <span aria-hidden="true"></span>
                  </span>
                  <span>Show name and slogan</span>
                </label>
                <small class="field-note">
                  Puts <strong>{{ ownerDisplayName || "your name" }}</strong> under the avatar, with an optional line
                  beneath it. The name comes from your Profile, so changing it there updates every page.
                </small>
                <label v-if="builder.show_identity" class="offer-field">
                  <span>Slogan <em>(optional)</em></span>
                  <input
                    v-model.trim="builder.tagline"
                    type="text"
                    :maxlength="HERO_TAGLINE_MAX"
                    placeholder="be kind" />
                  <small class="field-note">
                    {{ HERO_TAGLINE_MAX - (builder.tagline || "").length }} characters left — the cap keeps it to one
                    line on a phone, where nearly all of this traffic is.
                  </small>
                </label>

                <label class="builder-switch-row">
                  <span class="builder-switch" @click.stop>
                    <input v-model="builder.brand_overlay" type="checkbox" aria-label="Show brand name on hero image" />
                    <span aria-hidden="true"></span>
                  </span>
                  <span>Show brand on hero image</span>
                </label>
                <label v-if="builder.brand_overlay" class="offer-field">
                  <span>Brand position</span>
                  <select v-model="builder.brand_position">
                    <option value="top-left">Top left</option>
                    <option value="top-right">Top right</option>
                    <option value="bottom-left">Bottom left</option>
                    <option value="bottom-right">Bottom right</option>
                  </select>
                </label>
                <label class="builder-toggle">
                  <input v-model="builder.brand_dot_pulse" type="checkbox" />
                  <span>Pulsate brand dot</span>
                </label>
                <small class="field-note">Applies to the brand dot wherever it appears — on the hero chip, or above the hero when the overlay is off.</small>
                </template>
            </template>
            <template v-else-if="sectionEditor.row.editor === 'brand_label'">
                <!-- Breadcrumb FIRST, brand name second: this editor is ordered the way the header renders
                     (author, 2026-09-12). The trail sits above the brand mark on the page, so reading the two
                     controls top to bottom matches reading the page top to bottom. -->
                <label class="builder-switch-row">
                  <span class="builder-switch" @click.stop>
                    <input v-model="breadcrumbOn" type="checkbox" aria-label="Show breadcrumb trail" />
                    <span aria-hidden="true"></span>
                  </span>
                  <span>Show breadcrumb trail</span>
                </label>
                <small class="field-note">
                  The <strong>Home / {{ builder.name || "This page" }}</strong> trail above the brand. It says where
                  this page sits in your store, so it only appears once the page is attached to a Site.
                  <template v-if="!breadcrumbDefault">
                    A {{ builderOfferType === "lead_social" ? "link page" : "lead page" }} is not part of a
                    catalogue, so it is off here by default.
                  </template>
                </small>

                <label class="offer-field">
                  <span>Brand name</span>
                  <input v-model.trim="builder.brand_label_text" type="text" :placeholder="brandLabelFallback" />
                  <small class="field-note">
                    Leave blank to use your business name. Without one it falls back to the product's name,
                    which is why a page can end up branded after the thing it sells — set a business name in
                    Profile → Business, or override it here for this page.
                  </small>
                </label>
            </template>

            <template v-else-if="sectionEditor.row.editor === 'trust_badges'">
                <div class="builder-repeat-list">
                  <div v-for="(badge, index) in builder.trust_badges.badges" :key="`badge-${index}`" class="builder-repeat-row builder-trust-badge-row">
                    <label class="builder-switch" @click.stop>
                      <input v-model="badge.enabled" type="checkbox" :aria-label="`Enable trust badge ${index + 1}`" />
                      <span aria-hidden="true"></span>
                    </label>
                    <strong>Trust Badge {{ index + 1 }}</strong>
                    <button
                      type="button"
                      class="badge-icon-picker-btn"
                      :disabled="!badge.enabled"
                      :aria-label="`Change icon for trust badge ${index + 1}`"
                      @click.stop="showIconPicker(badge.emoji, (emoji) => { badge.emoji = emoji; }, 'Choose an Icon')"
                    >{{ badge.emoji || '—' }}</button>
                    <input v-model.trim="badge.label" type="text" :disabled="!badge.enabled" aria-label="Badge label" />
                  </div>
                </div>
              </template>
            <template v-else-if="sectionEditor.row.editor === 'refund_policy'">
                <label class="builder-toggle">
                  <input v-model="builder.refund_policy.enabled" type="checkbox" />
                  <span>Show refund policy</span>
                </label>
                <small>Refund policy copy comes from the selected offer.</small>
              </template>
            <template v-else-if="sectionEditor.row.editor === 'checkout_cta'">
                <label class="offer-field">
                  <span>Button Label</span>
                  <input v-model.trim="builder.cta_label" type="text" />
                </label>
                <div class="lead-action-summary">
                  <strong>{{ ctaTypeLabel(builderCta.type) }}</strong>
                  <span>{{ ctaTypeDescription(builderCta.type) }} This comes from the offer and can't be changed here.</span>
                  <code v-if="builderCta.target">{{ builderCta.target }}</code>
                </div>
              </template>
              <template v-else-if="sectionEditor.row.editor === 'element' && sectionEditor.row.element">
                <template v-for="element in [sectionEditor.row.element]" :key="element.id">

                    <template v-if="element.type === 'content_block'">
                      <input :value="element.title" type="text" placeholder="Title" @input="applyTitleCaseInput((value) => { element.title = value; }, $event)" />
                      <textarea v-model.trim="element.text" rows="2" placeholder="Text"></textarea>
                      <ImageUploadField
                        v-model="element.image_url"
                        :crop="element.image_crop"
                        :ratios="imageRatios.placement.content_block"
                        :uploader="uploadPageImage"
                        label="Upload Image"
                        alt="Content image preview"
                        allow-url
                        url-placeholder="Optional image URL"
                        @update:crop="(rect) => (element.image_crop = rect)"
                      />
                      <div v-if="blurbImageErrors[element.id]" class="price-image-error">{{ blurbImageErrors[element.id] }}</div>
                      <label class="builder-toggle"><input v-model="element.centered" type="checkbox" /><span>Center this block</span></label>
                    </template>

                    <template v-else-if="element.type === 'testimonials'">
                      <input v-model.trim="element.heading" type="text" placeholder="Section heading (optional)" />
                      <div v-for="(item, i) in element.items" :key="i" class="element-subrow">
                        <textarea v-model.trim="item.quote" rows="2" placeholder="Quote"></textarea>
                        <input v-model.trim="item.author" type="text" placeholder="Author" />
                        <input v-model.trim="item.role" type="text" placeholder="Role (optional)" />
                        <div class="selectable-price-image-controls" :class="{ 'has-image-preview': item.avatar_url }">
                          <div v-if="item.avatar_url" class="selectable-price-image-preview"><img :src="item.avatar_url" alt="Avatar preview" /></div>
                          <input :ref="(el) => setSubImageInput(subImgKey(element, 'items', i), el)" type="file" accept="image/*" hidden @change="handleSubImagePicked(item, 'avatar_url', subImgKey(element, 'items', i), $event)" />
                          <button class="secondary-action compact" type="button" :disabled="Boolean(subImageUploading[subImgKey(element, 'items', i)])" @click.prevent="triggerSubImageUpload(subImgKey(element, 'items', i))">
                            {{ subImageUploading[subImgKey(element, 'items', i)] ? "Uploading..." : "Upload avatar" }}
                          </button>
                          <input v-model.trim="item.avatar_url" type="url" placeholder="or paste avatar URL" />
                        </div>
                        <div v-if="subImageErrors[subImgKey(element, 'items', i)]" class="price-image-error">{{ subImageErrors[subImgKey(element, 'items', i)] }}</div>
                        <button class="danger-action compact" type="button" @click="removeSubItem(element, 'items', i)">Remove</button>
                      </div>
                      <button class="secondary-action compact" type="button" @click="addSubItem(element, 'items', { quote: '', author: '', role: '', avatar_url: '' })">+ Add testimonial</button>
                    </template>

                    <template v-else-if="element.type === 'rating'">
                      <div class="offer-two-column">
                        <label class="offer-field"><span>Stars (0–5)</span><input v-model.number="element.value" type="number" min="0" max="5" step="0.1" /></label>
                        <label class="offer-field"><span>Review count</span><input v-model.number="element.count" type="number" min="0" /></label>
                      </div>
                      <label class="offer-field"><span>Label</span><input v-model.trim="element.label" type="text" placeholder="e.g. on Google" /></label>
                    </template>

                    <template v-else-if="element.type === 'page_ribbon'">
                      <p v-if="ribbonCount > 2" class="field-warning">
                        Three ribbons stop being interruptions and become wallpaper. Two is the most a page should carry.
                      </p>
                      <label class="offer-field">
                        <span>Layout</span>
                        <select v-model="element.presentation">
                          <option value="image_left">Image left — image, then the copy and button</option>
                          <option value="centered">Centered — no image</option>
                          <option value="compact">Compact row — small image, one line of copy</option>
                        </select>
                      </label>
                      <ImageUploadField
                        v-if="element.presentation !== 'centered'"
                        v-model="element.image_url"
                        :crop="element.image_crop"
                        :ratios="imageRatios.placement.page_ribbon"
                        :uploader="uploadPageImage"
                        alt="Ribbon image preview"
                        @update:crop="(rect) => (element.image_crop = rect)"
                      />
                      <label class="offer-field"><span>Eyebrow (optional)</span><input v-model.trim="element.eyebrow" type="text" placeholder="e.g. Limited time" /></label>
                      <label class="offer-field">
                        <span>Headline</span>
                        <input v-model.trim="element.headline" type="text" placeholder="What you want them to do" />
                        <small class="field-note">**text** colours a phrase, ^^text^^ highlights it.</small>
                      </label>
                      <label class="offer-field"><span>Supporting copy</span><textarea v-model.trim="element.body" rows="2" placeholder="One or two lines of why."></textarea></label>
                      <div class="offer-two-column">
                        <label class="offer-field"><span>Button label</span><input v-model.trim="element.cta.label" type="text" placeholder="e.g. Reactivate now" /></label>
                        <label class="offer-field">
                          <span>Button does</span>
                          <select v-model="element.cta.action">
                            <option value="promote_page">Promotes another of my pages</option>
                            <option value="download">Downloads a file</option>
                            <option value="email_file" :disabled="!businessEmailVerified">
                              Sends an email with the file{{ businessEmailVerified ? "" : " — needs a verified business email" }}
                            </option>
                            <option value="redirect">Opens a link</option>
                            <option value="call_phone">Starts a call</option>
                            <option value="email">Opens their email app</option>
                          </select>
                        </label>
                      </div>
                      <!-- Blocking, not a warning after the fact: the tenant should learn they cannot send
                           BEFORE uploading a file and writing copy for a button that will refuse to work. -->
                      <p v-if="element.cta.action === 'email_file' && !businessEmailVerified" class="field-error">
                        You must first enter a valid business email address before using this feature!
                        Go to your Profile page to enter a business email.
                      </p>
                      <div v-if="element.cta.action === 'download' || element.cta.action === 'email_file'" class="offer-field">
                        <span>File to hand over</span>
                        <div class="ribbon-page-choice">
                          <span v-if="element.cta.asset" class="ribbon-page-chosen">
                            <strong>{{ element.cta.asset.filename }}</strong>
                            <small>{{ formatBytes(element.cta.asset.size_bytes) }}</small>
                          </span>
                          <span v-else class="ribbon-page-empty">No file uploaded yet.</span>
                          <input :ref="(el) => setRibbonFileInput(element.id, el)" type="file" hidden @change="handleRibbonFilePicked(element, $event)" />
                          <button class="secondary-action compact" type="button" :disabled="ribbonUploading[element.id]" @click.prevent="triggerRibbonFileUpload(element.id)">
                            {{ ribbonUploading[element.id] ? `Uploading ${ribbonUploadPct[element.id] || 0}%` : (element.cta.asset ? "Replace" : "Upload file") }}
                          </button>
                        </div>
                        <small v-if="ribbonUploadError[element.id]" class="field-error">{{ ribbonUploadError[element.id] }}</small>
                        <label class="builder-toggle">
                          <input v-model="element.cta.collect_email" type="checkbox" :disabled="element.cta.action === 'email_file'" />
                          <span>Ask for their email first</span>
                        </label>
                        <label class="builder-toggle"><input v-model="element.cta.collect_phone" type="checkbox" /><span>Ask for their phone first</span></label>
                        <small class="field-note">
                          {{ element.cta.action === "email_file"
                             ? "An email address is always required — there is nowhere to send it otherwise. It is saved to Leads, then the file is emailed as a link that works for 24 hours."
                             : (element.cta.collect_email || element.cta.collect_phone
                               ? "They fill this in, it is saved to Leads, then the file downloads."
                               : "Nothing is asked for — the file downloads straight away, and no lead is recorded.") }}
                        </small>
                      </div>
                      <div v-else-if="element.cta.action === 'promote_page'" class="offer-field">
                        <span>Page to promote</span>
                        <div class="ribbon-page-choice">
                          <span v-if="ribbonTargetPage(element)" class="ribbon-page-chosen">
                            <strong>{{ ribbonTargetPage(element).name || "Untitled page" }}</strong>
                            <small>{{ pageUrl(ribbonTargetPage(element)) }}</small>
                          </span>
                          <span v-else class="ribbon-page-empty">No page chosen yet.</span>
                          <button class="secondary-action compact" type="button" @click="openRibbonPagePicker(element)">
                            {{ ribbonTargetPage(element) ? "Change" : "Choose a page" }}
                          </button>
                        </div>
                        <small v-if="ribbonTargetPage(element) && ribbonTargetPage(element).status !== 'published'" class="field-warning">
                          That page is no longer published, so the button would lead nowhere. Publish it again, or choose another page.
                        </small>
                        <small v-else class="field-note">Only published pages can be chosen. The live URL is filled in for you, and refreshed each time you save.</small>
                      </div>
                      <label v-else class="offer-field">
                        <span>{{ element.cta.action === "call_phone" ? "Phone number" : element.cta.action === "email" ? "Email address" : "Link" }}</span>
                        <input v-model.trim="element.cta.target" type="text" :placeholder="element.cta.action === 'call_phone' ? '+1 555 010 1234' : element.cta.action === 'email' ? 'hello@example.com' : 'https://… or /another-page'" />
                        <small class="field-note">Leave the label or this blank and the ribbon renders without a button.</small>
                      </label>
                      <label class="builder-toggle">
                        <input type="checkbox" :checked="Boolean(element.theme && element.theme.bg)" @change="toggleSectionBreak(element, $event, 'accent')" />
                        <span>Break the page style for this section</span>
                      </label>
                      <div v-if="element.theme && element.theme.bg" class="offer-two-column">
                        <label class="offer-field">
                          <span>Background</span>
                          <input v-model.trim="element.theme.bg" type="color" />
                          <small class="field-note">Text colour is chosen automatically so it stays readable.</small>
                        </label>
                        <label class="offer-field"><span>Button</span><input v-model.trim="element.theme.accent" type="color" /></label>
                      </div>
                    </template>

                    <template v-else-if="element.type === 'video'">
                      <label class="offer-field">
                        <span>Heading (optional)</span>
                        <input v-model.trim="element.heading" type="text" placeholder="e.g. See how it works" />
                      </label>
                      <label class="offer-field">
                        <span>Video</span>
                        <input v-model.trim="element.url" type="url" placeholder="YouTube or Vimeo link, or upload below" />
                        <small v-if="element.url" class="field-note">{{ videoKindLabel(element.url) }}</small>
                        <small v-else class="field-note">Paste a YouTube or Vimeo link, or upload your own file.</small>
                      </label>
                      <div class="image-upload-actions">
                        <input :ref="(el) => setElementVideoInput(element.id, el)" type="file" accept="video/*" hidden @change="handleElementVideoPicked(element, $event)" />
                        <button class="secondary-action compact" type="button" :disabled="Boolean(elementVideoUploading[element.id])" @click.prevent="triggerElementVideoUpload(element.id)">
                          {{ elementVideoUploading[element.id] ? (elementVideoStatus[element.id] || "Uploading...") : "Upload video file" }}
                        </button>
                      </div>
                      <p v-if="elementVideoErrors[element.id]" class="field-error">{{ elementVideoErrors[element.id] }}</p>
                      <div v-if="isEmbedLink(element.url)" class="offer-field">
                        <span>Poster (optional)</span>
                        <ImageUploadField
                          v-model="element.poster"
                          :ratios="1.7777777778"
                          :uploader="uploadPageImage"
                          label="Upload poster"
                          alt="Video poster preview"
                        />
                        <small class="field-note">Vimeo has no automatic thumbnail, and YouTube picks its own frame — set one to control what people see before they press play.</small>
                      </div>
                      <label class="offer-field">
                        <span>Shape</span>
                        <select v-model.number="element.aspect">
                          <option v-for="o in videoShapes" :key="o.value" :value="o.value">{{ o.label }}</option>
                        </select>
                        <small class="field-note">{{ isEmbedLink(element.url)
                          ? "A linked video's shape cannot be detected — pick the one it was filmed in."
                          : "Set automatically when you upload a file; change it if you want a different frame." }}</small>
                      </label>
                      <label class="offer-field">
                        <span>Caption (optional)</span>
                        <input v-model.trim="element.caption" type="text" placeholder="e.g. A two-minute walkthrough" />
                      </label>
                      <p v-if="!element.url" class="field-warning">
                        Add a video — this element will not render until it has one.
                      </p>
                    </template>
                    <template v-else-if="element.type === 'before_after'">
                      <label class="offer-field">
                        <span>Heading (optional)</span>
                        <input v-model.trim="element.heading" type="text" placeholder="e.g. The difference one visit makes" />
                      </label>
                      <label class="offer-field">
                        <span>Shape</span>
                        <select v-model.number="element.ratio" @change="resetBeforeAfterCrops(element)">
                          <option v-for="r in beforeAfterShapes" :key="r.value" :value="r.value">{{ r.label }}</option>
                        </select>
                        <small class="field-note">Both photos are cropped to this shape — that is what makes the slider line up.</small>
                      </label>
                      <div class="offer-two-column">
                        <div class="offer-field">
                          <span>Before</span>
                          <ImageUploadField
                            v-model="element.before_url"
                            :crop="element.before_crop"
                            :ratios="element.ratio"
                            :uploader="uploadPageImage"
                            label="Upload before"
                            alt="Before image preview"
                            @update:crop="(rect) => (element.before_crop = rect)"
                          />
                          <input v-model.trim="element.before_label" type="text" placeholder="Before" />
                        </div>
                        <div class="offer-field">
                          <span>After</span>
                          <ImageUploadField
                            v-model="element.after_url"
                            :crop="element.after_crop"
                            :ratios="element.ratio"
                            :uploader="uploadPageImage"
                            label="Upload after"
                            alt="After image preview"
                            @update:crop="(rect) => (element.after_crop = rect)"
                          />
                          <input v-model.trim="element.after_label" type="text" placeholder="After" />
                        </div>
                      </div>
                      <label class="offer-field">
                        <span>Slider starts at {{ element.start }}%</span>
                        <input v-model.number="element.start" type="range" min="0" max="100" step="5" />
                        <small class="field-note">Where the divider sits before anyone touches it — and where it stays if scripts are blocked.</small>
                      </label>
                      <p v-if="!element.before_url || !element.after_url" class="field-warning">
                        Both photos are needed — one image is not a comparison, so this element will not render yet.
                      </p>
                    </template>
                    <template v-else-if="element.type === 'numbered_list'">
                      <label class="offer-field">
                        <span>Heading</span>
                        <input v-model.trim="element.heading" type="text" placeholder="e.g. What's Inside The Course" />
                        <small class="field-note">**text** colours a phrase, ^^text^^ highlights it. Works for benefits or how-it-works steps — the heading decides which.</small>
                      </label>
                      <div v-for="(item, i) in element.items" :key="i" class="element-subrow">
                        <input v-model="element.items[i]" type="text" placeholder="One line — a benefit, or a step" />
                        <button class="danger-action compact" type="button" @click="removeSubItem(element, 'items', i)">Remove</button>
                      </div>
                      <button v-if="(element.items || []).length < 12" class="secondary-action compact" type="button" @click="addSubItem(element, 'items', '')">+ Add line</button>
                      <small v-else class="field-note">12 lines is the maximum.</small>
                    </template>

                    <template v-else-if="element.type === 'quote'">
                      <label class="offer-field">
                        <span>Title (optional)</span>
                        <input v-model.trim="element.title" type="text" placeholder="e.g. What Our Founder Says" />
                      </label>
                      <div class="selectable-price-image-controls" :class="{ 'has-image-preview': element.image_url }">
                        <div v-if="element.image_url" class="selectable-price-image-preview">
                          <img :src="element.image_url" alt="Quote image preview" />
                        </div>
                        <input :ref="(el) => setElementImageInput(element.id, el)" type="file" accept="image/*" hidden @change="handleElementImagePicked(element, $event, 'image_url')" />
                        <button class="secondary-action compact" type="button" :disabled="Boolean(blurbImageUploading[element.id])" @click.prevent="triggerElementImageUpload(element.id)">
                          {{ blurbImageUploading[element.id] ? "Uploading..." : "Upload image (optional)" }}
                        </button>
                      </div>
                      <label class="offer-field">
                        <span>Quote</span>
                        <textarea v-model.trim="element.text" rows="3" placeholder="A line worth pausing on — a principle, a maxim, your own words."></textarea>
                        <small class="field-note">For a customer vouching for the product, use Testimonials instead — a quote is styled so it does not read as an endorsement.</small>
                      </label>
                      <label class="offer-field">
                        <span>Attribution (optional)</span>
                        <input v-model.trim="element.attribution" type="text" placeholder="e.g. Seth Godin" />
                        <small class="field-note">The dash is added for you.</small>
                      </label>
                      <label class="builder-toggle">
                        <input type="checkbox" :checked="Boolean(element.theme && element.theme.bg)" @change="toggleSectionBreak(element, $event, 'accent')" />
                        <span>Break the page style for this section</span>
                      </label>
                      <div v-if="element.theme && element.theme.bg" class="offer-two-column">
                        <label class="offer-field">
                          <span>Background</span>
                          <input v-model.trim="element.theme.bg" type="color" />
                          <small class="field-note">Text colour is chosen automatically so it stays readable.</small>
                        </label>
                        <label class="offer-field">
                          <span>{{ element.style === "fancy" ? "Card" : "Bar" }}</span>
                          <input v-model.trim="element.theme.accent" type="color" />
                        </label>
                      </div>
                      <fieldset class="builder-choice">
                        <legend>Style</legend>
                        <label class="builder-choice-option">
                          <input v-model="element.style" type="radio" value="minimal" />
                          <span><strong>Minimalist</strong> — a bar and italic type, quiet inside body copy.</span>
                        </label>
                        <label class="builder-choice-option">
                          <input v-model="element.style" type="radio" value="fancy" />
                          <span><strong>Fancy</strong> — a coloured card with the image beside the quote.</span>
                        </label>
                      </fieldset>
                    </template>

                    <template v-else-if="element.type === 'bragging_points'">
                      <label class="offer-field">
                        <span>Section heading (optional)</span>
                        <input v-model.trim="element.heading" type="text" placeholder="e.g. By The Numbers" />
                      </label>
                      <div v-for="(item, i) in element.items" :key="i" class="element-subrow">
                        <input v-model.trim="item.value" type="text" placeholder="Value — e.g. $6M+, 12 yrs, Q-Media" />
                        <input v-model.trim="item.label" type="text" placeholder="What it counts — e.g. In sales" />
                        <button class="danger-action compact" type="button" @click="removeSubItem(element, 'items', i)">Remove</button>
                      </div>
                      <button class="secondary-action compact" type="button" @click="addSubItem(element, 'items', { value: '', label: '' })">+ Add point</button>
                      <small class="field-note">One card is full width, two sit side by side, three read 2 + 1.</small>
                      <label class="builder-toggle">
                        <input type="checkbox" :checked="Boolean(element.theme && element.theme.bg)" @change="toggleSectionBreak(element, $event, 'accent')" />
                        <span>Break the page style for this section</span>
                      </label>
                      <div v-if="element.theme && element.theme.bg" class="offer-two-column">
                        <label class="offer-field">
                          <span>Background</span>
                          <input v-model.trim="element.theme.bg" type="color" />
                          <small class="field-note">Text colour is chosen automatically so it stays readable.</small>
                        </label>
                        <label class="offer-field">
                          <span>Cards</span>
                          <input v-model.trim="element.theme.accent" type="color" />
                        </label>
                      </div>
                    </template>

                    <template v-else-if="element.type === 'author_bio'">
                      <ImageUploadField
                        v-model="element.photo_url"
                        :crop="element.image_crop"
                        :ratios="imageRatios.placement.author_bio"
                        :uploader="uploadPageImage"
                        label="Upload photo"
                        alt="Author photo preview"
                        @update:crop="(rect) => (element.image_crop = rect)"
                      />
                      <label class="offer-field"><span>Name</span><input v-model.trim="element.name" type="text" placeholder="e.g. Jordan Belfort" /></label>
                      <label class="offer-field">
                        <span>Credibility headline</span>
                        <input v-model.trim="element.headline" type="text" placeholder="Learn From Someone Who's Done **$6M+** In Sales" />
                        <small class="field-note">**text** colours a phrase, ^^text^^ highlights it.</small>
                      </label>
                      <label class="offer-field"><span>About</span><textarea v-model.trim="element.body" rows="4" placeholder="Why this person is worth listening to."></textarea></label>
                      <label class="builder-toggle">
                        <input type="checkbox" :checked="Boolean(element.theme && element.theme.bg)" @change="toggleSectionBreak(element, $event)" />
                        <span>Break the page style for this section</span>
                      </label>
                      <div v-if="element.theme && element.theme.bg" class="offer-two-column">
                        <label class="offer-field">
                          <span>Background</span>
                          <input v-model.trim="element.theme.bg" type="color" />
                          <small class="field-note">Text colour is chosen automatically so it stays readable.</small>
                        </label>
                        <label class="offer-field">
                          <span>Photo ring</span>
                          <input v-model.trim="element.theme.border" type="color" />
                        </label>
                      </div>
                    </template>

                    <template v-else-if="element.type === 'price_highlight'">
                      <p class="field-note">
                        The prices come from this offer's products — the sale price, and the regular price
                        struck through when one is set. A tiered product shows its lowest price as
                        <strong>as low as&hellip;</strong>, so the figure stays true whichever tier a visitor picks.
                      </p>
                      <label class="offer-field">
                        <span>Main text</span>
                        <input v-model.trim="element.main_text" type="text" placeholder="e.g. Today Only" />
                      </label>
                      <label class="offer-field">
                        <span>Subtext</span>
                        <input v-model.trim="element.subtext" type="text" placeholder="e.g. Lifetime Access" />
                      </label>
                    </template>

                    <template v-else-if="element.type === 'client_marquee'">
                      <input v-model.trim="element.heading" type="text" placeholder="Section heading (optional)" />
                      <div v-for="(logo, i) in element.logos" :key="i" class="element-subrow">
                        <input v-model.trim="logo.name" type="text" placeholder="Client name — shown as text when there is no logo" />
                        <div class="selectable-price-image-controls" :class="{ 'has-image-preview': logo.image_url }">
                          <div v-if="logo.image_url" class="selectable-price-image-preview"><img :src="logo.image_url" alt="Logo preview" /></div>
                          <input :ref="(el) => setSubImageInput(subImgKey(element, 'logos', i), el)" type="file" accept="image/*" hidden @change="handleSubImagePicked(logo, 'image_url', subImgKey(element, 'logos', i), $event)" />
                          <button class="secondary-action compact" type="button" :disabled="Boolean(subImageUploading[subImgKey(element, 'logos', i)])" @click.prevent="triggerSubImageUpload(subImgKey(element, 'logos', i))">
                            {{ subImageUploading[subImgKey(element, 'logos', i)] ? "Uploading..." : "Upload logo" }}
                          </button>
                          <input v-model.trim="logo.image_url" type="url" placeholder="or paste image URL" />
                        </div>
                        <div v-if="subImageErrors[subImgKey(element, 'logos', i)]" class="price-image-error">{{ subImageErrors[subImgKey(element, 'logos', i)] }}</div>
                        <button class="danger-action compact" type="button" @click="removeSubItem(element, 'logos', i)">Remove</button>
                      </div>
                      <button class="secondary-action compact" type="button" @click="addSubItem(element, 'logos', { image_url: '', name: '' })">+ Add logo</button>
                      <small class="field-note">A name alone is enough — it renders as a wordmark. Add a logo to show that instead. Transparent PNGs sit best on any theme.</small>
                      <div class="offer-two-column">
                        <label class="offer-field">
                          <span>Scrolling</span>
                          <select v-model="element.scroll">
                            <option value="auto">Auto — scrolls once there are 5 or more</option>
                            <option value="always">Always scroll</option>
                            <option value="never">Never scroll</option>
                          </select>
                        </label>
                        <label class="offer-field">
                          <span>Logo backing</span>
                          <select v-model="element.logo_backing">
                            <option value="card">Card — safe on any theme</option>
                            <option value="none">None — logos sit on the page</option>
                          </select>
                        </label>
                      </div>
                      <label v-if="element.scroll !== 'never'" class="offer-field">
                        <span>Scroll Speed</span>
                        <div class="builder-speed-row">
                          <span aria-hidden="true" title="Slower">&#128034;</span>
                          <input
                            :value="BRAND_MARQUEE_MIN + BRAND_MARQUEE_MAX - (Number(element.scroll_seconds) || 30)"
                            type="range"
                            :min="BRAND_MARQUEE_MIN"
                            :max="BRAND_MARQUEE_MAX"
                            step="1"
                            aria-label="Marquee scroll speed"
                            @input="element.scroll_seconds = BRAND_MARQUEE_MIN + BRAND_MARQUEE_MAX - Number($event.target.value)"
                          />
                          <span aria-hidden="true" title="Faster">&#128007;</span>
                        </div>
                      </label>
                    </template>

                    <template v-else-if="element.type === 'faq'">
                      <input :value="element.heading" type="text" placeholder="Section heading (optional)" @input="applyTitleCaseInput((value) => { element.heading = value; }, $event)" />
                      <div v-for="(item, i) in element.items" :key="i" class="element-subrow">
                        <input :value="item.question" type="text" placeholder="Question" @input="applyTitleCaseInput((value) => { item.question = value; }, $event)" />
                        <textarea v-model.trim="item.answer" rows="2" placeholder="Answer"></textarea>
                        <button class="danger-action compact" type="button" @click="removeSubItem(element, 'items', i)">Remove</button>
                      </div>
                      <button class="secondary-action compact" type="button" @click="addSubItem(element, 'items', { question: '', answer: '' })">+ Add question</button>
                    </template>

                    <template v-else-if="element.type === 'product_details'">
                      <p class="element-empty">Shows the current product's gallery, badges, and description — pulled from the offer and synced to the carousel. No configuration needed.</p>
                    </template>

                    <template v-else-if="element.type === 'social_links'">
                      <input v-model.trim="element.heading" type="text" placeholder="Section heading (optional)" />

                      <!-- INHERITING. The same override-or-inherit choice the page avatar has, shown the same
                           way: say which source is in force, and give one button to change it. The element
                           starts with no items, so a tenant who never opens this keeps the old behaviour. -->
                      <template v-if="!(element.items || []).length">
                        <p v-if="builderSiteProfiles.length" class="element-empty">
                          Showing {{ builderSiteProfiles.length }} profile{{ builderSiteProfiles.length === 1 ? "" : "s" }}
                          from <strong>{{ builderSiteName || "your Site" }}</strong>, so you enter them once instead
                          of on every page. Change them in <strong>Sites → edit your Site → Business identity</strong>.
                        </p>
                        <ul v-if="builderSiteProfiles.some((p) => linkClicksFor(p.url) !== null)" class="link-click-list">
                          <li v-for="p in builderSiteProfiles" :key="p.url">
                            <span>{{ p.url }}</span>
                            <strong>{{ linkClicksFor(p.url) ?? 0 }} ↗</strong>
                          </li>
                        </ul>
                        <p v-else class="element-empty is-warning">
                          <strong>No links yet, so this section shows nothing.</strong>
                          Add them to your Site's Business identity to reuse them on every page, or list them just
                          for this page below.
                        </p>
                        <button class="secondary-action compact" type="button" @click="element.items = [{ url: '' }]">
                          Use links just for this page
                        </button>
                      </template>

                      <!-- OVERRIDDEN. -->
                      <template v-else>
                        <div v-for="(item, i) in element.items" :key="i" class="element-subrow">
                          <input v-model.trim="item.url" type="url" placeholder="https://instagram.com/yourname" autocapitalize="off" spellcheck="false" />
                          <span v-if="linkClicksFor(item.url) !== null" class="link-click-count" :title="linkClicksFor(item.url) + ' people have tapped this link'">{{ linkClicksFor(item.url) }} ↗</span>
                          <button class="link-danger" type="button" @click="element.items.splice(i, 1)">Remove</button>
                        </div>
                        <button class="secondary-action compact" type="button" @click="element.items.push({ url: '' })">+ Add a link</button>
                        <button class="secondary-action compact" type="button" @click="element.items = []">Use my Site's profiles</button>
                        <p class="element-empty">
                          Any link works here — these are shown to visitors, not claimed as your identity, so they
                          never affect what search engines are told about who you are. Only profiles on your Site's
                          Business identity do that.
                          <template v-if="!builderSiteHasCustomDomain">
                            On your free platform address only well-known profile sites become tappable links —
                            anything else is shown but not clickable until you connect a custom domain.
                          </template>
                        </p>
                      </template>
                    </template>

                    <template v-else-if="element.type === 'link_cards'">
                      <input v-model.trim="element.heading" type="text" placeholder="Section heading (optional)" />
                      <div v-for="(item, i) in element.items" :key="i" class="element-subrow">
                        <input :value="item.label" type="text" placeholder="Card title — e.g. My Amazon storefront" @input="applyTitleCaseInput((value) => { item.label = value; }, $event)" />
                        <input v-model.trim="item.url" type="url" placeholder="https://…" autocapitalize="off" spellcheck="false" />
                        <span v-if="linkClicksFor(item.url) !== null" class="link-click-count" :title="linkClicksFor(item.url) + ' people have tapped this card'">{{ linkClicksFor(item.url) }} ↗</span>
                        <textarea v-model.trim="item.description" rows="2" placeholder="One line about it (optional)"></textarea>
                        <div class="selectable-price-image-controls" :class="{ 'has-image-preview': item.image_url }">
                          <div v-if="item.image_url" class="selectable-price-image-preview"><img :src="item.image_url" alt="Card image preview" /></div>
                          <input :ref="(el) => setSubImageInput(subImgKey(element, 'items', i), el)" type="file" accept="image/*" hidden @change="handleSubImagePicked(item, 'image_url', subImgKey(element, 'items', i), $event)" />
                          <button class="secondary-action compact" type="button" :disabled="Boolean(subImageUploading[subImgKey(element, 'items', i)])" @click.prevent="triggerSubImageUpload(subImgKey(element, 'items', i))">
                            {{ subImageUploading[subImgKey(element, 'items', i)] ? "Uploading..." : "Upload image" }}
                          </button>
                          <input v-model.trim="item.image_url" type="url" placeholder="or paste image URL" />
                        </div>
                        <div v-if="subImageErrors[subImgKey(element, 'items', i)]" class="price-image-error">{{ subImageErrors[subImgKey(element, 'items', i)] }}</div>
                        <button class="danger-action compact" type="button" @click="removeSubItem(element, 'items', i)">Remove</button>
                      </div>
                      <button class="secondary-action compact" type="button" @click="addSubItem(element, 'items', { url: '', label: '', description: '', image_url: '' })">+ Add link</button>
                      <p v-if="!onCustomDomainForLinks" class="element-empty">
                        On your free {{ hostingSuffixHint }} address only well-known destinations become tappable links —
                        the rest still appear, just not clickable. This protects everyone sharing that address from
                        one bad link. Connect your own domain and every destination becomes a real link.
                      </p>
                    </template>

                    <template v-else-if="element.type === 'related_products'">
                      <input v-model.trim="element.heading" type="text" placeholder="Section heading (optional)" />
                      <p class="element-empty">Automatically shows other Site pages in the same category as this one — a same-category rail for internal linking. It fills itself; there's nothing to pick.</p>
                    </template>

                </template>
              </template>
        </div>
        <footer class="section-editor-footer">
          <button class="secondary-action" type="button" @click="cancelSectionEditor">Cancel</button>
          <button v-if="sectionEditor.isNew" class="primary-action" type="button" @click="commitNewSection()">Add Section</button>
          <button v-else class="primary-action" type="button" @click="closeSectionEditor()">Done</button>
        </footer>
      </section>
    </div>
    <div v-if="ribbonPicker.element" class="modal-backdrop offer-selector-backdrop" @click.self="closeRibbonPagePicker">
      <section class="modal-card offer-product-selector-modal" role="dialog" aria-modal="true" aria-labelledby="ribbonPickerTitle">
        <header class="modal-card-header">
          <h2 id="ribbonPickerTitle">Choose a page to promote</h2>
          <button type="button" class="modal-close" aria-label="Close page picker" @click="closeRibbonPagePicker">×</button>
        </header>
        <div class="offer-product-selector-body">
          <input v-model.trim="ribbonPicker.search" class="offer-product-search" type="search" placeholder="Search pages..." />
          <div v-if="!ribbonPickerPages.length" class="selector-load-state">
            There are no published pages to choose from. Publish another landing page and it will appear here.
          </div>
          <div v-else class="selector-grid">
            <!-- overlay: the picture is the point here and the NAME is the disambiguator, since two pages
                 can promote the same product and look identical. -->
            <SelectorCard
              v-for="page in ribbonPickerPages"
              :key="page.page_id"
              :image="pageImage(page)"
              :title="page.name"
              fallback-title="Untitled page"
              :selected="ribbonPicker.element?.cta?.page_id === page.page_id"
              overlay
              @choose="chooseRibbonPage(page)"
            >
              <span class="selector-card-sub">{{ page.route?.slug ? "/" + String(page.route.slug).replace(/^\//, "") : "" }}</span>
            </SelectorCard>
          </div>
        </div>
        <footer class="modal-footer">
          <button class="secondary-action" type="button" @click="closeRibbonPagePicker">Cancel</button>
        </footer>
      </section>
    </div>
    <div v-if="wizardOpen" class="modal-backdrop" @click.self="closeWizard">
      <section class="modal-card landing-wizard-modal" role="dialog" aria-modal="true" aria-labelledby="landingWizardTitle">
        <header class="modal-card-header">
          <div>
            <h2 id="landingWizardTitle">{{ isEditingOfferless ? "Edit page" : "Create Landing Page" }}</h2>
            <p v-if="!isEditingOfferless">Step {{ displayStep }} of {{ displayTotal }}</p>
          </div>
          <button type="button" class="modal-close" aria-label="Close landing page wizard" @click="closeWizard">×</button>
        </header>

        <div v-if="!isEditingOfferless" class="wizard-progress" aria-hidden="true">
          <span v-for="step in displayTotal" :key="step" :class="{ active: step <= displayStep }"></span>
        </div>

        <div class="landing-wizard-body">
          <section v-if="sitePhase" class="wizard-step">
            <header class="wizard-step-header">
              <h3>Choose a Site</h3>
              <p>Which website will this page live under? A landing page belongs to one Site.</p>
            </header>
            <div v-if="sitesStore.sites.length" class="wizard-goal-list">
              <button
                v-for="s in sitesStore.sites"
                :key="s.site_id"
                type="button"
                class="wizard-goal-card"
                :class="{ selected: !siteCreateOpen && selectedSiteId === s.site_id }"
                @click="selectExistingSite(s.site_id)"
              >
                <strong>{{ s.name || s.site_id }}</strong>
                <span>{{ s.hosting?.custom_domain || s.hosting?.platform_hostname || "" }}</span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
              <button
                type="button"
                class="wizard-goal-card"
                :class="{ selected: siteCreateOpen }"
                @click="openInlineSiteCreate"
              >
                <strong>+ New Site</strong>
                <span>Create a new website to hold this page.</span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
            </div>
            <div v-if="siteCreateOpen || !sitesStore.sites.length" class="wizard-inline-site-create">
              <p v-if="!sitesStore.sites.length" class="field-note">You don't have a Site yet — create your first one to hold this page.</p>
              <label class="offer-field">
                <span>Site name</span>
                <input :value="newSiteName" type="text" placeholder="My Shop"
                       @input="applyTitleCaseInput((value) => { newSiteName = value; }, $event)" />
              </label>
              <StoreAddressField
                v-model="newSiteSubdomain"
                v-model:available="siteAvailable"
                v-model:normalized="siteNormalized"
                :name="newSiteName"
                :hosting-domain="sitesStore.hostingDomain || 'jbay.uk'"
                label="Store address"
                placeholder="my-shop"
              />
              <button type="button" class="secondary-action" :disabled="!canCreateInlineSite" @click="createInlineSite">
                {{ creatingSite ? "Creating…" : "Create Site" }}
              </button>
            </div>
            <p v-if="siteStepError" class="field-error">{{ siteStepError }}</p>
          </section>

          <section v-else-if="wizardStep === 1" class="wizard-step">
            <div class="wizard-goal-list">
              <button type="button" class="wizard-goal-card" :class="{ selected: form.pageKind === 'offer' }" @click="form.pageKind = 'offer'">
                <strong>Offer page</strong>
                <span>A landing page for a single offer — checkout or lead capture.</span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
              <button type="button" class="wizard-goal-card" :class="{ selected: form.pageKind === 'storefront' }" @click="form.pageKind = 'storefront'">
                <strong>Storefront homepage</strong>
                <span>A brand hero + a grid of your products, each linking to its page.</span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
              <button type="button" class="wizard-goal-card" :class="{ selected: form.pageKind === 'category' }" @click="selectCategoryKind">
                <strong>Category page</strong>
                <span>Lists every attached page in one category — fills itself as you add products.</span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
              <button type="button" class="wizard-goal-card" :class="{ selected: form.pageKind === 'profile' }" @click="form.pageKind = 'profile'">
                <strong>Store profile</strong>
                <span>An "about" page with your store's identity, contact, and catalog — builds trust and SEO.</span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
            </div>
            <template v-if="form.pageKind === 'offer'">
              <header class="wizard-step-header">
                <h3>Choose an Offer</h3>
                <p>The offer controls whether this flow is transaction checkout or lead generation.</p>
              </header>
              <input v-model.trim="offerSearch" class="landing-search full" type="search" placeholder="Search offers..." />
            <div v-if="offersLoading || productsLoading" class="selector-load-state">Loading offers...</div>
            <div v-else-if="!wizardOffers.length" class="selector-load-state">No offers found. Create an offer first.</div>
            <div v-else class="wizard-offer-list">
              <button
                v-for="offer in wizardOffers"
                :key="offer.offer_id"
                type="button"
                class="wizard-offer-card"
                :class="{ selected: form.offer_id === offer.offer_id }"
                @click="selectOffer(offer)"
              >
                <span class="wizard-offer-image">
                  <img v-if="offerImage(offer)" :src="offerImage(offer)" :alt="offer.name || 'Offer image'" />
                  <svg v-else fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12v7.5A1.5 1.5 0 0 1 18.5 21h-13A1.5 1.5 0 0 1 4 19.5V12m16 0H4m16 0h-4.5A3.5 3.5 0 0 0 19 8.5 2.5 2.5 0 0 0 14.5 7L12 12m-8 0h4.5A3.5 3.5 0 0 1 5 8.5 2.5 2.5 0 0 1 9.5 7L12 12m0 0v9" />
                  </svg>
                </span>
                <span>
                  <strong>{{ offer.name || "Untitled Offer" }}</strong>
                  <small>{{ offerIntentLabel(offer) }} · {{ offerItemCount(offer) }} item(s)</small>
                </span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
            </div>
            </template>
          </section>

          <section v-else-if="wizardStep === 2 && form.pageKind === 'storefront'" class="wizard-step">
            <header class="wizard-step-header">
              <h3>Build your storefront</h3>
              <p>Name your store, then pick which pages appear in the product grid.</p>
            </header>
            <p v-if="selectedSiteHomepageLabel" class="wizard-warning">
              ⚠ {{ selectedSite?.name }} already has a homepage ({{ selectedSiteHomepageLabel }}). Creating this will replace it as the “/” page; the old one stays live at its own slug.
            </p>
            <label class="offer-field">
              <span>Page name (internal)</span>
              <input v-model.trim="form.name" type="text" placeholder="Storefront homepage" />
            </label>
            <div class="offer-field">
              <span>Store name (shown as the headline)</span>
              <!-- Choose an existing brand OR a custom name — mutually exclusive. The toggle appears only when the
                   business has brands set up; with none, only the custom-name box shows. -->
              <div v-if="storeBrands.length" class="storefront-name-modes">
                <button type="button" class="storefront-name-mode" :class="{ active: storefrontNameMode === 'brand' }" @click="setStorefrontNameMode('brand')">Use a brand</button>
                <button type="button" class="storefront-name-mode" :class="{ active: storefrontNameMode === 'custom' }" @click="setStorefrontNameMode('custom')">Custom name</button>
              </div>
              <select v-if="storeBrands.length && storefrontNameMode === 'brand'" v-model="storefrontBrand">
                <option v-for="b in storeBrands" :key="b" :value="b">{{ b }}</option>
              </select>
              <input v-else v-model.trim="form.storefront.headline" type="text" placeholder="Your store name" />
              <small v-if="showDupNameWarning" class="storefront-dup-warning">
                ⚠ Another of your storefronts already uses “{{ duplicateStoreName }}”. You can still use it.
                <button type="button" class="link-btn" @click="dupNameDismissed = duplicateStoreName">Dismiss</button>
              </small>
            </div>
            <label class="offer-field">
              <span>Tagline (optional)</span>
              <input v-model.trim="form.storefront.tagline" type="text" placeholder="What your store is about" />
            </label>
            <div class="offer-field">
              <span>Logo (optional)</span>
              <div class="storefront-logo-field">
                <div class="storefront-logo-preview" :class="{ faux: !form.storefront.logo_url }">
                  <img v-if="form.storefront.logo_url" :src="form.storefront.logo_url" alt="Store logo preview" />
                  <svg v-else viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z" /></svg>
                </div>
                <div class="storefront-logo-actions">
                  <input ref="storefrontLogoInput" type="file" accept="image/*" class="visually-hidden" @change="onStorefrontLogoPicked" />
                  <button type="button" class="secondary-action compact" :disabled="storefrontLogoUploading" @click="$refs.storefrontLogoInput.click()">
                    {{ storefrontLogoUploading ? "Uploading…" : (form.storefront.logo_url ? "Replace logo" : "Upload logo") }}
                  </button>
                  <button v-if="form.storefront.logo_url" type="button" class="link-danger-btn" @click="form.storefront.logo_url = ''">Remove</button>
                  <small class="field-note">No logo? We'll show a clean placeholder mark.</small>
                  <small v-if="storefrontLogoError" class="field-error">{{ storefrontLogoError }}</small>
                </div>
              </div>
            </div>
            <label class="offer-field">
              <span>Grid heading (optional)</span>
              <input v-model.trim="form.storefront.heading" type="text" placeholder="Shop all" />
            </label>
            <div class="offer-field">
              <span>Products in the grid</span>
              <!-- Reuse: embed a collection that already exists on this Site instead of defining products here.
                   Only offered when the Site has collections to pick (plans/SITE_COLLECTIONS.md — reusable playlists). -->
              <div v-if="siteCollections.length" class="storefront-name-modes">
                <button type="button" class="storefront-name-mode" :class="{ active: form.storefront.source !== 'existing' }" @click="form.storefront.source = 'new'">Define products here</button>
                <button type="button" class="storefront-name-mode" :class="{ active: form.storefront.source === 'existing' }" @click="form.storefront.source = 'existing'">Use an existing collection</button>
              </div>
              <template v-if="form.storefront.source === 'existing'">
                <select v-model="form.storefront.existingCollectionId">
                  <option value="">Choose a collection…</option>
                  <option v-for="c in siteCollections" :key="c.collection_id" :value="c.collection_id">{{ c.name || c.collection_id }} · {{ collectionRuleLabel(c) }}</option>
                </select>
                <small class="field-note">This page shows that collection's products. Edit its contents on the Collections screen — changes apply everywhere the collection is used.</small>
              </template>
              <template v-else>
                <label class="builder-toggle"><input v-model="form.storefront.autoFill" type="checkbox" /><span>Show all my products automatically</span></label>
                <small v-if="form.storefront.autoFill" class="field-note">The grid fills itself with every offer page on this Site and stays current as you add more — you can create this homepage now with no offers yet.</small>
                <template v-else>
                  <div v-if="storefrontCandidatePages.length" class="storefront-page-picker">
                    <label v-for="page in storefrontCandidatePages" :key="page.page_id" class="storefront-page-option">
                      <input type="checkbox" :value="page.page_id" v-model="form.storefront.items" />
                      <span>{{ page.name || page.page_id }}<span v-if="page.status !== 'published'" class="page-picker-draft">draft</span></span>
                      <em>/{{ page.route?.slug || '' }} · <span class="page-picker-id">{{ page.page_id }}</span></em>
                    </label>
                  </div>
                  <small v-else>No products on this Site yet — attach an offer page to this Site (or turn on “Show all my products”). Only products on this Site can appear in the grid, so their cards link to real store pages.</small>
                </template>
              </template>
            </div>
          </section>

          <section v-else-if="wizardStep === 2 && form.pageKind === 'category'" class="wizard-step">
            <header class="wizard-step-header">
              <h3>Build a category page</h3>
              <p>Pick a category. The page lists every page you've attached to your Site in that category — new ones appear automatically.</p>
            </header>
            <label class="offer-field">
              <span>Category</span>
              <select v-model="form.categoryKey">
                <option value="">Choose a category…</option>
                <option v-for="c in storefrontCategories" :key="c.key" :value="c.key">{{ c.label }}</option>
              </select>
            </label>
            <label class="offer-field">
              <span>Page name (internal)</span>
              <input v-model.trim="form.name" type="text" :placeholder="categoryLabel(form.categoryKey) || 'Category page'" />
            </label>
            <label class="offer-field">
              <span>Heading (shown on the page)</span>
              <input v-model.trim="form.storefront.heading" type="text" :placeholder="categoryLabel(form.categoryKey) || 'Category'" />
            </label>
            <small v-if="!storefrontCategories.length">No product categories yet — add categories to your products first.</small>
          </section>

          <section v-else-if="wizardStep === 2 && form.pageKind === 'profile'" class="wizard-step">
            <header class="wizard-step-header">
              <h3>Store profile page</h3>
              <p>An "about" page. Its content — your store name, description, contact, catalog — comes from your Site's business profile, so keep that up to date on the Sites screen.</p>
            </header>
            <label class="offer-field">
              <span>Page name (internal)</span>
              <input v-model.trim="form.name" type="text" placeholder="About / Store profile" />
            </label>
            <label class="offer-field">
              <span>Heading (shown on the page)</span>
              <input v-model.trim="form.storefront.heading" type="text" placeholder="About our store" />
            </label>
          </section>

          <section v-else-if="wizardStep === 2" class="wizard-step">
            <header class="wizard-step-header">
              <h3>Page Goal</h3>
              <p>Where will this page's traffic come from? This decides what the page starts with — you can change any of it later.</p>
              <p class="field-note">This only sets what's <em>on</em> the page. Whether it appears in search is a Site-level setting (Sites → search visibility), not a per-page choice.</p>
            </header>
            <div class="wizard-goal-list">
              <button
                v-for="option in goalOptions"
                :key="option.value"
                type="button"
                class="wizard-goal-card"
                :class="{ selected: form.goal === option.value }"
                @click="form.goal = option.value"
              >
                <strong>{{ option.label }}</strong>
                <span>{{ option.note }}</span>
                <span v-if="goalSeedLabels(option.value).length" class="wizard-goal-adds">
                  Starts with: {{ goalSeedLabels(option.value).join(", ") }}
                </span>
                <span v-else class="wizard-goal-adds is-lean">Starts with the offer only</span>
                <span class="wizard-card-check" aria-hidden="true">✓</span>
              </button>
            </div>
          </section>

          <section v-else-if="wizardStep === 3" class="wizard-step">
            <header class="wizard-step-header">
              <h3>Configure Page</h3>
              <p>Pick a preset. The call-to-action is determined by the offer — the page just renders it.</p>
            </header>

            <div v-if="selectedOffer" class="wizard-selected-summary">
              <strong>{{ selectedOffer.name }}</strong>
              <span class="page-source-badge">{{ offerIntentLabel(selectedOffer) }}</span>
            </div>

            <div class="offer-two-column">
              <label class="offer-field">
                <span>Preset</span>
                <select v-model="form.preset">
                  <option v-for="option in presetOptions" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </label>
            </div>

            <div class="lead-action-summary">
              <strong>Call to action: {{ ctaTypeLabel(selectedOfferCta.type) }}</strong>
              <span>{{ ctaTypeDescription(selectedOfferCta.type) }}</span>
              <code v-if="selectedOfferCta.target">{{ selectedOfferCta.target }}</code>
            </div>
          </section>

          <section v-else class="wizard-step">
            <header class="wizard-step-header">
              <h3>Review Page</h3>
              <p>This creates the page document and lets the publishing pipeline render it.</p>
            </header>
            <div class="wizard-review-grid">
              <div><span>Offer</span><strong>{{ selectedOffer?.name || "None selected" }}</strong></div>
              <div><span>Intent</span><strong>{{ selectedOfferIntent === "lead_gen" ? "Lead generation" : "Transaction" }}</strong></div>
              <div><span>Goal</span><strong>{{ goalLabel(form.goal) || "Not set" }}</strong></div>
              <div><span>Template</span><strong>{{ selectedTemplateLabel }}</strong></div>
              <div><span>Preset</span><strong>{{ selectedPresetLabel }}</strong></div>
              <div><span>Page ID</span><strong>{{ form.page_id }}</strong></div>
              <div><span>Published path</span><strong>/{{ form.page_id }}/index.html</strong></div>
            </div>
            <!-- The composer decides the section list from offer_type x goal; show it before the builder opens. -->
            <div class="wizard-sections-summary">
              <span>Sections</span>
              <strong>{{ wizardSectionLabels.join(", ") }}</strong>
            </div>
            <details class="offer-json-preview">
              <summary>Generated page JSON</summary>
              <pre>{{ JSON.stringify(draftPage, null, 2) }}</pre>
            </details>
          </section>

          <div v-if="wizardError" class="keys-status-banner error">{{ wizardError }}</div>
        </div>

        <footer class="modal-footer">
          <template v-if="sitePhase">
            <button class="secondary-action" type="button" @click="closeWizard">Cancel</button>
            <button class="primary-action" type="button" :disabled="!canLeaveSiteStep" @click="leaveSiteStep">Next</button>
          </template>
          <template v-else>
          <button class="secondary-action" type="button" @click="backFromStep">
            {{ isEditingOfferless ? "Cancel" : "Back" }}
          </button>
          <template v-if="form.pageKind === 'storefront'">
            <button v-if="wizardStep === 1" class="primary-action" type="button" @click="nextWizardStep">Next</button>
            <button v-else class="primary-action" type="button" :disabled="creatingStorefront" @click="createStorefront">
              {{ creatingStorefront ? "Saving…" : isEditingOfferless ? "Save changes" : "Create storefront homepage" }}
            </button>
          </template>
          <template v-else-if="form.pageKind === 'category'">
            <button v-if="wizardStep === 1" class="primary-action" type="button" @click="nextWizardStep">Next</button>
            <button v-else class="primary-action" type="button" :disabled="creatingStorefront || !form.categoryKey" @click="createCategory">
              {{ creatingStorefront ? "Saving…" : isEditingOfferless ? "Save changes" : "Create category page" }}
            </button>
          </template>
          <template v-else-if="form.pageKind === 'profile'">
            <button v-if="wizardStep === 1" class="primary-action" type="button" @click="nextWizardStep">Next</button>
            <button v-else class="primary-action" type="button" :disabled="creatingStorefront" @click="createProfile">
              {{ creatingStorefront ? "Saving…" : isEditingOfferless ? "Save changes" : "Create store profile" }}
            </button>
          </template>
          <template v-else>
            <button v-if="wizardStep < 4" class="primary-action" type="button" @click="nextWizardStep">Next</button>
            <button v-else class="primary-action" type="button" @click="startBuilderFromWizard">
              Continue to Builder
            </button>
          </template>
          </template>
        </footer>
      </section>
    </div>

    <section v-if="builderOpen" class="landing-builder-shell" :class="[{ 'preview-only': builderFormHidden }, `preview-${previewDevice}`]">
      <article v-if="!builderFormHidden" class="dashboard-card landing-builder-form-card">
        <header class="dashboard-card-header landing-builder-header">
          <div>
            <h2>{{ builderExistingPageId ? "Edit Landing Page" : "Create Landing Page" }}</h2>
            <p>{{ builder.offerName || "Configure the page before saving." }}</p>
          </div>
          <button class="secondary-action compact" type="button" @click="toggleBuilderForm()">
            {{ builderFormHidden ? "Show Form" : "‹‹ Hide Form" }}
          </button>
        </header>

        <div v-if="error" class="keys-status-banner error landing-builder-status">
          <span>{{ error }}</span>
          <button type="button" class="status-banner-dismiss" aria-label="Dismiss" @click="error = ''">✕</button>
        </div>
        <div v-else-if="message" class="keys-status-banner landing-builder-status">
          <span>{{ message }}</span>
          <button type="button" class="status-banner-dismiss" aria-label="Dismiss" @click="message = ''">✕</button>
        </div>

        <div v-if="!builderFormHidden" class="landing-builder-body">
          <div v-if="isBuilderPublished" class="keys-status-banner warning">
            Published pages cannot be modified. Unpublish this page before editing.
          </div>






          <!-- Page Settings sits ABOVE Page Content, with a gear rather than a lock: it is not a section
               of the page at all, and putting it in the sequence would teach that list to mean two
               things. Same row/modal gesture, deliberately different placement and icon. -->
          <div class="page-settings-row">
            <span class="page-settings-icon" aria-hidden="true">⚙️</span>
            <span class="content-row-name">Page Settings</span>
            <span class="content-row-summary">Name, goal, appearance, SEO, analytics</span>
            <span v-if="builderPresetLabel" class="composition-tag is-preset">{{ builderPresetLabel }}</span>
            <button class="secondary-action compact" type="button" @click="pageSettingsOpen = true">Edit</button>
          </div>

          <!-- PAGE CONTENT — renders in page order, so the form reads exactly as the page does
               (plans/BUILDER_SECTION_ORDER.md). Fixed sections stay outside it: countdown and hero above,
               footer below, because their position never changes. -->
          <div class="content-sequence">
            <div class="content-sequence-head">
              <h3>Page Content</h3>
              <small v-if="hasCustomOrder">Your own order. Drag a section to move it.</small>
              <small v-else>Recommended order for this goal. Drag a section to move it.</small>
              <button v-if="hasCustomOrder" class="link-action" type="button" @click="resetSectionOrder()">
                Reset to recommended order
              </button>
            </div>
            <article
              v-for="(row, rowIndex) in sequenceRows"
              :key="row.key"
              class="content-section"
              :class="{ 'is-locked': !row.movable }"
              @dragover.prevent
              @drop="onRowDrop(rowIndex)"
            >
              <span
                v-if="row.movable && !isBuilderPublished"
                class="content-section-drag"
                draggable="true"
                title="Drag to reorder"
                @dragstart="onRowDragStart(rowIndex)"
              >⠿</span>
              <span v-else-if="row.movable" class="content-section-lock" title="Unpublish this page to reorder">🔒</span>
              <span v-else class="content-section-lock" title="Fixed position on the page">🔒</span>
              <span class="content-row-name">{{ row.label }}</span>
              <span class="content-row-summary">{{ rowSummary(row) }}</span>
              <button
                v-if="row.editor"
                class="secondary-action compact"
                type="button"
                :disabled="isBuilderPublished"
                :title="isBuilderPublished ? 'Unpublish this page to edit it' : undefined"
                @click="openSectionEditor(row)"
              >Edit</button>
              <button
                v-if="row.editor === 'element'"
                class="danger-action compact"
                type="button"
                :disabled="isBuilderPublished"
                :title="isBuilderPublished ? 'Unpublish this page to edit it' : undefined"
                @click="removeElement(row.element.id)"
              >Remove</button>
            </article>
            <div class="composition-subhead">Add content</div>
            <div class="element-add-row">
            <button
              v-for="entry in ELEMENT_TYPES"
              :key="entry.type"
              class="secondary-action compact"
              type="button"
              :disabled="isBuilderPublished || (entry.type === 'page_ribbon' && ribbonCount >= RIBBON_MAX)"
              :title="isBuilderPublished ? 'Unpublish this page to edit it' : (entry.type === 'page_ribbon' && ribbonCount >= RIBBON_MAX ? 'Two ribbons is the most a page should carry' : undefined)"
              @click="addElement(entry.type)">
            + {{ entry.label }}
            </button>
            </div>
            <p v-if="!builder.elements.length" class="element-empty">
            Add testimonials, ratings, content, client logos, or FAQs — drag to reorder.
            </p>
          </div>



          <!-- Same rule as the Page Sections toggle: no resolvable policy copy (e.g. service offers) = no control. -->


          <!-- SETTINGS — page-wide configuration with no position on the page, so it lives BELOW the
               content sequence instead of interleaved with it (plans/BUILDER_SECTION_ORDER.md §2). -->
          <div class="builder-settings-head">
            <h3>Settings</h3>
            <small>Page-wide options. These do not appear as sections on the page.</small>
          </div>
          <section v-if="builderIntent === 'transaction'" class="builder-section">
            <h3>Sale &amp; Flash Sale</h3>
            <p>Publish <code>/sale</code> and <code>/flash-sale</code> views of this page that show your discounted pricing. Add the matching price to the product first (Products → pricing context).</p>
            <label class="builder-toggle">
              <input v-model="builder.sale.enabled" type="checkbox" @change="warnIfMissingPriceContext('sale')" />
              <span>Enable Sale (<code>/sale</code>)</span>
            </label>
            <div v-if="builder.sale.enabled" class="builder-sale-options">
              <p v-if="!offerHasPriceContext('sale')" class="field-error">This product doesn't have a Sale pricing context. Please go to the products page and set it there.</p>
              <label class="offer-field">
                <span>Expiration (optional — leave blank for a perpetual sale)</span>
                <input v-model="saleEndsAtLocal" type="datetime-local" />
              </label>
            </div>
            <label class="builder-toggle">
              <input v-model="builder.flash_sale.enabled" type="checkbox" @change="warnIfMissingPriceContext('flash_sale')" />
              <span>Enable Flash Sale (<code>/flash-sale</code>)</span>
            </label>
            <div v-if="builder.flash_sale.enabled" class="builder-sale-options">
              <p v-if="!offerHasPriceContext('flash_sale')" class="field-error">This product doesn't have a Flash Sale pricing context. Please go to the products page and set it there.</p>
              <div class="offer-two-column">
                <label class="offer-field">
                  <span>Starts (optional)</span>
                  <input v-model="flashStartsOnLocal" type="datetime-local" />
                </label>
                <label class="offer-field">
                  <span>Ends (required)</span>
                  <input v-model="flashEndsAtLocal" type="datetime-local" />
                </label>
              </div>
              <p v-if="!builder.flash_sale.ends_at" class="field-error">You must set an expiration date in order to enable this feature.</p>
              <p v-else-if="builder.flash_sale.starts_on && builder.flash_sale.starts_on >= builder.flash_sale.ends_at" class="field-error">The start date must be before the end date.</p>
            </div>
          </section>
          <section class="builder-section">
            <header class="builder-section-title">
              <h3>Page Sections</h3>
            </header>
            <small>Everything that goes on the page, in one place. Recommended sections for a {{ builderOfferType }} page are on by default; toggle optional ones or add content blocks — preview and published stay in sync.</small>
            <div class="composition-list">
              <label v-for="key in togglableSections" :key="key" class="composition-row">
                <input type="checkbox" :checked="isSectionEnabled(key)" @change="toggleSection(key, $event.target.checked)" />
                <span class="composition-name">{{ sectionKeyLabel(key) }}</span>
                <span class="composition-tag" :class="defaultVisible(builderOfferType, key, builderGoal) ? 'is-recommended' : 'is-optional'">
                  {{ defaultVisible(builderOfferType, key, builderGoal) ? "Recommended" : "Optional" }}
                </span>
              </label>
            </div>

          </section>

          <!-- Discoverability: the sections that render to <head> / their own artifact rather than to the
               page. Collapsed and out of the way because there is nothing to fill in — the output is DERIVED
               from the offer and the composed sections ("SEO" is a mode the goal flips on, not a form).
               plans/LANDING_PAGE_GOAL_COMPOSITION.md -->




          <section v-if="builderIntent === 'transaction'" class="builder-section">
            <div class="builder-section-title">
              <h3>Post-Checkout Flow</h3>
              <button type="button" class="secondary-action compact" @click="showPurchaseFlow = true">View purchase flow</button>
            </div>
            <p>Configure the pages customers see after checkout. Open a step to edit it — the Live Preview switches to that page. Leave a field blank to use the default (shown as the placeholder). Put <code>{{ PRICE_TOKEN }}</code> in a button label to insert that product's price.</p>

            <div class="funnel-accordion">
              <div v-for="step in funnelSteps" :key="step.key" class="funnel-acc-item" :class="{ open: openFunnelStep === step.key }">
                <button type="button" class="funnel-acc-head" @click="toggleFunnelStep(step.key)">
                  <span class="funnel-acc-caret">{{ openFunnelStep === step.key ? "▾" : "▸" }}</span>
                  <span class="funnel-acc-num" :class="step.kind">{{ step.num }}</span>
                  <span class="funnel-acc-label">{{ step.label }}</span>
                  <span class="funnel-acc-hint">{{ openFunnelStep === step.key ? "Previewing" : "" }}</span>
                </button>

                <div v-if="openFunnelStep === step.key" class="funnel-acc-body">
                  <!-- Thank-you page -->
                  <template v-if="step.kind === 'thank_you'">
                    <div class="ty-field-row">
                      <label class="offer-field ty-emoji"><span>Emoji</span>
                        <input v-model.trim="builder.post_purchase.thank_you.headline_icon" type="text" maxlength="4" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_headline_icon" /></label>
                      <label class="offer-field"><span>Headline</span>
                        <input v-model.trim="builder.post_purchase.thank_you.headline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_headline" /></label>
                    </div>
                    <label class="offer-field"><span>Subheadline</span>
                      <input v-model.trim="builder.post_purchase.thank_you.subheadline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_subheadline" /></label>
                    <label class="offer-field"><span>Message</span>
                      <textarea v-model.trim="builder.post_purchase.thank_you.message" rows="2" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_message"></textarea></label>
                    <label class="builder-toggle"><input v-model="builder.post_purchase.thank_you.enable_celebration" type="checkbox" /><span>Show the celebration animation</span></label>

                    <label class="builder-toggle"><input v-model="builder.post_purchase.thank_you.enable_next_steps" type="checkbox" /><span>Show a “What’s Next?” section</span></label>
                    <template v-if="builder.post_purchase.thank_you.enable_next_steps">
                      <label class="offer-field"><span>Section title</span>
                        <input v-model.trim="builder.post_purchase.thank_you.next_steps_title" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_next_steps_title" /></label>
                      <div v-for="(card, i) in builder.post_purchase.thank_you.next_steps" :key="i" class="ty-card-editor">
                        <div class="ty-field-row">
                          <label class="offer-field ty-emoji"><span>Icon</span><input v-model.trim="card.icon" type="text" maxlength="4" placeholder="📧" /></label>
                          <label class="offer-field"><span>Card title</span><input v-model.trim="card.title" type="text" placeholder="Check Your Email" /></label>
                          <button type="button" class="ty-card-remove" title="Remove card" @click="removeNextStepCard(i)">✕</button>
                        </div>
                        <label class="offer-field"><span>Card text</span><input v-model.trim="card.desc" type="text" placeholder="Confirmation and tracking details…" /></label>
                      </div>
                      <button v-if="builder.post_purchase.thank_you.next_steps.length < 6" type="button" class="secondary-action compact" @click="addNextStepCard">+ Add card</button>
                    </template>

                    <label class="builder-toggle"><input v-model="builder.post_purchase.thank_you.enable_footer" type="checkbox" /><span>Show a footer message</span></label>
                    <template v-if="builder.post_purchase.thank_you.enable_footer">
                      <label class="offer-field"><span>Footer headline</span>
                        <input v-model.trim="builder.post_purchase.thank_you.footer_headline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_footer_headline" /></label>
                      <label class="offer-field"><span>Footer message</span>
                        <input v-model.trim="builder.post_purchase.thank_you.footer_message" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_footer_message" /></label>
                    </template>

                    <label class="builder-toggle"><input v-model="builder.post_purchase.thank_you.show_home_button" type="checkbox" /><span>Show a “Back to Home” link</span></label>
                    <label v-if="builder.post_purchase.thank_you.show_home_button" class="offer-field"><span>Home link text</span>
                      <input v-model.trim="builder.post_purchase.thank_you.home_button_text" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_home_button_text" /></label>

                    <label class="builder-toggle"><input v-model="builder.post_purchase.thank_you.enable_download" type="checkbox" /><span>Show a download button</span></label>
                    <template v-if="builder.post_purchase.thank_you.enable_download">
                      <label class="offer-field"><span>Download URL</span>
                        <input v-model.trim="builder.post_purchase.thank_you.download_url" type="url" placeholder="https://…" /></label>
                      <label class="offer-field"><span>Download button text</span>
                        <input v-model.trim="builder.post_purchase.thank_you.download_button_text" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.ty_download_button_text" /></label>
                    </template>
                  </template>

                  <!-- Sequential upsell page (copy shared across upsell steps) -->
                  <template v-else-if="step.kind === 'upsell'">
                    <small v-if="funnelUpsellCount > 1" class="funnel-shared-note">This copy is shared across all upsell steps; each step previews its own product.</small>
                    <label class="offer-field"><span>Headline</span>
                      <input v-model.trim="builder.post_purchase.upsell.headline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.headline" /></label>
                    <label class="offer-field"><span>Subheadline</span>
                      <input v-model.trim="builder.post_purchase.upsell.subheadline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.subheadline" /></label>
                    <label class="offer-field"><span>Accept button</span>
                      <input v-model.trim="builder.post_purchase.upsell.accept_label" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.accept_label" /></label>
                    <label class="offer-field"><span>Decline link</span>
                      <input v-model.trim="builder.post_purchase.upsell.decline_label" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.decline_label" /></label>
                    <label class="offer-field"><span>Price label (above the price)</span>
                      <input v-model.trim="builder.post_purchase.upsell.price_label" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.price_label" /></label>
                    <label v-if="funnelDownsellCount" class="offer-field"><span>Downsell headline (shown in-place on decline)</span>
                      <input v-model.trim="builder.post_purchase.upsell.downsell_headline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.downsell_headline" /></label>
                    <label v-if="funnelDownsellCount" class="offer-field"><span>Downsell note (above the button, last chance)</span>
                      <input v-model.trim="builder.post_purchase.upsell.downsell_note" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.downsell_note" /></label>
                    <label class="builder-toggle"><input v-model="builder.post_purchase.upsell.savings_badge" type="checkbox" /><span>Show a savings badge</span></label>
                    <label class="builder-toggle"><input v-model="builder.post_purchase.upsell.countdown_enabled" type="checkbox" /><span>Show a countdown timer</span></label>
                    <label v-if="builder.post_purchase.upsell.countdown_enabled" class="offer-field"><span>Countdown minutes</span>
                      <input v-model.number="builder.post_purchase.upsell.countdown_minutes" type="number" min="1" max="60" /></label>
                  </template>

                  <!-- Carousel screen (4+ upsells) -->
                  <template v-else-if="step.kind === 'carousel'">
                    <label class="offer-field"><span>Headline</span>
                      <input v-model.trim="builder.post_purchase.upsell.carousel_headline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.carousel_headline" /></label>
                    <label class="offer-field"><span>Subheadline</span>
                      <input v-model.trim="builder.post_purchase.upsell.carousel_subheadline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.carousel_subheadline" /></label>
                    <label class="offer-field"><span>Add button</span>
                      <input v-model.trim="builder.post_purchase.upsell.carousel_add_label" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.carousel_add_label" /></label>
                    <label class="offer-field"><span>Dismiss link</span>
                      <input v-model.trim="builder.post_purchase.upsell.carousel_dismiss_label" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.carousel_dismiss_label" /></label>
                    <label class="offer-field"><span>Proceed link (after adding any)</span>
                      <input v-model.trim="builder.post_purchase.upsell.carousel_proceed_label" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.carousel_proceed_label" /></label>
                    <label class="offer-field"><span>Downsell carousel headline</span>
                      <input v-model.trim="builder.post_purchase.upsell.downsell_carousel_headline" type="text" :placeholder="SCAFFOLD_PLACEHOLDERS.downsell_carousel_headline" /></label>
                  </template>
                </div>
              </div>
            </div>
            <small v-if="!hasPostPurchaseFunnel" class="funnel-shared-note">Add upsell or downsell products to this offer (Offers → the funnel) to add one-click upsell steps.</small>
          </section>

          <section class="builder-section">
            <h3>Generated Page JSON</h3>
            <pre class="builder-json">{{ JSON.stringify(builderPageDocument, null, 2) }}</pre>
          </section>
        </div>

        <footer v-if="!builderFormHidden" class="landing-builder-footer">
          <button class="secondary-action" type="button" @click="backToList">Cancel</button>
          <button class="primary-action" type="button" :disabled="saving || isBuilderPublished" @click="saveBuilderPage">
            {{ saving ? "Saving..." : "Save Page" }}
          </button>
          <button
            class="primary-action publish-action"
            :class="{ unpublished: isBuilderPublished }"
            type="button"
            :disabled="saving"
            @click="toggleBuilderPublished"
          >
            {{ saving ? (isBuilderPublished ? "Unpublishing..." : "Publishing...") : (isBuilderPublished ? "Unpublish" : "Publish") }}
          </button>
        </footer>
      </article>

      <article class="dashboard-card landing-builder-preview-card">
        <header class="dashboard-card-header landing-builder-preview-header">
          <h2>Live Preview</h2>
          <div class="preview-header-actions">
            <!-- Which page the preview is showing: the landing page, or a Post-Checkout Flow step. -->
            <div v-if="openFunnelStep" class="preview-funnel-badge">
              <span>{{ activeFunnelStepLabel }}</span>
              <button type="button" title="Back to the landing page" @click="openFunnelStep = null">✕</button>
            </div>
            <button v-if="builderFormHidden" class="secondary-action compact" type="button" @click="showBuilderForm()">
              Show Form
            </button>
            <div v-if="previewContextOptions.length > 1" class="preview-device-controls" aria-label="Preview pricing view">
              <button
                v-for="opt in previewContextOptions"
                :key="opt.value"
                type="button"
                :class="{ active: previewContext === opt.value }"
                @click="previewContext = opt.value"
              >{{ opt.label }}</button>
            </div>
            <div class="preview-device-controls" aria-label="Preview device">
              <!-- Icons, not words: the monitor/phone pair is universally understood, and the labels were the
                   widest thing in this header. aria-label carries the meaning for screen readers. -->
              <button
                type="button"
                class="preview-device-btn"
                :class="{ active: previewDevice === 'desktop' }"
                aria-label="Desktop preview"
                title="Desktop — hides the form to give the preview a real desktop width"
                @click="setPreviewDevice('desktop')"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <rect x="2.5" y="4" width="19" height="12.5" rx="1.5" />
                  <path d="M8.5 20h7M12 16.5V20" />
                </svg>
              </button>
              <button
                type="button"
                class="preview-device-btn"
                :class="{ active: previewDevice === 'mobile' }"
                aria-label="Mobile preview"
                title="Mobile"
                @click="setPreviewDevice('mobile')"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <rect x="6.5" y="2.5" width="11" height="19" rx="2" />
                  <path d="M10.75 18.5h2.5" />
                </svg>
              </button>
            </div>
          </div>
        </header>
        <!-- Shareable test link for the previewed view. Appears once the page is published (it then has a
             snowflake short_code); the URL tracks the Standard/Sale/Flash-Sale toggle. -->
        <div ref="previewPane" class="landing-builder-preview-body">
        <div v-if="testShareLink" class="preview-share-link">
          <span class="preview-share-label">Test link</span>
          <input type="text" readonly :value="testShareLink" @focus="$event.target.select()" />
          <button type="button" @click="copyTestShareLink">{{ testLinkCopied ? "Copied" : "Copy" }}</button>
        </div>
        <!-- The Live Preview IS the published renderer. We POST the draft page document to
             /pages/render, which runs the same runtime/html.py render_page() that publishes the page,
             and show the returned HTML here. One JSON, one renderer, two consumers (this iframe and the
             published artifact) — there is no second implementation left to drift out of sync. -->
        <div v-if="previewError" class="preview-render-error">{{ previewError }}</div>
        <!-- A Sale / Flash Sale view renders as Standard when no product carries that price context
             (html.py _offer_has_price_context). Silently showing the standard page under a "Flash Sale"
             tab reads as a missing banner, so say why. -->
        <p v-if="previewContextUnavailable" class="preview-context-note">
          No {{ previewContextUnavailable }} price on this offer, so the preview falls back to Standard —
          and the banner won't show. Add one under Products → pricing context.
        </p>
        <!-- Quality-baseline nudges on the rendered page (heading outline; a11y/CLS later). Never blocks
             publishing — the outline is correct by construction, so this usually stays hidden and only
             appears if something regresses. plans/SEMANTIC_HTML.md -->
        <!-- The preview resolves the Site this page WILL attach to, so it shows the profiles and the brand a
             visitor would see once it is attached. Until then the saved page has neither. Say so here, beside
             the thing that is telling the comforting half of the truth, rather than leaving the tenant to
             discover it after publishing (reported 2026-09-10: glyphs in the preview, nothing on the page). -->
        <div v-if="previewNeedsSite" class="page-health-warnings is-blocking">
          <strong>Not attached to a Site yet</strong>
          <p>
            This preview is showing the brand and social profiles from
            <strong>{{ builderSiteName || "your Site" }}</strong>, but the page is not attached to it. A link
            page gets both from its Site, so publishing now would put out an empty page. Save the page and
            attach it to a Site — everything you see here comes with it.
          </p>
        </div>
        <div v-if="pageHealthWarnings.length" class="page-health-warnings">
          <strong>Page health</strong>
          <ul>
            <li v-for="(warning, i) in pageHealthWarnings" :key="i">{{ warning }}</li>
          </ul>
        </div>
        <iframe
          v-show="previewHtml"
          ref="previewFrame"
          class="landing-live-preview-frame"
          :class="previewDevice"
          :srcdoc="previewHtml"
          title="Live preview"
          sandbox="allow-scripts allow-same-origin"
          @load="restorePreviewScroll"
        ></iframe>
        <p v-if="!previewHtml && !previewError" class="landing-live-preview-status">
          {{ builder.offer_id ? "Rendering preview..." : "Select an offer to see the preview." }}
        </p>
        <!-- Hidden probe: Advanced Color Settings reads the active preset's effective --preview-* values
             off this element to seed its pickers. It carries the preset classes and nothing else. -->
        <div ref="previewEl" class="landing-live-preview preview-token-probe" :class="[builder.preset]" :style="previewTokenStyle" aria-hidden="true"></div>
        </div>
      </article>
    </section>

    <div v-if="selectedPageDetails" class="modal-backdrop" @click.self="selectedPageDetails = null">
      <section class="modal-card offer-details-modal" role="dialog" aria-modal="true" aria-labelledby="pageDetailsTitle">
        <header class="modal-card-header">
          <h2 id="pageDetailsTitle">{{ selectedPageDetails.name }}</h2>
          <button type="button" class="modal-close" aria-label="Close page details" @click="selectedPageDetails = null">×</button>
        </header>
        <div class="offer-details-body">
          <pre>{{ JSON.stringify(selectedPageDetails, null, 2) }}</pre>
        </div>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingArchivePage"
      danger
      :title="pendingArchivePage?.status === 'published' ? 'Archive page?' : 'Delete page?'"
      :confirm-label="pendingArchivePage?.status === 'published' ? 'Archive' : 'Delete'"
      :busy="saving"
      @cancel="pendingArchivePage = null"
      @confirm="removePage"
    >
      {{ pendingArchivePage?.status === "published" ? "Archive" : "Delete" }} "{{ pendingArchivePage?.name || "this landing page" }}"?
      <template v-if="siteForPage(pendingArchivePage)"> It will first be detached from {{ siteForPage(pendingArchivePage)?.name }}.</template>
    </ConfirmDialog>

    <ConfirmDialog
      :open="!!pendingDetachPage"
      :title="'Detach from ' + (siteForPage(pendingDetachPage)?.name || 'its Site') + '?'"
      confirm-label="Detach"
      :busy="saving"
      @cancel="pendingDetachPage = null"
      @confirm="detachSite"
    >
      "{{ pendingDetachPage?.name || "This page" }}" will stop serving under {{ siteForPage(pendingDetachPage)?.name || "the Site" }} (and its custom domain, if published). The page itself is kept — you can attach it to another Site.
    </ConfirmDialog>

    <ConfirmDialog
      :open="!!copyPlan"
      :danger="!!copyPlan?.existingTarget"
      :title="(copyPlan?.existingTarget ? 'Replace in ' : 'Copy to ') + targetEnvLabel + '?'"
      :confirm-label="(copyPlan?.existingTarget ? 'Replace in ' : 'Copy to ') + targetEnvLabel"
      :busy="copyBusy"
      @cancel="copyPlan = null"
      @confirm="executeCopy"
    >
      <template v-if="copyPlan">
        Copies <strong>{{ copyPlan.page.name }}</strong>{{ copyPlan.offerDocs.length ? ` plus its offer and ${copyPlan.productDocs.length} product${copyPlan.productDocs.length === 1 ? '' : 's'}` : '' }} to {{ targetEnvLabel }} (same IDs).
        <template v-if="copyPlan.existingTarget">
          <br><strong class="copy-replace-warning">⚠ This replaces the existing {{ targetEnvLabel }} page{{ copyPlan.offerDocs.length ? ' and its catalog' : '' }} and cannot be undone.</strong>
          <template v-if="copyPlan.existingTarget.status === 'published'"> The {{ targetEnvLabel }} page stays published; its content is overwritten.</template>
          <template v-else> The existing {{ targetEnvLabel }} page (currently {{ copyPlan.existingTarget.status }}) is overwritten.</template>
        </template>
        <template v-else> It lands as a new draft in {{ targetEnvLabel }}, unattached to any Site.</template>
        <template v-if="copyPlan.hasServices"> Note: this offer includes services, which aren't copied — set them up in {{ targetEnvLabel }}.</template>
        <template v-if="copyError"><br><span class="field-error">{{ copyError }}</span></template>
      </template>
    </ConfirmDialog>

    <div v-if="attachTarget" class="modal-backdrop" @click.self="attachTarget = null">
      <section class="modal-card attach-site-modal" role="dialog" aria-modal="true">
        <header class="modal-card-header">
          <h2>Attach to a Site</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="attachTarget = null">×</button>
        </header>
        <div class="modal-card-body">
          <p class="field-note">Choose which Site "{{ attachTarget.name || "this page" }}" should live under. It attaches at its own slug (a storefront homepage takes the “/” root).</p>
          <label v-if="sitesStore.sites.length" class="offer-field">
            <span>Site</span>
            <select v-model="attachSiteId">
              <option v-for="s in sitesStore.sites" :key="s.site_id" :value="s.site_id">{{ s.name || s.site_id }}</option>
            </select>
          </label>
          <p v-else class="field-note">You don't have any Sites yet — create one on the Sites screen first.</p>
        </div>
        <footer class="modal-footer">
          <button type="button" class="secondary-action" @click="attachTarget = null">Cancel</button>
          <button type="button" class="primary-action" :disabled="!attachSiteId" @click="confirmAttachSite">Attach</button>
        </footer>
      </section>
    </div>

    <!-- Read-only purchase-flow reference (same diagram as the Offer editor), from the current offer. -->
    <div v-if="showPurchaseFlow" class="modal-backdrop" @click.self="showPurchaseFlow = false">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="purchaseFlowTitle">
        <header class="modal-card-header">
          <h2 id="purchaseFlowTitle">Purchase Flow</h2>
          <button type="button" class="modal-close" aria-label="Close purchase flow" @click="showPurchaseFlow = false">×</button>
        </header>
        <div class="modal-card-body">
          <p class="funnel-shared-note">Read-only. Every step is inferred from this offer's products and their pricing contexts (set in Products → pricing context). Configure it in the offer.</p>
          <PurchaseFlowDiagram :offer-name="builderOffer?.name || builder.offerName" :stages="funnelFlowStages" />
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from "vue";
import SelectorCard from "./SelectorCard.vue";
import ImageUploadField from "./shared/ImageUploadField.vue";
import imageRatios from "../../../src/stripe_link/image_ratios.json";
import { offerViewTargets, offerViewTargetsFromExpanded } from "../composables/useConversionContext";
import { isSectionVisible, defaultVisible, excludedSections, recommendedSectionKeys, optionalSectionKeys, governedKeys, elementLabel, elementChannel, addableElements, tokenGroups, previewVar, supportedGoals, goalLabel, packSeeds, orderSections, sectionOrderKey, isMovable, elementPlacement, orderSectionKeys, isRepeatableSection } from "../composables/pageComposer";
import { apiRequest, assetUrl, getApiBase, getAuthSession, getStripeMode, getOtherEnvironment, getPagesBaseUrl, getPreviewPagesBaseUrl, getTestPagesHost, getTenantId } from "../api/client";
import { useToastsStore } from "../stores/toasts";
import { formatMoney } from "../stores/products";
import PurchaseFlowDiagram from "./PurchaseFlowDiagram.vue";
import { useProfileStore } from "../stores/profile";
import { useSitesStore } from "../stores/sites";
import { searchableItemText } from "../composables/offerItems";
import { filterRows } from "../composables/indexedList";
import { stagesFromSavedOffer } from "../composables/purchaseFlow";
import { useCollectionsStore } from "../stores/collections";
import SettingsAccordion from "./shared/SettingsAccordion.vue";
import MediaListField from "./shared/MediaListField.vue";
import StoreAddressField from "./StoreAddressField.vue";
import { resolvePageDeps, copyCatalogToEnv, pageForTarget } from "../composables/environmentCopy";
import { idColorStyle } from "../utils/iconColor";
import { uploadImage, uploadVideo } from "../api/uploads";
import { recordImageDims } from "../utils/imageDims";
import { showIconPicker } from "../icon-picker.js";
import { applyTitleCaseInput, formatHeadline } from "../utils/titleCase.js";
import ConfirmDialog from "./shared/ConfirmDialog.vue";

const pages = ref([]);
const offers = ref([]);
const profileStore = useProfileStore();
const sitesStore = useSitesStore();
const collectionsStore = useCollectionsStore();
const toasts = useToastsStore();

// Step 0 of the create wizard: which Site will this page live under (a page belongs to one Site). Skipped
// when editing an existing offer-less page. `pendingSiteAttach` carries the chosen Site into the offer
// builder, whose page is created later (on Save) rather than in the wizard.
const sitePhase = ref(false);
const selectedSiteId = ref("");
const pendingSiteAttach = ref("");
const siteStepError = ref("");
const siteCreateOpen = ref(false);
const newSiteName = ref("");
const newSiteSubdomain = ref("");
const creatingSite = ref(false);
// Store-address availability + canonical value are owned by the StoreAddressField component and surfaced here.
const siteAvailable = ref(false);
const siteNormalized = ref("");

const selectedSite = computed(() => sitesStore.sites.find((s) => s.site_id === selectedSiteId.value) || null);
const selectedSiteHomepageLabel = computed(() => {
  const home = (selectedSite.value?.pages || {})["/"];
  return home ? home.label || home.page_id : "";
});
const canLeaveSiteStep = computed(() => !!selectedSiteId.value);
const canCreateInlineSite = computed(() => !!newSiteSubdomain.value && siteAvailable.value && !creatingSite.value);
profileStore.ensureLoaded();
const products = ref([]);
const services = ref([]);
const search = ref("");
const offerSearch = ref("");
const loading = ref(false);
const offersLoading = ref(false);
const productsLoading = ref(false);
const servicesLoading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");

// The save confirmation clears itself so it stops holding space once it has been read; the ✕ is still
// there for anyone who wants it gone sooner. An ERROR never auto-clears — something went wrong, and the
// tenant decides when they are done reading it.
const MESSAGE_AUTO_DISMISS_MS = 15000;
let messageDismissTimer = null;

function clearMessageTimer() {
  if (messageDismissTimer) {
    window.clearTimeout(messageDismissTimer);
    messageDismissTimer = null;
  }
}

watch(message, (value) => {
  // Restart on every new message, so a second save gets its own full 15s rather than inheriting the
  // remainder of the first one's.
  clearMessageTimer();
  if (!value) return;
  messageDismissTimer = window.setTimeout(() => {
    messageDismissTimer = null;
    message.value = "";
  }, MESSAGE_AUTO_DISMISS_MS);
});

onBeforeUnmount(clearMessageTimer);
const wizardError = ref("");
const wizardOpen = ref(false);
const wizardStep = ref(1);
const openMenuId = ref("");
const selectedPageDetails = ref(null);
const pendingArchivePage = ref(null);
const pagesLoaded = ref(false);
const builderOpen = ref(false);
const builderFormHidden = ref(false);
const builderExistingPageId = ref("");
const builderOriginalPage = ref(null);
// Mobile by default, because it is the only layout the side-by-side panel can show HONESTLY: the panel
// is narrower than the published page's 700px breakpoint, so a "Desktop" preview beside the form would
// be rendering the mobile layout under a desktop label. Choosing Desktop hides the form and gives the
// preview the full width, which is a real desktop viewport (see setPreviewDevice).
// Marquee speed. The renderer takes a DURATION (bigger = slower), but the slider reads left-to-right as
// slow -> fast, so the bound value is the duration inverted about the range. Turtle at the low end,
// hare at the high end, and the tenant never sees seconds.
// Brand marquee speed. Same inversion as the countdown's below — dragging right must mean FASTER, so
// the bound value is the duration reflected about the range. Its own constants because the two elements
// have different sensible ranges: a logo row reads at a far more leisurely pace than a countdown banner.
const BRAND_MARQUEE_MIN = 8;
const BRAND_MARQUEE_MAX = 60;

const MARQUEE_MIN_SECONDS = 5;
const MARQUEE_MAX_SECONDS = 24;
const marqueeSpeedSlider = computed({
  get: () => MARQUEE_MIN_SECONDS + MARQUEE_MAX_SECONDS - (Number(builder.countdown.marquee_seconds) || 14),
  set: (value) => {
    builder.countdown.marquee_seconds = MARQUEE_MIN_SECONDS + MARQUEE_MAX_SECONDS - Number(value);
  },
});

const previewDevice = ref("mobile");


// Desktop preview and the form are mutually exclusive — one control, one honest state.
function setPreviewDevice(device) {
  previewDevice.value = device;
  builderFormHidden.value = device === "desktop";
}

// The pairing is an INVARIANT, enforced once rather than remembered at each of the four places that
// reveal the form (Show Form, closing the builder, opening a page, the funnel-step exit). A visible
// form means the preview panel is narrower than the page's 700px breakpoint, so desktop cannot be
// shown honestly there.
watch(builderFormHidden, (hidden) => {
  if (!hidden) previewDevice.value = "mobile";
});

// Bringing the form back returns the preview to mobile; a desktop preview in the narrow panel would be
// mislabelled again the moment the form reappears.
function showBuilderForm() {
  builderFormHidden.value = false;
}

// Hiding the form on its own leaves the device alone — someone may want a bigger MOBILE preview.
function toggleBuilderForm() {
  if (builderFormHidden.value) showBuilderForm();
  else builderFormHidden.value = true;
}
const faviconFileInput = ref(null);
const heroFileInput = ref(null);
const avatarFileInput = ref(null);
const blurbImageInputs = ref({});
const faviconUploading = ref(false);
const heroUploading = ref(false);
const avatarUploading = ref(false);
const blurbImageUploading = reactive({});
const faviconUploadError = ref("");
const heroUploadError = ref("");
const avatarUploadError = ref("");
const blurbImageErrors = reactive({});
// Per-sub-item image uploads (testimonial avatars, client logos), keyed by element:list:index.
const subImageInputs = ref({});
const subImageUploading = reactive({});
const subImageErrors = reactive({});
const form = reactive(defaultWizardForm());
// The default "What's Next?" cards (mirror of upsell_pages.DEFAULT_THANK_YOU.next_steps). Declared BEFORE
// `builder` because defaultBuilderForm() reads it — a const referenced before its line throws a TDZ error.
const THANK_YOU_DEFAULT_CARDS = [
  { icon: "📧", title: "Check Your Email", desc: "Confirmation and tracking details are on the way to your inbox." },
  { icon: "📦", title: "Free Shipping", desc: "Your order will arrive within 5–7 business days." },
  { icon: "🚀", title: "Start Your Journey", desc: "Begin your routine as soon as it arrives." },
];
const builder = reactive(defaultBuilderForm());
const defaultFaviconUrl = assetUrl("/icon/favicon.png");  // configured asset CDN (public_asset_base_url)
// The saved document carries no legal URLs and no resolved year: render_legal_footer builds the platform
// /legal/* links from the api_base_url we send with each render, and expands {{current_year}} itself.
const defaultFooterCopyrightTemplate = "© {{current_year}} All rights reserved.";

// The keying lives HERE, not in the upload field: the field stays presentational and simply reads and
// writes a description for whatever image it currently holds.
provide("imageAltStore", {
  get: (url) => builder.image_alts?.[url] || "",
  set: (url, value) => {
    const text = String(value || "").trim();
    // Blank means "no override" -- store nothing rather than an empty string, so the renderer falls back
    // to the alt it derives from surrounding data instead of emitting alt="" on a content image.
    if (text) builder.image_alts[url] = text;
    else delete builder.image_alts[url];
  },
});

const universalBundlePresets = [
  { value: "clean-slate", label: "Clean Slate" },
  { value: "techno-green", label: "Techno Green" },
  { value: "rose-minimalist", label: "Rose Minimalist" },
  { value: "midnight-luxe", label: "Midnight Luxe" },
  { value: "trust-blue", label: "Trust Blue" },
  { value: "coral-sunrise", label: "Coral Sunrise" },
  { value: "royal-velvet", label: "Royal Velvet" },
  { value: "fire-sale", label: "Fire Sale" },
  { value: "natural-calm", label: "Natural Calm" },
  { value: "cyber-pulse", label: "Cyber Pulse" },
  // Socialite palettes (plans/SOCIALITE_PARITY.md)
  { value: "linkedin-blue", label: "LinkedIn Blue" },
  { value: "instagram-gradient", label: "Instagram Gradient" },
  { value: "tiktok-dark", label: "TikTok Dark" },
  { value: "youtube-red", label: "YouTube Red" },
  { value: "twitter-dark", label: "Twitter Dark" },
  { value: "professional-gray", label: "Professional Gray" },
];
// MIRRORS SERVABLE_FAMILIES in src/stripe_link/domain/fonts.py. Offering a family the service cannot serve
// produces a stylesheet request that 404s, which is worse than no webfont at all — so the two lists must
// agree, and tests/test_font_picker_options.py fails if they drift.
const builderFontFamilies = [
  "Aileron", "Arapey", "Bebas Neue", "Comic Relief", "DM Serif Display", "Heebo", "Inter", "Karla", "Konya",
  "Lato", "Lora", "Merriweather", "Merriweather Sans", "Montserrat", "Nunito", "Open Sans", "Oswald",
  "Overpass", "Overpass Mono", "PT Sans Caption", "PT Serif", "Playfair", "Poppins", "Quantico",
  "Quicksand", "Raleway", "Roboto", "Rubik", "Slabo", "Source Code Pro", "Source Sans 3", "Source Sans Pro",
];
// Heading and body only. `accent` is permitted by the resolver but no preset proposes one, it follows the
// heading when unset, and a third family is a third download on a page tuned for LCP — so it stays a
// deliberate omission from the picker rather than a third dropdown nobody needs.
// The store's imported faces. Kept out of builderFontFamilies on purpose: that list mirrors the fonts-api
// catalogue and is pinned against it by tests/test_font_picker_options.py. These are the tenant's own, the
// service has never heard of them, and the renderer emits their @font-face itself.
const tenantFontFamilies = ref([]);

async function loadTenantFonts() {
  try {
    const body = await apiRequest("/fonts/import");
    // One entry per weight, so a family with Regular and Bold must appear once, not twice.
    tenantFontFamilies.value = [...new Set((body.fonts || []).map((f) => f.family).filter(Boolean))].sort();
  } catch {
    tenantFontFamilies.value = [];   // never let this break the builder
  }
}

const builderFontRoles = [
  { key: "heading", label: "Headings" },
  { key: "body", label: "Body text" },
];
const landingPagePriceContexts = new Set(["standard", "sale", "flash_sale", "flash sale"]);
const productsById = computed(() => new Map(products.value.map((product) => [productId(product), product])));
const servicesById = computed(() => new Map(services.value.map((service) => [service.service_id, service])));
const selectedOffer = computed(() => offers.value.find((offer) => offer.offer_id === form.offer_id) || null);
const selectedOfferProducts = computed(() => offerProducts(selectedOffer.value));
const selectedOfferIntent = computed(() => offerIntent(selectedOffer.value));
// The link-in-bio page is the one lead shape with no goal question to answer: its traffic is ALWAYS a tap
// from a bio field, and every pack seeds the wrong thing for it (testimonials and FAQs on a link hub are
// noise). Capture, call and bridge pages keep the step -- "ads vs search vs social" is a real question
// there, with useful seeds behind it.
const selectedOfferIsSocialPage = computed(() =>
  selectedOffer.value?.lead_capture_action === "social_redirect"
  || selectedOfferProducts.value.some((product) => product?.lead_capture?.action === "social_redirect"));
const selectedLeadAction = computed(() => selectedOfferProducts.value.find((product) => product.lead_capture)?.lead_capture || null);
const builderOffer = computed(() => offers.value.find((offer) => offer.offer_id === builder.offer_id) || null);
const builderOfferProducts = computed(() => offerProducts(builderOffer.value));
const builderIntent = computed(() => offerIntent(builderOffer.value));
// Post-purchase funnel gating (P3.5): the upsell/downsell/carousel copy only matters when the offer carries a
// funnel; the thank-you copy applies to every transaction funnel. MAX_SEQUENTIAL_UPSELLS=4 → the grid/carousel
// screen (matches upsell_pages.py); expose the carousel copy only when there are that many upsells.
const funnelUpsellCount = computed(() => (builderOffer.value?.funnel?.upsells || []).length);
const funnelDownsellCount = computed(() => (builderOffer.value?.funnel?.downsells || []).length);
const hasPostPurchaseFunnel = computed(() => funnelUpsellCount.value + funnelDownsellCount.value > 0);
// The offer's purchase flow, computed from the SAVED offer (items + funnel) for the read-only reference diagram
// (shared PurchaseFlowDiagram, same as the Offer editor). plans/SALES_FUNNELS.md.
const showPurchaseFlow = ref(false);
// Stages come from the SHARED builder (composables/purchaseFlow.js). This screen used to read the legacy
// items[] + funnel.* fields directly, which are dual-written today but are dropped by
// plans/OFFER_MODEL_REDESIGN.md P4 — at which point the flow would have silently lost its bumps and
// upsells. The shared builder prefers purchase_opportunities and falls back, so it survives that.
const funnelFlowStages = computed(() => {
  const offer = builderOffer.value;
  if (!offer) return [];
  return stagesFromSavedOffer(offer, {
    resolveProduct: (id) => productsById.value.get(id) || null,
    formatAmount: (amount, currency) => formatMoney(amount, currency),
  });
});
// The runtime default copy shown as editor placeholders (mirrors upsell_pages.py DEFAULT_UPSELL_SCAFFOLD /
// DEFAULT_THANK_YOU). PRICE_TOKEN is interpolated as literal text (a bare {{ }} in the template would break
// the parser). {{ upsell_price }} in a button label is replaced with the product's price at render.
const PRICE_TOKEN = "{{ upsell_price }}";
const SCAFFOLD_PLACEHOLDERS = {
  ty_headline: "Thank You for Your Purchase!",
  ty_subheadline: "Your order is confirmed — a receipt is on its way to your inbox.",
  ty_message: "We're getting your order ready. You'll get an email with the details shortly.",
  headline: "Wait! Before You Go…",
  subheadline: "Exclusive One-Time Offer Just For You",
  accept_label: "Yes, I'll Take This Deal for {{ upsell_price }}",
  decline_label: "No, Thank You! Let's Move On",
  price_label: "Yours for only",
  downsell_headline: "Wait — Here's a Smaller Option",
  downsell_note: "This offer will not be shown again.",
  carousel_headline: "Special Deals — Just For You",
  carousel_subheadline: "One-time offers at checkout prices. Add any you like, then continue.",
  carousel_add_label: "Add for {{ upsell_price }}",
  carousel_dismiss_label: "No thanks, I'm good!",
  carousel_proceed_label: "Continue to the next step",
  downsell_carousel_headline: "Before You Go — A Lower-Priced Option",
  // Thank-you extras (Phase 2 — mirrors upsell_pages.DEFAULT_THANK_YOU).
  ty_headline_icon: "🎉",
  ty_next_steps_title: "What's Next?",
  ty_footer_headline: "The Ball Is in Our Court",
  ty_footer_message: "Look for an email from us with tracking information about your order.",
  ty_home_button_text: "Back to Home",
  ty_download_button_text: "Download Your Product",
};
// Post-Checkout Flow accordion (SALES_FUNNELS.md P3.5): opening a step switches the Live Preview to render
// THAT funnel page (via /pages/render funnel_step). null = the landing page.
const openFunnelStep = ref(null);
// Every product the offer references (landing items + funnel upsells/downsells) — the funnel-step preview needs
// the upsell products in its products map, not just the landing items.
const builderOfferAllProducts = computed(() => {
  const ids = new Set();
  (builderOffer.value?.items || []).forEach((i) => i.product_id && ids.add(i.product_id));
  const funnel = builderOffer.value?.funnel || {};
  [...(funnel.upsells || []), ...(funnel.downsells || [])].forEach((u) => u.product_id && ids.add(u.product_id));
  return [...ids].map((id) => productsById.value.get(id)).filter(Boolean);
});
// The accordion steps: one per sequential upsell (named by product), then Thank You. >3 upsells collapse to a
// single carousel step (MAX_SEQUENTIAL_UPSELLS in the runtime). `key` doubles as the /pages/render funnel_step.
const funnelSteps = computed(() => {
  const steps = [];
  const upsells = builderOffer.value?.funnel?.upsells || [];
  if (upsells.length > 3) {
    steps.push({ key: "upsell_carousel", num: "★", label: "Upsell offers (carousel)", kind: "carousel" });
  } else {
    upsells.forEach((u, i) => {
      const name = productsById.value.get(u.product_id)?.name || "Upsell";
      steps.push({ key: `upsell:${i}`, num: String(i + 1), label: `Upsell ${i + 1}: ${name}`, kind: "upsell" });
    });
  }
  steps.push({ key: "thank_you", num: "TY", label: "Thank You Page", kind: "thank_you" });
  return steps;
});
const activeFunnelStepLabel = computed(() => funnelSteps.value.find((s) => s.key === openFunnelStep.value)?.label || "");

function toggleFunnelStep(key) {
  openFunnelStep.value = openFunnelStep.value === key ? null : key;
}
// If the funnel changes (offer switched, upsell removed) so the open step no longer exists, collapse to landing.
watch(funnelSteps, (steps) => {
  if (openFunnelStep.value && !steps.some((s) => s.key === openFunnelStep.value)) openFunnelStep.value = null;
});
// The smart defaults shown when the tenant leaves the SEO fields blank — the renderer derives the same
// values live (never stored unless the tenant overrides), so the placeholder matches what publishes.
const seoTitlePlaceholder = computed(() => offerSeoTitleDefault(builderOffer.value) || "Product — Category");
const seoDescriptionPlaceholder = computed(() => offerSeoDescriptionDefault(builderOffer.value) || "Auto-generated from the product description");
// The offer's snapshotted CTA contract drives the preview's on-page experience (buy/call/email/external/booking).
const builderCta = computed(() => builderOffer.value?.presentation?.cta || { type: builderIntent.value === "lead_gen" ? "email" : "buy" });

// Sale / Flash-Sale (plans/SALES_FUNNELS.md P1d): does any product the offer sells carry a price in `context`?
// Enabling a sale view only does something if a product actually carries a price in that context —
// otherwise the page renders as Standard and the banner never appears, which is what caught the author
// out. The field-level warning existed but sits far down in Settings; this nudges at the moment of the
// action. Keyed so it cannot stack if the box is toggled repeatedly.
function warnIfMissingPriceContext(context) {
  const enabled = context === "sale" ? builder.sale.enabled : builder.flash_sale.enabled;
  if (!enabled || offerHasPriceContext(context)) return;
  const label = context === "sale" ? "Sale" : "Flash Sale";
  toasts.push({
    key: `missing-price-context:${context}`,
    severity: "warning",
    icon: "⚠️",
    message: `This product does not have a "${label}" pricing context. Please create a "${label}" price for this product in the Products module.`,
  });
}

function offerHasPriceContext(context) {
  return builderOfferProducts.value.some((product) => (product.prices || []).some((price) => (price.context || "standard") === context));
}
// datetime-local <-> epoch seconds. The <input type="datetime-local"> works in the tenant's local time.
function epochToLocalInput(secs) {
  if (!secs) return "";
  const d = new Date(secs * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function localInputToEpoch(value) {
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? 0 : Math.floor(ms / 1000);
}
const saleEndsAtLocal = computed({ get: () => epochToLocalInput(builder.sale.ends_at), set: (v) => { builder.sale.ends_at = localInputToEpoch(v); } });
const flashStartsOnLocal = computed({ get: () => epochToLocalInput(builder.flash_sale.starts_on), set: (v) => { builder.flash_sale.starts_on = localInputToEpoch(v); } });
const flashEndsAtLocal = computed({ get: () => epochToLocalInput(builder.flash_sale.ends_at), set: (v) => { builder.flash_sale.ends_at = localInputToEpoch(v); } });
// A flash sale can't be enabled without an expiration (mirrors the backend document rule).
const flashSaleInvalid = computed(() => builder.flash_sale.enabled && !builder.flash_sale.ends_at);
const selectedOfferCta = computed(() => selectedOffer.value?.presentation?.cta || { type: selectedOfferIntent.value === "lead_gen" ? "email" : "buy" });
// offer_type is being retired (plans/OFFER_MODEL_REDESIGN.md): read it through a derive helper — the stored
// field wins during migration, else infer from the landing items — so this keeps working once it's dropped.
// Mirrors LEAD_COMPOSITIONS in domain/composition.py; pinned by tests/test_lead_gen_composition.py.
// Mirrors HERO_TAGLINE_MAX_LENGTH in domain/documents.py -- a slogan has to fit ONE line on a phone, which
// is where nearly all of this traffic is. Pinned by a test so the two cannot drift.
const HERO_TAGLINE_MAX = 40;
const LEAD_COMPOSITION_TYPES = new Set(["lead_capture", "lead_call", "lead_bridge", "lead_social"]);
const LEAD_COMPOSITIONS = {
  capture_email: "lead_capture",
  capture_phone: "lead_capture",
  capture_email_phone: "lead_capture",
  call_number: "lead_call",
  external_url: "lead_bridge",
  social_redirect: "lead_social",
};

function deriveOfferType(offer) {
  // Mirrors composition_key() in domain/composition.py. A lead-gen offer gets its OWN composition rather
  // than a checkout page with the price hidden -- and intent is a different question from pricing shape,
  // which is why this sits here and not inside the items/prices derivation below.
  //
  // The ACTION picks which of the four: the three capture_* actions share a page (the field differs, the
  // page does not), while call, bridge and link-in-bio are genuinely different. Falls back to the offer's
  // primary product when the offer predates the denormalised copy.
  if (offerIntent(offer) === "lead_gen") {
    const action = offer?.lead_capture_action || offerProducts(offer)[0]?.lead_capture?.action || "";
    return LEAD_COMPOSITIONS[action] || "lead_capture";
  }
  if (offer?.offer_type) return offer.offer_type;
  const items = Array.isArray(offer?.items) ? offer.items : [];
  if (items.length > 1) return "listicle";
  if (items.length === 1 && Array.isArray(items[0]?.selectable_prices) && items[0].selectable_prices.length > 1) return "bundle";
  return "single";
}
// A listicle offer renders its items as a carousel (each add-to-cart) instead of the pick-one selector.
const isListicleOffer = computed(() => deriveOfferType(builderOffer.value) === "listicle");
// --- Page Composer (see plans/PAGE_COMPOSER.md) ---
// Visibility comes from the SHARED rules file (imported by pageComposer.js — the exact file Python reads)
// plus the tenant's overrides. The preview AND the saved section list both call sectionVisible(), and
// Python's compose_page() applies the same rules, so preview and published can't disagree.
// The page's avatar is an OVERRIDE. Empty means "use the store avatar", resolved at render -- so the
// builder must show the store's image as the effective preview without COPYING it onto the page, which
// would freeze this page at whatever the avatar was the day it was built.
// What the brand label would say if the tenant typed nothing -- shown as the placeholder so the fallback
// is visible rather than mysterious.
const brandLabelFallback = computed(() => offerBrandDefault(builderOffer.value) || "Your business name");
const storeAvatarUrl = computed(() => profileStore.storeAvatarUrl || "");
const effectiveAvatarUrl = computed(() => builder.avatar_url || storeAvatarUrl.value);
const avatarIsFromProfile = computed(() => !builder.avatar_url && Boolean(storeAvatarUrl.value));
const builderOfferType = computed(() => deriveOfferType(builderOffer.value));
// Mirrors shows_breadcrumb() in domain/composition.py. A breadcrumb says "you are HERE in a hierarchy", which
// is true of a product inside a catalogue and false of the lead shapes -- a link hub is an identity page, not
// a node under a store, and a bridge page is noindex by rule, so a crawlable trail on it has no reader.
const breadcrumbDefault = computed(() => !LEAD_COMPOSITION_TYPES.has(builderOfferType.value));
// The checkbox binds to the EFFECTIVE value, not the stored one. builder.breadcrumb is undefined until the
// tenant touches it -- that is what "derive from the shape" looks like in the document -- and an undefined
// v-model renders unchecked, which would have shown every checkout page as breadcrumb-off while it rendered
// one. Reading through the default keeps the control honest about what the page actually does.
const breadcrumbOn = computed({
  get: () => (typeof builder.breadcrumb === "boolean" ? builder.breadcrumb : breadcrumbDefault.value),
  set: (value) => { builder.breadcrumb = value; },
});
function sectionVisible(sectionType) {
  return isSectionVisible(builderOfferType.value, sectionType, builder.composition.overrides, builderGoal.value);
}
// The page's goal is the second composition axis: offer_type sets the base sections, the goal unions in the
// sections its capability packs enable (plans/LANDING_PAGE_GOAL_COMPOSITION.md). "" = a page from before
// goals existed, which composes from the base alone.
const builderGoal = computed(() => builder.goal || "");
// Changing the goal here re-composes governed sections (e.g. structured data appears for Search / SEO). It
// deliberately does NOT re-seed content elements: seeds are a create-time starting point and become the
// tenant's, so switching goal must never inject or delete their written copy.
const builderGoalNote = computed(() => {
  if (!builder.goal) return "No goal set. The page composes from the offer type alone.";
  const option = goalOptions.value.find((entry) => entry.value === builder.goal);
  return option ? option.note : "";
});
// Governed sections a tenant can toggle for this offer type + goal (Recommended = on by default).
const recommendedSections = computed(() => recommendedSectionKeys(builderOfferType.value, builderGoal.value));
const optionalSections = computed(() => optionalSectionKeys(builderOfferType.value, builderGoal.value));
// Structural sections are always present; these are the optional content sections the tenant can add/remove.
const MANDATORY_SECTION_KEYS = new Set(["hero", "hero_media", "offer_price_selector", "legal_footer", "checkout_cta"]);
const optionalGovernedSections = computed(() => governedKeys().filter((key) => {
  if (MANDATORY_SECTION_KEYS.has(key)) return false;
  // A section the composition declares IMPOSSIBLE cannot be switched on, so listing it offers a control that
  // does nothing -- reported on a link page, where Trust badges and Refund policy sat there inert. An
  // exclusion is a statement about what the page IS (a page that takes no money has no refund policy), not a
  // preference, so the honest thing is to not offer it rather than to offer it and ignore the answer.
  if (excludedSections(builderOfferType.value).has(key)) return false;
  // Don't offer a toggle the page can't honour: refund policy copy comes from the offer or its product
  // (render_refund_policy does offer.refund_policy or product.refund_policy). Service offers have items
  // keyed by service_id with no product and no policy of their own, so the section renders nothing on the
  // published page no matter what this toggle says. Hide it rather than promise a section that can't exist.
  if (key === "refund_policy" && !previewRefundPolicy.value) return false;
  return true;
}));
// Page Sections lists what a visitor can SEE. Non-visible sections (head/sidecar — structured data, later
// llms.txt) are real composed sections but paint no pixels, so listing them beside "Trust badges" invites a
// tenant to hunt for something they'll never find on the page. They get their own drawer below.
const togglableSections = computed(() =>
  optionalGovernedSections.value.filter((key) => elementChannel(key) === "body"));
const discoverabilitySections = computed(() =>
  optionalGovernedSections.value.filter((key) => elementChannel(key) !== "body"));
// Nothing in the drawer is editable — the whole point is that SEO output is DERIVED from the offer and the
// composed sections, not typed into a form. So the drawer's job is to show what WILL be emitted. Mirrors
// render_structured_data(): Product needs prices the page displays; FAQPage needs a filled-in faq section.
const structuredDataTypes = computed(() => {
  const types = [];
  if (previewPricesExist.value) types.push("Product");
  if (builder.elements.some((element) => element.type === "faq"
    && (element.items || []).some((item) => item.question && item.answer))) {
    types.push("FAQPage");
  }
  return types;
});
const previewPricesExist = computed(() =>
  (builderOffer.value?.items || []).some((item) => (item.selectable_prices || []).length || item.service_id));
function sectionKeyLabel(key) {
  return elementLabel(key);
}
function isSectionEnabled(key) {
  const override = builder.composition.overrides[key];
  if (override && typeof override.enabled === "boolean") return override.enabled;
  return defaultVisible(builderOfferType.value, key, builderGoal.value);
}
async function toggleSection(key, enabled) {
  // Only persist a deviation from the offer_type default; clearing back to default drops the override.
  if (enabled === defaultVisible(builderOfferType.value, key, builderGoal.value)) {
    delete builder.composition.overrides[key];
  } else {
    builder.composition.overrides[key] = { enabled };
  }
  await autoSavePage();
}
// "Hide brand name" writes a composition OVERRIDE -- the same mechanism the Page Sections panel uses, so the
// two switches describe one state instead of becoming two ways to turn brand_label off that can disagree.
// Inverted, because the control is phrased as hiding: a tenant reaching for it wants the brand gone, and a
// switch labelled "hide" that has to be turned OFF to hide is a puzzle.
const brandLabelHidden = computed({
  get: () => !isSectionEnabled("brand_label"),
  set: (hidden) => { toggleSection("brand_label", !hidden); },
});
// The name the identity block will show. Mirrors tenant_display_name() in runtime/html.py: the owner's
// display name as the Profile page and the user pill show it.
const ownerDisplayName = computed(() => profileStore.displayName || "");

// --- Advanced Color Settings (plans/ADVANCED_COLOR_SETTINGS.md) ---
const previewEl = ref(null);
// Effective colour for a token: the override if set, else the preset's value read off the live preview.
function effectiveColor(token) {
  if (builder.theme_tokens[token]) return builder.theme_tokens[token];
  if (!previewEl.value) return "";
  return getComputedStyle(previewEl.value).getPropertyValue(previewVar(token)).trim();
}
function setTokenColor(token, value) {
  const v = String(value || "").trim();
  if (v) builder.theme_tokens[token] = v;
  else delete builder.theme_tokens[token];   // empty = fall back to the preset
}
// A stored entry is either a bare family string or { family, fallback }. Read through both shapes so a
// fallback set elsewhere is not invisible here — and, below, not destroyed on the next edit.
function fontFamilyFor(role) {
  const entry = builder.theme_fonts?.[role];
  return String((entry && typeof entry === "object" ? entry.family : entry) || "");
}
function setFontFamily(role, value) {
  const family = String(value || "").trim();
  if (!family) {
    delete builder.theme_fonts[role];   // empty = fall back to the preset, same rule as a colour token
    return;
  }
  const entry = builder.theme_fonts[role];
  // ALWAYS an object. validate_font_settings requires { family, fallback } and rejects a bare string with
  // "theme.fonts.body must be an object" — resolve_families reads a plain string too, but the validator is
  // the contract and it runs first. Spread any existing entry so a `fallback` stack survives the edit.
  builder.theme_fonts[role] = { ...(entry && typeof entry === "object" ? entry : {}), family };
}
// "Reset to preset" means the whole appearance, not half of it: leaving fonts behind while colours reset
// would make the button lie about what it did.
function resetAppearanceOverrides() {
  builder.theme_tokens = {};
  builder.theme_fonts = {};
}
// Native color inputs need a #rrggbb value; normalize the effective colour (rgba/short hex fall back).
function pickerColor(token) {
  const c = effectiveColor(token);
  if (/^#[0-9a-fA-F]{6}$/.test(c)) return c;
  if (/^#[0-9a-fA-F]{3}$/.test(c)) return "#" + c.slice(1).split("").map((x) => x + x).join("");
  return "#000000";
}
// Overrides applied to the preview root as inline --preview-* vars (they win over the preset class).
const previewTokenStyle = computed(() => {
  const style = {};
  for (const [token, value] of Object.entries(builder.theme_tokens || {})) {
    if (value) style[previewVar(token)] = value;
  }
  return style;
});
// The ConversionContext targets. Source of truth is the SERVER's expand_offer (fetched via ?expand=1 into
// builderExpandedOffer) so the preview prices items with the exact same implementation as the published
// page — no drift. Until that fetch resolves (or if it fails) we fall back to the local projection.
const builderExpandedOffer = ref(null);
async function loadBuilderExpandedOffer(offerId) {
  if (!offerId) { builderExpandedOffer.value = null; return; }
  try {
    const body = await apiRequest(`/offers/${offerId}?expand=1`);
    // Guard against a stale response if the user switched offers mid-flight.
    if (builder.offer_id === offerId) builderExpandedOffer.value = body?.offer || null;
  } catch (err) {
    if (builder.offer_id === offerId) builderExpandedOffer.value = null;
  }
}
watch(() => builder.offer_id, (offerId) => { loadBuilderExpandedOffer(offerId); }, { immediate: true });
const conversionTargets = computed(() => {
  const expanded = builderExpandedOffer.value;
  if (expanded && expanded.offer_id === builder.offer_id && Array.isArray(expanded.items)) {
    return offerViewTargetsFromExpanded(expanded.items);
  }
  return offerViewTargets(offerItemModels(builderOffer.value));
});
// conversionTargets still drives the listicle hero auto-fill below. The ConversionContext itself (current
// target index, carousel sync, per-target detail panels) existed only to drive the old Vue preview twin —
// the server renderer owns all of that now, so it is gone along with the twin.
const builderProductImages = computed(() => [...new Set(builderOfferProducts.value.flatMap((product) => product.images || []).filter(Boolean))]);
const heroMediaList = computed(() => parseLines(builder.hero_media_text));
// What the renderer falls back to when hero_media.images is empty — mirrors runtime/html.py
// hero_media_images()/offer_uses_grouped_item_media(): a multi-item offer contributes ONE image per item
// (so an image-less item still occupies a slide and renders the placeholder), a single-product offer
// contributes all of that product's images. Surfaced read-only in the media field as AUTO rows.
const builderDerivedHeroMedia = computed(() => {
  const products = builderOfferProducts.value;
  if (!products.length) return [];
  if (products.length > 1) {
    return products.map((product) => ({
      url: (product.images || []).find(Boolean) || "",
      label: product.name || "Product",
    }));
  }
  const only = products[0];
  return (only.images || []).filter(Boolean).map((url) => ({ url, label: only.name || "Product" }));
});
const previewHeroImage = computed(() => heroMediaList.value[0] || offerImage(builderOffer.value) || "");
const visibleTrustBadges = computed(() => builder.trust_badges.badges.filter((badge) => badge.enabled !== false && badge.label));
// ---------------------------------------------------------------------------------------------------
// Live Preview = the published renderer. We send the draft page document to /pages/render, which runs the
// same render_page() that publishes the page, and drop the HTML into an iframe. The builder no longer
// reimplements any section, so preview and published are the same bytes by construction.
// ---------------------------------------------------------------------------------------------------
const previewHtml = ref("");
const previewError = ref("");
// Advisory only: what would stop this page's structured data earning a rich result. Never blocks a save.
const structuredDataWarnings = ref([]);
// Quality-baseline warnings for the whole page (heading outline now; a11y/CLS later). Not tied to any
// section, so shown always, not inside the Discoverability drawer.
const pageHealthWarnings = ref([]);
const previewFrame = ref(null);
// Which pricing context the Live Preview renders. Lets tenants proof the /sale and /flash-sale views
// without a custom domain (the pretty slugs only exist via the published resolver). Only surfaced when the
// page actually has that context enabled.
const previewContext = ref("standard");

// Which context the preview is showing but cannot honour. Returns its LABEL (truthy) or "" so the
// template can both test and print it.
const previewContextUnavailable = computed(() => {
  const ctx = previewContext.value;
  if (ctx !== "sale" && ctx !== "flash_sale") return "";
  return offerHasPriceContext(ctx) ? "" : (ctx === "flash_sale" ? "Flash Sale" : "Sale");
});

const previewContextOptions = computed(() => {
  const opts = [{ value: "standard", label: "Standard" }];
  if (builder.sale?.enabled) opts.push({ value: "sale", label: "Sale" });
  if (builder.flash_sale?.enabled) opts.push({ value: "flash_sale", label: "Flash Sale" });
  return opts;
});
let previewRenderTimer = null;
let previewRenderSeq = 0;
// Swapping srcdoc reloads the iframe, which would bounce the tenant back to the top of the page on every
// keystroke. Carry the scroll offset across the reload so editing stays where they are working.
let previewScrollY = 0;

function capturePreviewScroll() {
  try {
    previewScrollY = previewFrame.value?.contentWindow?.scrollY ?? previewScrollY;
  } catch {
    /* cross-origin frame: keep the last known offset */
  }
}

function restorePreviewScroll() {
  if (!previewScrollY) return;
  try {
    previewFrame.value?.contentWindow?.scrollTo(0, previewScrollY);
  } catch {
    /* nothing to restore */
  }
}

// Reload the frame with the HTML it already has. renderPreview() skips byte-identical HTML (so ordinary
// edits don't repaint), but a just-uploaded image needs a re-fetch even though the markup is unchanged —
// assigning srcdoc directly forces that.
function reloadPreviewFrame() {
  const frame = previewFrame.value;
  if (!frame || !previewHtml.value) return;
  capturePreviewScroll();
  frame.srcdoc = previewHtml.value;
}

// Image renditions are processed asynchronously and land biggest-last, so an image can still be missing
// when the page first renders after an upload — it paints broken until something repaints the frame.
// Repaint it ourselves a couple of times instead. We deliberately never request the pending URL to test
// for it: the CDN answers 403 for a missing object and caches that, which would turn a self-healing race
// into a permanently broken image.
function schedulePreviewImageRefresh() {
  [4000, 10000].forEach((delay) => window.setTimeout(reloadPreviewFrame, delay));
}

// Every builder upload goes through here so a freshly processed image always gets its heal repaint,
// and so its intrinsic dimensions are captured once, centrally, for every page image field.
// Hero video upload. Returns the CDN URL; MediaListField appends it to the list, and the renderer
// derives "this is a video" from the extension (runtime/html.py is_video_url), so no schema change.
async function uploadPageVideo(file, onProgress = null) {
  const url = await uploadVideo(file, { onProgress });
  schedulePreviewImageRefresh();
  return url;
}

async function uploadPageImage(file) {
  const { url, dims, imageId } = await uploadImage(file);
  recordImageDims(builder.image_dims, url, dims);
  // Keep the asset id against the URL: baking a crop reads the ORIGINAL by id, so a re-crop never
  // compounds the last one. Only images uploaded here have one -- a pasted URL cannot be cropped.
  if (imageId) builder.image_assets = { ...(builder.image_assets || {}), [url]: imageId };
  schedulePreviewImageRefresh();
  return url;
}

// A tenant-supplied poster for an embed. YouTube has a deterministic thumbnail, Vimeo has none without an
// oEmbed lookup, and either can be overridden with something better than the provider's auto-frame.
function onHeroPosterSet({ url, poster }) {
  if (!url || !poster) return;
  builder.video_posters = { ...(builder.video_posters || {}), [url]: poster };
  schedulePreviewImageRefresh();
}

// A baked hero crop replaces the URL, so the asset id follows it to the new one.
function onHeroCropApplied({ oldUrl, url, imageId }) {
  const assets = { ...(builder.image_assets || {}) };
  delete assets[oldUrl];
  assets[url] = imageId;
  builder.image_assets = assets;
  schedulePreviewImageRefresh();
}

// A service offer's items carry service_id (not product_id); render_page resolves those separately.
function offerServices(offer) {
  const items = Array.isArray(offer?.items) ? offer.items : [];
  return items.map((item) => (item.service_id ? servicesById.value.get(item.service_id) : null)).filter(Boolean);
}

async function renderPreview() {
  const page = buildBuilderPageDocument();
  const offer = builderOffer.value;
  if (!page || !offer) {
    previewHtml.value = "";
    return;
  }
  const seq = ++previewRenderSeq;
  try {
    const body = await apiRequest("/pages/render", {
      method: "POST",
      body: {
        page,
        offer,
        // A funnel-step preview needs the upsell products too; the landing preview only needs its own items.
        products: openFunnelStep.value ? builderOfferAllProducts.value : builderOfferProducts.value,
        services: offerServices(offer),
        // When a Post-Checkout Flow step is open, render THAT funnel page instead of the landing page.
        funnel_step: openFunnelStep.value || undefined,
        // The page document stores no legal URLs on purpose (legalLinks() returns {}); render_legal_footer
        // builds the platform /legal/* hrefs from api_base_url. Without it the footer links vanish.
        api_base_url: getApiBase(),
        // The page's canonical public URL so the preview shows the same canonical/OG the published page emits
        // (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-01; interim published-artifact URL).
        canonical_url: artifactPageUrl({ page_id: page.page_id }),
        // Proof the /sale or /flash-sale context view inline (no custom domain needed).
        price_context: previewContext.value,
        // Which Site this page belongs to -- or, for a page not yet saved, the one it will attach to. The
        // renderer reads the Site for the store's identity, and attachment only happens on save, so without
        // this every page under construction previewed as the platform brand with no social profiles. The
        // server takes the tenant from the PAGE, never from here, so this only names WHICH of the tenant's
        // own Sites to read.
        site_id: builderSiteId.value || undefined,
      },
    });
    // Ignore a stale response that lands after a newer edit.
    if (seq !== previewRenderSeq) return;
    const html = body?.html || "";
    // Warnings travel with the render, so they describe the same bytes the visitor gets. Capture them
    // before the identical-HTML early return below, or a no-op re-render would leave them stale.
    structuredDataWarnings.value = body?.warnings?.structured_data || [];
    pageHealthWarnings.value = body?.warnings?.page_health || [];
    // Clear the error HERE, above the identical-HTML early return — same reason the warnings are
    // captured here. A render that now SUCCEEDS but produces the same bytes would otherwise leave a
    // stale failure on screen: enabling a flash sale fails, setting its end date fixes it, but the
    // standard preview is unchanged (flash pricing only shows in the /flash-sale context), so the
    // banner never went away.
    previewError.value = "";
    if (html === previewHtml.value) return;  // nothing changed: don't reload and lose the scroll position
    capturePreviewScroll();
    previewHtml.value = html;
  } catch (err) {
    if (seq !== previewRenderSeq) return;
    previewError.value = err.message || "Preview render failed.";
  }
}

// The builder is keystroke-reactive but the renderer is a network call, so debounce. The watch key omits
// created_at/updated_at — buildBuilderPageDocument() stamps those on every call and would loop forever.
watch(
  () => {
    const doc = buildBuilderPageDocument();
    if (!doc) return "";
    const { created_at, updated_at, ...stable } = doc;
    // If the chosen preview context got toggled off, fall back to Standard before rendering.
    if (!previewContextOptions.value.some((o) => o.value === previewContext.value)) previewContext.value = "standard";
    return JSON.stringify([stable, builderOffer.value, builderOfferProducts.value, previewContext.value, openFunnelStep.value]);
  },
  () => {
    clearTimeout(previewRenderTimer);
    previewRenderTimer = setTimeout(renderPreview, 400);
  },
  { immediate: true },
);
const previewRefundPolicy = computed(() => builderOffer.value?.refund_policy || builderOfferProducts.value[0]?.refund_policy || null);
const emptyStateText = computed(() => {
  if (pages.value.length) return "No landing pages match your search.";
  return pagesLoaded.value ? "No landing pages found. Create a page to get started." : 'Click "Load Pages" to view your landing pages.';
});
// One universal template for every offer type; the offer's CTA drives the on-page experience, not a template swap.
const presetOptions = computed(() => universalBundlePresets);
const selectedTemplateLabel = computed(() => "Universal Bundle");
const selectedPresetLabel = computed(() => presetOptions.value.find((option) => option.value === form.preset)?.label || "None");
// The EDIT builder's preset, surfaced on the Page Settings row. Reads the same list the picker renders
// from, so a preset added there shows up here with no second place to update.
const builderPresetLabel = computed(() => universalBundlePresets.find((option) => option.value === builder.preset)?.label || "");
// Goal step. Options come from composition_rules.json, so adding a goal there surfaces it here — the
// wizard never hardcodes the list (plans/LANDING_PAGE_GOAL_COMPOSITION.md).
const goalOptions = computed(() => supportedGoals());
// What a goal starts the page with, in the tenant's words (element labels, not section keys).
function goalSeedLabels(goal) {
  return packSeeds(goal).map((type) => elementLabel(type));
}
// The section list the composer will produce for this offer_type + goal, shown on Review before the
// builder opens. Governed sections come from the composer; the goal's packs add their seeded content.
const wizardSectionLabels = computed(() => {
  const offerType = deriveOfferType(selectedOffer.value);
  const governed = recommendedSectionKeys(offerType, form.goal).map((key) => elementLabel(key));
  return [...governed, ...goalSeedLabels(form.goal)];
});
const siteFilter = ref("");  // "" = all, "__none__" = unattached, else a site_id
// Resolve a catalog id for THIS screen's stores; the composable owns the rules (see Offers.vue, same shape).
function resolveItemProduct(id) {
  return productsById.value.get(id) || servicesById.value.get(id) || null;
}
// The offer a page renders, plus everything in that offer, as searchable text.
function pageOfferSearchText(page) {
  const offer = offers.value.find((entry) => entry.offer_id === page.offer_id);
  if (!offer) return "";
  return [offer.name, offer.slug, searchableItemText(offer, resolveItemProduct)].filter(Boolean).join(" ");
}

// What a page is searchable by. `route.slug` and the template label are derived, so they are function
// fields; the offer join comes in as extraText below.
const PAGE_SEARCH_FIELDS = [
  "name",
  "page_id",
  "offer_id",
  (page) => page?.route?.slug,
  (page) => templateLabel(page),
  "status",
];

const filteredPages = computed(() => filterRows(pages.value, {
  term: search.value,
  fields: PAGE_SEARCH_FIELDS,
  // A page is only findable by its own fields otherwise — not by the OFFER it renders, nor by any product
  // in that offer. Searching "Whey Protein" found nothing here (plans/OFFER_ITEM_VISIBILITY.md).
  extraText: pageOfferSearchText,
  // The Site filter is this screen's own predicate: "__none__" means pages attached to no Site at all,
  // which is a real state and not the same as "no filter".
  where: siteFilter.value
    ? (page) => {
        const site = siteForPage(page);
        return siteFilter.value === "__none__" ? !site : site?.site_id === siteFilter.value;
      }
    : null,
}));
const wizardOffers = computed(() => {
  const term = offerSearch.value.toLowerCase();
  const activeOffers = offers.value.filter((offer) => offer.status !== "archived");
  if (!term) return activeOffers;
  return activeOffers.filter((offer) => [
    offer.name,
    offer.offer_id,
    offer.slug,
    offer.product_intent,
    productSummary(offer),
  ].filter(Boolean).join(" ").toLowerCase().includes(term));
});
const draftPage = computed(() => buildPageDocument());
const builderPageDocument = computed(() => buildBuilderPageDocument());
const isBuilderPublished = computed(() => builder.status === "published");

// The shareable test link for the currently-previewed view. Only a published page has a short_code, so the
// link (and copy affordance) appears only once published (plans/SALES_FUNNELS.md Phase B). The view segment
// tracks the Standard/Sale/Flash-Sale toggle.
const testShareLink = computed(() => {
  if (!isBuilderPublished.value) return "";
  // Prefer the real, navigable store URL (Standard view) on the Site's platform host / custom domain — a page
  // attached to a Site now serves there in both environments (plans/PLATFORM_HOSTNAME_SERVING.md P3).
  if (previewContext.value === "standard") {
    const siteUrl = sitePublicUrl({ page_id: builder.page_id });
    if (siteUrl) return siteUrl;
  }
  const host = getTestPagesHost();  // {stage}-test.juniorbay.com from app_config
  if (!builder.short_code || !host) return "";
  const seg = previewContext.value === "sale" ? "/sale" : previewContext.value === "flash_sale" ? "/flash-sale" : "";
  return `https://${host}/published/${builder.short_code}${seg}`;
});
const testLinkCopied = ref(false);
async function copyTestShareLink() {
  if (!testShareLink.value || !navigator.clipboard?.writeText) return;
  await navigator.clipboard.writeText(testShareLink.value).catch(() => {});
  testLinkCopied.value = true;
  setTimeout(() => { testLinkCopied.value = false; }, 1500);
}

watch(() => form.template, () => {
  if (!presetOptions.value.length) {
    form.preset = "";
    return;
  }
  if (!presetOptions.value.some((option) => option.value === form.preset)) form.preset = presetOptions.value[0].value;
});

function defaultWizardForm() {
  return {
    page_id: localId("page"),
    thank_you_page_id: localId("page"),
    // "offer" = a landing page for one offer (the classic flow); "storefront" = an offer-less homepage that
    // lists other pages in a catalog grid (plans/SITE_OBJECT.md §2.5b).
    pageKind: "offer",
    offer_id: "",
    name: "",
    slug: "",
    template: "universal_bundle",
    preset: "clean-slate",
    // Second composition axis: why the page exists / where its traffic comes from. Presets which capability
    // packs the page starts with (plans/LANDING_PAGE_GOAL_COMPOSITION.md).
    goal: "",
    storefront: { headline: "", brand: "", nameMode: "", tagline: "", heading: "Shop all", logo_url: "", items: [], autoFill: true, collection_id: "", source: "new", existingCollectionId: "" },
    categoryKey: "",
  };
}

function defaultBuilderForm() {
  return {
    // The tenant's drag order for the free band, as section keys (element instances key by id).
    // Derived from page.sections on load; empty means "use the builder's natural order".
    section_order: [],
    page_id: localId("page"),
    thank_you_page_id: localId("page"),
    offer_id: "",
    offerName: "",
    name: "",
    slug: "",
    template: "universal_bundle",
    preset: "clean-slate",
    // "" = no goal (a page created before the goal axis) — composes from the offer_type base alone.
    goal: "",
    favicon_url: "",
    // Intrinsic dimensions of uploaded page images (rendition-base -> [w, h]) for CLS-free rendering.
    image_dims: {},
    // url -> asset id for images uploaded here, so a baked crop can be re-cropped from the ORIGINAL
    // rather than compounding the previous crop. A pasted URL has none and cannot be cropped.
    image_assets: {},
    // embed url -> tenant-supplied poster image.
    video_posters: {},
    seo_title: "",
    seo_description: "",
    seo_image: "",
    headline: "",
    subheadline: "",
    hero_media_text: "",
    autoplay: false,
    cta_label: "Buy Now",
    countdown: {
      enabled: false,
      duration_minutes: 15,
      start_text: "Offer expires in",
      end_text: "Offer expired",
      start_enabled: true,
      end_enabled: true,
      marquee_seconds: 14,   // lower = faster; the renderer clamps to 3..60
      start_icon: "⏰",
      end_icon: "⏰",
      start_color: "#f97316",
      end_color: "#64748b",
      sticky: true,
      persistent: true,
      transparent: false,
      marquee: false,
    },
    // Sale / Flash-Sale views (plans/SALES_FUNNELS.md P1). Dates are epoch seconds; 0 = unset.
    sale: { enabled: false, ends_at: 0 },
    flash_sale: { enabled: false, starts_on: 0, ends_at: 0 },
    // Post-purchase funnel page copy (plans/SALES_FUNNELS.md P3.5). Every text field is a per-page OVERRIDE:
    // blank falls back to the runtime defaults (upsell_pages.DEFAULT_UPSELL_SCAFFOLD / DEFAULT_THANK_YOU), so
    // placeholders in the editor show the default. thank_you -> post_checkout.thank_you_page copy; upsell ->
    // post_checkout.upsell_scaffold. Only the upsell/downsell/carousel copy matters when offer.funnel carries
    // upsells/downsells; the thank-you copy applies to every transaction funnel.
    post_purchase: {
      thank_you: {
        headline: "", headline_icon: "", subheadline: "", message: "",
        enable_celebration: true,
        enable_next_steps: true, next_steps_title: "",
        next_steps: THANK_YOU_DEFAULT_CARDS.map((card) => ({ ...card })),
        enable_footer: false, footer_headline: "", footer_message: "",
        show_home_button: false, home_button_text: "",
        enable_download: false, download_button_text: "", download_url: "",
      },
      upsell: {
        headline: "", subheadline: "", accept_label: "", decline_label: "", price_label: "",
        downsell_headline: "", downsell_note: "",
        countdown_enabled: true, countdown_minutes: 1, savings_badge: true,
        carousel_headline: "", carousel_subheadline: "", carousel_add_label: "",
        carousel_dismiss_label: "", carousel_proceed_label: "", downsell_carousel_headline: "",
      },
    },
    trust_badges: {
      enabled: true,
      badges: [
        { enabled: true, emoji: "🚀", label: "Fast Checkout" },
        { enabled: true, emoji: "✅", label: "Satisfaction Guarantee" },
        { enabled: true, emoji: "🇺🇸", label: "Ships from USA" },
      ],
    },
    refund_policy: {
      enabled: true,
    },
    // Socialite hero overlays (plans/SOCIALITE_PARITY.md).
    avatar_url: "",
    avatar_placement: "overlay",
    show_identity: false,
    tagline: "",
    brand_overlay: false,
    brand_position: "top-right",
    brand_dot_pulse: false,
    brand_label_text: "",
    // Advanced Color Settings (plans/ADVANCED_COLOR_SETTINGS.md): per-token overrides on top of the preset
    // (compact map, keyed by theme token -> hex). Empty = pure preset. Persisted as page.theme.tokens.
    advanced_appearance: false,
    theme_tokens: {},
    // Per-page font override (plans/FONT_SERVICE.md): role -> family, persisted as page.theme.fonts and
    // beating both the preset and the tenant default. Empty = whatever the preset proposes.
    theme_fonts: {},
    // Per-ASSET alt text (page.image_alts), keyed by the stored image URL. The server normalises each key
    // to its rendition base, so one description covers every size of the same upload.
    image_alts: {},
    // Page Composer overrides: the tenant's deviations from the offer_type section defaults (compact map,
    // keyed by section key -> { enabled }). Empty = pure offer_type defaults.
    composition: {
      overrides: {},
    },
    elements: [],
    google_tag_id: "",
    pixel_id: "",
    status: "draft",
    published_at: null,
    short_code: "",
    created_at: 0,
    revision: 1,
  };
}

function resetWizard() {
  Object.assign(form, defaultWizardForm());
  wizardStep.value = 1;
  wizardError.value = "";
  offerSearch.value = "";
  editingOfferlessOriginal.value = null;
  sitePhase.value = false;
  selectedSiteId.value = "";
  pendingSiteAttach.value = "";
  siteStepError.value = "";
  siteCreateOpen.value = false;
  newSiteName.value = "";
  newSiteSubdomain.value = "";
  siteAvailable.value = false;
  siteNormalized.value = "";
}

// Load on first search-box focus so filtering works without clicking Load Pages first (mirrors Products).
function ensurePagesLoaded() {
  if (!pagesLoaded.value && !loading.value) loadPages();
  loadBusinessEmailState();
}

// Auto-load the pages list on mount so it's fresh immediately — and, since this view is keyed on the
// environment, it reloads on an env switch (Vue remounts → this re-runs). Mirrors Products.
// The tenant's Configuration → Page Defaults, used to seed a page's funnel copy (SALES_FUNNELS.md P3.5). Loaded
// once so new pages inherit the tenant's preferred wording instead of the platform defaults.
const tenantPageDefaults = ref({});
async function loadTenantPageDefaults() {
  try {
    const body = await apiRequest("/config");
    tenantPageDefaults.value = (body.config || {}).page_defaults || {};
  } catch {
    tenantPageDefaults.value = {};
  }
}
onMounted(() => { ensurePagesLoaded(); loadTenantPageDefaults(); loadTenantFonts(); });

async function loadPages() {
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    const catalogPromise = ensureCatalogLoaded().catch((err) => {
      message.value = err.message || "Catalog context could not be loaded. Landing pages will show without offer details.";
    });
    sitesStore.load().catch(() => {});  // resolve each page's owning Site (fresh per env; non-blocking)
    const pagesPromise = apiRequest("/pages");
    const body = await pagesPromise;
    pages.value = Array.isArray(body.pages) ? body.pages : [];
    pagesLoaded.value = true;
    const activeCount = pages.value.filter((page) => page.status !== "archived").length;
    // No "N landing pages loaded." banner — the list itself is the feedback, and the blue box was pure
    // chrome above the builder. Action confirmations (saved/attached/published) still set `message`.
    catalogPromise.catch(() => {});
  } catch (err) {
    error.value = err.message || "Failed to load landing pages.";
  } finally {
    loading.value = false;
  }
}

async function ensureCatalogLoaded() {
  await Promise.all([ensureProductsLoaded(), ensureServicesLoaded(), ensureOffersLoaded()]);
}

async function ensureOffersLoaded() {
  if (offers.value.length || offersLoading.value) return;
  offersLoading.value = true;
  try {
    const body = await apiRequest("/offers");
    offers.value = Array.isArray(body.offers) ? body.offers : [];
  } finally {
    offersLoading.value = false;
  }
}

async function ensureProductsLoaded() {
  if (products.value.length || productsLoading.value) return;
  productsLoading.value = true;
  try {
    const body = await apiRequest("/products");
    products.value = Array.isArray(body.products) ? body.products : [];
  } finally {
    productsLoading.value = false;
  }
}

async function ensureServicesLoaded() {
  if (services.value.length || servicesLoading.value) return;
  servicesLoading.value = true;
  try {
    const body = await apiRequest("/services");
    services.value = Array.isArray(body.services) ? body.services : [];
  } finally {
    servicesLoading.value = false;
  }
}

async function openWizard() {
  resetWizard();
  sitePhase.value = true;  // choose a Site before choosing a page type
  wizardOpen.value = true;
  try {
    await Promise.all([ensureCatalogLoaded(), sitesStore.ensureLoaded(), profileStore.ensureLoaded(), collectionsStore.ensureLoaded()]);
  } catch (err) {
    wizardError.value = err.message || "Failed to load offers.";
  }
  // Preselect the only Site so the common single-Site case is one click; force inline create when there are none.
  if (!sitesStore.sites.length) {
    siteCreateOpen.value = true;
    seedInlineSiteFields();
  } else if (sitesStore.sites.length === 1) {
    selectedSiteId.value = sitesStore.sites[0].site_id;
  }
}

function seedInlineSiteFields() {
  // Seed the Site name from the business profile; StoreAddressField derives + checks the address from it.
  if (!newSiteName.value) newSiteName.value = profileStore.business?.name || "";
}

function selectExistingSite(siteId) {
  selectedSiteId.value = siteId;
  siteCreateOpen.value = false;
  siteStepError.value = "";
}

function openInlineSiteCreate() {
  siteCreateOpen.value = true;
  selectedSiteId.value = "";
  seedInlineSiteFields();
}

async function createInlineSite() {
  siteStepError.value = "";
  creatingSite.value = true;
  try {
    const business = { ...(profileStore.business || {}), name: newSiteName.value || profileStore.business?.name };
    const site = await sitesStore.createDefault([], business, siteNormalized.value || newSiteSubdomain.value);
    selectedSiteId.value = site.site_id;
    siteCreateOpen.value = false;
  } catch (err) {
    siteStepError.value = err.message || "Failed to create the Site.";
  } finally {
    creatingSite.value = false;
  }
}

function leaveSiteStep() {
  if (!selectedSiteId.value) {
    siteStepError.value = "Choose a Site (or create one) to continue.";
    return;
  }
  sitePhase.value = false;
  wizardStep.value = 1;
}

function backFromStep() {
  if (isEditingOfferless.value) return closeWizard();
  if (wizardStep.value === 1) {
    sitePhase.value = true;  // back to the Site picker
    return;
  }
  wizardStep.value--;
}

function closeWizard() {
  wizardOpen.value = false;
}

function backToList() {
  builderOpen.value = false;
  builderExistingPageId.value = "";
  builderOriginalPage.value = null;
  builderFormHidden.value = false;
}

function selectOffer(offer) {
  form.offer_id = offer.offer_id;
  const baseName = offer.name || "Landing Page";
  form.name = `${baseName} Landing Page`;
  form.slug = slugify(offer.slug || baseName);
  form.template = "universal_bundle";
  form.preset = "clean-slate";
}

function nextWizardStep() {
  wizardError.value = "";
  if (form.pageKind !== "offer") {
    wizardStep.value = 2;  // offer-less kinds are a two-step flow: pick kind, then configure + create
    return;
  }
  if (wizardStep.value === 1 && !selectedOffer.value) {
    wizardError.value = "Choose an offer before continuing.";
    return;
  }
  if (wizardStep.value === 1 && selectedOfferIsSocialPage.value) {
    // Skip the goal step entirely rather than showing it pre-answered: an option nobody should change is
    // a question that should not be asked.
    form.goal = "minimal";
    wizardStep.value = 3;
    return;
  }
  if (wizardStep.value === 2 && !form.goal) {
    wizardError.value = "Choose a goal before continuing.";
    return;
  }
  wizardStep.value += 1;
}

const wizardTotalSteps = computed(() => (form.pageKind === "offer" ? 4 : 2));
// The Site picker is a prepended step 1; the numbered build steps shift to 2..N+1 for display only
// (internal wizardStep stays 1..N so the existing step logic is untouched).
// A skipped step must not leave a hole in the count: without this a Social Page read "Step 2 of 5" and
// then "Step 4 of 5", which looks like the wizard lost one.
const wizardSkipsGoal = computed(() => form.pageKind === "offer" && selectedOfferIsSocialPage.value);
const displayTotal = computed(() => wizardTotalSteps.value + 1 - (wizardSkipsGoal.value ? 1 : 0));
const displayStep = computed(() => {
  if (sitePhase.value) return 1;
  const step = wizardStep.value + 1;
  return wizardSkipsGoal.value && wizardStep.value > 2 ? step - 1 : step;
});

// Distinct product categories the tenant actually uses (so a category page's key matches denormalized
// landing pages). Keys stay normalized; labels are humanized for display.
const storefrontCategories = computed(() => {
  const seen = new Map();
  for (const p of products.value || []) {
    const key = String(p?.product_category || "").trim();
    if (key && !seen.has(key)) seen.set(key, categoryLabel(key));
  }
  return [...seen.entries()].map(([key, label]) => ({ key, label })).sort((a, b) => a.label.localeCompare(b.label));
});

function categoryLabel(key) {
  return String(key || "").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function selectCategoryKind() {
  form.pageKind = "category";
  ensureProductsLoaded();  // populate the category picker
}

// Pages that can appear in a storefront grid: an offer-backed page (has an offer_id) with a slug to link to.
// Storefront pages themselves (no offer) are excluded — a grid links to sellable pages, not to other grids.
// page_id -> owning Site {site_id, name}, from the Sites' route maps (a page belongs to at most one Site).
const siteByPageId = computed(() => {
  const map = {};
  for (const s of sitesStore.sites) {
    for (const entry of Object.values(s.pages || {})) {
      if (entry && entry.page_id) map[entry.page_id] = { site_id: s.site_id, name: s.name || s.site_id };
    }
  }
  return map;
});
function siteForPage(page) {
  return siteByPageId.value[page?.page_id] || null;
}
// The Site the page being built belongs to, for preview identity. Attached wins; a page that has not been
// saved yet is not attached to anything, so the wizard's choice stands in. A tenant with exactly one Site
// gets it without having chosen -- reopening an older page has neither of the first two, and guessing wrong
// is impossible when there is only one to guess.
// The profiles this page's social_links section will actually render. Read from the SAME Site the preview
// resolves, so the editor and the preview cannot disagree about whether there is anything to show.
const builderSiteProfiles = computed(() => {
  const site = sitesStore.sites.find((s) => s.site_id === builderSiteId.value);
  return ((site?.organization || {}).same_as || []).filter((entry) => (entry?.url || "").trim());
});
// A link page whose Site is only a PROMISE. The preview reads the Site the page will attach to, which is the
// right thing to render and the wrong thing to leave unexplained: the published artifact reads attachment,
// which this page does not have yet. Scoped to lead_social because it is the only shape where the Site is not
// the identity around the content but the content itself -- every other page still says something on its own.
// Silent once the page lists its OWN links: then the preview and the published page agree, and there is
// nothing left to warn about.
const previewNeedsSite = computed(() =>
  builderOfferType.value === "lead_social"
  && !siteByPageId.value[builder.page_id]
  && !!builderSiteId.value
  && !builder.elements.some((el) => el.type === "social_links" && (el.items || []).some((i) => (i.url || "").trim())));
// Per-link clicks for the page in the builder, keyed by URL (plans/SOCIAL_MEDIA_PAGES.md §11). Fetched
// lazily when a link page is opened rather than attached to the listing: it is one query per page, so the
// listing would pay for it on every row while only a link hub has anything to show. The server resolves ids
// to URLs -- the id is a hash we own, and the dashboard should never have to reproduce it to read its own
// numbers.
const linkClicks = ref({});
async function loadLinkClicks(pageId) {
  linkClicks.value = {};
  if (!pageId) return;
  try {
    const body = await apiRequest(`/pages/${encodeURIComponent(pageId)}`);
    linkClicks.value = body?.page?.link_clicks || {};
  } catch (err) {
    // Numbers are decoration on a builder. Never let them stop a tenant editing the page.
    linkClicks.value = {};
  }
}
function linkClicksFor(url) {
  const key = (url || "").trim();
  return key && Object.prototype.hasOwnProperty.call(linkClicks.value, key) ? linkClicks.value[key] : null;
}
const builderSiteName = computed(() =>
  sitesStore.sites.find((s) => s.site_id === builderSiteId.value)?.name || "");
// Mirrors the renderer's §7 boundary (linkable_on_platform_host): on the tenant's OWN domain any destination
// may be linked because the reputation at stake is theirs; on shared platform infrastructure only allowlisted
// profile hosts become anchors. Said in the editor so a creator learns it while typing the link, not by
// finding a dead tile on a published page.
const builderSiteHasCustomDomain = computed(() => {
  const hosting = sitesStore.sites.find((s) => s.site_id === builderSiteId.value)?.hosting || {};
  return hosting.type === "custom" && !!(hosting.verification || {}).verified;
});
const builderSiteId = computed(() => {
  const attached = siteByPageId.value[builder.page_id];
  if (attached) return attached.site_id;
  if (pendingSiteAttach.value) return pendingSiteAttach.value;
  return sitesStore.sites.length === 1 ? sitesStore.sites[0].site_id : "";
});
function siteNameForPage(page) {
  return siteForPage(page)?.name || "";
}
// The page's real public URL when it's on a Site with a VERIFIED custom domain: https://domain/slug (homepage
// at "/"). Only verified (prod) Sites qualify — custom domains are live-only — so this never shows a dead URL.
function sitePublicUrl(page) {
  for (const s of sitesStore.sites) {
    const hosting = s.hosting || {};
    // The Site's navigable host: a verified custom domain if connected, else its free platform host
    // ({label}.jbay.uk / .jbay.be), which now serves in BOTH environments (platform-hostname serving).
    const host = (hosting.custom_domain && hosting.verification?.verified) ? hosting.custom_domain : hosting.platform_hostname;
    if (!host) continue;
    for (const [slug, entry] of Object.entries(s.pages || {})) {
      if (entry?.page_id === page.page_id) return `https://${host}${slug === "/" ? "/" : slug}`;
    }
  }
  return "";
}
// The store URL a not-yet-published, Site-attached page WILL serve at once published — surfaced as a muted "will
// publish to" hint so the tenant sees its real {site}.jbay.uk/slug home instead of only the preview-artifact URL.
// "" for published pages (their live URL is already the main line) and for unattached drafts (no Site home yet).
// Not made actionable (Copy/Preview stay on the working render) because this URL 404s until the page is published.
function pendingSiteUrl(page) {
  if (!page || page.status === "published") return "";
  return sitePublicUrl(page);
}
// Slug shown on the metrics row, capped so a long slug can't blow out the card (full value on hover via title).
function displaySlug(page) {
  const slug = `/${page.route?.slug || ""}`;
  return slug.length > 32 ? `${slug.slice(0, 31)}…` : slug;
}

// The Site this storefront belongs to (editing) or is being attached to (creating, once chosen). Its route map
// is the source of truth for which products can appear in the grid + at what slug.
const storefrontSite = computed(() => {
  if (selectedSite.value) return selectedSite.value;  // full Site chosen in the attach phase (create flow)
  // Editing: resolve the FULL Site that owns this storefront page (siteByPageId only holds {site_id, name}).
  const siteId = form.page_id ? siteByPageId.value[form.page_id]?.site_id : "";
  return siteId ? sitesStore.sites.find((s) => s.site_id === siteId) || null : null;
});
// link_cards mirrors the renderer's rule exactly: html.py treats a page as "on a custom domain" only when
// _RENDER_STATE.home_url is set, and that happens only for a VERIFIED custom domain. Anything looser here
// would promise the tenant clickable links the published page then refuses to render.
const onCustomDomainForLinks = computed(() => {
  const hosting = storefrontSite.value?.hosting || {};
  return Boolean(hosting.custom_domain && hosting.verification?.verified);
});
const hostingSuffixHint = computed(() => sitesStore.hostingDomain || "jbay.uk");

const siteSlugByPageId = computed(() => {
  const m = new Map();
  for (const [slug, entry] of Object.entries(storefrontSite.value?.pages || {})) {
    if (entry?.page_id) m.set(entry.page_id, slug);
  }
  return m;
});
// Only pages attached to THIS Site can appear in the grid — the published grid links to Site slugs, so an
// off-Site page would dead-end (the publisher drops it). Until a Site is chosen (create flow) we can't filter,
// so show all offer pages; the backend still resolves against the Site at publish.
const storefrontCandidatePages = computed(() => {
  const all = (pages.value || []).filter((p) => p && p.offer_id && (p.route?.slug || p.name));
  const site = storefrontSite.value;
  if (!site) return all;
  return all.filter((p) => siteSlugByPageId.value.has(p.page_id));
});

// Existing collections on the storefront's Site — so a new storefront page can EMBED one that already exists
// (reuse) instead of always minting its own (plans/SITE_COLLECTIONS.md — collections are reusable playlists).
const siteCollections = computed(() => {
  const siteId = storefrontSite.value?.site_id || selectedSiteId.value;
  return siteId ? collectionsStore.forSite(siteId) : [];
});
function collectionRuleLabel(c) {
  if (c.rule === "all") return "all products";
  if (c.rule === "category") return `category: ${categoryLabel(c.category || "—")}`;
  return `${(c.members || []).length} pages`;
}
// How many published/draft pages embed a given collection — so editing a SHARED collection routes through the
// reference (don't silently mutate a collection other pages depend on).
function collectionUsageCount(collectionId) {
  if (!collectionId) return 0;
  let n = 0;
  for (const p of pages.value || []) {
    if ((p.sections || []).some((s) => s && s.type === "catalog_grid" && s.collection_id === collectionId)) n += 1;
  }
  return n;
}

const creatingStorefront = ref(false);
// When set, the offer-less wizard is EDITING this existing page (merge into it) rather than creating a new one.
const editingOfferlessOriginal = ref(null);
const isEditingOfferless = computed(() => !!editingOfferlessOriginal.value);

// Build the final offer-less page doc: a fresh draft when creating, or the original page merged with the
// edited fields (preserving id / status / created_at / theme / analytics / etc.) when editing.
function finalizeOfferlessDoc(sections, { name, slug, title }) {
  const now = Math.floor(Date.now() / 1000);
  const base = editingOfferlessOriginal.value || {
    schema_version: "2026-05-29",
    document_type: "page",
    tenant_id: getTenantId(),
    page_id: form.page_id,
    status: "draft",
    published_at: null,
    theme: { template: "universal_bundle", preset: form.preset || "clean-slate" },
    created_at: now,
    revision: 0,
  };
  return cleanObject({
    ...base,
    name,
    route: { ...(base.route || {}), slug: slugify(slug || name) },
    seo: { ...(base.seo || {}), title },
    sections,
    revision: (base.revision || 0) + 1,
    created_at: base.created_at || now,
    updated_at: now,
  });
}

function isStorefrontPage(page) {
  // Offer-less pages (storefront / category / profile) can't hydrate the offer-builder — guard them out.
  if (!page) return false;
  if (!page.offer_id) return true;
  return (page.sections || []).some((s) => s && (s.type === "catalog_grid" || s.type === "seller_profile" || s.type === "brand_hero"));
}

// Storefront headline source: an existing business brand (dropdown) OR a typed custom store name (textbox) —
// mutually exclusive. With no brands set up, it's always the custom name; when brands exist the tenant chooses.
const storeBrands = computed(() => profileStore.brands || []);
// Effective mode: honor an explicit choice, else default to "brand" when brands exist, "custom" otherwise.
const storefrontNameMode = computed(() => form.storefront.nameMode || (storeBrands.value.length ? "brand" : "custom"));
// The selected brand, defaulting to the first one so the dropdown is never blank.
const storefrontBrand = computed({
  get: () => form.storefront.brand || storeBrands.value[0] || "",
  set: (v) => { form.storefront.brand = v; },
});
// The resolved store name for the brand_hero headline + <title>.
const storefrontName = computed(() => (storefrontNameMode.value === "brand" ? storefrontBrand.value : form.storefront.headline));
function setStorefrontNameMode(mode) {
  form.storefront.nameMode = mode;
}

// Auto-fill the internal page name from the store name so tenants don't have to name it twice. We only overwrite
// while form.name is still empty or matches the previous auto-value — the moment the user types their own name we
// stop touching it. Storefront/category only (offer pages name themselves from the offer).
const lastAutoPageName = ref("");
watch(storefrontName, (name) => {
  if (form.pageKind !== "storefront") return;
  const suggested = (name || "").trim() ? `${name.trim()} homepage` : "";
  if (!form.name || form.name === lastAutoPageName.value) {
    form.name = suggested;
    lastAutoPageName.value = suggested;
  }
});

// Soft, non-blocking notice when another of the tenant's storefronts already uses this store name. There's no
// hard uniqueness on the display name (two Sites can legitimately differ by address, not name), so we only warn.
const dupNameDismissed = ref("");
const duplicateStoreName = computed(() => {
  if (form.pageKind !== "storefront") return "";
  const name = (storefrontName.value || "").trim().toLowerCase();
  if (!name) return "";
  const clash = (pages.value || []).some((p) => {
    if (p.page_id === form.page_id || !isStorefrontPage(p)) return false;
    const bh = (p.sections || []).find((s) => s && s.type === "brand_hero");
    return String(bh?.headline || "").trim().toLowerCase() === name;
  });
  return clash ? storefrontName.value : "";
});
const showDupNameWarning = computed(() => !!duplicateStoreName.value && duplicateStoreName.value !== dupNameDismissed.value);

// Storefront logo upload — reuses the shared uploadImage() service (same as builder/sub-item images).
const storefrontLogoUploading = ref(false);
const storefrontLogoError = ref("");
async function onStorefrontLogoPicked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  storefrontLogoError.value = "";
  storefrontLogoUploading.value = true;
  try {
    form.storefront.logo_url = await uploadPageImage(file);
  } catch (err) {
    storefrontLogoError.value = err.message || "Logo upload failed.";
  } finally {
    storefrontLogoUploading.value = false;
  }
}

// Build (or update) the Collection a storefront/category grid embeds, from the wizard's grid config
// (plans/SITE_COLLECTIONS.md P1e). A storefront: rule 'all' (auto-fill) or 'manual' (the picked page ids); a
// category page: rule 'category'. Pure data — no slug. Its id is reused when editing an existing collection.
function buildOfferlessCollection(kind) {
  const heading = form.storefront.heading || "";
  const collection = {
    document_type: "collection",
    site_id: storefrontSite.value?.site_id || selectedSiteId.value || "",
    name: heading || (kind === "category" ? categoryLabel(form.categoryKey) : (storefrontName.value || "Products")),
  };
  if (form.storefront.collection_id) collection.collection_id = form.storefront.collection_id;  // update in place
  if (kind === "category") {
    collection.rule = "category";
    collection.category = form.categoryKey;
  } else if (form.storefront.autoFill !== false) {
    collection.rule = "all";  // fills from every offer page on the Site at publish
  } else {
    collection.rule = "manual";
    collection.members = [...(form.storefront.items || [])];  // ordered page_id references
  }
  if (heading) collection.presentation = { heading };
  return collection;
}

// The storefront page is a brand-hero + a catalog_grid that EMBEDS the collection (its items resolve from the
// Collection at publish). The grid holds no inline items — the Collection is the source of truth.
function buildStorefrontPageDocument(collectionId) {
  const headline = storefrontName.value || form.name || "Storefront";
  return finalizeOfferlessDoc([
    { id: "brand-hero", type: "brand_hero", headline, tagline: form.storefront.tagline || undefined, logo_url: form.storefront.logo_url || undefined },
    { id: "catalog-grid", type: "catalog_grid", collection_id: collectionId, heading: form.storefront.heading || undefined },
  ], { name: form.name || "Storefront homepage", slug: form.slug || form.name || "home", title: headline });
}

// Attach a page to a Site's route map. A storefront becomes the Site's homepage (slug "/"); every other
// kind attaches at its own slug. Throws on failure (callers decide how to surface it).
function attachPageToSiteCore(page, siteId, kind, category) {
  if (kind === "storefront") {
    return sitesStore.setHomepage(siteId, page.page_id, page.tenant_id);
  }
  const slug = `/${slugify(page.route?.slug || page.name || page.page_id)}`;
  const pageType = kind === "category" ? "category" : kind === "profile" ? "about" : "landing";
  return sitesStore.attachPage(
    siteId,
    { pageId: page.page_id, slug, pageType, category: kind === "category" ? category : undefined },
    page.tenant_id,
  );
}

// Bind a freshly-created page to the chosen Site (the wizard's step 1). Non-fatal: the page is already
// created, so a failed attach only degrades to "attach it on the Sites screen".
async function attachCreatedPageToSite(saved, siteId, kind, category) {
  if (!siteId || !saved?.page_id) return true;
  try {
    await attachPageToSiteCore(saved, siteId, kind, category);
    return true;
  } catch (err) {
    wizardError.value = `Page created, but attaching it to the Site failed: ${err.message || err}. Attach it on the Sites screen.`;
    return false;
  }
}

// Infer how an existing page should attach to a Site, from its own sections (mirrors the wizard's kinds).
function pageAttachKind(page) {
  const sections = page?.sections || [];
  if (sections.some((s) => s && s.type === "seller_profile")) return "profile";
  const grid = sections.find((s) => s && s.type === "catalog_grid");
  if (grid?.category) return "category";
  if (grid && sections.some((s) => s && s.type === "brand_hero")) return "storefront";
  return "offer";
}

const attachTarget = ref(null);   // the page awaiting a Site choice in the attach modal
const attachSiteId = ref("");
const pendingDetachPage = ref(null);

function openAttachSite(page) {
  openMenuId.value = "";
  attachTarget.value = page;
  attachSiteId.value = sitesStore.sites[0]?.site_id || "";
}

async function confirmAttachSite() {
  const page = attachTarget.value;
  const siteId = attachSiteId.value;
  if (!page || !siteId) return;
  error.value = "";
  try {
    const kind = pageAttachKind(page);
    const category = kind === "category" ? (page.sections.find((s) => s && s.type === "catalog_grid") || {}).category : undefined;
    await attachPageToSiteCore(page, siteId, kind, category);
    message.value = `Attached “${page.name || "page"}” to ${sitesStore.sites.find((s) => s.site_id === siteId)?.name || "the Site"}.`;
    attachTarget.value = null;
  } catch (err) {
    error.value = err.message || "Failed to attach the page to the Site.";
  }
}

// After a page is published, make sure it has a home Site so it serves on a real store URL ({site}.jbay.uk/slug)
// instead of the bare artifact viewer. One Site → attach silently; several → let the tenant pick (the existing
// attach modal); none → leave it (nothing to attach to yet). Non-fatal: the page is already published, and attach
// stays available from the menu. Returns the Site name it auto-attached to, else "" (attachPage._replace refreshes
// the store, so the list badge + nice URL update reactively). See plans/TODO.md "Auto-attach a page … on Publish".
async function ensureSiteAttachmentOnPublish(page) {
  try {
    if (!page || page.status !== "published") return "";
    await sitesStore.ensureLoaded();
    if (siteForPage(page)) return "";                 // already has a home
    const sites = sitesStore.sites;
    if (sites.length === 0) return "";                // no Site to attach to; serves via the artifact viewer for now
    if (sites.length === 1) {
      const kind = pageAttachKind(page);
      const category = kind === "category"
        ? (page.sections?.find((s) => s && s.type === "catalog_grid") || {}).category
        : undefined;
      await attachPageToSiteCore(page, sites[0].site_id, kind, category);
      return sites[0].name || "your Site";
    }
    openAttachSite(page);                              // >1 Site: prompt which one (does not block the publish)
    return "";
  } catch (err) {
    console.warn("Auto-attach on publish failed; attach it from the page menu instead.", err);
    return "";
  }
}

function requestDetachSite(page) {
  openMenuId.value = "";
  pendingDetachPage.value = page;
}

async function detachSite() {
  const page = pendingDetachPage.value;
  const site = siteForPage(page);
  if (!page || !site) {
    pendingDetachPage.value = null;
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await sitesStore.detachPage(site.site_id, page.page_id, page.tenant_id);
    message.value = `Detached “${page.name || "page"}” from ${site.name}.`;
    pendingDetachPage.value = null;
  } catch (err) {
    error.value = err.message || "Failed to detach the page from its Site.";
  } finally {
    saving.value = false;
  }
}

async function createStorefront() {
  wizardError.value = "";
  const reusing = form.storefront.source === "existing";
  if (reusing && !form.storefront.existingCollectionId) {
    wizardError.value = "Choose an existing collection, or switch to “Define products here.”";
    return;
  }
  // Auto-fill needs no upfront items (the grid fills itself from the Site at publish); only curated mode does.
  if (!reusing && form.storefront.autoFill === false && !(form.storefront.items || []).length) {
    wizardError.value = "Pick at least one page for the product grid, or switch on “Show all my products.”";
    return;
  }
  creatingStorefront.value = true;
  try {
    // Reuse: embed an existing Collection by reference (mint nothing). Otherwise save this page's own Collection
    // first (it's the grid's source of truth), then the page that embeds it.
    const collectionId = reusing
      ? form.storefront.existingCollectionId
      : (await collectionsStore.save(buildOfferlessCollection("storefront"))).collection_id;
    form.storefront.collection_id = reusing ? "" : collectionId;
    const document = buildStorefrontPageDocument(collectionId);
    const body = await apiRequest("/pages", { method: "POST", body: document });
    const saved = body.page || document;
    pages.value = [saved, ...pages.value.filter((p) => p.page_id !== saved.page_id)];
    await reflectCascadedMembers(saved);  // editing a published storefront re-publishes it → reflect the cascade
    const attached = isEditingOfferless.value || (await attachCreatedPageToSite(saved, selectedSiteId.value, "storefront"));
    message.value = isEditingOfferless.value
      ? "Storefront homepage saved."
      : `Storefront homepage created and set as ${selectedSite.value?.name || "your Site"}'s homepage. Publish it to go live.`;
    if (attached) closeWizard();
  } catch (error) {
    wizardError.value = error.message || "Failed to create the storefront homepage.";
  } finally {
    creatingStorefront.value = false;
  }
}

function buildCategoryPageDocument(collectionId) {
  const label = categoryLabel(form.categoryKey);
  return finalizeOfferlessDoc([
    { id: "brand-hero", type: "brand_hero", headline: label },
    // A category-driven grid embeds a rule='category' Collection; the publisher fills it from the Site's pages.
    { id: "catalog-grid", type: "catalog_grid", collection_id: collectionId, heading: form.storefront.heading || label },
  ], { name: form.name || `${label} (category)`, slug: form.slug || form.name || label || "category", title: label });
}

function buildProfilePageDocument() {
  const heading = form.storefront.heading || "About our store";
  // Offer-less: the seller_profile section derives its content from the Site Organization at publish.
  return finalizeOfferlessDoc([
    { id: "brand-hero", type: "brand_hero", headline: heading },
    { id: "seller-profile", type: "seller_profile", heading },
  ], { name: form.name || "Store profile", slug: form.slug || form.name || "about", title: heading });
}

async function createProfile() {
  wizardError.value = "";
  creatingStorefront.value = true;
  try {
    const document = buildProfilePageDocument();
    const body = await apiRequest("/pages", { method: "POST", body: document });
    const saved = body.page || document;
    pages.value = [saved, ...pages.value.filter((p) => p.page_id !== saved.page_id)];
    const attached = isEditingOfferless.value || (await attachCreatedPageToSite(saved, selectedSiteId.value, "profile"));
    message.value = isEditingOfferless.value
      ? "Store profile page saved."
      : `Store profile page created and attached to ${selectedSite.value?.name || "your Site"}. Publish it to go live.`;
    if (attached) closeWizard();
  } catch (error) {
    wizardError.value = error.message || "Failed to create the store profile page.";
  } finally {
    creatingStorefront.value = false;
  }
}

async function createCategory() {
  wizardError.value = "";
  if (!form.categoryKey) {
    wizardError.value = "Choose a category.";
    return;
  }
  creatingStorefront.value = true;
  try {
    const collection = await collectionsStore.save(buildOfferlessCollection("category"));
    form.storefront.collection_id = collection.collection_id;
    const document = buildCategoryPageDocument(collection.collection_id);
    const body = await apiRequest("/pages", { method: "POST", body: document });
    const saved = body.page || document;
    pages.value = [saved, ...pages.value.filter((p) => p.page_id !== saved.page_id)];
    const attached = isEditingOfferless.value || (await attachCreatedPageToSite(saved, selectedSiteId.value, "category", form.categoryKey));
    message.value = isEditingOfferless.value
      ? "Category page saved."
      : `Category page created and attached to ${selectedSite.value?.name || "your Site"}. Publish it to go live.`;
    if (attached) closeWizard();
  } catch (error) {
    wizardError.value = error.message || "Failed to create the category page.";
  } finally {
    creatingStorefront.value = false;
  }
}

function startBuilderFromWizard() {
  wizardError.value = "";
  const page = draftPage.value;
  if (!page) {
    wizardError.value = "Page could not be generated.";
    return;
  }
  populateBuilderFromPage(page);
  seedGoalElements(form.goal);
  seedShapeElements();
  builderExistingPageId.value = "";
  builderOriginalPage.value = null;
  pendingSiteAttach.value = selectedSiteId.value;  // attach this offer page to the chosen Site on first save
  builderOpen.value = true;
  builderFormHidden.value = false;
  wizardOpen.value = false;
}

// A goal's packs seed content-bearing elements as EMPTY scaffolds for the tenant to fill. They live in
// builder state, not the draft document: an empty faq/testimonial is not a valid page section (its items
// need answers), and builderSections() drops still-empty elements on save anyway. Once seeded they are
// tenant-owned — nothing re-seeds or retracts them if the goal changes.
function seedGoalElements(goal) {
  for (const type of packSeeds(goal)) {
    if (builder.elements.some((element) => element.type === type)) continue;
    builder.elements.push(newElement(type));
  }
}

// Elements a SHAPE starts with, as opposed to the ones its goal seeds. A link-in-bio page is the case that
// needs this: it has no checkout_cta, so with an empty elements list a brand-new Social Page rendered a
// hero image, a footer, and nothing a visitor could act on -- the tenant reached a builder and had to guess
// that the links were two "+ Add element" clicks away. Seeding is not new machinery; the subheadline was
// already auto-populated from the action's description. It was seeding the OLD meaning of this shape.
//
// Same contract as the goal seeds above: a create-time starting point that becomes the tenant's the moment
// it exists. Nothing re-seeds or retracts if the offer changes, and a type already present is left alone.
//
// lead_call is deliberately NOT here. seller_profile belongs on that shape and the composition says so, but
// it is an ungoverned addable element -- and it renders the Site's NAP whether or not the page asks for it,
// so seeding one would put the same block on the page twice.
const SHAPE_SEEDS = {
  lead_social: ["social_links", "link_cards"],
};

function seedShapeElements() {
  for (const type of SHAPE_SEEDS[builderOfferType.value] || []) {
    if (builder.elements.some((element) => element.type === type)) continue;
    builder.elements.push(newElement(type));
  }
}

async function savePage() {
  wizardError.value = "";
  if (!draftPage.value) {
    wizardError.value = "Page could not be generated.";
    return;
  }
  saving.value = true;
  try {
    const body = await apiRequest("/pages", { method: "POST", body: draftPage.value });
    const saved = body.page || draftPage.value;
    pages.value = [saved, ...pages.value.filter((page) => page.page_id !== saved.page_id)];
    pagesLoaded.value = true;
    // A page created via the wizard→builder flow attaches to the Site chosen in step 1 (once, on first save).
    if (pendingSiteAttach.value && !builderExistingPageId.value) {
      await attachCreatedPageToSite(saved, pendingSiteAttach.value, "offer");
      const siteName = sitesStore.sites.find((s) => s.site_id === pendingSiteAttach.value)?.name;
      pendingSiteAttach.value = "";
      message.value = `${saved.name} was saved and attached to ${siteName || "your Site"}.`;
    } else {
      message.value = `${saved.name} was saved.`;
    }
    wizardOpen.value = false;
  } catch (err) {
    wizardError.value = err.message || "Failed to save landing page.";
  } finally {
    saving.value = false;
  }
}

function populateBuilderFromPage(page) {
  const offer = offers.value.find((item) => item.offer_id === page.offer_id);
  const sections = Array.isArray(page.sections) ? page.sections : [];
  const countdown = sections.find((section) => section.type === "countdown_timer") || {};
  const hero = sections.find((section) => section.type === "hero") || {};
  const heroMedia = sections.find((section) => section.type === "hero_media") || {};
  const trustBadges = sections.find((section) => section.type === "trust_badges") || {};
  const refundPolicy = sections.find((section) => section.type === "refund_policy") || {};
  const cta = sections.find((section) => section.type === "checkout_cta") || {};
  Object.assign(builder, defaultBuilderForm(), {
    // The tenant's OWN arrangement, and nothing else. Absent until they actually drag something, which
    // is what lets baseline_order(goal) govern a page nobody has rearranged. This used to be derived
    // from the saved sections array — which made every page a fixed point, since whatever order it
    // happened to be saved with came back as "the tenant's order" and the baseline never got a look in.
    section_order: Array.isArray(page.section_order) ? page.section_order.filter((k) => typeof k === "string") : [],
    // Absent means "derive from the shape", which is why this reads the default rather than defaulting to true.
    breadcrumb: typeof page.chrome?.breadcrumb === "boolean" ? page.chrome.breadcrumb : undefined,
    page_id: page.page_id || localId("page"),
    thank_you_page_id: page.post_checkout?.thank_you_page?.page_id || localId("page"),
    post_purchase: loadPostPurchase(page),
    offer_id: page.offer_id || "",
    offerName: offer?.name || "",
    name: page.name || "",
    slug: page.route?.slug || slugify(page.name || page.page_id),
    template: page.theme?.template || "universal_bundle",
    preset: page.theme?.preset || "clean-slate",
    // Absent on pages created before the goal axis — "" keeps them composing from the base alone.
    goal: page.goal || "",
    favicon_url: page.seo?.favicon_url || "",
    // Drop legacy auto-baked SEO so the page re-derives; a genuine tenant override is preserved.
    seo_title: isAutoBakedSeoTitle(page) ? "" : page.seo.title,
    seo_description: isAutoBakedSeoTitle(page) ? "" : (page.seo?.description || ""),
    seo_image: page.seo?.image || pageImage(page),
    headline: hero.headline || sectionText(sections, "headline") || page.name || "",
    subheadline: hero.subheadline || sectionText(sections, "subheadline") || "",
    hero_media_text: (heroMedia.images || [page.seo?.image || pageImage(page)].filter(Boolean)).join("\n"),
    autoplay: Boolean(heroMedia.autoplay),
    avatar_url: heroMedia.avatar_url || "",
    avatar_placement: heroMedia.avatar_placement || "overlay",
    show_identity: Boolean(heroMedia.show_identity),
    tagline: heroMedia.tagline || "",
    brand_overlay: Boolean(heroMedia.brand_overlay),
    brand_position: heroMedia.brand_position || "top-right",
    brand_dot_pulse: Boolean(heroMedia.brand_dot_pulse),
    brand_label_text: (sections.find((section) => section.type === "brand_label") || {}).label || "",
    cta_label: cta.label || (offerIntentLabel(offer) === "Lead generation" ? "Continue" : "Buy Now"),
    elements: elementsFromPage(sections),
    google_tag_id: page.analytics?.google_tag_id || "",
    pixel_id: page.analytics?.pixel_id || "",
    status: page.status || "draft",
    published_at: page.published_at || null,
    short_code: page.short_code || "",
    created_at: page.created_at || 0,
    revision: page.revision || 1,
  });
  // Restore captured image dimensions so re-saving an untouched page keeps them.
  builder.image_dims = { ...(page.image_dims || {}) };
  builder.image_assets = { ...(page.image_assets || {}) };
  builder.video_posters = { ...(page.video_posters || {}) };
  // Restore the Page Composer overrides so section toggles reflect the tenant's prior choices.
  builder.composition.overrides = { ...(page.composition?.overrides || {}) };
  // Restore Advanced Color Settings overrides; auto-open the panel if any were set.
  builder.theme_tokens = { ...(page.theme?.tokens || {}) };
  builder.theme_fonts = { ...(page.theme?.fonts || {}) };
  builder.image_alts = { ...(page.image_alts || {}) };
  // Open the panel for EITHER kind of override, or a page whose only deviation is a font would look
  // untouched and the tenant would have no way to see what they had set.
  builder.advanced_appearance =
    Object.keys(builder.theme_tokens).length > 0 || Object.keys(builder.theme_fonts).length > 0;
  // Restore Sale / Flash-Sale toggles + dates (plans/SALES_FUNNELS.md P1d).
  Object.assign(builder.sale, defaultBuilderForm().sale, page.sale || {});
  Object.assign(builder.flash_sale, defaultBuilderForm().flash_sale, page.flash_sale || {});
  Object.assign(builder.countdown, defaultBuilderForm().countdown, {
    enabled: Boolean(countdown.id),
    duration_minutes: countdown.duration_minutes || 15,
    start_text: countdown.start_text || countdown.label || "Offer expires in",
    end_text: countdown.end_text || "Offer expired",
    start_enabled: countdown.start_enabled !== false,
    end_enabled: countdown.end_enabled !== false,
    marquee_seconds: Number(countdown.marquee_seconds) || 14,
    start_icon: countdown.start_icon ?? "⏰",
    end_icon: countdown.end_icon ?? "⏰",
    start_color: countdown.start_color || "#f97316",
    end_color: countdown.end_color || "#64748b",
    sticky: countdown.sticky !== false,
    persistent: countdown.persistent !== false,
    transparent: Boolean(countdown.transparent),
    marquee: Boolean(countdown.marquee),
  });
  Object.assign(builder.trust_badges, defaultBuilderForm().trust_badges, {
    enabled: trustBadges.enabled !== false,
    badges: Array.isArray(trustBadges.badges) && trustBadges.badges.length
      ? trustBadges.badges.map((badge) => ({
        ...badge,
        enabled: trustBadges.enabled !== false && badge.enabled !== false,
      }))
      : defaultBuilderForm().trust_badges.badges,
  });
  Object.assign(builder.refund_policy, defaultBuilderForm().refund_policy, {
    enabled: refundPolicy.enabled !== false,
  });
}

// P3.5 post-purchase copy. Text fields are sent only when non-blank (the runtime fills the rest from
// upsell_pages defaults); the countdown/badge toggles are sent only when they DEVIATE from the runtime
// defaults (countdown on, 1 minute, savings badge on), so an untouched funnel persists no scaffold at all.
const UPSELL_SCAFFOLD_TEXT_FIELDS = [
  "headline", "subheadline", "accept_label", "decline_label", "price_label", "downsell_headline", "downsell_note",
  "carousel_headline", "carousel_subheadline", "carousel_add_label", "carousel_dismiss_label",
  "carousel_proceed_label", "downsell_carousel_headline",
];

function thankYouCopyOverrides() {
  const thankYou = builder.post_purchase?.thank_you || {};
  const out = {};
  // Text fields: sent only when non-blank (blank falls back to the runtime default).
  ["headline", "headline_icon", "subheadline", "message", "next_steps_title",
   "footer_headline", "footer_message", "home_button_text", "download_button_text", "download_url"]
    .forEach((key) => { const value = (thankYou[key] || "").trim(); if (value) out[key] = value; });
  // Toggles: sent only when they DEVIATE from the runtime default (celebration/next-steps on; footer/home/
  // download off), so an untouched thank-you page persists nothing.
  if (thankYou.enable_celebration === false) out.enable_celebration = false;
  if (thankYou.enable_next_steps === false) out.enable_next_steps = false;
  if (thankYou.enable_footer === true) out.enable_footer = true;
  if (thankYou.show_home_button === true) out.show_home_button = true;
  if (thankYou.enable_download === true) out.enable_download = true;
  // "What's Next?" cards: sent only when edited away from the defaults.
  const cards = (thankYou.next_steps || [])
    .map((c) => ({ icon: (c.icon || "").trim(), title: (c.title || "").trim(), desc: (c.desc || "").trim() }))
    .filter((c) => c.title || c.desc);
  if (JSON.stringify(cards) !== JSON.stringify(THANK_YOU_DEFAULT_CARDS)) out.next_steps = cards;
  return out;
}

function upsellScaffoldOverrides() {
  const upsell = builder.post_purchase?.upsell || {};
  const out = {};
  UPSELL_SCAFFOLD_TEXT_FIELDS.forEach((key) => {
    const value = (upsell[key] || "").trim();
    if (value) out[key] = value;
  });
  if (upsell.countdown_enabled === false) out.countdown_enabled = false;
  if (upsell.savings_badge === false) out.savings_badge = false;
  const minutes = Number(upsell.countdown_minutes);
  if (minutes && minutes !== 1) out.countdown_minutes = minutes;
  return Object.keys(out).length ? out : null;
}

// Map the tenant's Configuration page_defaults onto the builder's funnel fields (config uses a few different
// field names: thank-you `subtitle` -> `subheadline`; upsell `*_button_text` -> `*_label`).
function configThankYouSeed() {
  const c = tenantPageDefaults.value.thank_you || {};
  const seed = {};
  const map = {
    headline: "headline", headline_icon: "headline_icon", subtitle: "subheadline", message: "message",
    next_steps_title: "next_steps_title", footer_headline: "footer_headline", footer_message: "footer_message",
    home_button_text: "home_button_text", download_button_text: "download_button_text", download_url: "download_url",
  };
  for (const [configKey, builderKey] of Object.entries(map)) {
    if (c[configKey] != null && c[configKey] !== "") seed[builderKey] = c[configKey];
  }
  ["enable_celebration", "enable_next_steps", "enable_footer", "show_home_button", "enable_download"]
    .forEach((k) => { if (c[k] != null) seed[k] = c[k]; });
  if (Array.isArray(c.next_steps) && c.next_steps.length) {
    seed.next_steps = c.next_steps.map((x) => ({ icon: x.icon || "", title: x.title || "", desc: x.desc || "" }));
  }
  return seed;
}
function configUpsellSeed() {
  const c = tenantPageDefaults.value.upsell || {};
  const seed = {};
  if (c.headline) seed.headline = c.headline;
  if (c.subheadline) seed.subheadline = c.subheadline;
  if (c.accept_button_text) seed.accept_label = c.accept_button_text;
  if (c.decline_button_text) seed.decline_label = c.decline_button_text;
  if (c.price_label) seed.price_label = c.price_label;
  if (c.downsell_headline) seed.downsell_headline = c.downsell_headline;
  if (c.downsell_note) seed.downsell_note = c.downsell_note;
  return seed;
}

function loadPostPurchase(page) {
  const base = defaultBuilderForm().post_purchase;
  const postCheckout = page.post_checkout || {};
  const thankYou = postCheckout.thank_you_page || {};
  const scaffold = postCheckout.upsell_scaffold || {};
  const cfgThankYou = configThankYouSeed();
  // Precedence: the page's own saved override > the tenant's Configuration default > the platform default.
  // page_id is not an editor field; next_steps (a list) is layered explicitly below.
  const savedThankYou = Object.fromEntries(
    Object.entries(thankYou).filter(([k, v]) => k !== "page_id" && k !== "next_steps" && v != null));
  const thank_you = { ...base.thank_you, ...cfgThankYou, ...savedThankYou };
  thank_you.next_steps = Array.isArray(thankYou.next_steps) && thankYou.next_steps.length
    ? thankYou.next_steps.map((c) => ({ icon: c.icon || "", title: c.title || "", desc: c.desc || "" }))
    : (cfgThankYou.next_steps || base.thank_you.next_steps);
  const upsell = {
    ...base.upsell, ...configUpsellSeed(),
    ...Object.fromEntries(Object.entries(scaffold).filter(([, v]) => v != null)),
  };
  return { thank_you, upsell };
}

function addNextStepCard() {
  builder.post_purchase.thank_you.next_steps.push({ icon: "", title: "", desc: "" });
}
function removeNextStepCard(index) {
  builder.post_purchase.thank_you.next_steps.splice(index, 1);
}

function buildBuilderPageDocument() {
  if (!builder.offer_id) return null;
  const now = Math.floor(Date.now() / 1000);
  const offer = builderOffer.value;
  const intent = builderIntent.value;
  const createdAt = builder.created_at || now;
  return cleanObject({
    schema_version: "2026-05-29",
    document_type: "page",
    tenant_id: getTenantId(),
    page_id: builder.page_id,
    name: builder.name || `${offer?.name || "Offer"} Landing Page`,
    status: builder.status || "draft",
    published_at: builder.published_at || null,
    // Preserve the page's sticky snowflake so re-saves keep the same shareable test link (backend also
    // re-inherits it, but round-tripping keeps lifecycle_only_change a no-op on unpublish/edit).
    ...(builder.short_code ? { short_code: builder.short_code } : {}),
    route: {
      slug: slugify(builder.slug || offer?.slug || builder.name || builder.page_id),
    },
    seo: {
      // Store only the tenant's explicit SEO copy; when blank, omit it so the renderer derives the same
      // product-based default live (plans/LANDING_PAGE_DEFAULT_COPY.md — derive live, override when set).
      title: builder.seo_title || undefined,
      description: builder.seo_description || undefined,
      image: builder.seo_image || previewHeroImage.value,
      favicon_url: builder.favicon_url,
    },
    offer_id: builder.offer_id,
    goal: builder.goal || undefined,
    // Absent means "use the default for this shape", so only a DEVIATION is stored. Writing the resolved
    // value would freeze today's answer into the document -- the same mistake the brand label made.
    ...(breadcrumbOn.value === breadcrumbDefault.value ? {} : { chrome: { breadcrumb: breadcrumbOn.value } }),
    theme: {
      template: "universal_bundle",
      preset: builder.preset,
      // Advanced Color Settings overrides (the server merges theme.tokens over the preset).
      ...(Object.keys(builder.theme_tokens || {}).length ? { tokens: { ...builder.theme_tokens } } : {}),
      // Omitted entirely when empty, so an untouched page carries no font key and resolve_families falls
      // straight through to the preset.
      ...(Object.keys(builder.theme_fonts || {}).length ? { fonts: { ...builder.theme_fonts } } : {}),
    },
    post_checkout: intent === "transaction" ? {
      thank_you_page: {
        page_id: builder.thank_you_page_id,
        ...thankYouCopyOverrides(),
      },
      ...(upsellScaffoldOverrides() ? { upsell_scaffold: upsellScaffoldOverrides() } : {}),
    } : undefined,
    // Sale / Flash-Sale views (plans/SALES_FUNNELS.md P1). Omitted (removed) when disabled.
    sale: (intent === "transaction" && builder.sale.enabled)
      ? { enabled: true, ...(builder.sale.ends_at ? { ends_at: builder.sale.ends_at } : {}) }
      : undefined,
    flash_sale: (intent === "transaction" && builder.flash_sale.enabled)
      ? { enabled: true, ...(builder.flash_sale.starts_on ? { starts_on: builder.flash_sale.starts_on } : {}), ...(builder.flash_sale.ends_at ? { ends_at: builder.flash_sale.ends_at } : {}) }
      : undefined,
    analytics: {
      google_tag_id: builder.google_tag_id,
      pixel_id: builder.pixel_id,
    },
    legal: legalLinks(),
    // Page Composer intent: the tenant's section overrides. Python re-applies the same shared rules on top.
    composition: { overrides: { ...builder.composition.overrides } },
    // Intrinsic dimensions for uploaded page images so the renderer reserves layout space (no CLS).
    ...(Object.keys(builder.image_dims || {}).length ? { image_dims: { ...builder.image_dims } } : {}),
    // Omitted when empty, so an untouched page carries no key and the renderer keeps deriving alt text
    // from surrounding data exactly as it did before this field existed.
    ...(Object.keys(builder.image_alts || {}).length ? { image_alts: { ...builder.image_alts } } : {}),
    // Without this the ids never persist and a saved crop stops being re-editable -- the payload is
    // an allow-list, so a field the builder holds but does not list here is silently dropped.
    ...(Object.keys(builder.image_assets || {}).length ? { image_assets: { ...builder.image_assets } } : {}),
    ...(Object.keys(builder.video_posters || {}).length ? { video_posters: { ...builder.video_posters } } : {}),
    // Persisted only once the tenant has rearranged the page: an absent section_order means "use the
    // baseline for this goal", which is the default a new page must keep getting.
    ...(builder.section_order?.length ? { section_order: [...builder.section_order] } : {}),
    sections: builderSections(intent),
    revision: builder.revision || 1,
    created_at: createdAt,
    updated_at: now,
  });
}

function builderSections(intent) {
  return orderSections(builderSectionCandidates(intent), builder.section_order || [], builderGoal.value);
}

// Assembles every section the page WILL contain. Emission order here is only a default -- placement
// bands and the tenant's drag order are applied by builderSections() above.
function builderSectionCandidates(intent) {
  const sections = [];
  if (builder.countdown.enabled) {
    sections.push({
      id: "countdown",
      type: "countdown_timer",
      enabled: true,
      duration_minutes: Math.max(1, Number(builder.countdown.duration_minutes || 15)),
      start_text: builder.countdown.start_text || "Offer expires in",
      end_text: builder.countdown.end_text || "Offer expired",
      start_enabled: builder.countdown.start_enabled !== false,
      end_enabled: builder.countdown.end_enabled !== false,
      marquee_seconds: Number(builder.countdown.marquee_seconds) || 14,
      start_icon: builder.countdown.start_icon ?? "⏰",
      end_icon: builder.countdown.end_icon ?? "⏰",
      start_color: builder.countdown.start_color || "#f97316",
      end_color: builder.countdown.end_color || "#64748b",
      sticky: Boolean(builder.countdown.sticky),
      persistent: Boolean(builder.countdown.persistent),
      transparent: Boolean(builder.countdown.transparent),
      marquee: Boolean(builder.countdown.marquee),
    });
  }
  // What the hero chip shows. It resolves a default for DISPLAY, which is right for a chip that must never be
  // blank -- but only the tenant's own text is persisted as the brand label below.
  const brandText = formatHeadline(builder.brand_label_text || offerBrandDefault(builderOffer.value));
  // The brand overlay (on the hero) replaces the separate above-hero brand label so the brand shows once.
  if (sectionVisible("brand_label") && !builder.brand_overlay) {
    sections.push({
      id: "brand",
      type: "brand_label",
      enabled: true,
      // ONLY what the tenant typed. Storing the resolved default would freeze today's answer into the
      // document: rename the business, attach a Site, fill in the Business Profile -- the page would go on
      // showing whatever was true the moment it was first saved, and nothing would explain why.
      label: formatHeadline(builder.brand_label_text || "") || undefined,
      // Written from the SAME builder field as the hero chip's, so the two cannot disagree within a save.
      brand_dot_pulse: builder.brand_dot_pulse ? true : undefined,
    });
  }
  // The hero-media carousel — for a listicle it's the product images (auto-filled into the field), driving
  // the price card. Carries the socialite overlays (avatar + brand chip) that render inside it.
  // Composed like everything else below it. These two were the ONLY sections here pushed unconditionally, on
  // the assumption that every page has a hero -- true until the lead shapes arrived. A bridge page omits
  // hero_media (an image is weight on a page that exists to forward) and a link-in-bio page omits hero (the
  // identity header already says who this is). Both still appeared in the builder, with editable copy that the
  // server composer then dropped at publish: the form promised a headline the page would never show.
  if (sectionVisible("hero_media")) sections.push({
    id: "hero-media",
    type: "hero_media",
    images: heroMediaList.value,
    autoplay: Boolean(builder.autoplay),
    avatar_url: builder.avatar_url || "",
    // NOT gated on builder.avatar_url. Once the avatar became a REFERENCE, a page inheriting the store
    // image has an empty avatar_url -- so gating here silently discarded the placement on exactly the
    // pages most likely to use it, and every one of them rendered as an overlay whatever the tenant chose.
    avatar_placement: builder.avatar_placement || undefined,
    brand_overlay: Boolean(builder.brand_overlay),
    brand_position: builder.brand_position || "top-right",
    brand_dot_pulse: builder.brand_dot_pulse ? true : undefined,
    brand_text: builder.brand_overlay ? brandText : "",
    // The identity block. The NAME is not stored -- it resolves from the owner's profile at render, so
    // renaming yourself updates every page instead of leaving each one frozen. Only the switch and the
    // page's own sentence travel with the document.
    show_identity: builder.show_identity ? true : undefined,
    tagline: builder.show_identity && builder.tagline ? builder.tagline.slice(0, HERO_TAGLINE_MAX) : undefined,
  });
  // Hero copy. A listicle's hero is TARGET-BOUND (the renderer fills it with each carousel product's own
  // name/description and swaps per slide), so its stored copy is always empty — a fixed hero would sit static
  // and wrong on every other slide. Other offer types keep the name/default fallback so the hero is never empty.
  if (sectionVisible("hero")) sections.push({
    id: "hero",
    type: "hero",
    headline: isListicleOffer.value ? "" : formatHeadline(builder.headline || builder.name || "Landing Page"),
    subheadline: isListicleOffer.value ? "" : (builder.subheadline || "Continue when you are ready."),
  });
  // The Page Composer decides which optional sections exist (sectionVisible). A listicle hides the fluff
  // (trust badges, elements, refund, sticky CTA — the add-to-cart lives in the price card); other offer
  // types keep everything. The preview obeys the SAME rule, so the two can never disagree.
  if (sectionVisible("trust_badges") && visibleTrustBadges.value.length) {
    sections.push({
      id: "trust-badges",
      type: "trust_badges",
      enabled: true,
      badges: visibleTrustBadges.value.map((badge) => ({
        enabled: true,
        emoji: badge.emoji,
        label: badge.label,
      })),
    });
  }
  // Composable body: the tenant's ordered elements (content, testimonials, rating, logos, FAQ).
  builder.elements.forEach((element) => {
    const section = elementSection(element);
    if (section && sectionVisible(section.type)) sections.push(section);
  });
  if (intent === "transaction") {
    sections.push({
      id: "offer-selector",
      type: "offer_price_selector",
      offer_id: builder.offer_id,
    });
  }
  // A listicle's CTA lives inside the price card (add-to-cart), so it doesn't emit a standalone checkout_cta
  // candidate — the composer still lists "cta" as allowed for listicle, but there's no separate section.
  if (!isListicleOffer.value && sectionVisible("checkout_cta")) {
    sections.push({
      id: "checkout-cta",
      type: "checkout_cta",
      label: builder.cta_label || (intent === "transaction" ? "Buy Now" : "Continue"),
    });
  }
  // previewRefundPolicy mirrors the server's lookup (offer.refund_policy, then the product's). With no
  // policy to show, the server renders "" anyway — don't persist a section that can never render.
  if (sectionVisible("refund_policy") && previewRefundPolicy.value) {
    sections.push({
      id: "refund-policy",
      type: "refund_policy",
      enabled: builder.refund_policy.enabled !== false,
      heading: "Refund Policy",
    });
  }
  sections.push({
    id: "legal-footer",
    type: "legal_footer",
    copyright: defaultFooterCopyrightTemplate,
  });
  // The structured_data head section is NOT stored: compose_page derives it from the goal's capability
  // pack plus the tenant's toggle, which is where its truth already lived. It used to be pushed here only
  // because the composer filtered and never added — and that duplicate is exactly what cost a page its
  // Product/FAQPage markup when a save-path bug dropped the marker while the goal still said to emit it.
  return sections;
}

async function saveBuilderPage() {
  return saveBuilderPageWithStatus();
}

async function publishBuilderPage() {
  return saveBuilderPageWithStatus("published");
}

async function toggleBuilderPublished() {
  if (isBuilderPublished.value) return unpublishBuilderPage();
  return publishBuilderPage();
}

async function unpublishBuilderPage() {
  const source = builderOriginalPage.value || builderPageDocument.value;
  if (!source) {
    error.value = "Page could not be generated.";
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const document = applyPageStatus(source, "draft");
    const body = await apiRequest("/pages", { method: "POST", body: document });
    const saved = body.page || document;
    pages.value = [saved, ...pages.value.filter((page) => page.page_id !== saved.page_id)];
    message.value = `${saved.name || "Landing page"} was unpublished.`;
    builder.status = saved.status || "draft";
    builder.published_at = saved.published_at || null;
    builderOriginalPage.value = { ...saved };
  } catch (err) {
    error.value = err.message || "Failed to unpublish landing page.";
  } finally {
    saving.value = false;
  }
}

// `silent` suppresses the routine success banner. Auto-save fires on every Done, and a banner each time is
// noise — the point is to stop thinking about saving. Failures are never silent: carrying on editing a page
// that is no longer being stored is the one outcome worth interrupting for.
async function saveBuilderPageWithStatus(statusOverride = "", { silent = false } = {}) {
  error.value = "";
  message.value = "";
  if (flashSaleInvalid.value) {
    error.value = "You must set an expiration date to enable the Flash Sale.";
    return;
  }
  if (!builderPageDocument.value) {
    error.value = "Page could not be generated.";
    return;
  }
  saving.value = true;
  try {
    const document = applyPageStatus(builderPageDocument.value, statusOverride);
    const body = await apiRequest("/pages", { method: "POST", body: document });
    const saved = body.page || document;
    pages.value = [saved, ...pages.value.filter((page) => page.page_id !== saved.page_id)];
    pagesLoaded.value = true;
    if (!silent) {
      message.value = statusOverride === "published" ? `${saved.name} was published.` : `${saved.name} was saved.`;
    }
    builderExistingPageId.value = saved.page_id;
    builder.status = saved.status || builder.status;
    builder.published_at = saved.published_at || builder.published_at;
    builder.short_code = saved.short_code || builder.short_code;  // populated the moment a page is published
    builderOriginalPage.value = { ...saved };
    if (statusOverride === "published") {
      const attachedTo = await ensureSiteAttachmentOnPublish(saved);
      if (attachedTo) message.value = `${saved.name} was published and attached to ${attachedTo}.`;
    }
  } catch (err) {
    error.value = err.message || "Failed to save landing page.";
  } finally {
    saving.value = false;
  }
}

function buildPageDocument() {
  if (!selectedOffer.value) return null;
  const now = Math.floor(Date.now() / 1000);
  const offer = selectedOffer.value;
  const intent = selectedOfferIntent.value;
  const pageId = form.page_id || localId("page");
  const leadAction = selectedLeadAction.value;
  return cleanObject({
    schema_version: "2026-05-29",
    document_type: "page",
    tenant_id: getTenantId(),
    page_id: pageId,
    name: form.name || `${offer.name || "Offer"} Landing Page`,
    status: "draft",
    published_at: null,
    route: {
      slug: slugify(form.slug || offer.slug || offer.name || pageId),
    },
    seo: {
      title: form.name || offer.name,
      description: offer.presentation?.headline || leadAction?.description || "",
      image: offerImage(offer),
    },
    offer_id: offer.offer_id,
    goal: form.goal || undefined,
    theme: {
      template: "universal_bundle",
      preset: form.preset || "clean-slate",
    },
    post_checkout: intent === "transaction" ? postCheckoutBlock() : undefined,
    legal: legalLinks(),
    sections: pageSections(intent, offer, leadAction),
    revision: 1,
    created_at: now,
    updated_at: now,
  });
}

function postCheckoutBlock() {
  return {
    thank_you_page: {
      page_id: form.thank_you_page_id || localId("page"),
    },
  };
}

function pageSections(intent, offer, leadAction) {
  // One section list for every offer type. The CTA component is chosen by the offer's cta.type at
  // render time (server + preview), so the page only needs a hero, an optional price selector, and a
  // checkout_cta — never a lead-flow content block or a page-level CTA override.
  const sections = [
    {
      id: "brand",
      // No label. The draft used to bake in formatHeadline("Junior Bay") -- the PLATFORM's name, written into
      // the tenant's page as though they had typed it, where it then outlived every later fix because a
      // stored label beats any fallback. Seen live on a link hub headed "Junior Bay" instead of the creator's
      // name. Absent means "derive at render", which is the same by-reference rule the page avatar follows.
      type: "brand_label",
      enabled: true,
    },
    {
      id: "hero",
      type: "hero",
      headline: formatHeadline(offerHeadline(offer) || (intent === "transaction" ? "Complete your order" : "Get started")),
      subheadline: offerDescription(offer) || leadAction?.description || "Choose your option and continue.",
    },
  ];
  if (intent === "transaction") {
    sections.push({
      id: "offer-selector",
      type: "offer_price_selector",
      offer_id: offer.offer_id,
    });
  }
  sections.push(
    {
      id: "checkout-cta",
      type: "checkout_cta",
      label: offer.presentation?.cta?.label || offer.presentation?.cta_label
        || (intent === "transaction" ? "Continue to Checkout" : "Continue"),
    },
    {
      id: "refund-policy",
      type: "refund_policy",
      enabled: true,
      heading: "Refund Policy",
    },
    {
      id: "legal-footer",
      type: "legal_footer",
      copyright: defaultFooterCopyrightTemplate,
    },
  );
  return sections;
}

function pageImage(page) {
  // A storefront's card image is its brand logo (if uploaded); with none, the card shows the house placeholder.
  if (isStorefrontPage(page)) {
    return (page.sections || []).find((s) => s && s.type === "brand_hero")?.logo_url || "";
  }
  const offer = offers.value.find((item) => item.offer_id === page.offer_id);
  return page.seo?.image || offerImage(offer) || "";
}

function sectionText(sections, type) {
  return sections.find((section) => section.type === type)?.text || "";
}

function parseLines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isLandingPagePrice(price) {
  const context = String(price?.context || "standard").trim().toLowerCase();
  return landingPagePriceContexts.has(context);
}

function landingPagePriceQuantity(price, option = {}) {
  const explicitQuantity = Number(price?.quantity || option?.quantity || 0);
  if (Number.isFinite(explicitQuantity) && explicitQuantity > 0) return explicitQuantity;
  const label = String(option?.label || price?.label || "");
  const match = label.match(/\b(\d+)\b/);
  return match ? Number(match[1]) : 0;
}

function legalLinks() {
  // Persist no legal URLs on the page document; the renderer injects the platform
  // /legal/* links at publish time so pages stay environment-agnostic.
  return {};
}

function toggleHeroMedia(image) {
  const items = new Set(heroMediaList.value);
  if (items.has(image)) items.delete(image);
  else items.add(image);
  builder.hero_media_text = Array.from(items).join("\n");
  if (!builder.seo_image) builder.seo_image = image;
}

// The media field speaks arrays; the builder keeps storing newline text, so buildBuilderPageDocument()
// and the product-image autofill below are unchanged (hero_media.images is still a plain URL array).
function setHeroMedia(list) {
  builder.hero_media_text = (Array.isArray(list) ? list : []).join("\n");
}

function appendHeroMedia(image) {
  const items = new Set(heroMediaList.value);
  items.add(image);
  builder.hero_media_text = Array.from(items).join("\n");
  if (!builder.seo_image) builder.seo_image = image;
}

async function handleFaviconPicked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  faviconUploadError.value = "";
  faviconUploading.value = true;
  try {
    builder.favicon_url = await uploadPageImage(file);
  } catch (err) {
    faviconUploadError.value = err.message || "Favicon upload failed.";
  } finally {
    faviconUploading.value = false;
  }
}

async function handleHeroMediaPicked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  heroUploadError.value = "";
  heroUploading.value = true;
  try {
    appendHeroMedia(await uploadPageImage(file));
  } catch (err) {
    heroUploadError.value = err.message || "Hero image upload failed.";
  } finally {
    heroUploading.value = false;
  }
}

async function handleAvatarPicked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  avatarUploadError.value = "";
  avatarUploading.value = true;
  try {
    builder.avatar_url = await uploadPageImage(file);
  } catch (err) {
    avatarUploadError.value = err.message || "Avatar upload failed.";
  } finally {
    avatarUploading.value = false;
  }
}

// Composable page elements: an ordered, draggable list the tenant builds. Each element maps 1:1 to a
// rendered page section (plans/LANDING_PAGE_CTA_AND_COMPOSITION.md phase 4).
// A listicle is now driven by the offer (offer_type: listicle renders its items as a carousel), so the
// page-level multi-offer carousel element was retired — see plans/LISTICLE_AND_CART.md.
// The addable body elements come from the shared element catalog (Builder Reframe) — one source, one label.
const ELEMENT_TYPES = computed(() => addableElements());

// The pattern break is driven by the BACKGROUND: the ink derives from it, so clearing the background is
// what returns the section to the page preset. A default is seeded on enable so the toggle does something
// visible immediately.
// Each element names the SECOND surface it colours — the author bio rings a photo, bragging points fill
// cards. The ink for both is derived server-side, so this only ever picks surfaces, never text colours.
const SECTION_BREAK_DEFAULTS = { bg: "#111827", border: "#ffffff", accent: "#1f2937" };

function toggleSectionBreak(element, event, surface = "border") {
  if (!element.theme) element.theme = {};
  if (event.target.checked) {
    element.theme.bg = element.theme.bg || SECTION_BREAK_DEFAULTS.bg;
    element.theme[surface] = element.theme[surface] || SECTION_BREAK_DEFAULTS[surface];
  } else {
    element.theme = {};
  }
}

// Offered shapes for a Before/After pair. Both sides take the element's choice, so this is asked once.
const beforeAfterShapes = [
  { value: 1.3333333333, label: "4:3 — landscape" },
  { value: 1.7777777778, label: "16:9 — wide" },
  { value: 1, label: "1:1 — square" },
  { value: 0.8, label: "4:5 — portrait" },
];

// A crop is framed against a specific shape, so changing the shape invalidates both. Keeping them would
// silently render the pair at the wrong aspect and the seam would stop lining up.
function resetBeforeAfterCrops(element) {
  element.before_crop = null;
  element.after_crop = null;
}

// Mirrors domain/video_embeds.py: the builder must agree with the renderer about what counts as a link,
// or it will promise a poster for something that renders as a file, or refuse one that needs it.
const EMBED_LINK = /^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?.*v=|embed\/|shorts\/|live\/|v\/)|youtu\.be\/|(?:www\.)?vimeo\.com\/|player\.vimeo\.com\/video\/)/i;

function isEmbedLink(url) {
  return EMBED_LINK.test(String(url || ""));
}

function videoKindLabel(url) {
  if (!isEmbedLink(url)) return "Hosted video file";
  return /vimeo/i.test(url) ? "Vimeo — loads only when a visitor presses play" : "YouTube — loads only when a visitor presses play";
}

// Vertical first: Shorts, Reels and TikTok-style video are the common case now, so the list should not
// read as if landscape were the only real option.
const videoShapes = [
  { value: 1.7777777778, label: "16:9 — landscape" },
  { value: 0.5625, label: "9:16 — vertical" },
  { value: 1, label: "1:1 — square" },
  { value: 0.8, label: "4:5 — portrait" },
  { value: 1.3333333333, label: "4:3 — classic" },
];

const elementVideoInputs = ref({});
// A percentage while the bytes move, then an honest "Processing" while the server works -- the two
// phases have very different lengths and only one of them can report progress.
const elementVideoStatus = reactive({});
const elementVideoUploading = reactive({});
const elementVideoErrors = reactive({});

function setElementVideoInput(id, el) {
  if (el) elementVideoInputs.value[id] = el;
  else delete elementVideoInputs.value[id];
}
function triggerElementVideoUpload(id) {
  elementVideoInputs.value[id]?.click();
}
// The browser knows the real shape of a file, so read it instead of asking. Vertical video is common now
// and a wrong default either letterboxes it into a stripe or crops the subject out.
function videoAspectOf(file) {
  return new Promise((resolve) => {
    const probe = document.createElement("video");
    probe.preload = "metadata";
    const src = URL.createObjectURL(file);
    const done = (value) => { URL.revokeObjectURL(src); resolve(value); };
    probe.onloadedmetadata = () => done(probe.videoWidth && probe.videoHeight
      ? probe.videoWidth / probe.videoHeight : 0);
    probe.onerror = () => done(0);
    probe.src = src;
  });
}

async function handleElementVideoPicked(element, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  elementVideoErrors[element.id] = "";
  elementVideoUploading[element.id] = true;
  elementVideoStatus[element.id] = "Uploading 0%";
  try {
    const measured = await videoAspectOf(file);
    element.url = await uploadPageVideo(file, ({ phase, percent }) => {
      elementVideoStatus[element.id] = phase === "processing" ? "Processing..." : `Uploading ${percent}%`;
    });
    if (measured) element.aspect = Math.round(measured * 1e4) / 1e4;
    // A file plays inline; a poster belongs to an embed, so anything left over would never be used.
    element.poster = "";
  } catch (err) {
    elementVideoErrors[element.id] = err?.message || "Video upload failed.";
  } finally {
    elementVideoUploading[element.id] = false;
    elementVideoStatus[element.id] = "";
  }
}

function newElement(type) {
  const base = { id: localId("el"), type };
  // Sensible default headings so the tenant isn't guessing — they can always reword them.
  if (type === "content_block") return { ...base, title: "", text: "", image_url: "", centered: false };
  if (type === "testimonials") return { ...base, heading: "What Our Clients Say", items: [{ quote: "", author: "", role: "", avatar_url: "" }] };
  if (type === "rating") return { ...base, value: 5, count: 0, label: "" };
  if (type === "client_marquee") return { ...base, heading: "Our Clients", logos: [{ image_url: "", name: "" }], scroll: "auto", scroll_seconds: 30, logo_backing: "card" };
  if (type === "faq") return { ...base, heading: "Frequently Asked Questions", items: [{ question: "", answer: "" }] };
  if (type === "related_products") return { ...base, heading: "Related products" };
  // social_links has no per-page content: it reads the Site's Business Profile, so a tenant fills their
  // profiles in once rather than retyping them on every page.
  // Starts with NO items, which means "inherit the Site's profiles" -- the behaviour every page had before
  // page-local links existed. Overriding is an explicit act, so nothing changes under a tenant who never
  // opens this editor.
  if (type === "social_links") return { ...base, heading: "", items: [] };
  if (type === "link_cards") return { ...base, heading: "", items: [{ url: "", label: "", description: "", image_url: "" }] };
  // ONE ratio for the element, not one per image: locking both sides to the same shape is what makes the
  // wipe align. 4:3 is the common phone-photo shape, so most pairs need no change.
  if (type === "video") return { ...base, heading: "", url: "", poster: "", caption: "", aspect: 1.7777777778 };
  if (type === "before_after") return { ...base, heading: "", before_url: "", after_url: "",
    before_crop: null, after_crop: null, before_label: "Before", after_label: "After",
    ratio: 1.3333333333, start: 50 };
  if (type === "bragging_points") return { ...base, heading: "", items: [{ value: "", label: "" }], theme: {} };
  if (type === "quote") return { ...base, text: "", attribution: "", title: "", image_url: "", style: "minimal", theme: {} };
  if (type === "numbered_list") return { ...base, heading: "", items: [""] };
  if (type === "page_ribbon") return { ...base, purpose: "custom", presentation: "image_left",
    image_url: "", eyebrow: "", headline: "", body: "",
    cta: { label: "", action: "promote_page", page_id: "", target: "",
           asset: null, collect_email: false, collect_phone: false }, theme: {} };
  // The NUMBERS are derived from the offer; only these two lines are the tenant's.
  if (type === "price_highlight") return { ...base, main_text: "Today Only", subtext: "" };
  if (type === "author_bio") return { ...base, photo_url: "", name: "", headline: "", body: "", theme: {} };
  // product_details is fully offer-driven (current target's gallery/badges/description) — no config.
  return base;
}

// Opens the editor on a DRAFT. Nothing reaches builder.elements until "Add Section" — so Cancel leaves
// no trace, and an empty half-made section can never exist.
//
// EXCEPT for container sections. Testimonials and FAQ are one section holding many items, not many
// sections: a second "Testimonials" heading further down the page is never what the tenant meant. For
// those, adding opens the EXISTING section where it already sits — no new section, no move — with a
// blank item ready to fill, which is what "add a testimonial" actually means.
function addElement(type) {
  if (!isRepeatableSection(type)) {
    const existing = builder.elements.find((el) => el.type === type);
    if (existing) {
      appendBlankItem(existing);
      sectionEditor.value = {
        isNew: false,
        row: { key: existing.id, type, label: elementLabel(type), editor: "element", element: existing, movable: true },
      };
      return;
    }
  }
  if (builder.elements.length >= 20) return;
  const element = newElement(type);
  sectionEditor.value = {
    isNew: true,
    row: { key: element.id, type, label: elementLabel(type), editor: "element", element, movable: true },
  };
}

// Give the tenant a row to type into, but never stack blanks: if an empty one is already waiting, that
// is the row they wanted.
function appendBlankItem(element) {
  const blanks = {
    testimonials: ["items", { quote: "", author: "", role: "", avatar_url: "" }, "quote"],
    faq: ["items", { question: "", answer: "" }, "question"],
    client_marquee: ["logos", { image_url: "", name: "" }, "image_url"],
    link_cards: ["items", { url: "", label: "", description: "", image_url: "" }, "url"],
  }[element.type];
  if (!blanks) return;
  const [field, blank, probe] = blanks;
  const list = element[field] || (element[field] = []);
  if (list.some((item) => !String(item?.[probe] || "").trim())) return;
  list.push({ ...blank });
}

async function removeElement(id) {
  const index = builder.elements.findIndex((element) => element.id === id);
  if (index < 0) return;
  builder.elements.splice(index, 1);
  delete blurbImageUploading[id];
  delete blurbImageErrors[id];
  delete blurbImageInputs.value[id];
  // Persist at once, like a section editor's Done and Page Settings' close. Reported 2026-09-09: a removed
  // section reappeared, because Remove only mutated the local array. The row vanishing from the panel reads
  // as "done" -- there is no visible difference between removed-and-saved and removed-and-not -- so the
  // tenant has no way to tell the change is still pending until it is lost.
  await autoSavePage();
}

function addSubItem(element, key, item) {
  (element[key] = element[key] || []).push(item);
}

function removeSubItem(element, key, index) {
  element[key].splice(index, 1);
}

const elementDragIndex = ref(-1);

function setElementImageInput(id, el) {
  if (el) blurbImageInputs.value[id] = el;
  else delete blurbImageInputs.value[id];
}
function triggerElementImageUpload(id) {
  blurbImageInputs.value[id]?.click();
}
// `field` lets an element name its own image property — author_bio stores a photo_url, content_block an
// image_url. Defaulted, so every existing caller is unchanged.
async function handleElementImagePicked(element, event, field = "image_url") {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  blurbImageErrors[element.id] = "";
  blurbImageUploading[element.id] = true;
  try {
    element[field] = await uploadPageImage(file);
  } catch (err) {
    blurbImageErrors[element.id] = err.message || "Image upload failed.";
  } finally {
    blurbImageUploading[element.id] = false;
  }
}

// Reusable image upload for a sub-item field (testimonial avatar, client logo) — same uploadImage() service.
function subImgKey(element, list, index) {
  return `${element.id}:${list}:${index}`;
}
function setSubImageInput(key, el) {
  if (el) subImageInputs.value[key] = el;
  else delete subImageInputs.value[key];
}
function triggerSubImageUpload(key) {
  subImageInputs.value[key]?.click();
}
async function handleSubImagePicked(target, field, key, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  subImageErrors[key] = "";
  subImageUploading[key] = true;
  try {
    target[field] = await uploadPageImage(file);
  } catch (err) {
    subImageErrors[key] = err.message || "Image upload failed.";
  } finally {
    subImageUploading[key] = false;
  }
}

// Map a composable element to its rendered page section, or null when empty.
// What the page will actually contain, in final order — the same list builderSections() emits, so the
// panel can never disagree with the page. Pinned rows are shown (a locked hero is information, not
// clutter) but are not draggable.

// --- Content sequence model (plans/BUILDER_SECTION_ORDER.md) -------------------------------------
// The form renders THIS, in this order, so the builder reads top-to-bottom exactly as the page does.
//
// Two things the raw section list gets wrong for a builder view:
//   1. One "Hero" form block covers four catalog elements (hero_media, hero, headline, subheadline).
//      They share a placement and always move together, so the builder shows ONE row.
//   2. Some sections have no editor at all — price cards are offer-driven and the footer is generated.
//      They still belong on the map: a tenant needs to see WHERE they land, even with nothing to set.
const HERO_FAMILY = ["hero_media", "hero", "headline", "subheadline"];

// section type -> which editor block renders inside the row. Absent = a name-only row (no editor).
const SECTION_EDITORS = {
  brand_label: "brand_label",
  countdown_timer: "countdown",
  hero_media: "hero",
  trust_badges: "trust_badges",
  checkout_cta: "checkout_cta",
  refund_policy: "refund_policy",
};

const contentRows = computed(() => {
  const rows = [];
  let heroEmitted = false;
  for (const section of builderSections(builderIntent.value)) {
    const type = section.type;
    if (HERO_FAMILY.includes(type)) {
      if (heroEmitted) continue;           // collapse the family into a single "Hero" row
      heroEmitted = true;
      rows.push({ key: "hero", type: "hero_media", label: "Hero", editor: "hero", movable: false });
      continue;
    }
    rows.push({
      key: sectionOrderKey(section),
      type,
      label: elementLabel(type),
      editor: SECTION_EDITORS[type] || (isElementType(type) ? "element" : ""),
      element: isElementType(type) ? builder.elements.find((el) => el.id === section.id) : null,
      movable: isMovable(type),
    });
  }
  // Same rule for elements, and it bites harder: elementSection() returns null for an EMPTY element, so
  // a freshly added content block emits nothing and would never appear — the tenant clicks "+ Content
  // block" and sees no result. Element rows therefore come from builder.elements, the tenant's actual
  // list, not from what happens to render.
  // Key the row the way the SECTION would be keyed, not by element id. Only repeatable types key by id;
  // a non-repeatable element (author_bio, faq, price_highlight) keys by TYPE, so deduping on element.id
  // matched nothing and every one of them got a second, phantom row — sorted somewhere else entirely,
  // which is what "the section is out of order" looked like from the form.
  for (const element of builder.elements) {
    const key = sectionOrderKey(element);
    if (rows.some((row) => row.key === key)) continue;
    rows.push({
      key,
      type: element.type,
      label: elementLabel(element.type),
      editor: "element",
      element,
      movable: isMovable(element.type),
    });
  }
  // A section that currently renders NOTHING still needs its row, or its editor — and with it the only
  // switch that brings it back — becomes unreachable. Fourth instance of this in the restructure:
  // emptied trust badges, blank elements, and the countdown, which is off by default and so never
  // emitted at all. The row's presence follows AVAILABILITY, never whether it currently renders.
  for (const { type, available } of ALWAYS_PRESENT_SECTIONS) {
    if (!available() || rows.some((row) => row.type === type)) continue;
    rows.push({
      key: type,
      type,
      label: elementLabel(type),
      editor: SECTION_EDITORS[type],
      element: null,
      movable: isMovable(type),
      empty: true,
    });
  }
  return rows;
});

// Sections whose ROW must exist even when they render nothing, each with its own availability test.
// Not refund_policy: when the offer carries no policy copy there is nothing a tenant can do from here,
// so an editor would be a dead control.
const ALWAYS_PRESENT_SECTIONS = [
  // Every badge switched off — the section stops rendering, but the toggles must stay reachable.
  { type: "trust_badges", available: () => sectionVisible("trust_badges") },
  // The countdown is NOT a governed section: its availability is builder.countdown.enabled, which is set
  // inside its own editor. So its row is always present — otherwise the feature can never be turned on.
  // Except where urgency is meaningless: a link hub and a redirect have no deadline to count down to, and
  // offering the control implies they do. Capture and call pages KEEP it — "registration closes Friday" is
  // a real and common lead-magnet device.
  { type: "countdown_timer", available: () => !["lead_social", "lead_bridge"].includes(builderOfferType.value) },
];

// An element row is one of the tenant-added cards, which already have their own editors.
function isElementType(type) {
  return ELEMENT_TYPES.value.some((entry) => entry.type === type);
}

// The draggable run only. Fixed sections are static markup in their correct places (countdown + hero
// above, footer below), so the form still reads top-to-bottom as the page does without duplicating them
// here. Element cards are excluded for now — their editors still live in the Page Sections panel.
const sequenceRows = computed(() => {
  const rows = [...contentRows.value];
  // Sort by KEY, not type: repeatable elements share a type, so two content blocks would collapse to
  // the same sort index. Element ids are absent from the catalog and fall into the free band, which is
  // exactly right. Rows added for emptied sections skip builderSections(), so order is applied here too.
  // Pass the TYPE alongside the key. A repeatable element keys by id, and an id has no baseline position —
  // without the type these rows fell to the very end of the list while the page rendered them at their
  // type's slot, so the form and the preview disagreed about where the content blocks were.
  const order = orderSectionKeys(
    rows.map((row) => ({ key: row.key, type: row.type })),
    builder.section_order || [], builderGoal.value,
  );
  return [...rows].sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
});

// { row, isNew }. isNew means the row's element is a DRAFT that is not in builder.elements yet.
const pageSettingsOpen = ref(false);

// Settings-accordion glyphs: SVG path `d` strings in the same 24x24 stroke style as the sidebar, so the
// modal does not introduce a second icon language. Keyed by the accordion's label.
const SETTINGS_ICONS = {
  "Page Basics": ["M9 3.75h6M5.25 6.75h13.5A1.5 1.5 0 0 1 20.25 8.25v10.5a1.5 1.5 0 0 1-1.5 1.5H5.25a1.5 1.5 0 0 1-1.5-1.5V8.25a1.5 1.5 0 0 1 1.5-1.5Z", "M8 11.5h8M8 15h5"],
  "Page Goal": ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Z", "M12 13.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"],
  "Appearance": ["M12 3a9 9 0 1 0 0 18c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1a1.49 1.49 0 0 1 1.14-2.5H16a5 5 0 0 0 5-5c0-4.42-4.03-8-9-8Z", "M7.5 12a1 1 0 1 0 0-2 1 1 0 0 0 0 2ZM10.5 8.25a1 1 0 1 0 0-2 1 1 0 0 0 0 2ZM15 8.25a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"],
  "SEO": ["M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15Z", "M21 21l-5.2-5.2"],
  "Discoverability": ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", "M3.6 9h16.8M3.6 15h16.8", "M12 3a13.5 13.5 0 0 1 0 18a13.5 13.5 0 0 1 0-18Z"],
  "Analytics": ["M4.5 19.5V13M9.75 19.5V8.25M15 19.5v-4.5M20.25 19.5V5.25"],
  "Favicon": ["M12 3.75l2.5 5.2 5.75.83-4.16 4.02 1 5.7L12 16.83l-5.09 2.67 1-5.7L3.75 9.78l5.75-.83L12 3.75Z"],
};

// One settings accordion open at a time, keyed by label. Several tall panels open together turns the
// modal into a wall; the Post-Checkout steps behave the same way, so the idiom is already familiar.
const openSetting = ref("");

function toggleSetting(key) {
  openSetting.value = openSetting.value === key ? "" : key;
}

const sectionEditor = ref(null);

function openSectionEditor(row) {
  sectionEditor.value = { row, isNew: false };
}

// Editing writes through live, so closing is just closing.
// Done SAVES. Editing an element and then having to find the Save button is a step the tenant should not
// have to remember, and forgetting it loses the edit. Cancel deliberately does not save — that is the
// whole point of Cancel.
async function closeSectionEditor() {
  sectionEditor.value = null;
  await autoSavePage();
}

// Auto-save uses the BUILDER's save, not the wizard's. savePage() builds its document from `draftPage`,
// which only exists inside the create-a-page wizard — calling it from the builder produced "Page could not
// be generated." on every Done. saveBuilderPageWithStatus() with no override saves as a DRAFT and reports
// into the builder's own error banner, which is what the tenant is looking at.
let autoSaveQueued = false;
async function autoSavePage() {
  if (!builderOpen.value) return;
  // Matches the Save Page button's own rule: a published page is not saveable from the builder, so
  // auto-save must not quietly try. Saving is not publishing, and it must never become publishing.
  if (isBuilderPublished.value) return;
  // A save already in flight used to make this return, DROPPING the change silently -- the edit stayed in
  // `builder`, looked applied, and was never written. Anything the tenant did while a save was running was
  // lost the moment they navigated away. Queue instead: the in-flight save is already sending a document
  // that predates this change, so exactly one more save is owed once it lands.
  if (saving.value) {
    autoSaveQueued = true;
    return;
  }
  await saveBuilderPageWithStatus("", { silent: true });
  if (autoSaveQueued) {
    autoSaveQueued = false;
    await autoSavePage();
  }
}

// Page Settings SAVES on close, like a section editor's Done. Every field in it writes through live to
// `builder`, so none of the three exits — Done, ✕, backdrop — reverts anything: closing already leaves the
// change applied and merely unsaved, which looks identical to saved until the tenant navigates away and
// loses it. There is no Cancel here to mean "discard", so persisting is the honest reading of all three.
async function closePageSettings() {
  pageSettingsOpen.value = false;
  await autoSavePage();
}

// Cancel on an ADD throws the draft away — nothing was ever created, so there are no empty cards.
function cancelSectionEditor() {
  sectionEditor.value = null;
}

// The page carries the tenant's own arrangement rather than the baseline for its goal. Drives the
// sequence header's wording, and whether there is anything to reset.
const hasCustomOrder = computed(() => Boolean(builder.section_order?.length));

// Hand the page back to the baseline. Because an absent section_order MEANS "use the baseline", giving
// it up is the whole operation — there is no stored copy of the recommended sequence to restore.
async function resetSectionOrder() {
  builder.section_order = [];
  await autoSavePage();
}

// Three ribbons stop being interruptions and become wallpaper, which destroys the only property that
// makes the element worth having (plans/ATTENTION_PRIMITIVE.md §4a "the wallpaper rule"). Capped at two.
// Whether this tenant may send email at all. The SEND is the real gate (handlers/downloads.py) — this only
// tells the tenant before they invest effort in a button that would refuse to work.
const businessEmailVerified = ref(false);

async function loadBusinessEmailState() {
  try {
    const session = getAuthSession() || {};
    const body = await apiRequest("/profile", { params: { user_id: session.user_id || "" } });
    businessEmailVerified.value = Boolean(body.profile?.business?.email_verified);
  } catch {
    // Unknown is not "unverified": a failed profile load must not accuse a verified tenant of not being
    // set up. The send-time gate is what actually decides.
    businessEmailVerified.value = true;
  }
}

const RIBBON_MAX = 2;

// A ribbon's lead magnet. There is no 50MB technical limit here — that number was invented, not measured.
// The browser PUTs straight to a presigned S3 URL, so API Gateway's 10MB payload cap is not in the path;
// the real boundary is S3's 5GB single-PUT maximum. Beyond that would need multipart, which is a different
// feature. What large files DO need is feedback, so the upload reports progress rather than sitting on
// "Uploading..." for minutes.
const RIBBON_FILE_MAX_BYTES = 5 * 1024 * 1024 * 1024;
const ribbonFileInputs = {};
const ribbonUploading = reactive({});
const ribbonUploadError = reactive({});
const ribbonUploadPct = reactive({});

function setRibbonFileInput(id, el) {
  if (el) ribbonFileInputs[id] = el;
}

function triggerRibbonFileUpload(id) {
  ribbonFileInputs[id]?.click();
}

function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (!n) return "";
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

async function handleRibbonFilePicked(element, event) {
  const file = event.target?.files?.[0];
  if (event.target) event.target.value = "";   // so re-picking the same file still fires
  if (!file) return;
  ribbonUploadError[element.id] = "";
  if (file.size > RIBBON_FILE_MAX_BYTES) {
    ribbonUploadError[element.id] = `That file is ${formatBytes(file.size)}. A single upload can be up to 5 GB.`;
    return;
  }
  ribbonUploading[element.id] = true;
  ribbonUploadPct[element.id] = 0;
  try {
    // Reuses the tenant upload endpoint, scoped to this PAGE rather than a product.
    const contentType = file.type || "application/octet-stream";
    const presign = await apiRequest("/downloads/upload-url", {
      method: "POST",
      body: { page_id: builder.page_id, filename: file.name, content_type: contentType, size_bytes: file.size },
    });
    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", presign.upload_url);
      xhr.setRequestHeader("Content-Type", contentType);
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) ribbonUploadPct[element.id] = Math.round((e.loaded / e.total) * 100);
      });
      xhr.addEventListener("load", () => (xhr.status >= 200 && xhr.status < 300
        ? resolve() : reject(new Error(`Upload failed with ${xhr.status}`))));
      xhr.addEventListener("error", () => reject(new Error("Upload failed. Check your connection.")));
      xhr.send(file);
    });
    element.cta.asset = presign.digital_asset;
  } catch (err) {
    ribbonUploadError[element.id] = err.message || "Upload failed. Please try again.";
  } finally {
    ribbonUploading[element.id] = false;
  }
}

// Single-select, unlike the Offers product picker it mirrors: a ribbon promotes ONE page, so choosing
// closes the modal rather than accumulating a selection.
const ribbonPicker = reactive({ element: null, search: "" });

// The current page can never be its own target — a ribbon linking to the page it sits on is a dead end.
const ribbonPickerPages = computed(() => {
  const term = ribbonPicker.search.trim().toLowerCase();
  return pages.value
    // PUBLISHED only. A draft has no live URL, so offering it and then warning about it was making the
    // tenant undo a choice we should never have let them make.
    .filter((p) => p.status === "published" && p.page_id !== builder.page_id)
    .filter((p) => !term || (p.name || "").toLowerCase().includes(term));
});

function ribbonTargetPage(element) {
  const id = element?.cta?.page_id;
  return id ? pages.value.find((p) => p.page_id === id) || null : null;
}

function openRibbonPagePicker(element) {
  ribbonPicker.element = element;
  ribbonPicker.search = "";
}

function closeRibbonPagePicker() {
  ribbonPicker.element = null;
}

function chooseRibbonPage(page) {
  const element = ribbonPicker.element;
  if (!element) return;
  element.cta.page_id = page.page_id;
  // Resolve the live URL now AND again on save, so a later slug or domain change is picked up.
  element.cta.target = pageUrl(page);
  closeRibbonPagePicker();
}
const ribbonCount = computed(() => builder.elements.filter((el) => el.type === "page_ribbon").length);

async function commitNewSection() {
  const element = sectionEditor.value?.row?.element;
  sectionEditor.value = null;
  if (!element || builder.elements.length >= 20) return;
  builder.elements.push(element);
  // On a page the tenant has NOT arranged, this deliberately writes nothing: the new section lands at
  // its baseline position, which is the researched sequence and the whole point of having a baseline.
  // Recording an order here would quietly promote "I added a section" into "I have arranged this page
  // myself" and freeze the page against every future baseline change.
  if (builder.section_order?.length) {
    // Once they HAVE arranged it, their order is authoritative — the new section joins the end of it
    // rather than jumping to a baseline slot they never chose. Keyed the way readers key it: only
    // repeatable types key by element id, everything else by type.
    const key = sectionOrderKey(element);
    builder.section_order = [...sequenceRows.value.map((r) => r.key).filter((k) => k !== key), key];
  }
  await autoSavePage();
}

// The one line that makes a collapsed row worth scanning. Without it the map is a list of type names.
function rowSummary(row) {
  const e = row.element;
  if (row.type === "trust_badges") {
    const on = (builder.trust_badges.badges || []).filter((b) => b.enabled).length;
    return on ? `${on} showing` : "none showing";
  }
  if (row.type === "refund_policy") return builder.refund_policy.enabled === false ? "hidden" : "shown";
  if (row.type === "checkout_cta") return builder.cta_label || "Buy Now";
  if (row.type === "offer_price_selector") return "from the offer";
  if (row.type === "legal_footer") return "generated";
  if (row.type === "countdown_timer") return builder.countdown.enabled ? `${builder.countdown.duration_minutes || 15} min` : "off";
  if (!e) return "";
  if (row.type === "testimonials") return countLabel((e.items || []).filter((i) => (i.quote || "").trim()).length, "quote");
  if (row.type === "faq") return countLabel((e.items || []).filter((i) => (i.question || "").trim()).length, "question");
  if (row.type === "client_marquee") return countLabel((e.logos || []).filter((l) => l.image_url).length, "logo");
  if (row.type === "rating") return `${e.value || 5} stars`;
  if (row.type === "content_block") return e.title?.trim() || (e.text?.trim() ? "text" : "empty");
  // The author IS the section — whose credibility it borrows is the one thing worth reading off a
  // collapsed row, the way a content block shows its title.
  if (row.type === "author_bio") return e.name?.trim() || e.headline?.trim() || "empty";
  if (row.type === "bragging_points") return countLabel((e.items || []).filter((i) => (i.value || "").trim()).length, "point");
  if (row.type === "quote") return e.attribution?.trim() || (e.text?.trim() ? "quote" : "empty");
  if (row.type === "video") return (e.url || "").trim() ? videoKindLabel(e.url) : "no video yet";
  if (row.type === "before_after") {
    const have = [e.before_url, e.after_url].filter((u) => (u || "").trim()).length;
    return have === 2 ? "pair ready" : `${have} of 2 images`;
  }
  if (row.type === "numbered_list") return countLabel((e.items || []).filter((i) => (i || "").trim()).length, "item");
  if (row.type === "page_ribbon") return e.headline?.trim() || e.eyebrow?.trim() || "empty";
  return "";
}

function countLabel(n, noun) {
  if (!n) return "empty";
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

// Sections with no editor still earn a row: a tenant needs to see WHERE they land, even with nothing to set.
function rowNote(row) {
  if (row.empty) return "Nothing is showing on the page yet — switch one on below.";
  if (row.type === "offer_price_selector") return "Prices and options come from the offer.";
  if (row.type === "related_products") return "Chosen automatically from your catalog.";
  return "Nothing to configure — this section is generated.";
}

const rowDragFrom = ref(-1);

function onRowDragStart(index) {
  rowDragFrom.value = index;
}

async function onRowDrop(index) {
  const from = rowDragFrom.value;
  rowDragFrom.value = -1;
  const rows = sequenceRows.value;
  if (from < 0 || from === index || !rows[from] || !rows[index]) return;
  await moveSectionBefore(rows[from].key, rows[index].key);
}



// Reorder within the FREE band only: a drop onto (or across) a pinned row is ignored rather than
// silently doing nothing surprising, and orderSections re-applies the bands afterwards regardless.
// Reorder by section KEY — used by the drag handles on the form blocks themselves, where there is no
// row index to work from. Same builder.section_order the Section order list writes, so the two controls
// are one mechanism with two surfaces rather than two mechanisms that must agree.
async function moveSectionBefore(dragKey, dropKey) {
  if (!dragKey || !dropKey || dragKey === dropKey) return;
  const rows = sequenceRows.value;
  // The sequence now includes PINNED rows, so this guard is load-bearing again — without it the hero
  // could be dragged out of the top, which is the one thing placement exists to prevent.
  const movable = (key) => rows.find((row) => row.key === key)?.movable;
  if (!movable(dragKey) || !movable(dropKey)) return;
  const keys = rows.map((row) => row.key);
  const from = keys.indexOf(dragKey);
  const to = keys.indexOf(dropKey);
  if (from < 0 || to < 0) return;
  const [moved] = keys.splice(from, 1);
  keys.splice(to, 0, moved);
  builder.section_order = keys;
  // Both drag surfaces (the sequence rows and the form-block handles) route through here, so one call
  // covers them. `composition.overrides` and `section_order` are saved page fields, not view state --
  // before this they persisted only if the tenant happened to do something else that auto-saved
  // afterwards, which made "did my change stick?" depend on what they did next.
  await autoSavePage();
}







// The ribbon's CTA, or nothing. A button needs BOTH a label and somewhere to go, so a half-filled CTA
// renders no button rather than a dead one.
//
// For promote_page the URL is RE-RESOLVED here on every save, not just when the page was picked: the
// target's slug, Site or custom domain can change afterwards, and a stale absolute URL is exactly the
// kind of quietly-wrong link this codebase keeps producing.
function ribbonCta(cta) {
  const action = cta.action || "redirect";
  const label = (cta.label || "").trim();
  if (!label) return {};
  if (action === "email_file" && !businessEmailVerified.value) return {};
  if (action === "download" || action === "email_file") {
    // The asset IS the target here. Without a file there is nothing to hand over, so no button renders —
    // the same rule as a link with no URL.
    if (!cta.asset?.bucket_key) return {};
    return { cta: { label, action, asset: cta.asset,
      ...(cta.collect_email ? { collect_email: true } : {}),
      ...(cta.collect_phone ? { collect_phone: true } : {}) } };
  }
  if (action === "promote_page") {
    const page = cta.page_id ? pages.value.find((p) => p.page_id === cta.page_id) : null;
    if (!page) return {};
    return { cta: { label, action, page_id: page.page_id, target: pageUrl(page) } };
  }
  const target = (cta.target || "").trim();
  return target ? { cta: { label, action, target } } : {};
}

function elementSection(element) {
  if (element.type === "content_block") {
    if (!element.title && !element.text && !element.image_url) return null;
    return { id: element.id, type: "content_block", ...(element.centered ? { centered: true } : {}), blocks: [{ title: formatHeadline(element.title || ""), text: element.text || "", image_url: element.image_url || undefined }] };
  }
  if (element.type === "testimonials") {
    const items = (element.items || []).filter((item) => (item.quote || "").trim());
    if (!items.length) return null;
    return { id: element.id, type: "testimonials", heading: element.heading || undefined,
      items: items.map((item) => ({ quote: item.quote, author: item.author || undefined, role: item.role || undefined, avatar_url: item.avatar_url || undefined })) };
  }
  if (element.type === "rating") {
    return { id: element.id, type: "rating", value: Number(element.value || 0), count: Number(element.count || 0), label: element.label || undefined };
  }
  if (element.type === "client_marquee") {
    // An entry needs a name OR an image — the old filter required an image and silently dropped text.
    const logos = (element.logos || []).filter((l) => (l.name || "").trim() || (l.image_url || "").trim());
    if (!logos.length) return null;
    const scroll = element.scroll === "always" || element.scroll === "never" ? element.scroll : "auto";
    const seconds = Math.max(3, Math.min(60, Number(element.scroll_seconds) || 30));
    return { id: element.id, type: "client_marquee", heading: element.heading || undefined,
      logos: logos.map((l) => ({ name: l.name || "", image_url: l.image_url || undefined })),
      ...(scroll !== "auto" ? { scroll } : {}),
      ...(seconds !== 30 ? { scroll_seconds: seconds } : {}),
      ...(element.logo_backing === "none" ? { logo_backing: "none" } : {}) };
  }
  if (element.type === "faq") {
    const items = (element.items || []).filter((item) => item.question && item.answer);
    if (!items.length) return null;
    return {
      id: element.id,
      type: "faq",
      heading: formatHeadline(element.heading || "") || "Frequently Asked Questions",
      items: items.map((item) => ({ question: formatHeadline(item.question || ""), answer: item.answer })),
    };
  }
  if (element.type === "product_details") {
    return { id: element.id, type: "product_details" };   // content is the current target (offer-driven)
  }
  if (element.type === "social_links") {
    // Its OWN links if the tenant typed any, otherwise none at all -- and "none" is what tells the renderer
    // to fall back to the Site's organization.same_as. Absent rather than empty on purpose: an empty array
    // would be indistinguishable from "override with nothing", which is a page showing no links at all.
    const items = (element.items || []).filter((item) => (item.url || "").trim());
    return {
      id: element.id,
      type: "social_links",
      heading: formatHeadline(element.heading || "") || undefined,
      items: items.length ? items.map((item) => ({ url: item.url.trim() })) : undefined,
    };
  }
  if (element.type === "link_cards") {
    // A card needs somewhere to go AND something to call it; either alone is not a card.
    const items = (element.items || []).filter((item) => (item.url || "").trim() && (item.label || "").trim());
    if (!items.length) return null;
    return {
      id: element.id,
      type: "link_cards",
      heading: formatHeadline(element.heading || "") || undefined,
      items: items.map((item) => ({
        url: item.url.trim(),
        label: formatHeadline(item.label || ""),
        description: (item.description || "").trim() || undefined,
        image: (item.image_url || "").trim() || undefined,
      })),
    };
  }
  if (element.type === "page_ribbon") {
    if (!(element.headline || "").trim() && !(element.body || "").trim()) return null;
    const theme = element.theme && element.theme.bg ? element.theme : undefined;
    const cta = element.cta || {};
    return { id: element.id, type: "page_ribbon",
      purpose: element.purpose || "custom",
      presentation: element.presentation || "image_left",
      // centered has no image slot, so the URL is not carried into a document that will ignore it
      image_url: element.presentation === "centered" ? undefined : (element.image_url || undefined),
      eyebrow: element.eyebrow || undefined,
      headline: element.headline || undefined,
      body: element.body || undefined,
      ...ribbonCta(cta),
      theme };
  }
  if (element.type === "video") {
    if (!(element.url || "").trim()) return null;  // nothing to show
    return { id: element.id, type: "video", url: element.url.trim(),
      heading: (element.heading || "").trim() || undefined,
      caption: (element.caption || "").trim() || undefined,
      poster: (element.poster || "").trim() || undefined,
      aspect: Number(element.aspect) || undefined };
  }
  if (element.type === "before_after") {
    // One image is not a comparison, so an incomplete pair is dropped rather than half-rendered.
    if (!(element.before_url || "").trim() || !(element.after_url || "").trim()) return null;
    return { id: element.id, type: "before_after",
      heading: (element.heading || "").trim() || undefined,
      before_url: element.before_url, after_url: element.after_url,
      before_crop: element.before_crop || undefined, after_crop: element.after_crop || undefined,
      before_label: (element.before_label || "").trim() || undefined,
      after_label: (element.after_label || "").trim() || undefined,
      ratio: Number(element.ratio) || undefined, start: Number(element.start) };
  }
  if (element.type === "numbered_list") {
    // Plain strings, capped the way the renderer caps them so the document cannot carry more than shows.
    const items = (element.items || []).map((i) => (i || "").trim()).filter(Boolean).slice(0, 12);
    if (!items.length) return null;
    return { id: element.id, type: "numbered_list", heading: element.heading || undefined, items };
  }
  if (element.type === "quote") {
    if (!(element.text || "").trim()) return null;
    const theme = element.theme && element.theme.bg ? element.theme : undefined;
    return { id: element.id, type: "quote", text: element.text,
      title: element.title || undefined, image_url: element.image_url || undefined,
      attribution: element.attribution || undefined,
      ...(element.style === "fancy" ? { style: "fancy" } : {}), theme };
  }
  if (element.type === "bragging_points") {
    const items = (element.items || []).filter((i) => (i.value || "").trim() || (i.label || "").trim());
    if (!items.length) return null;
    const theme = element.theme && element.theme.bg ? element.theme : undefined;
    return { id: element.id, type: "bragging_points", heading: element.heading || undefined,
      items: items.map((i) => ({ value: i.value || "", label: i.label || "" })), theme };
  }
  if (element.type === "author_bio") {
    if (!element.photo_url && !element.name && !element.headline && !element.body) return null;
    const theme = element.theme && element.theme.bg ? element.theme : undefined;
    return { id: element.id, type: "author_bio", photo_url: element.photo_url || undefined,
      name: element.name || undefined, headline: formatHeadline(element.headline || "") || undefined,
      body: element.body || undefined, theme };
  }
  if (element.type === "price_highlight") {
    // Never null: the NUMBERS come from the offer, so this section is meaningful even with no copy at all.
    // The empty-check other elements use would wrongly drop it.
    return { id: element.id, type: "price_highlight",
      main_text: element.main_text || undefined, subtext: element.subtext || undefined };
  }
  if (element.type === "related_products") {
    return { id: element.id, type: "related_products", heading: element.heading || undefined };  // cards resolved at publish
  }
  return null;
}

// Rebuild the editable element list from an existing page's sections (round-trip on edit).
function elementsFromPage(sections) {
  const elements = [];
  for (const section of sections || []) {
    if (section.type === "content_block") {
      for (const block of section.blocks || []) {
        elements.push({ id: localId("el"), type: "content_block", title: block.title || "", text: block.text || "", image_url: block.image_url || "", centered: Boolean(section.centered) });
      }
    } else if (section.type === "testimonials") {
      elements.push({ id: localId("el"), type: "testimonials", heading: section.heading || "",
        items: (section.items || []).map((item) => ({ quote: item.quote || "", author: item.author || "", role: item.role || "", avatar_url: item.avatar_url || "" })) });
    } else if (section.type === "page_ribbon") {
      elements.push({ id: localId("el"), type: "page_ribbon",
        purpose: section.purpose || "custom", presentation: section.presentation || "image_left",
        image_url: section.image_url || "", eyebrow: section.eyebrow || "",
        headline: section.headline || "", body: section.body || "",
        cta: { label: section.cta?.label || "", action: section.cta?.action || "redirect",
               page_id: section.cta?.page_id || "", target: section.cta?.target || "",
               asset: section.cta?.asset || null,
               collect_email: Boolean(section.cta?.collect_email),
               collect_phone: Boolean(section.cta?.collect_phone) },
        theme: section.theme ? { ...section.theme } : {} });
    } else if (section.type === "video") {
      elements.push({ id: localId("el"), type: "video", url: section.url || "",
        heading: section.heading || "", caption: section.caption || "", poster: section.poster || "",
        aspect: Number(section.aspect) || 1.7777777778 });
    } else if (section.type === "before_after") {
      elements.push({ id: localId("el"), type: "before_after", heading: section.heading || "",
        before_url: section.before_url || "", after_url: section.after_url || "",
        before_crop: section.before_crop || null, after_crop: section.after_crop || null,
        before_label: section.before_label || "Before", after_label: section.after_label || "After",
        ratio: Number(section.ratio) || 1.3333333333,
        start: Number.isFinite(Number(section.start)) ? Number(section.start) : 50 });
    } else if (section.type === "numbered_list") {
      elements.push({ id: localId("el"), type: "numbered_list", heading: section.heading || "",
        items: (section.items || []).map((i) => String(i || "")) });
    } else if (section.type === "quote") {
      elements.push({ id: localId("el"), type: "quote", text: section.text || "",
        title: section.title || "", image_url: section.image_url || "",
        attribution: section.attribution || "", style: section.style === "fancy" ? "fancy" : "minimal",
        theme: section.theme ? { ...section.theme } : {} });
    } else if (section.type === "bragging_points") {
      elements.push({ id: localId("el"), type: "bragging_points", heading: section.heading || "",
        items: (section.items || []).map((i) => ({ value: i.value || "", label: i.label || "" })),
        theme: section.theme ? { ...section.theme } : {} });
    } else if (section.type === "author_bio") {
      elements.push({ id: localId("el"), type: "author_bio", photo_url: section.photo_url || "",
        name: section.name || "", headline: section.headline || "", body: section.body || "",
        theme: section.theme ? { ...section.theme } : {} });
    } else if (section.type === "price_highlight") {
      elements.push({ id: localId("el"), type: "price_highlight",
        main_text: section.main_text || "", subtext: section.subtext || "" });
    } else if (section.type === "rating") {
      elements.push({ id: localId("el"), type: "rating", value: section.value ?? 5, count: section.count ?? 0, label: section.label || "" });
    } else if (section.type === "client_marquee") {
      elements.push({ id: localId("el"), type: "client_marquee", heading: section.heading || "",
        logos: (section.logos || []).map((l) => ({ name: l.name || "", image_url: l.image_url || "" })),
        scroll: section.scroll === "always" || section.scroll === "never" ? section.scroll : "auto",
        scroll_seconds: Number(section.scroll_seconds) || 30,
        logo_backing: section.logo_backing === "none" ? "none" : "card" });
    } else if (section.type === "faq") {
      elements.push({ id: localId("el"), type: "faq", heading: section.heading || "Frequently Asked Questions", items: (section.items || []).map((item) => ({ question: item.question || "", answer: item.answer || "" })) });
    } else if (section.type === "product_details") {
      elements.push({ id: localId("el"), type: "product_details" });
    } else if (section.type === "related_products") {
      elements.push({ id: localId("el"), type: "related_products", heading: section.heading || "Related products" });
    } else if (section.type === "social_links") {
      elements.push({ id: localId("el"), type: "social_links", heading: section.heading || "",
        items: (section.items || []).map((item) => ({ url: item.url || "" })) });
    } else if (section.type === "link_cards") {
      // `image` on the wire, `image_url` in the form — the upload helper writes image_url, and every other
      // element in this builder spells it that way.
      elements.push({ id: localId("el"), type: "link_cards", heading: section.heading || "",
        items: (section.items || []).map((item) => ({
          url: item.url || "", label: item.label || "",
          description: item.description || "", image_url: item.image || "",
        })) });
    }
  }
  return elements;
}

async function onBuilderOfferChange() {
  const offer = builderOffer.value;
  if (!offer) return;
  // The offer's presentation (name/description/hero/prices) resolves against products+services;
  // ensure they're loaded before seeding so defaults come from the offer contract, not fallbacks.
  await ensureCatalogLoaded();
  builder.offerName = offer.name || "";
  if (!builder.name) builder.name = `${offer.name || "Offer"} Landing Page`;
  if (!builder.slug) builder.slug = slugify(offer.slug || offer.name || builder.page_id);
  // A listicle sells several distinct products, so seeding the hero with ONE product's copy makes it wrong on
  // every other slide. Leave the hero blank instead — the renderer makes it target-bound (each product's own
  // name/description, swapped per slide). Other offer types seed the single product's copy as before.
  if (deriveOfferType(offer) !== "listicle") {
    builder.headline = formatHeadline(offerHeadline(offer) || builder.headline || builder.name);
    builder.subheadline = offerDescription(offer) || builder.subheadline || "Choose your option and continue.";
  }
  // Leave SEO title/description blank by default so the renderer derives them live (the fields show the
  // derived default as a placeholder). Only a tenant edit is stored.
  if (!builder.seo_image) builder.seo_image = offerImage(offer);
  // A listicle's hero carousel IS the product images — auto-fill the hero media field with one per item.
  if (deriveOfferType(offer) === "listicle") {
    const productImages = conversionTargets.value.map((target) => target.hero_image).filter(Boolean);
    if (productImages.length) builder.hero_media_text = productImages.join("\n");
  } else if (!builder.hero_media_text && offerImage(offer)) {
    builder.hero_media_text = offerImage(offer);
  }
  // The offer is the page's contract: take the CTA label it snapshotted, falling back to a sensible default.
  builder.cta_label = offer.presentation?.cta?.label || offer.presentation?.cta_label
    || (builderIntent.value === "lead_gen" ? "Continue" : "Buy Now");
  builder.template = "universal_bundle";
  builder.preset = builder.preset || "clean-slate";
}

async function editOfferlessPage(page) {
  const sections = page.sections || [];
  const brandHero = sections.find((s) => s && s.type === "brand_hero");
  const catalog = sections.find((s) => s && s.type === "catalog_grid");
  const profile = sections.find((s) => s && s.type === "seller_profile");

  // The grid embeds a Collection (its source of truth). Load it to determine kind (category vs storefront) and
  // restore the grid config. A legacy INLINE grid (pre-migration) has no collection_id — read its inline config;
  // saving then mints a Collection and migrates the page (plans/SITE_COLLECTIONS.md P1e).
  collectionsStore.ensureLoaded();  // populate the list so the "use an existing collection" picker has options
  const collection = catalog?.collection_id ? await collectionsStore.get(catalog.collection_id).catch(() => null) : null;
  const kind = profile ? "profile"
    : collection ? (collection.rule === "category" ? "category" : "storefront")
    : (catalog?.category ? "category" : "storefront");

  resetWizard();
  form.pageKind = kind;
  form.page_id = page.page_id;
  form.name = page.name || "";
  form.slug = page.route?.slug || "";
  // Restore the store-name mode: a saved headline matching a business brand edits as a brand selection.
  const savedHeadline = brandHero?.headline || "";
  if (savedHeadline && storeBrands.value.includes(savedHeadline)) {
    form.storefront.nameMode = "brand";
    form.storefront.brand = savedHeadline;
  } else {
    form.storefront.nameMode = "custom";
    form.storefront.headline = savedHeadline;
  }
  form.storefront.tagline = brandHero?.tagline || "";
  form.storefront.logo_url = brandHero?.logo_url || "";
  form.storefront.collection_id = catalog?.collection_id || "";
  if (collection) {
    form.storefront.heading = collection.presentation?.heading || catalog?.heading || "";
    if (kind === "category") form.categoryKey = collection.category || "";
    else {
      form.storefront.autoFill = collection.rule === "all";
      form.storefront.items = collection.rule === "manual" ? [...(collection.members || [])] : [];
      // A storefront embedding a collection SHARED by other pages edits it by reference (source=existing), so a
      // tweak here can't silently rewrite what those other pages show; a 1:1 owned collection stays inline.
      if (collectionUsageCount(collection.collection_id) > 1) {
        form.storefront.source = "existing";
        form.storefront.existingCollectionId = collection.collection_id;
      }
    }
  } else {
    form.storefront.heading = catalog?.heading || profile?.heading || "";
    form.categoryKey = catalog?.category || "";
  }
  editingOfferlessOriginal.value = { ...page };
  wizardOpen.value = true;
  wizardStep.value = 2;
  try {
    await ensureCatalogLoaded();
    if (kind === "category") await ensureProductsLoaded();
  } catch (err) {
    wizardError.value = err.message || "Failed to load catalog.";
  }
  // Legacy inline storefront: map the stored {offer_id} items back to page_ids for the picker (needs pages loaded).
  if (kind === "storefront" && !collection) {
    form.storefront.autoFill = catalog?.scope === "all";
    const pageByOffer = new Map((pages.value || []).filter((p) => p.offer_id).map((p) => [p.offer_id, p.page_id]));
    form.storefront.items = (catalog?.items || []).map((it) => pageByOffer.get(it.offer_id)).filter(Boolean);
  }
}

function editPage(page) {
  openMenuId.value = "";
  if (isStorefrontPage(page)) {
    editOfferlessPage(page);
    return;
  }
  populateBuilderFromPage(page);
  loadLinkClicks(page.page_id);
  builderExistingPageId.value = page.page_id;
  builderOriginalPage.value = { ...page };
  builderOpen.value = true;
  builderFormHidden.value = false;
}

function requestArchivePage(page) {
  openMenuId.value = "";
  pendingArchivePage.value = page;
}

// Clone a page into a fresh draft: new page_id, "(Copy)" name, a distinct slug, and unattached from any
// Site (the copy is the tenant's to place). Same env — cross-environment copy is a separate action.
async function duplicatePage(page) {
  openMenuId.value = "";
  const now = Math.floor(Date.now() / 1000);
  const copy = cleanObject({
    ...page,
    page_id: localId("page"),
    name: `${page.name || "Landing page"} (Copy)`,
    route: { ...(page.route || {}), slug: slugify(`${page.route?.slug || page.name || "page"}-copy`) },
    status: "draft",
    published_at: null,
    revision: 1,
    created_at: now,
    updated_at: now,
  });
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const body = await apiRequest("/pages", { method: "POST", body: copy });
    const saved = body.page || copy;
    pages.value = [saved, ...pages.value.filter((p) => p.page_id !== saved.page_id)];
    message.value = `Duplicated as “${saved.name}” (draft, no Site).`;
  } catch (err) {
    error.value = err.message || "Failed to duplicate the page.";
  } finally {
    saving.value = false;
  }
}

// ---- Copy a page (and its catalog) to the other environment (plans/COPY_TO_ENVIRONMENT.md) ----
const targetEnv = computed(() => getOtherEnvironment());
const targetEnvLabel = computed(() => (targetEnv.value === "live" ? "Live" : "Test"));
const copyBusy = ref(false);
const copyError = ref("");
const copyPlan = ref(null);  // { page, offerDocs, productDocs, existingTarget, hasServices } while the confirm is open

async function copyPageToEnvironment(page) {
  openMenuId.value = "";
  copyError.value = "";
  copyBusy.value = true;
  try {
    await ensureCatalogLoaded().catch(() => {});
    const { offerDocs, productDocs, hasServices } = await resolvePageDeps(page, { offerCache: offers.value, productCache: products.value });
    // Pre-flight the target PAGE (drives the draft-vs-keep-published rule + overwrite messaging).
    const existingTarget = await apiRequest(`/pages/${encodeURIComponent(page.page_id)}`, { mode: targetEnv.value })
      .then((b) => b.page).catch(() => null);
    copyPlan.value = { page, offerDocs, productDocs, existingTarget, hasServices };
  } catch (err) {
    copyError.value = err.message || "Couldn't prepare the copy.";
  } finally {
    copyBusy.value = false;
  }
}

async function executeCopy() {
  const plan = copyPlan.value;
  if (!plan) return;
  const env = targetEnv.value;
  copyError.value = "";
  copyBusy.value = true;
  try {
    // Bottom-up so references resolve in the target: products -> offer(s) -> page.
    await copyCatalogToEnv(plan.productDocs, plan.offerDocs, env);
    await apiRequest("/pages", { method: "POST", body: pageForTarget(plan.page, plan.existingTarget, env), mode: env });
    const n = plan.productDocs.length;
    message.value = `Copied “${plan.page.name}”${plan.offerDocs.length ? ` + its offer and ${n} product${n === 1 ? "" : "s"}` : ""} to ${targetEnvLabel.value}.`;
    copyPlan.value = null;
  } catch (err) {
    copyError.value = err.message || "Copy failed. Some items may have been copied; re-run to finish.";
  } finally {
    copyBusy.value = false;
  }
}

// When the dashboard publishes a page that embeds a manual collection, the server auto-publishes that collection's
// draft members (the cascade in runtime/publishing.py). That runs asynchronously via the publish stream, so those
// members keep showing DRAFT in this list until a manual reload. Reflect it optimistically — mark the collection's
// draft members published locally now. A reload reconciles from the server (the source of truth); this only clears
// the transient stale badge, mirroring the cascade's deterministic rule (manual collection → its draft members).
async function reflectCascadedMembers(savedPage) {
  if (!savedPage || savedPage.status !== "published") return;
  const memberIds = new Set();
  for (const section of savedPage.sections || []) {
    if (section?.type !== "catalog_grid" || !section.collection_id) continue;
    const collection = await collectionsStore.get(section.collection_id).catch(() => null);
    if (collection?.rule === "manual") (collection.members || []).forEach((id) => memberIds.add(String(id)));
  }
  if (!memberIds.size) return;
  const now = Math.floor(Date.now() / 1000);
  pages.value = pages.value.map((p) =>
    memberIds.has(p.page_id) && p.status === "draft"
      ? { ...p, status: "published", published_at: p.published_at || now }
      : p);
}

async function publishPage(page) {
  openMenuId.value = "";
  const publishedPage = applyPageStatus(page, "published");
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const body = await apiRequest("/pages", { method: "POST", body: publishedPage });
    const saved = body.page || publishedPage;
    pages.value = pages.value.map((item) => item.page_id === saved.page_id ? saved : item);
    await reflectCascadedMembers(saved);  // reflect the server-side draft-member cascade in the list badges
    const attachedTo = await ensureSiteAttachmentOnPublish(saved);
    message.value = attachedTo
      ? `${saved.name || "Landing page"} was published and attached to ${attachedTo}.`
      : `${saved.name || "Landing page"} was published.`;
  } catch (err) {
    error.value = err.message || "Failed to publish landing page.";
  } finally {
    saving.value = false;
  }
}

async function togglePagePublished(page) {
  if (page.status === "published") return unpublishPage(page);
  return publishPage(page);
}

async function unpublishPage(page) {
  openMenuId.value = "";
  const unpublishedPage = applyPageStatus(page, "draft");
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const body = await apiRequest("/pages", { method: "POST", body: unpublishedPage });
    const saved = body.page || unpublishedPage;
    pages.value = pages.value.map((item) => item.page_id === saved.page_id ? saved : item);
    message.value = `${saved.name || "Landing page"} was unpublished.`;
  } catch (err) {
    error.value = err.message || "Failed to unpublish landing page.";
  } finally {
    saving.value = false;
  }
}

async function removePage() {
  if (!pendingArchivePage.value) return;
  const page = pendingArchivePage.value;
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    // A page leaving the catalog must also leave its Site, or the Site's route map is left pointing at a
    // gone/stale page — a phantom slug, or a homepage that 404s on the custom domain. Detach first so the
    // Site stays consistent even if the archive/delete below fails.
    const site = siteForPage(page);
    if (site) await sitesStore.detachPage(site.site_id, page.page_id, page.tenant_id);
    if (page.status === "published") {
      const archivedPage = applyPageStatus(page, "archived");
      const body = await apiRequest("/pages", { method: "POST", body: archivedPage });
      const saved = body.page || archivedPage;
      pages.value = pages.value.map((item) => item.page_id === saved.page_id ? saved : item);
      message.value = `${saved.name || "Landing page"} was archived.`;
    } else {
      await apiRequest(`/pages/${encodeURIComponent(page.page_id)}`, { method: "DELETE" });
      pages.value = pages.value.filter((item) => item.page_id !== page.page_id);
      message.value = `${page.name || "Landing page"} was deleted.`;
    }
    pendingArchivePage.value = null;
  } catch (err) {
    error.value = err.message || "Failed to remove landing page.";
  } finally {
    saving.value = false;
  }
}

function applyPageStatus(page, statusOverride = "") {
  if (!statusOverride) return { ...page };
  const now = Math.floor(Date.now() / 1000);
  return {
    ...page,
    status: statusOverride,
    published_at: statusOverride === "published" ? (page.published_at || now) : page.published_at,
    archived_at: statusOverride === "archived" ? now : page.archived_at,
    updated_at: now,
  };
}

function servicePricesOf(service) {
  if (Array.isArray(service?.prices) && service.prices.length) return service.prices;
  return service?.price ? [{ price_id: `svcprice_${service.service_id}`, ...service.price }] : [];
}

function normalizedPriceCard(priceRecord, option, model, item, displayIndex) {
  const unitAmount = Number(priceRecord.unit_amount || 0);
  const compareAt = Number(priceRecord.compare_at_unit_amount || 0);
  const calculatedSavings = compareAt > unitAmount && unitAmount > 0
    ? Math.round(((compareAt - unitAmount) / compareAt) * 100)
    : 0;
  return {
    price_id: option?.price_id || priceRecord.price_id || item.price_id,
    label: option?.label || item.display_label || priceRecord.label || model.name || "Option",
    description: option?.description || priceRecord.description || model.description || "",
    badge: option?.badge || "",
    image_url: option?.image_url || priceRecord.image_url || model.image || "",
    unit_amount: unitAmount,
    compare_at_unit_amount: compareAt,
    savings_pct: Number(option?.savings_pct || priceRecord.savings_pct || calculatedSavings || 0),
    currency: priceRecord.currency || "usd",
    quantity: option ? landingPagePriceQuantity(priceRecord, option) : Number(item.quantity || 1),
    display_index: displayIndex,
  };
}

// Single normalization: shape any offer item (product, service, or a future type) into a uniform
// presentation model { type, id, name, description, image, priceCards[] }. Everything else in the
// builder consumes these models and stays blind to the underlying object type — the offer is the
// contract. To support a new item type, add a branch here and nothing else changes.
function offerItemModels(offer) {
  const items = Array.isArray(offer?.items) ? offer.items : [];
  const models = [];
  let displayIndex = 0;
  for (const item of items) {
    let model = null;
    if (item.service_id) {
      const service = servicesById.value.get(item.service_id);
      if (!service) continue;
      model = { type: "service", id: item.service_id, name: service.name || "", description: service.description || "", image: service.presentation?.hero_image_url || "", priceCards: [] };
      const prices = servicePricesOf(service);
      const price = prices.find((candidate) => candidate.price_id === item.price_id) || prices[0];
      if (price && isLandingPagePrice(price)) {
        model.priceCards.push(normalizedPriceCard(price, null, model, item, displayIndex));
        displayIndex += 1;
      }
    } else if (item.product_id) {
      const product = productsById.value.get(item.product_id);
      if (!product) continue;
      model = { type: "product", id: item.product_id, name: product.name || "", description: product.description || "", image: product.images?.[0] || "", priceCards: [] };
      for (const option of item.selectable_prices || []) {
        const price = (product.prices || []).find((candidate) => candidate.price_id === option.price_id);
        if (!price || !isLandingPagePrice(price)) continue;
        model.priceCards.push(normalizedPriceCard(price, option, model, item, displayIndex));
        displayIndex += 1;
      }
    }
    if (model) models.push(model);
  }
  return models;
}

// --- Offer presentation contract: the fields the landing page derives from any offer by default ---
function offerImage(offer) {
  return offer?.presentation?.image_url || offer?.presentation?.hero_image_url || offerItemModels(offer)[0]?.image || "";
}

function offerHeadline(offer) {
  return offer?.presentation?.headline || offer?.name || "";
}

function offerDescription(offer) {
  return offer?.presentation?.subheadline || offerItemModels(offer)[0]?.description || "";
}

// The four landing-page copy fields get DISTINCT, product-derived defaults — never the internal offer
// label ("… Single Offer"). Live-derived (plans/LANDING_PAGE_DEFAULT_COPY.md): a tenant edit overrides;
// an untouched field falls back here.

// Brand shown on the page: the offer's picked brand, else the tenant's business name, else the product name.
// presentation.headline is the product-name snapshot stored on the offer — a robust last resort that needs
// no product fetch and is never the internal offer label.
function offerBrandDefault(offer) {
  return offer?.presentation?.brand
    || profileStore.businessName
    || offerProducts(offer)[0]?.name
    || offerItemModels(offer)[0]?.name
    || offer?.presentation?.headline
    || "";
}

// SEO <title> distinct from the H1: "<Product> | <Brand>" (brand = offer's pick / business name / platform).
// Mirrors the renderer's document_title so the placeholder matches what publishes.
function offerSeoTitleDefault(offer) {
  const name = offerProducts(offer)[0]?.name || offer?.presentation?.headline || "";
  const brand = offer?.presentation?.brand || profileStore.businessName || "Junior Bay";
  return name ? `${name} | ${brand}` : brand;
}

// Meta description: the offer subheadline (product description), trimmed — never the offer label.
function offerSeoDescriptionDefault(offer) {
  const text = offer?.presentation?.subheadline || offerProducts(offer)[0]?.description || "";
  return trimForMeta(text);
}

// Old code baked the internal offer label into page.seo (title = "… Single Offer Landing Page",
// description = product name). Treat those as non-overrides on load so the page re-derives — a genuine
// tenant title/description is kept.
function isAutoBakedSeoTitle(page) {
  const title = String(page?.seo?.title || "");
  return !title || /\bSingle Offer\b|\bBundle\b|Landing Page\s*$/i.test(title) || title === page?.name;
}

// Trim to a SERP-friendly length at a word boundary (no mid-word cut, no trailing punctuation).
function trimForMeta(text, max = 155) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  return clean.slice(0, clean.lastIndexOf(" ", max) > 0 ? clean.lastIndexOf(" ", max) : max).replace(/[,;:\s]+$/, "");
}

// ONE answer to "is this offer lead-gen?". Four places asked it and three agreed: deriveOfferType --
// the one driving SECTION VISIBILITY -- read the offer alone, with no product fallback. An offer whose
// intent had to come from its product therefore got a lead-gen CTA and TRANSACTIONAL sections, which is
// a page wearing trust badges and a refund policy while selling nothing.
function offerIntent(offer) {
  return offer?.product_intent || offerProducts(offer)[0]?.product_intent || "transaction";
}

function offerProducts(offer) {
  const items = Array.isArray(offer?.items) ? offer.items : [];
  return items.map((item) => productsById.value.get(item.product_id)).filter(Boolean);
}

function offerIntentLabel(offer) {
  const intent = offerIntent(offer);
  return intent === "lead_gen" ? "Lead generation" : "Transaction";
}

function pageIntentLabel(page) {
  const offer = offers.value.find((item) => item.offer_id === page.offer_id);
  return offer ? offerIntentLabel(offer) : "Offer";
}

function productSummary(offer) {
  return (Array.isArray(offer?.items) ? offer.items : []).map((item) => item.product_id).filter(Boolean).join(", ");
}

function offerItemCount(offer) {
  return Array.isArray(offer?.items) ? offer.items.length : 0;
}

function itemCount(page) {
  const offer = offers.value.find((item) => item.offer_id === page.offer_id);
  return offerItemCount(offer) || "0";
}

// Every page uses the one universal_bundle template, so the template name is noise — show the PRESET
// (the tenant's actual visual choice: Trust Blue, Rose Minimalist, ...) instead.
function templateLabel(page) {
  const preset = page.theme?.preset || "";
  return universalBundlePresets.find((option) => option.value === preset)?.label
    || (preset ? preset : "Clean Slate");
}

function statusLabel(status) {
  return String(status || "draft").replace(/_/g, " ").toUpperCase();
}

function pagePathId(page) {
  return String(page.page_id || "").replace(/^\/+|\/+$/g, "");
}

// Test pages publish under a `test/` prefix so they never collide with the live promotion of the same page_id
// (plans/STRIPE_MODE_DECOUPLING.md P5); live pages keep the root key.
function modePrefix() {
  return getStripeMode() === "live" ? "" : "test/";
}

function artifactPageUrl(page) {
  const pageId = pagePathId(page).split("/").map(encodeURIComponent).join("/");
  return `${getPagesBaseUrl()}/${modePrefix()}${pageId}/index.html`;
}

function previewArtifactPageUrl(page) {
  const tenantId = encodeURIComponent(page.tenant_id || getTenantId());
  const pageId = pagePathId(page).split("/").map(encodeURIComponent).join("/");
  return `${getPreviewPagesBaseUrl()}/preview/${modePrefix()}${tenantId}/${pageId}/index.html`;
}

// Per-card pricing-view selection (Standard / Sale / Flash Sale) for the test viewer, keyed by page_id. The
// URL / Copy / Preview all follow the selected view, mirroring the builder's Live Preview toggle.
const cardViews = reactive({});
function cardViewOptions(page) {
  // Only the test viewer has /sale //flash-sale views, and only when the page enables that context.
  if (getStripeMode() !== "test" || !page.short_code) return [];
  const opts = [{ value: "standard", label: "Standard" }];
  if (page.sale?.enabled) opts.push({ value: "sale", label: "Sale" });
  if (page.flash_sale?.enabled) opts.push({ value: "flash_sale", label: "Flash Sale" });
  return opts;
}
function cardView(page) {
  const chosen = cardViews[page.page_id] || "standard";
  // If the chosen view was toggled off, fall back to Standard.
  return cardViewOptions(page).some((o) => o.value === chosen) ? chosen : "standard";
}
function setCardView(page, view) {
  cardViews[page.page_id] = view;
}

function pageUrl(page) {
  // A published, Site-attached page is served on the Site's navigable host — a verified custom domain or its
  // free platform host ({label}.jbay.uk / .jbay.be), which now resolves in BOTH environments. Prefer that real,
  // navigable store URL (Standard view) over the single-page test viewer, so links land on the actual store
  // where the buyer can navigate (plans/PLATFORM_HOSTNAME_SERVING.md P3).
  const view = cardView(page);
  if (page.status === "published" && view === "standard") {
    const siteUrl = sitePublicUrl(page);
    if (siteUrl) return siteUrl;
  }
  // Sale/Flash-Sale preview views + unattached/draft pages: the platform test viewer, keyed by short_code.
  const testHost = getTestPagesHost();  // {stage}-test.juniorbay.com from app_config
  if (testHost && getStripeMode() === "test" && page.short_code) {
    const seg = page.status === "published" ? "published" : "preview";
    const viewSeg = view === "sale" ? "/sale" : view === "flash_sale" ? "/flash-sale" : "";
    return `https://${testHost}/${seg}/${encodeURIComponent(page.short_code)}${viewSeg}`;
  }
  if (page.status === "published") return sitePublicUrl(page) || artifactPageUrl(page);
  return previewArtifactPageUrl(page);
}

function previewPageUrl(page) {
  return pageUrl(page);
}

async function copyPageUrl(page) {
  openMenuId.value = "";
  const value = pageUrl(page);
  if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value).catch(() => {});
  message.value = "Landing page URL copied.";
}

function previewPage(page) {
  openMenuId.value = "";
  window.open(previewPageUrl(page), "_blank", "noopener,noreferrer");
}

function viewPage(page) {
  openMenuId.value = "";
  selectedPageDetails.value = page;
}

function toggleMenu(pageId) {
  openMenuId.value = openMenuId.value === pageId ? "" : pageId;
}

// The offer's cta.type is the single source of truth for the on-page CTA; these just label it for the UI.
function ctaTypeLabel(type) {
  const labels = {
    buy: "Buy — price + checkout",
    call: "Call — click-to-call",
    email: "Email — inline capture form",
    external: "External link",
    download: "Download — file",
    booking: "Booking — inline calendar",
    appointment: "Appointment — inline calendar",
  };
  return labels[type] || "Buy — price + checkout";
}

function ctaTypeDescription(type) {
  const descriptions = {
    buy: "Shows the price card(s) and a Stripe checkout button.",
    call: "Shows a tel: call button and the phone number.",
    email: "Collects the visitor's contact details inline.",
    external: "Sends the visitor to an external URL.",
    download: "Downloads a file for the visitor.",
    booking: "Reveals a booking calendar to schedule the service.",
    appointment: "Reveals a booking calendar to schedule the appointment.",
  };
  return descriptions[type] || descriptions.buy;
}

function productId(product) {
  return product?.product_id || product?.stripe_product_id || product?.name || "";
}

function slugify(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "landing-page";
}

function localId(prefix = "local") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

function cleanObject(value) {
  if (Array.isArray(value)) return value.map(cleanObject);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value)
    .filter(([, item]) => item !== undefined && item !== "" && item !== null)
    .map(([key, item]) => [key, cleanObject(item)]));
}

</script>

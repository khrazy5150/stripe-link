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
          <input
            v-model.trim="search"
            class="landing-search"
            type="search"
            placeholder="Search pages..."
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
          <article v-for="page in filteredPages" :key="page.page_id" class="landing-page-card">
            <div class="landing-page-image">
              <img v-if="pageImage(page)" :src="pageImage(page)" :alt="page.name || 'Landing page image'" />
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
                  <p>{{ templateLabel(page) }} <span>{{ page.page_id }}</span></p>
                </div>
              </div>

              <div class="landing-page-url-row">
                <span class="landing-page-url">{{ pageUrl(page) }}</span>
                <button class="copy-icon-button" type="button" aria-label="Copy landing page URL" @click="copyPageUrl(page)">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9h9.75A1.25 1.25 0 0 1 20 10.25V20a1.25 1.25 0 0 1-1.25 1.25H9A1.25 1.25 0 0 1 7.75 20v-9.75A1.25 1.25 0 0 1 9 9Zm-5-5h9.75A1.25 1.25 0 0 1 15 5.25V7.5M4 4h9.75M4 4v9.75A1.25 1.25 0 0 0 5.25 15H7.5" />
                  </svg>
                </button>
                <button class="secondary-action compact" type="button" @click="previewPage(page)">Preview</button>
              </div>

              <div class="landing-page-meta">
                <span>{{ itemCount(page) }} item(s)</span>
                <span>{{ Number(page.analytics_summary?.views || 0) }} views</span>
                <span>{{ Number(page.analytics_summary?.conversions || 0) }} conversions</span>
                <strong>{{ formatMoney(page.analytics_summary?.revenue_cents || 0) }}</strong>
                <span>revenue</span>
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

    <div v-if="wizardOpen" class="modal-backdrop" @click.self="closeWizard">
      <section class="modal-card landing-wizard-modal" role="dialog" aria-modal="true" aria-labelledby="landingWizardTitle">
        <header class="modal-card-header">
          <div>
            <h2 id="landingWizardTitle">Create Landing Page</h2>
            <p>Step {{ wizardStep }} of 4</p>
          </div>
          <button type="button" class="modal-close" aria-label="Close landing page wizard" @click="closeWizard">×</button>
        </header>

        <div class="wizard-progress" aria-hidden="true">
          <span v-for="step in 4" :key="step" :class="{ active: step <= wizardStep }"></span>
        </div>

        <div class="landing-wizard-body">
          <section v-if="wizardStep === 1" class="wizard-step">
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
          </section>

          <section v-else-if="wizardStep === 2" class="wizard-step">
            <header class="wizard-step-header">
              <h3>Page Goal</h3>
              <p>Where will this page's traffic come from? This decides what the page starts with — you can change any of it later.</p>
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
          <button class="secondary-action" type="button" @click="wizardStep === 1 ? closeWizard() : wizardStep--">
            {{ wizardStep === 1 ? "Cancel" : "Back" }}
          </button>
          <button v-if="wizardStep < 4" class="primary-action" type="button" @click="nextWizardStep">Next</button>
          <button v-else class="primary-action" type="button" @click="startBuilderFromWizard">
            Continue to Builder
          </button>
        </footer>
      </section>
    </div>

    <section v-if="builderOpen" class="landing-builder-shell" :class="{ 'preview-only': builderFormHidden }">
      <article v-if="!builderFormHidden" class="dashboard-card landing-builder-form-card">
        <header class="dashboard-card-header landing-builder-header">
          <div>
            <h2>{{ builderExistingPageId ? "Edit Landing Page" : "Create Landing Page" }}</h2>
            <p>{{ builder.offerName || "Configure the page before saving." }}</p>
          </div>
          <button class="secondary-action compact" type="button" @click="builderFormHidden = !builderFormHidden">
            {{ builderFormHidden ? "Show Form" : "‹‹ Hide Form" }}
          </button>
        </header>

        <div v-if="error" class="keys-status-banner error landing-builder-status">{{ error }}</div>
        <div v-else-if="message" class="keys-status-banner landing-builder-status">{{ message }}</div>

        <div v-if="!builderFormHidden" class="landing-builder-body">
          <div v-if="isBuilderPublished" class="keys-status-banner warning">
            Published pages cannot be modified. Unpublish this page before editing.
          </div>

          <section class="builder-section">
            <h3>Page Basics</h3>
            <label class="offer-field">
              <span>Page Name</span>
              <input v-model.trim="builder.name" type="text" />
              <small>Internal name for organizing your pages.</small>
            </label>

            <div class="offer-two-column">
              <label class="offer-field">
                <span>Preset</span>
                <select v-model="builder.preset">
                  <option v-for="option in universalBundlePresets" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </label>
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
            </div>

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
          </section>

          <section class="builder-section">
            <h3>Countdown Timer</h3>
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
              <div class="builder-countdown-row">
                <label class="builder-toggle">
                  <input v-model="builder.countdown.start_enabled" type="checkbox" />
                  <span>Banner Start</span>
                </label>
                <input v-model.trim="builder.countdown.start_icon" class="builder-icon-input" type="text" aria-label="Start icon" />
                <input v-model.trim="builder.countdown.start_text" type="text" aria-label="Start text" />
                <input v-model="builder.countdown.start_color" type="color" aria-label="Start color" />
              </div>
              <div class="builder-countdown-row">
                <label class="builder-toggle">
                  <input v-model="builder.countdown.end_enabled" type="checkbox" />
                  <span>Banner End</span>
                </label>
                <input v-model.trim="builder.countdown.end_icon" class="builder-icon-input" type="text" aria-label="End icon" />
                <input v-model.trim="builder.countdown.end_text" type="text" aria-label="End text" />
                <input v-model="builder.countdown.end_color" type="color" aria-label="End color" />
              </div>
            </div>
          </section>

          <section class="builder-section">
            <h3>SEO</h3>
            <label class="offer-field">
              <span>SEO Title</span>
              <input :value="builder.seo_title" type="text" @input="applyTitleCaseInput((value) => { builder.seo_title = value; }, $event)" />
            </label>
            <label class="offer-field">
              <span>SEO Description</span>
              <textarea v-model.trim="builder.seo_description" rows="3"></textarea>
            </label>
          </section>

          <section class="builder-section">
            <h3>Hero</h3>
            <label class="offer-field">
              <span>Hero Headline</span>
              <input :value="builder.headline" type="text" @input="applyTitleCaseInput((value) => { builder.headline = value; }, $event)" />
            </label>
            <label class="offer-field">
              <span>Hero Subheadline</span>
              <textarea v-model.trim="builder.subheadline" rows="3"></textarea>
            </label>
            <label class="offer-field">
              <span>Hero Media URLs</span>
              <div class="builder-upload-stack">
                <input ref="heroFileInput" type="file" accept="image/*" hidden @change="handleHeroMediaPicked" />
                <button class="secondary-action compact" type="button" :disabled="heroUploading" @click="heroFileInput?.click()">
                  {{ heroUploading ? "Uploading..." : "Upload hero image" }}
                </button>
                <textarea v-model.trim="builder.hero_media_text" rows="4" placeholder="One image or video URL per line"></textarea>
              </div>
              <small v-if="heroUploadError" class="builder-upload-error">{{ heroUploadError }}</small>
            </label>
            <div class="builder-media-picker">
              <button
                v-for="image in builderProductImages"
                :key="image"
                type="button"
                class="builder-media-thumb"
                :class="{ selected: heroMediaList.includes(image) }"
                @click="toggleHeroMedia(image)"
              >
                <img :src="image" alt="" />
              </button>
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
                <img v-if="builder.avatar_url" :src="builder.avatar_url" class="builder-avatar-preview" alt="" />
                <input ref="avatarFileInput" type="file" accept="image/*" hidden @change="handleAvatarPicked" />
                <button class="secondary-action compact" type="button" :disabled="avatarUploading" @click="avatarFileInput?.click()">
                  {{ avatarUploading ? "Uploading..." : (builder.avatar_url ? "Replace avatar" : "Upload avatar") }}
                </button>
                <button v-if="builder.avatar_url" class="secondary-action compact" type="button" @click="builder.avatar_url = ''">Remove</button>
              </div>
              <small v-if="avatarUploadError" class="builder-upload-error">{{ avatarUploadError }}</small>
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
          </section>

          <section class="builder-section">
            <h3>Trust Badges</h3>
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
          </section>

          <!-- Same rule as the Page Sections toggle: no resolvable policy copy (e.g. service offers) = no control. -->
          <section v-if="previewRefundPolicy" class="builder-section">
            <h3>Refund Policy</h3>
            <label class="builder-toggle">
              <input v-model="builder.refund_policy.enabled" type="checkbox" />
              <span>Show refund policy</span>
            </label>
            <small>Refund policy copy comes from the selected offer.</small>
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
            <div class="composition-subhead">Add content</div>
            <div class="element-add-row">
              <button v-for="entry in ELEMENT_TYPES" :key="entry.type" class="secondary-action compact" type="button" @click="addElement(entry.type)">
                + {{ entry.label }}
              </button>
            </div>
            <p v-if="!builder.elements.length" class="element-empty">
              Add testimonials, ratings, content, client logos, or FAQs — drag to reorder.
            </p>
            <div class="element-list">
              <div
                v-for="(element, index) in builder.elements"
                :key="element.id"
                class="element-card"
                draggable="true"
                @dragstart="onElementDragStart(index)"
                @dragover.prevent
                @drop="onElementDrop(index)"
              >
                <header class="element-card-header">
                  <span class="element-drag" title="Drag to reorder">⠿</span>
                  <strong>{{ elementLabel(element.type) }}</strong>
                  <button class="danger-action compact" type="button" @click="removeElement(element.id)">Remove</button>
                </header>

                <template v-if="element.type === 'content_block'">
                  <input :value="element.title" type="text" placeholder="Title" @input="applyTitleCaseInput((value) => { element.title = value; }, $event)" />
                  <textarea v-model.trim="element.text" rows="2" placeholder="Text"></textarea>
                  <div class="selectable-price-image-controls" :class="{ 'has-image-preview': element.image_url }">
                    <div v-if="element.image_url" class="selectable-price-image-preview">
                      <img :src="element.image_url" alt="Content image preview" />
                    </div>
                    <input :ref="(el) => setElementImageInput(element.id, el)" type="file" accept="image/*" hidden @change="handleElementImagePicked(element, $event)" />
                    <button class="secondary-action compact" type="button" :disabled="Boolean(blurbImageUploading[element.id])" @click.prevent="triggerElementImageUpload(element.id)">
                      {{ blurbImageUploading[element.id] ? "Uploading..." : "Upload Image" }}
                    </button>
                    <input v-model.trim="element.image_url" type="url" placeholder="Optional image URL" />
                  </div>
                  <div v-if="blurbImageErrors[element.id]" class="price-image-error">{{ blurbImageErrors[element.id] }}</div>
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

                <template v-else-if="element.type === 'client_marquee'">
                  <input v-model.trim="element.heading" type="text" placeholder="Section heading (optional)" />
                  <div v-for="(logo, i) in element.logos" :key="i" class="element-subrow">
                    <input v-model.trim="logo.name" type="text" placeholder="Client name (only visible by search engines - recommended for SEO)" />
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

              </div>
            </div>
          </section>

          <!-- Discoverability: the sections that render to <head> / their own artifact rather than to the
               page. Collapsed and out of the way because there is nothing to fill in — the output is DERIVED
               from the offer and the composed sections ("SEO" is a mode the goal flips on, not a form).
               plans/LANDING_PAGE_GOAL_COMPOSITION.md -->
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

          <section class="builder-section">
            <h3>Call to Action</h3>
            <label class="offer-field">
              <span>Button Label</span>
              <input v-model.trim="builder.cta_label" type="text" />
            </label>
            <div class="lead-action-summary">
              <strong>{{ ctaTypeLabel(builderCta.type) }}</strong>
              <span>{{ ctaTypeDescription(builderCta.type) }} This comes from the offer and can't be changed here.</span>
              <code v-if="builderCta.target">{{ builderCta.target }}</code>
            </div>
          </section>

          <section class="builder-section">
            <h3>Analytics</h3>
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
          </section>

          <section class="builder-section">
            <h3>Advanced Color Settings</h3>
            <label class="builder-switch-row">
              <span class="builder-switch" @click.stop>
                <input v-model="builder.advanced_colors" type="checkbox" aria-label="Advanced color settings" />
                <span aria-hidden="true"></span>
              </span>
              <span>Customize individual colors</span>
            </label>
            <div v-if="builder.advanced_colors" class="advanced-colors">
              <div class="advanced-colors-head">
                <small>The preset already looks good — only tweak here if you need to. Empty = use the preset.</small>
                <button class="secondary-action compact" type="button" @click="resetThemeTokens">Reset to preset</button>
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
            <button v-if="builderFormHidden" class="secondary-action compact" type="button" @click="builderFormHidden = false">
              Show Form
            </button>
            <div class="preview-device-controls" aria-label="Preview device">
              <button type="button" :class="{ active: previewDevice === 'desktop' }" @click="previewDevice = 'desktop'">Desktop</button>
              <button type="button" :class="{ active: previewDevice === 'mobile' }" @click="previewDevice = 'mobile'">Mobile</button>
            </div>
          </div>
        </header>
        <!-- The Live Preview IS the published renderer. We POST the draft page document to
             /pages/render, which runs the same runtime/html.py render_page() that publishes the page,
             and show the returned HTML here. One JSON, one renderer, two consumers (this iframe and the
             published artifact) — there is no second implementation left to drift out of sync. -->
        <div v-if="previewError" class="preview-render-error">{{ previewError }}</div>
        <!-- Quality-baseline nudges on the rendered page (heading outline; a11y/CLS later). Never blocks
             publishing — the outline is correct by construction, so this usually stays hidden and only
             appears if something regresses. plans/SEMANTIC_HTML.md -->
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
    </ConfirmDialog>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { offerViewTargets, offerViewTargetsFromExpanded } from "../composables/useConversionContext";
import { isSectionVisible, defaultVisible, recommendedSectionKeys, optionalSectionKeys, governedKeys, elementLabel, elementChannel, addableElements, tokenGroups, previewVar, supportedGoals, goalLabel, packSeeds } from "../composables/pageComposer";
import { apiRequest, getApiBase, getApiEnvironment, getPagesBaseUrl, getPreviewPagesBaseUrl, getTenantId } from "../api/client";
import { formatMoney } from "../stores/products";
import { uploadImage } from "../api/uploads";
import { showIconPicker } from "../icon-picker.js";
import { applyTitleCaseInput, formatHeadline } from "../utils/titleCase.js";
import ConfirmDialog from "./shared/ConfirmDialog.vue";

const pages = ref([]);
const offers = ref([]);
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
const previewDevice = ref("desktop");
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
const builder = reactive(defaultBuilderForm());
const defaultFaviconUrl = "https://images.juniorbay.com/icon/favicon.png";
// The saved document carries no legal URLs and no resolved year: render_legal_footer builds the platform
// /legal/* links from the api_base_url we send with each render, and expands {{current_year}} itself.
const defaultFooterCopyrightTemplate = "© {{current_year}} All rights reserved.";

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
const landingPagePriceContexts = new Set(["standard", "sale", "flash_sale", "flash sale"]);
const productsById = computed(() => new Map(products.value.map((product) => [productId(product), product])));
const servicesById = computed(() => new Map(services.value.map((service) => [service.service_id, service])));
const selectedOffer = computed(() => offers.value.find((offer) => offer.offer_id === form.offer_id) || null);
const selectedOfferProducts = computed(() => offerProducts(selectedOffer.value));
const selectedOfferIntent = computed(() => selectedOffer.value?.product_intent || selectedOfferProducts.value[0]?.product_intent || "transaction");
const selectedLeadAction = computed(() => selectedOfferProducts.value.find((product) => product.lead_capture)?.lead_capture || null);
const builderOffer = computed(() => offers.value.find((offer) => offer.offer_id === builder.offer_id) || null);
const builderOfferProducts = computed(() => offerProducts(builderOffer.value));
const builderIntent = computed(() => builderOffer.value?.product_intent || builderOfferProducts.value[0]?.product_intent || "transaction");
// The offer's snapshotted CTA contract drives the preview's on-page experience (buy/call/email/external/booking).
const builderCta = computed(() => builderOffer.value?.presentation?.cta || { type: builderIntent.value === "lead_gen" ? "email" : "buy" });
const selectedOfferCta = computed(() => selectedOffer.value?.presentation?.cta || { type: selectedOfferIntent.value === "lead_gen" ? "email" : "buy" });
// A listicle offer renders its items as a carousel (each add-to-cart) instead of the pick-one selector.
const isListicleOffer = computed(() => (builderOffer.value?.offer_type || "single") === "listicle");
// --- Page Composer (see plans/PAGE_COMPOSER.md) ---
// Visibility comes from the SHARED rules file (imported by pageComposer.js — the exact file Python reads)
// plus the tenant's overrides. The preview AND the saved section list both call sectionVisible(), and
// Python's compose_page() applies the same rules, so preview and published can't disagree.
const builderOfferType = computed(() => builderOffer.value?.offer_type || "single");
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
function toggleSection(key, enabled) {
  // Only persist a deviation from the offer_type default; clearing back to default drops the override.
  if (enabled === defaultVisible(builderOfferType.value, key, builderGoal.value)) {
    delete builder.composition.overrides[key];
  } else {
    builder.composition.overrides[key] = { enabled };
  }
}
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
function resetThemeTokens() {
  builder.theme_tokens = {};
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

// Every builder upload goes through here so a freshly processed image always gets its heal repaint.
async function uploadPageImage(file) {
  const url = await uploadImage(file);
  schedulePreviewImageRefresh();
  return url;
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
        products: builderOfferProducts.value,
        services: offerServices(offer),
        // The page document stores no legal URLs on purpose (legalLinks() returns {}); render_legal_footer
        // builds the platform /legal/* hrefs from api_base_url. Without it the footer links vanish.
        api_base_url: getApiBase(),
      },
    });
    // Ignore a stale response that lands after a newer edit.
    if (seq !== previewRenderSeq) return;
    const html = body?.html || "";
    // Warnings travel with the render, so they describe the same bytes the visitor gets. Capture them
    // before the identical-HTML early return below, or a no-op re-render would leave them stale.
    structuredDataWarnings.value = body?.warnings?.structured_data || [];
    pageHealthWarnings.value = body?.warnings?.page_health || [];
    if (html === previewHtml.value) return;  // nothing changed: don't reload and lose the scroll position
    capturePreviewScroll();
    previewHtml.value = html;
    previewError.value = "";
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
    return JSON.stringify([stable, builderOffer.value, builderOfferProducts.value]);
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
  const offerType = selectedOffer.value?.offer_type || "single";
  const governed = recommendedSectionKeys(offerType, form.goal).map((key) => elementLabel(key));
  return [...governed, ...goalSeedLabels(form.goal)];
});
const filteredPages = computed(() => {
  const term = search.value.toLowerCase();
  if (!term) return pages.value;
  return pages.value.filter((page) => [
    page.name,
    page.page_id,
    page.offer_id,
    page.route?.slug,
    templateLabel(page),
    page.status,
  ].filter(Boolean).join(" ").toLowerCase().includes(term));
});
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
    offer_id: "",
    name: "",
    slug: "",
    template: "universal_bundle",
    preset: "clean-slate",
    // Second composition axis: why the page exists / where its traffic comes from. Presets which capability
    // packs the page starts with (plans/LANDING_PAGE_GOAL_COMPOSITION.md).
    goal: "",
  };
}

function defaultBuilderForm() {
  return {
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
      start_icon: "⏰",
      end_icon: "⏰",
      start_color: "#f97316",
      end_color: "#64748b",
      sticky: true,
      persistent: true,
      transparent: false,
      marquee: false,
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
    brand_overlay: false,
    brand_position: "top-right",
    // Advanced Color Settings (plans/ADVANCED_COLOR_SETTINGS.md): per-token overrides on top of the preset
    // (compact map, keyed by theme token -> hex). Empty = pure preset. Persisted as page.theme.tokens.
    advanced_colors: false,
    theme_tokens: {},
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
    created_at: 0,
    revision: 1,
  };
}

function resetWizard() {
  Object.assign(form, defaultWizardForm());
  wizardStep.value = 1;
  wizardError.value = "";
  offerSearch.value = "";
}

// Load on first search-box focus so filtering works without clicking Load Pages first (mirrors Products).
function ensurePagesLoaded() {
  if (!pagesLoaded.value && !loading.value) loadPages();
}

async function loadPages() {
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    const catalogPromise = ensureCatalogLoaded().catch((err) => {
      message.value = err.message || "Catalog context could not be loaded. Landing pages will show without offer details.";
    });
    const pagesPromise = apiRequest("/pages");
    const body = await pagesPromise;
    pages.value = Array.isArray(body.pages) ? body.pages : [];
    pagesLoaded.value = true;
    const activeCount = pages.value.filter((page) => page.status !== "archived").length;
    if (activeCount) message.value = `${activeCount} landing page${activeCount === 1 ? "" : "s"} loaded.`;
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
  wizardOpen.value = true;
  try {
    await ensureCatalogLoaded();
  } catch (err) {
    wizardError.value = err.message || "Failed to load offers.";
  }
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
  if (wizardStep.value === 1 && !selectedOffer.value) {
    wizardError.value = "Choose an offer before continuing.";
    return;
  }
  if (wizardStep.value === 2 && !form.goal) {
    wizardError.value = "Choose a goal before continuing.";
    return;
  }
  wizardStep.value += 1;
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
  builderExistingPageId.value = "";
  builderOriginalPage.value = null;
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
    message.value = `${saved.name} was saved.`;
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
    page_id: page.page_id || localId("page"),
    thank_you_page_id: page.post_checkout?.thank_you_page?.page_id || localId("page"),
    offer_id: page.offer_id || "",
    offerName: offer?.name || "",
    name: page.name || "",
    slug: page.route?.slug || slugify(page.name || page.page_id),
    template: page.theme?.template || "universal_bundle",
    preset: page.theme?.preset || "clean-slate",
    // Absent on pages created before the goal axis — "" keeps them composing from the base alone.
    goal: page.goal || "",
    favicon_url: page.seo?.favicon_url || "",
    seo_title: page.seo?.title || page.name || "",
    seo_description: page.seo?.description || "",
    seo_image: page.seo?.image || pageImage(page),
    headline: hero.headline || sectionText(sections, "headline") || page.name || "",
    subheadline: hero.subheadline || sectionText(sections, "subheadline") || "",
    hero_media_text: (heroMedia.images || [page.seo?.image || pageImage(page)].filter(Boolean)).join("\n"),
    autoplay: Boolean(heroMedia.autoplay),
    avatar_url: heroMedia.avatar_url || "",
    brand_overlay: Boolean(heroMedia.brand_overlay),
    brand_position: heroMedia.brand_position || "top-right",
    cta_label: cta.label || (offerIntentLabel(offer) === "Lead generation" ? "Continue" : "Buy Now"),
    elements: elementsFromPage(sections),
    google_tag_id: page.analytics?.google_tag_id || "",
    pixel_id: page.analytics?.pixel_id || "",
    status: page.status || "draft",
    published_at: page.published_at || null,
    created_at: page.created_at || 0,
    revision: page.revision || 1,
  });
  // Restore the Page Composer overrides so section toggles reflect the tenant's prior choices.
  builder.composition.overrides = { ...(page.composition?.overrides || {}) };
  // Restore Advanced Color Settings overrides; auto-open the panel if any were set.
  builder.theme_tokens = { ...(page.theme?.tokens || {}) };
  builder.advanced_colors = Object.keys(builder.theme_tokens).length > 0;
  Object.assign(builder.countdown, defaultBuilderForm().countdown, {
    enabled: Boolean(countdown.id),
    duration_minutes: countdown.duration_minutes || 15,
    start_text: countdown.start_text || countdown.label || "Offer expires in",
    end_text: countdown.end_text || "Offer expired",
    start_enabled: countdown.start_enabled !== false,
    end_enabled: countdown.end_enabled !== false,
    start_icon: countdown.start_icon || "⏰",
    end_icon: countdown.end_icon || "⏰",
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
    route: {
      slug: slugify(builder.slug || offer?.slug || builder.name || builder.page_id),
    },
    seo: {
      title: builder.seo_title || offerHeadline(builderOffer.value) || builder.name,
      description: builder.seo_description,
      image: builder.seo_image || previewHeroImage.value,
      favicon_url: builder.favicon_url,
    },
    offer_id: builder.offer_id,
    goal: builder.goal || undefined,
    theme: {
      template: "universal_bundle",
      preset: builder.preset,
      // Advanced Color Settings overrides (the server merges theme.tokens over the preset).
      ...(Object.keys(builder.theme_tokens || {}).length ? { tokens: { ...builder.theme_tokens } } : {}),
    },
    post_checkout: intent === "transaction" ? {
      thank_you_page: {
        page_id: builder.thank_you_page_id,
      },
    } : undefined,
    analytics: {
      google_tag_id: builder.google_tag_id,
      pixel_id: builder.pixel_id,
    },
    legal: legalLinks(),
    // Page Composer intent: the tenant's section overrides. Python re-applies the same shared rules on top.
    composition: { overrides: { ...builder.composition.overrides } },
    sections: builderSections(intent),
    revision: builder.revision || 1,
    created_at: createdAt,
    updated_at: now,
  });
}

function builderSections(intent) {
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
      start_icon: builder.countdown.start_icon || "⏰",
      end_icon: builder.countdown.end_icon || "⏰",
      start_color: builder.countdown.start_color || "#f97316",
      end_color: builder.countdown.end_color || "#64748b",
      sticky: Boolean(builder.countdown.sticky),
      persistent: Boolean(builder.countdown.persistent),
      transparent: Boolean(builder.countdown.transparent),
      marquee: Boolean(builder.countdown.marquee),
    });
  }
  const brandText = formatHeadline(builderOffer.value?.name || "Junior Bay");
  // The brand overlay (on the hero) replaces the separate above-hero brand label so the brand shows once.
  if (sectionVisible("brand_label") && !builder.brand_overlay) {
    sections.push({
      id: "brand",
      type: "brand_label",
      enabled: true,
      label: brandText,
    });
  }
  // The hero-media carousel — for a listicle it's the product images (auto-filled into the field), driving
  // the price card. Carries the socialite overlays (avatar + brand chip) that render inside it.
  sections.push({
    id: "hero-media",
    type: "hero_media",
    images: heroMediaList.value,
    autoplay: Boolean(builder.autoplay),
    avatar_url: builder.avatar_url || "",
    brand_overlay: Boolean(builder.brand_overlay),
    brand_position: builder.brand_position || "top-right",
    brand_text: builder.brand_overlay ? brandText : "",
  });
  sections.push({
    id: "hero",
    type: "hero",
    headline: formatHeadline(builder.headline || builder.name || "Landing Page"),
    subheadline: builder.subheadline || "Continue when you are ready.",
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
  // Derived head section: carries no tenant fields — render_structured_data generates the JSON-LD from the
  // offer and the sections the composer put on the page. It exists in sections[] only because compose_page
  // filters rather than adds, so the section has to be present for the composer to keep it. The goal turns
  // it on via the discoverability pack (plans/LANDING_PAGE_GOAL_COMPOSITION.md).
  if (sectionVisible("structured_data")) {
    sections.push({ id: "structured-data", type: "structured_data" });
  }
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

async function saveBuilderPageWithStatus(statusOverride = "") {
  error.value = "";
  message.value = "";
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
    message.value = statusOverride === "published" ? `${saved.name} was published.` : `${saved.name} was saved.`;
    builderExistingPageId.value = saved.page_id;
    builder.status = saved.status || builder.status;
    builder.published_at = saved.published_at || builder.published_at;
    builderOriginalPage.value = { ...saved };
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
      type: "brand_label",
      enabled: true,
      label: formatHeadline("Junior Bay"),
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

function newElement(type) {
  const base = { id: localId("el"), type };
  // Sensible default headings so the tenant isn't guessing — they can always reword them.
  if (type === "content_block") return { ...base, title: "", text: "", image_url: "" };
  if (type === "testimonials") return { ...base, heading: "What Our Clients Say", items: [{ quote: "", author: "", role: "", avatar_url: "" }] };
  if (type === "rating") return { ...base, value: 5, count: 0, label: "" };
  if (type === "client_marquee") return { ...base, heading: "Our Clients", logos: [{ image_url: "", name: "" }] };
  if (type === "faq") return { ...base, heading: "Frequently Asked Questions", items: [{ question: "", answer: "" }] };
  // product_details is fully offer-driven (current target's gallery/badges/description) — no config.
  return base;
}

function addElement(type) {
  if (builder.elements.length >= 20) return;
  builder.elements.push(newElement(type));
}

function removeElement(id) {
  const index = builder.elements.findIndex((element) => element.id === id);
  if (index >= 0) builder.elements.splice(index, 1);
  delete blurbImageUploading[id];
  delete blurbImageErrors[id];
  delete blurbImageInputs.value[id];
}

function addSubItem(element, key, item) {
  (element[key] = element[key] || []).push(item);
}

function removeSubItem(element, key, index) {
  element[key].splice(index, 1);
}

const elementDragIndex = ref(-1);
function onElementDragStart(index) {
  elementDragIndex.value = index;
}
function onElementDrop(index) {
  const from = elementDragIndex.value;
  elementDragIndex.value = -1;
  if (from < 0 || from === index) return;
  const [moved] = builder.elements.splice(from, 1);
  builder.elements.splice(index, 0, moved);
}

function setElementImageInput(id, el) {
  if (el) blurbImageInputs.value[id] = el;
  else delete blurbImageInputs.value[id];
}
function triggerElementImageUpload(id) {
  blurbImageInputs.value[id]?.click();
}
async function handleElementImagePicked(element, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  blurbImageErrors[element.id] = "";
  blurbImageUploading[element.id] = true;
  try {
    element.image_url = await uploadPageImage(file);
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
function elementSection(element) {
  if (element.type === "content_block") {
    if (!element.title && !element.text && !element.image_url) return null;
    return { id: element.id, type: "content_block", blocks: [{ title: formatHeadline(element.title || ""), text: element.text || "", image_url: element.image_url || undefined }] };
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
    const logos = (element.logos || []).filter((logo) => (logo.image_url || "").trim());
    if (!logos.length) return null;
    return { id: element.id, type: "client_marquee", heading: element.heading || undefined,
      logos: logos.map((logo) => ({ image_url: logo.image_url, name: logo.name || undefined })) };
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
  return null;
}

// Rebuild the editable element list from an existing page's sections (round-trip on edit).
function elementsFromPage(sections) {
  const elements = [];
  for (const section of sections || []) {
    if (section.type === "content_block") {
      for (const block of section.blocks || []) {
        elements.push({ id: localId("el"), type: "content_block", title: block.title || "", text: block.text || "", image_url: block.image_url || "" });
      }
    } else if (section.type === "testimonials") {
      elements.push({ id: localId("el"), type: "testimonials", heading: section.heading || "",
        items: (section.items || []).map((item) => ({ quote: item.quote || "", author: item.author || "", role: item.role || "", avatar_url: item.avatar_url || "" })) });
    } else if (section.type === "rating") {
      elements.push({ id: localId("el"), type: "rating", value: section.value ?? 5, count: section.count ?? 0, label: section.label || "" });
    } else if (section.type === "client_marquee") {
      elements.push({ id: localId("el"), type: "client_marquee", heading: section.heading || "",
        logos: (section.logos || []).map((logo) => ({ image_url: logo.image_url || "", name: logo.name || "" })) });
    } else if (section.type === "faq") {
      elements.push({ id: localId("el"), type: "faq", heading: section.heading || "Frequently Asked Questions", items: (section.items || []).map((item) => ({ question: item.question || "", answer: item.answer || "" })) });
    } else if (section.type === "product_details") {
      elements.push({ id: localId("el"), type: "product_details" });
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
  builder.headline = formatHeadline(offerHeadline(offer) || builder.headline || builder.name);
  builder.subheadline = offerDescription(offer) || builder.subheadline || "Choose your option and continue.";
  if (!builder.seo_title) builder.seo_title = offerHeadline(offer) || builder.name;
  if (!builder.seo_description) builder.seo_description = offerDescription(offer) || offer.name || "";
  if (!builder.seo_image) builder.seo_image = offerImage(offer);
  // A listicle's hero carousel IS the product images — auto-fill the hero media field with one per item.
  if ((offer.offer_type || "single") === "listicle") {
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

function editPage(page) {
  openMenuId.value = "";
  populateBuilderFromPage(page);
  builderExistingPageId.value = page.page_id;
  builderOriginalPage.value = { ...page };
  builderOpen.value = true;
  builderFormHidden.value = false;
}

function requestArchivePage(page) {
  openMenuId.value = "";
  pendingArchivePage.value = page;
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
    message.value = `${saved.name || "Landing page"} was published.`;
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

function offerProducts(offer) {
  const items = Array.isArray(offer?.items) ? offer.items : [];
  return items.map((item) => productsById.value.get(item.product_id)).filter(Boolean);
}

function offerIntentLabel(offer) {
  const intent = offer?.product_intent || offerProducts(offer)[0]?.product_intent || "transaction";
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

function artifactPageUrl(page) {
  const pageId = pagePathId(page).split("/").map(encodeURIComponent).join("/");
  return `${getPagesBaseUrl()}/${pageId}/index.html`;
}

function previewArtifactPageUrl(page) {
  const tenantId = encodeURIComponent(page.tenant_id || getTenantId());
  const pageId = pagePathId(page).split("/").map(encodeURIComponent).join("/");
  return `${getPreviewPagesBaseUrl()}/preview/${tenantId}/${pageId}/index.html`;
}

function pageUrl(page) {
  return page.status === "published" ? artifactPageUrl(page) : previewArtifactPageUrl(page);
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

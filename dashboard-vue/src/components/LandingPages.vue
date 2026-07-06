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
            <p>Step {{ wizardStep }} of 3</p>
          </div>
          <button type="button" class="modal-close" aria-label="Close landing page wizard" @click="closeWizard">×</button>
        </header>

        <div class="wizard-progress" aria-hidden="true">
          <span v-for="step in 3" :key="step" :class="{ active: step <= wizardStep }"></span>
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
              </button>
            </div>
          </section>

          <section v-else-if="wizardStep === 2" class="wizard-step">
            <header class="wizard-step-header">
              <h3>{{ selectedOfferIntent === "lead_gen" ? "Choose Lead Flow" : "Configure Checkout Page" }}</h3>
              <p>{{ selectedOfferIntent === "lead_gen" ? "Lead-gen offers create a landing page with a CTA action." : "Transaction offers create a checkout landing page with Stripe pricing sections." }}</p>
            </header>

            <div v-if="selectedOffer" class="wizard-selected-summary">
              <strong>{{ selectedOffer.name }}</strong>
              <span class="page-source-badge">{{ offerIntentLabel(selectedOffer) }}</span>
            </div>

            <div v-if="selectedOfferIntent === 'lead_gen'" class="experience-options">
              <button
                v-for="option in leadExperienceOptions"
                :key="option.value"
                type="button"
                class="experience-option"
                :class="{ selected: form.experience_type === option.value }"
                @click="form.experience_type = option.value"
              >
                <strong>{{ option.label }}</strong>
                <span>{{ option.description }}</span>
              </button>
            </div>

            <div class="offer-two-column">
              <label class="offer-field">
                <span>Template</span>
                <select v-model="form.template">
                  <option v-for="option in templateOptions" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </label>
              <label class="offer-field">
                <span>Preset</span>
                <select v-model="form.preset" :disabled="!presetOptions.length">
                  <option v-if="!presetOptions.length" value="">None</option>
                  <option v-for="option in presetOptions" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </label>
            </div>

            <label v-if="requiresExternalUrl" class="offer-field">
              <span>CTA Destination URL <strong>*</strong></span>
              <input v-model.trim="form.external_url" type="url" placeholder="https://example.com/offer" required />
            </label>

            <div v-if="selectedLeadAction" class="lead-action-summary">
              <strong>{{ selectedLeadAction.title }}</strong>
              <span>{{ selectedLeadAction.description }}</span>
              <code v-if="selectedLeadAction.target?.value">{{ selectedLeadAction.target.value }}</code>
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
              <div><span>Template</span><strong>{{ selectedTemplateLabel }}</strong></div>
              <div><span>Preset</span><strong>{{ selectedPresetLabel }}</strong></div>
              <div><span>Page ID</span><strong>{{ form.page_id }}</strong></div>
              <div><span>Published path</span><strong>/{{ form.page_id }}/index.html</strong></div>
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
          <button v-if="wizardStep < 3" class="primary-action" type="button" @click="nextWizardStep">Next</button>
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
                <span>Template Type</span>
                <select v-model="builder.template">
                  <option value="universal_bundle">Universal Bundle</option>
                  <option value="simple">Simple</option>
                </select>
              </label>
              <label class="offer-field">
                <span>Preset</span>
                <select v-model="builder.preset" :disabled="builder.template !== 'universal_bundle'">
                  <option v-if="builder.template !== 'universal_bundle'" value="">None</option>
                  <option v-for="option in universalBundlePresets" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
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
              <input v-model.trim="builder.seo_title" type="text" />
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
              <input :value="builder.headline" type="text" @input="updateHeadlineInput((value) => { builder.headline = value; }, $event)" />
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

          <section class="builder-section">
            <h3>Refund Policy</h3>
            <label class="builder-toggle">
              <input v-model="builder.refund_policy.enabled" type="checkbox" />
              <span>Show refund policy</span>
            </label>
            <small>Refund policy copy comes from the selected offer.</small>
          </section>

          <section class="builder-section">
            <header class="builder-section-title">
              <h3>Content Blurbs</h3>
              <button class="secondary-action compact" type="button" @click="addBlurb">+ Add Blurb</button>
            </header>
            <div class="builder-repeat-list">
              <div v-for="(block, index) in builder.blurbs" :key="`blurb-${index}`" class="builder-repeat-row">
                <input :value="block.title" type="text" placeholder="Title" @input="updateHeadlineInput((value) => { block.title = value; }, $event)" />
                <textarea v-model.trim="block.text" rows="2" placeholder="Text"></textarea>
                <div class="selectable-price-image-controls" :class="{ 'has-image-preview': block.image_url }">
                  <div v-if="block.image_url" class="selectable-price-image-preview">
                    <img :src="block.image_url" :alt="`${block.title || 'Blurb'} image preview`" />
                  </div>
                  <input
                    :ref="(el) => setBlurbImageInput(index, el)"
                    type="file"
                    accept="image/*"
                    hidden
                    @change="handleBlurbImagePicked(index, $event)"
                  />
                  <button
                    class="secondary-action compact"
                    type="button"
                    :disabled="Boolean(blurbImageUploading[index])"
                    @click.prevent="triggerBlurbImageUpload(index)"
                  >
                    {{ blurbImageUploading[index] ? "Uploading..." : "Upload Image" }}
                  </button>
                  <input v-model.trim="block.image_url" type="url" placeholder="Optional image URL" />
                </div>
                <div v-if="blurbImageErrors[index]" class="price-image-error">{{ blurbImageErrors[index] }}</div>
                <button class="danger-action compact" type="button" @click="removeBlurb(index)">Remove</button>
              </div>
            </div>
          </section>

          <section class="builder-section">
            <h3>{{ builderIntent === "lead_gen" ? "Lead Action" : "Checkout CTA" }}</h3>
            <label class="offer-field">
              <span>Button Label</span>
              <input v-model.trim="builder.cta_label" type="text" />
            </label>
            <label v-if="builderIntent === 'lead_gen'" class="offer-field">
              <span>Action URL</span>
              <input v-model.trim="builder.action_url" type="url" placeholder="https://example.com/affiliate-link" />
            </label>
          </section>

          <section class="builder-section">
            <header class="builder-section-title">
              <h3>FAQ</h3>
              <button class="secondary-action compact" type="button" @click="addFaq">+ Add FAQ</button>
            </header>
            <div class="builder-repeat-list">
              <div v-for="(item, index) in builder.faq" :key="`faq-${index}`" class="builder-repeat-row">
                <input :value="item.question" type="text" placeholder="Question" @input="updateHeadlineInput((value) => { item.question = value; }, $event)" />
                <textarea v-model.trim="item.answer" rows="2" placeholder="Answer"></textarea>
                <button class="danger-action compact" type="button" @click="removeFaq(index)">Remove</button>
              </div>
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
        <div class="landing-live-preview" :class="[builder.template, builder.preset, previewDevice]">
          <div
            v-if="builder.countdown.enabled && builder.countdown.start_enabled"
            class="preview-countdown"
            :class="{ transparent: builder.countdown.transparent, marquee: builder.countdown.marquee }"
            :style="{ '--preview-countdown-bg': builder.countdown.start_color || 'var(--preview-accent)' }"
          >
            <span>{{ builder.countdown.start_icon }} {{ builder.countdown.start_text || "Offer expires in" }}</span>
            <strong>{{ Number(builder.countdown.duration_minutes || 15) }}:00</strong>
          </div>
          <div class="preview-brand">
            <span class="preview-brand-dot" aria-hidden="true"></span>
            <span>{{ builderOffer?.name || builder.name || "Junior Bay" }}</span>
          </div>
          <img v-if="previewHeroImage" class="preview-hero-image" :src="previewHeroImage" alt="" />
          <h1 v-html="headlineHtml(builder.headline || builder.name)"></h1>
          <p>{{ builder.subheadline }}</p>
          <div v-if="visibleTrustBadges.length" class="preview-badges">
            <span v-for="badge in visibleTrustBadges" :key="badge.label">{{ badge.emoji }} {{ badge.label }}</span>
          </div>
          <div v-if="builderIntent === 'transaction'" class="preview-prices">
            <button
              v-for="price in previewPrices"
              :key="price.price_id"
              type="button"
              :class="{ selected: isPreviewPriceSelected(price), 'has-image': price.image_url }"
              @click="selectPreviewPrice(price.price_id)"
            >
              <img v-if="price.image_url" class="preview-price-image" :src="price.image_url" alt="" />
              <span class="preview-price-copy">
                <span v-if="price.badge" class="preview-price-badge">{{ price.badge }}</span>
                <strong class="preview-price-title">{{ price.label }}</strong>
                <span v-if="price.description" class="preview-price-description">{{ price.description }}</span>
                <span class="preview-price-row">
                  <span class="preview-price-amount">{{ formatMoney(price.unit_amount || 0, price.currency) }}</span>
                  <del v-if="price.compare_at_unit_amount" class="preview-price-regular">
                    {{ formatMoney(price.compare_at_unit_amount, price.currency) }}
                  </del>
                  <span v-if="price.savings_pct" class="preview-price-savings">Save {{ price.savings_pct }}%</span>
                </span>
              </span>
              <span class="preview-price-radio" aria-hidden="true"></span>
            </button>
          </div>
          <div v-else class="preview-lead-card">
            <strong>{{ builderLeadAction?.title || "Next step" }}</strong>
            <span>{{ builderLeadAction?.description || "Continue when you are ready." }}</span>
          </div>
          <div v-if="builder.blurbs.length" class="preview-blurbs">
            <article v-for="block in visibleBlurbs" :key="block.title">
              <span class="preview-blurb-copy">
                <strong v-html="headlineHtml(block.title)"></strong>
                <p>{{ block.text }}</p>
              </span>
              <img v-if="block.image_url" :src="block.image_url" alt="" />
            </article>
          </div>
          <div v-if="visibleFaqs.length" class="preview-faqs">
            <h2>FAQ</h2>
            <details v-for="item in visibleFaqs" :key="item.question" open>
              <summary v-html="headlineHtml(item.question)"></summary>
              <p>{{ item.answer }}</p>
            </details>
          </div>
          <details v-if="builder.refund_policy.enabled && previewRefundPolicy" class="preview-refund-policy">
            <summary>{{ previewRefundPolicy.short_label || "Refund policy" }}</summary>
            <div>
              <h2>Refund Policy</h2>
              <p v-if="previewRefundAppliesTo">Applies to: {{ previewRefundAppliesTo }}</p>
              <p v-if="previewRefundPolicy.full_policy">{{ previewRefundPolicy.full_policy }}</p>
              <p v-if="previewRefundReturnNote">{{ previewRefundReturnNote }}</p>
            </div>
          </details>
          <div class="preview-legal">
            <a :href="defaultLegalLinks.terms_url" target="_blank" rel="noopener">Terms of Service</a>
            <a :href="defaultLegalLinks.privacy_url" target="_blank" rel="noopener">Privacy Policy</a>
            <a :href="defaultLegalLinks.refund_url" target="_blank" rel="noopener">Refund Policy</a>
            <span>{{ defaultFooterCopyright }}</span>
          </div>
          <button type="button" class="preview-cta">
            {{ previewCtaLabel }}
          </button>
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

    <div v-if="pendingArchivePage" class="modal-backdrop" @click.self="pendingArchivePage = null">
      <section class="modal-card confirm-card" role="dialog" aria-modal="true" aria-labelledby="confirmPageArchiveTitle">
        <header class="confirm-icon danger">×</header>
        <h2 id="confirmPageArchiveTitle">{{ pendingArchivePage.status === "published" ? "Archive page?" : "Delete page?" }}</h2>
        <p>
          {{ pendingArchivePage.status === "published" ? "Archive" : "Delete" }}
          "{{ pendingArchivePage.name || "this landing page" }}"?
        </p>
        <div class="confirm-actions">
          <button type="button" class="secondary-action" @click="pendingArchivePage = null">Cancel</button>
          <button type="button" class="primary-action" :disabled="saving" @click="removePage">
            {{ pendingArchivePage.status === "published" ? "Archive" : "Delete" }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { apiRequest, getApiBase, getApiEnvironment, getPagesBaseUrl, getPreviewPagesBaseUrl, getTenantId } from "../api/client";
import { formatMoney } from "../stores/products";
import { showIconPicker } from "../icon-picker.js";

const pages = ref([]);
const offers = ref([]);
const products = ref([]);
const search = ref("");
const offerSearch = ref("");
const loading = ref(false);
const offersLoading = ref(false);
const productsLoading = ref(false);
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
const selectedPreviewPriceId = ref("");
const faviconFileInput = ref(null);
const heroFileInput = ref(null);
const blurbImageInputs = ref({});
const faviconUploading = ref(false);
const heroUploading = ref(false);
const blurbImageUploading = reactive({});
const faviconUploadError = ref("");
const heroUploadError = ref("");
const blurbImageErrors = reactive({});
const form = reactive(defaultWizardForm());
const builder = reactive(defaultBuilderForm());
const defaultFaviconUrl = "https://images.juniorbay.com/icon/favicon.png";
function legalPageUrl(pageId) {
  return `${getApiBase().replace(/\/$/, "")}/legal/${pageId}`;
}
// Preview links to the platform legal pages. Published pages resolve the same URLs at
// publish time from the API base, so the saved document stays environment-agnostic.
const defaultLegalLinks = computed(() => ({
  terms_url: legalPageUrl("terms"),
  privacy_url: legalPageUrl("privacy"),
  refund_url: legalPageUrl("refund"),
}));
const currentYear = new Date().getFullYear();
const defaultFooterCopyright = `© ${currentYear} All rights reserved.`;
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
];
const landingPagePriceContexts = new Set(["standard", "sale", "flash_sale", "flash sale"]);
const headlineLowercaseWords = new Set([
  "a",
  "an",
  "the",
  "and",
  "but",
  "or",
  "nor",
  "for",
  "yet",
  "so",
  "as",
  "at",
  "by",
  "in",
  "of",
  "off",
  "on",
  "per",
  "to",
  "up",
  "via",
  "if",
  "vs",
  "vs.",
]);

const productsById = computed(() => new Map(products.value.map((product) => [productId(product), product])));
const selectedOffer = computed(() => offers.value.find((offer) => offer.offer_id === form.offer_id) || null);
const selectedOfferProducts = computed(() => offerProducts(selectedOffer.value));
const selectedOfferIntent = computed(() => selectedOffer.value?.product_intent || selectedOfferProducts.value[0]?.product_intent || "transaction");
const selectedLeadAction = computed(() => selectedOfferProducts.value.find((product) => product.lead_capture)?.lead_capture || null);
const builderOffer = computed(() => offers.value.find((offer) => offer.offer_id === builder.offer_id) || null);
const builderOfferProducts = computed(() => offerProducts(builderOffer.value));
const builderIntent = computed(() => builderOffer.value?.product_intent || builderOfferProducts.value[0]?.product_intent || "transaction");
const builderLeadAction = computed(() => builderOfferProducts.value.find((product) => product.lead_capture)?.lead_capture || null);
const builderProductImages = computed(() => [...new Set(builderOfferProducts.value.flatMap((product) => product.images || []).filter(Boolean))]);
const heroMediaList = computed(() => parseLines(builder.hero_media_text));
const previewHeroImage = computed(() => heroMediaList.value[0] || offerImage(builderOffer.value) || "");
const visibleTrustBadges = computed(() => builder.trust_badges.badges.filter((badge) => badge.enabled !== false && badge.label));
const visibleBlurbs = computed(() => builder.blurbs.filter((block) => block.title || block.text || block.image_url));
const visibleFaqs = computed(() => builder.faq.filter((item) => item.question && item.answer));
const previewRefundPolicy = computed(() => builderOffer.value?.refund_policy || builderOfferProducts.value[0]?.refund_policy || null);
const previewRefundAppliesTo = computed(() => previewPrices.value.map((price) => price.label).filter(Boolean).join(", "));
const previewRefundReturnNote = computed(() => refundPolicyReturnNote(previewRefundPolicy.value));
const previewPrices = computed(() => {
  const prices = [];
  let displayIndex = 0;
  for (const item of builderOffer.value?.items || []) {
    const product = productsById.value.get(item.product_id);
    if (!product) continue;
    for (const option of item.selectable_prices || []) {
      const price = (product.prices || []).find((candidate) => candidate.price_id === option.price_id) || {};
      if (!isLandingPagePrice(price)) continue;
      const unitAmount = Number(price.unit_amount || 0);
      const compareAt = Number(price.compare_at_unit_amount || 0);
      const calculatedSavings = compareAt > unitAmount && unitAmount > 0
        ? Math.round(((compareAt - unitAmount) / compareAt) * 100)
        : 0;
      prices.push({
        price_id: option.price_id,
        label: option.label || price.label || product.name || "Option",
        description: option.description || price.description || product.description || "",
        badge: option.badge || "",
        image_url: option.image_url || price.image_url || product.images?.[0] || "",
        unit_amount: unitAmount,
        compare_at_unit_amount: compareAt,
        savings_pct: Number(option.savings_pct || price.savings_pct || calculatedSavings || 0),
        currency: price.currency || "usd",
        quantity: landingPagePriceQuantity(price, option),
        display_index: displayIndex,
      });
      displayIndex += 1;
    }
  }
  return prices.sort(compareLandingPagePrices);
});
const previewDefaultPriceId = computed(() => {
  const defaultPriceId = builderOffer.value?.items?.[0]?.default_price_id || "";
  if (previewPrices.value.some((price) => price.price_id === defaultPriceId)) return defaultPriceId;
  return previewPrices.value[0]?.price_id || "";
});
const selectedPreviewPrice = computed(() => {
  return previewPrices.value.find((price) => price.price_id === selectedPreviewPriceId.value)
    || previewPrices.value.find((price) => price.price_id === previewDefaultPriceId.value)
    || previewPrices.value[0]
    || null;
});
const previewCtaLabel = computed(() => {
  const label = builder.cta_label || (builderIntent.value === "transaction" ? "Buy Now" : "Continue");
  if (builderIntent.value !== "transaction" || !selectedPreviewPrice.value) return label;
  return `${label} - ${formatMoney(selectedPreviewPrice.value.unit_amount || 0, selectedPreviewPrice.value.currency)}`;
});
const requiresExternalUrl = computed(() => selectedOfferIntent.value === "lead_gen" && form.experience_type === "external_redirect");
const emptyStateText = computed(() => {
  if (pages.value.length) return "No landing pages match your search.";
  return pagesLoaded.value ? "No landing pages found. Create a page to get started." : 'Click "Load Pages" to view your landing pages.';
});
const templateOptions = computed(() => {
  if (selectedOfferIntent.value === "lead_gen") return [{ value: "simple", label: "Simple" }];
  return [{ value: "universal_bundle", label: "Universal Bundle" }];
});
const presetOptions = computed(() => form.template === "universal_bundle" ? universalBundlePresets : []);
const selectedTemplateLabel = computed(() => templateOptions.value.find((option) => option.value === form.template)?.label || "Simple");
const selectedPresetLabel = computed(() => presetOptions.value.find((option) => option.value === form.preset)?.label || "None");
const leadExperienceOptions = computed(() => {
  const action = selectedLeadAction.value?.action || "capture_email";
  const options = [
    {
      value: "lead_capture_page",
      label: actionLabel(action),
      description: "Create a simple lead-generation page using this product action.",
    },
    {
      value: "external_redirect",
      label: "External link CTA",
      description: "Create a landing page whose CTA sends visitors to an external URL.",
    },
  ];
  if (["call_number", "external_url", "social_redirect", "open_form"].includes(action)) {
    options.unshift({
      value: "direct_action",
      label: directActionLabel(action),
      description: "Create a landing page using the product's configured CTA target.",
    });
  }
  return options;
});
const filteredPages = computed(() => {
  const term = search.value.toLowerCase();
  if (!term) return pages.value;
  return pages.value.filter((page) => [
    page.name,
    page.page_id,
    page.offer_id,
    page.route?.slug,
    page.theme?.template,
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
const experienceLabel = computed(() => {
  if (selectedOfferIntent.value !== "lead_gen") return "Checkout landing page";
  return leadExperienceOptions.value.find((option) => option.value === form.experience_type)?.label || "Lead generation page";
});
const draftPage = computed(() => buildPageDocument());
const builderPageDocument = computed(() => buildBuilderPageDocument());
const isBuilderPublished = computed(() => builder.status === "published");

watch(previewPrices, (prices) => {
  if (!prices.length) {
    selectedPreviewPriceId.value = "";
    return;
  }
  if (!prices.some((price) => price.price_id === selectedPreviewPriceId.value)) {
    selectedPreviewPriceId.value = previewDefaultPriceId.value || prices[0].price_id;
  }
}, { immediate: true });

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
    experience_type: "checkout_page",
    external_url: "",
    template: "universal_bundle",
    preset: "clean-slate",
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
    favicon_url: "",
    seo_title: "",
    seo_description: "",
    seo_image: "",
    headline: "",
    subheadline: "",
    hero_media_text: "",
    cta_label: "Buy Now",
    action_url: "",
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
    blurbs: [],
    faq: [],
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
  await Promise.all([ensureProductsLoaded(), ensureOffersLoaded()]);
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

function updateHeadlineInput(assign, event) {
  const input = event.target;
  const original = input.value;
  const formatted = formatHeadline(original);
  const cursorFromEnd = original.length - input.selectionStart;
  assign(formatted);
  if (formatted !== original) {
    input.value = formatted;
    const nextPosition = Math.max(0, formatted.length - cursorFromEnd);
    requestAnimationFrame(() => input.setSelectionRange(nextPosition, nextPosition));
  }
}

function formatHeadline(text) {
  if (!text || typeof text !== "string") return text || "";
  const parts = text.split(/(\s+)/);
  const wordIndexes = parts.map((part, index) => (part && !/\s+/.test(part) ? index : -1)).filter((index) => index >= 0);
  if (!wordIndexes.length) return text;
  const firstWord = wordIndexes[0];
  const lastWord = wordIndexes[wordIndexes.length - 1];
  return parts.map((part, index) => {
    if (!part || /\s+/.test(part)) return part;
    return formatHeadlineWord(part, index === firstWord, index === lastWord);
  }).join("");
}

function formatHeadlineWord(word, isFirst, isLast) {
  if (word.length >= 2 && word === word.toUpperCase() && /^[A-Z]+$/.test(word)) return word;
  const leading = word.match(/^[^a-zA-Z]*/)?.[0] || "";
  const trailing = word.match(/[^a-zA-Z]*$/)?.[0] || "";
  const endIndex = trailing ? word.length - trailing.length : word.length;
  const core = word.slice(leading.length, endIndex);
  if (!core) return word;
  if (core.length >= 2 && core === core.toUpperCase() && /^[A-Z]+$/.test(core)) return word;
  const lowerCore = core.toLowerCase();
  if (lowerCore === "s" && /[\d']$/.test(leading)) return `${leading}${core}${trailing}`;
  if (!isFirst && !isLast && headlineLowercaseWords.has(lowerCore)) return `${leading}${lowerCore}${trailing}`;
  return `${leading}${capitalizeHeadlineCore(lowerCore)}${trailing}`;
}

function capitalizeHeadlineCore(word) {
  if (!word) return word;
  if (word.includes("-")) return word.split("-").map(capitalizeHeadlineCore).join("-");
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function headlineHtml(text) {
  return processHeadlineMarkup(formatHeadline(text || ""));
}

function processHeadlineMarkup(text) {
  return String(text || "").split(/(\*\*.*?\*\*|\^\^.*?\^\^)/g).map((part) => {
    if (!part) return "";
    if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      return `<span class="preview-mark-text">${escapeHtml(part.slice(2, -2))}</span>`;
    }
    if (part.startsWith("^^") && part.endsWith("^^") && part.length >= 4) {
      return `<span class="preview-mark-bg">${escapeHtml(part.slice(2, -2))}</span>`;
    }
    return escapeHtml(part);
  }).join("");
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function selectOffer(offer) {
  form.offer_id = offer.offer_id;
  const baseName = offer.name || "Landing Page";
  form.name = `${baseName} Landing Page`;
  form.slug = slugify(offer.slug || baseName);
  form.experience_type = offer.product_intent === "lead_gen" ? defaultLeadExperience(offer) : "checkout_page";
  form.external_url = defaultExternalUrl(offer);
  form.template = offer.product_intent === "lead_gen" ? "simple" : "universal_bundle";
  form.preset = form.template === "universal_bundle" ? "clean-slate" : "";
}

function nextWizardStep() {
  wizardError.value = "";
  if (wizardStep.value === 1 && !selectedOffer.value) {
    wizardError.value = "Choose an offer before continuing.";
    return;
  }
  if (wizardStep.value === 2) {
    if (requiresExternalUrl.value && !isHttpUrl(form.external_url)) {
      wizardError.value = "External URL must be a valid HTTP(S) URL.";
      return;
    }
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
  builderExistingPageId.value = "";
  builderOriginalPage.value = null;
  builderOpen.value = true;
  builderFormHidden.value = false;
  wizardOpen.value = false;
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
  const content = sections.find((section) => section.type === "content_block") || {};
  const faq = sections.find((section) => section.type === "faq") || {};
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
    favicon_url: page.seo?.favicon_url || "",
    seo_title: page.seo?.title || page.name || "",
    seo_description: page.seo?.description || "",
    seo_image: page.seo?.image || pageImage(page),
    headline: hero.headline || sectionText(sections, "headline") || page.name || "",
    subheadline: hero.subheadline || sectionText(sections, "subheadline") || "",
    hero_media_text: (heroMedia.images || [page.seo?.image || pageImage(page)].filter(Boolean)).join("\n"),
    cta_label: cta.label || (offerIntentLabel(offer) === "Lead generation" ? "Continue" : "Buy Now"),
    action_url: cta.url || page.post_checkout?.thank_you_page?.url || "",
    blurbs: Array.isArray(content.blocks) ? content.blocks.map((block) => ({ ...block })) : [],
    faq: Array.isArray(faq.items) ? faq.items.map((item) => ({ ...item })) : [],
    google_tag_id: page.analytics?.google_tag_id || "",
    pixel_id: page.analytics?.pixel_id || "",
    status: page.status || "draft",
    published_at: page.published_at || null,
    created_at: page.created_at || 0,
    revision: page.revision || 1,
  });
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
      title: builder.seo_title || builder.name,
      description: builder.seo_description,
      image: builder.seo_image || previewHeroImage.value,
      favicon_url: builder.favicon_url,
    },
    offer_id: builder.offer_id,
    theme: {
      template: builder.template,
      preset: builder.template === "universal_bundle" ? builder.preset : undefined,
      color: builder.template === "simple" ? {
        background: "#ffffff",
        text: "#111827",
        accent: "#4f46b5",
      } : undefined,
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
  sections.push(
    {
      id: "brand",
      type: "brand_label",
      enabled: true,
      label: formatHeadline(builderOffer.value?.name || "Junior Bay"),
    },
    {
      id: "hero-media",
      type: "hero_media",
      images: heroMediaList.value,
    },
    {
      id: "hero",
      type: "hero",
      headline: formatHeadline(builder.headline || builder.name || "Landing Page"),
      subheadline: builder.subheadline || "Continue when you are ready.",
    },
  );
  if (visibleTrustBadges.value.length) {
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
  if (visibleBlurbs.value.length) {
    sections.push({
      id: "content",
      type: "content_block",
      blocks: visibleBlurbs.value.map((block) => ({
        ...block,
        title: formatHeadline(block.title || ""),
      })),
    });
  }
  if (intent === "transaction") {
    sections.push({
      id: "offer-selector",
      type: "offer_price_selector",
      offer_id: builder.offer_id,
    });
  }
  if (builder.faq.some((item) => item.question && item.answer)) {
    sections.push({
      id: "faq",
      type: "faq",
      items: builder.faq
        .filter((item) => item.question && item.answer)
        .map((item) => ({ ...item, question: formatHeadline(item.question || "") })),
    });
  }
  sections.push(
    {
      id: "checkout-cta",
      type: "checkout_cta",
      label: builder.cta_label || (intent === "transaction" ? "Buy Now" : "Continue"),
      url: intent === "lead_gen" ? builder.action_url : undefined,
    },
    {
      id: "refund-policy",
      type: "refund_policy",
      enabled: builder.refund_policy.enabled !== false,
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
  if (builderIntent.value === "lead_gen" && builder.action_url && !isHttpUrl(builder.action_url)) {
    error.value = "Action URL must be a valid HTTP(S) URL.";
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
    theme: {
      template: form.template,
      preset: form.template === "universal_bundle" ? form.preset : undefined,
      color: intent === "lead_gen" ? {
        background: "#ffffff",
        text: "#111827",
        accent: "#4f46b5",
      } : undefined,
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
  if (intent === "transaction") {
    return [
      {
        id: "brand",
        type: "brand_label",
        enabled: true,
        label: formatHeadline("Junior Bay"),
      },
      {
        id: "hero",
        type: "hero",
        headline: formatHeadline(offer.presentation?.headline || offer.name || "Complete your order"),
        subheadline: offer.presentation?.subheadline || "Choose your option and continue to secure checkout.",
      },
      {
        id: "offer-selector",
        type: "offer_price_selector",
        offer_id: offer.offer_id,
      },
      {
        id: "checkout-cta",
        type: "checkout_cta",
        label: offer.presentation?.cta_label || "Continue to Checkout",
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
    ];
  }
  const direct = form.experience_type === "direct_action" || form.experience_type === "external_redirect";
  return [
    {
      id: "hero",
      type: "hero",
      headline: formatHeadline(offerHeadline(offer) || "Get started"),
      subheadline: offerDescription(offer) || leadAction?.description || "Complete the next step to continue.",
    },
    {
      id: "lead-action",
      type: "content_block",
      blocks: [
        {
          title: formatHeadline(direct ? experienceLabel.value : "Lead capture"),
          text: leadActionText(leadAction),
        },
      ],
    },
    {
      id: "lead-cta",
      type: "checkout_cta",
      label: leadCtaLabel(leadAction),
      url: form.experience_type === "external_redirect" ? form.external_url : leadAction?.target?.value,
    },
  ];
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

function compareLandingPagePrices(left, right) {
  if (left.quantity && right.quantity && left.quantity !== right.quantity) {
    return left.quantity - right.quantity;
  }
  if (left.quantity && !right.quantity) return -1;
  if (!left.quantity && right.quantity) return 1;
  return left.display_index - right.display_index;
}

function legalLinks() {
  // Persist no legal URLs on the page document; the renderer injects the platform
  // /legal/* links at publish time so pages stay environment-agnostic.
  return {};
}

function refundPolicyReturnNote(policy) {
  if (!policy) return "";
  if (policy.return_note) return policy.return_note;
  const method = String(policy.return_method || "").toLowerCase();
  if (method.includes("no return") || method.includes("customer keeps") || method.includes("no_return")) {
    return "This item doesn't need to be returned. The customer may keep the item and dispose of it in a responsible way. The seller may still grant a refund.";
  }
  if (method.includes("return_required") || method.includes("return required")) {
    return "The customer must return the item according to the seller's return instructions before the refund is completed.";
  }
  return "";
}

function selectPreviewPrice(priceId) {
  selectedPreviewPriceId.value = priceId;
}

function isPreviewPriceSelected(price) {
  return price.price_id === selectedPreviewPrice.value?.price_id;
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
    builder.favicon_url = await uploadBuilderImage(file);
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
    appendHeroMedia(await uploadBuilderImage(file));
  } catch (err) {
    heroUploadError.value = err.message || "Hero image upload failed.";
  } finally {
    heroUploading.value = false;
  }
}

function setBlurbImageInput(index, el) {
  if (el) blurbImageInputs.value[index] = el;
  else delete blurbImageInputs.value[index];
}

function triggerBlurbImageUpload(index) {
  blurbImageInputs.value[index]?.click();
}

async function handleBlurbImagePicked(index, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || !builder.blurbs[index]) return;
  blurbImageErrors[index] = "";
  blurbImageUploading[index] = true;
  try {
    builder.blurbs[index].image_url = await uploadBuilderImage(file);
  } catch (err) {
    blurbImageErrors[index] = err.message || "Image upload failed.";
  } finally {
    blurbImageUploading[index] = false;
  }
}

async function uploadBuilderImage(file) {
  if (!file.type.startsWith("image/") || file.size > 10 * 1024 * 1024) throw new Error("Use an image file up to 10MB.");
  const presigned = await apiRequest("/upload/multiple", {
    method: "POST",
    body: {
      fileName: file.name,
      contentType: file.type,
      basePrefix: "offers",
      targetBucket: "images.juniorbay.net",
    },
  });
  const formData = new FormData();
  Object.entries(presigned.upload?.fields || {}).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const uploadResponse = await fetch(presigned.upload.url, { method: "POST", body: formData });
  if (!uploadResponse.ok) throw new Error("Failed to upload file.");
  return pollBuilderImageUrl(presigned.id);
}

async function pollBuilderImageUrl(imageId) {
  const deadline = Date.now() + 180000;
  let delay = 1200;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(8000, Math.ceil(delay * 1.35));
    const body = await apiRequest(`/upload/status/${encodeURIComponent(imageId)}`).catch(() => ({}));
    if (body.status === "failed") throw new Error("Image processing failed.");
    for (const url of imageUrlCandidates(body.urls || {})) {
      if (await imageUrlLoads(url)) return url;
    }
  }
  throw new Error("Timed out waiting for processed image.");
}

function imageUrlCandidates(urls) {
  return [...new Set([
    urls.small?.webp,
    urls.small?.jpg,
    urls.medium?.webp,
    urls.medium?.jpg,
    urls.large?.webp,
    urls.large?.jpg,
    urls.original,
  ].filter(Boolean).map(cdnImageUrl))];
}

function cdnImageUrl(url) {
  return String(url || "").replace("images.juniorbay.net", "images.juniorbay.com");
}

function imageUrlLoads(url, timeoutMs = 4000) {
  return new Promise((resolve) => {
    const image = new Image();
    const timeout = window.setTimeout(() => finish(false), timeoutMs);
    function finish(result) {
      window.clearTimeout(timeout);
      image.onload = null;
      image.onerror = null;
      resolve(result);
    }
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = `${url}${url.includes("?") ? "&" : "?"}_probe=${Date.now()}`;
  });
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function addBlurb() {
  if (builder.blurbs.length >= 8) return;
  builder.blurbs.push({ title: "", text: "", image_url: "" });
}

function removeBlurb(index) {
  builder.blurbs.splice(index, 1);
  delete blurbImageUploading[index];
  delete blurbImageErrors[index];
  delete blurbImageInputs.value[index];
}

function addFaq() {
  if (builder.faq.length >= 10) return;
  builder.faq.push({ question: "", answer: "" });
}

function removeFaq(index) {
  builder.faq.splice(index, 1);
}

function onBuilderOfferChange() {
  const offer = builderOffer.value;
  if (!offer) return;
  builder.offerName = offer.name || "";
  if (!builder.name) builder.name = `${offer.name || "Offer"} Landing Page`;
  if (!builder.slug) builder.slug = slugify(offer.slug || offer.name || builder.page_id);
  builder.headline = formatHeadline(offerHeadline(offer) || builder.headline || builder.name);
  builder.subheadline = offerDescription(offer) || builder.subheadline || "Choose your option and continue.";
  if (!builder.seo_title) builder.seo_title = builder.name;
  if (!builder.seo_description) builder.seo_description = offerDescription(offer) || offer.name || "";
  if (!builder.seo_image) builder.seo_image = offerImage(offer);
  if (!builder.hero_media_text && offerImage(offer)) builder.hero_media_text = offerImage(offer);
  builder.cta_label = builderIntent.value === "lead_gen" ? leadCtaLabel(builderLeadAction.value) : "Buy Now";
  builder.action_url = defaultExternalUrl(offer);
  if (builderIntent.value === "lead_gen") {
    builder.template = "simple";
    builder.preset = "";
  } else {
    builder.template = "universal_bundle";
    builder.preset = builder.preset || "clean-slate";
  }
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

function offerImage(offer) {
  const firstProduct = offerProducts(offer)[0];
  return offer?.presentation?.image_url || offer?.presentation?.hero_image_url || firstProduct?.images?.[0] || "";
}

function firstProductDescription(offer) {
  return offerProducts(offer)[0]?.description || "";
}

function offerHeadline(offer) {
  return offer?.presentation?.headline || offer?.name || "";
}

function offerDescription(offer) {
  return offer?.presentation?.subheadline || firstProductDescription(offer) || "";
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

function templateLabel(page) {
  return page.theme?.template || "simple";
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

function defaultLeadExperience(offer) {
  const action = offerProducts(offer).find((product) => product.lead_capture)?.lead_capture?.action;
  if (["call_number", "external_url", "social_redirect", "open_form"].includes(action)) return "direct_action";
  return "lead_capture_page";
}

function defaultExternalUrl(offer) {
  const target = offerProducts(offer).find((product) => product.lead_capture)?.lead_capture?.target;
  return target?.type === "url" ? target.value || "" : "";
}

function actionLabel(action) {
  const labels = {
    capture_email: "Email capture page",
    capture_phone: "Phone capture page",
    capture_email_phone: "Contact capture page",
    call_number: "Call page",
    external_url: "Redirect page",
    open_form: "Form page",
    social_redirect: "Social redirect page",
  };
  return labels[action] || "Lead capture page";
}

function directActionLabel(action) {
  const labels = {
    call_number: "Click-to-call action",
    external_url: "Direct external URL",
    open_form: "Open external form",
    social_redirect: "Social redirect",
  };
  return labels[action] || "Direct action";
}

function leadActionText(action) {
  if (!action) return "The visitor will complete the configured lead action.";
  const target = action.target?.value ? ` Target: ${action.target.value}` : "";
  return `${action.description || "The visitor will complete the configured lead action."}${target}`;
}

function leadCtaLabel(action) {
  const labels = {
    capture_email: "Submit Email",
    capture_phone: "Submit Phone",
    capture_email_phone: "Submit Contact Info",
    call_number: "Call Now",
    external_url: "Continue",
    open_form: "Open Form",
    social_redirect: "Continue",
  };
  return labels[action?.action] || "Continue";
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

function isHttpUrl(value) {
  return /^https?:\/\/[^\s"'<>]+$/.test(String(value || ""));
}
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Shipping</h1>
        <p>Carrier provider, addresses, and parcel defaults for label purchase and rates</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
        <button class="primary-action" type="button" :disabled="saving || loading" @click="save">
          {{ saving ? "Saving..." : "Save Shipping" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error">{{ error }}</div>
    <div v-else-if="message" class="keys-status-banner">{{ message }}</div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>General</h2></header>
      <div class="dashboard-card-body">
        <label class="checkbox-row">
          <input v-model="form.enabled" type="checkbox" />
          <span>Enable shipping (rates and labels)</span>
        </label>
        <label class="checkbox-row">
          <input v-model="form.test_mode" type="checkbox" />
          <span>Test mode (use the provider's test environment)</span>
        </label>
        <label class="checkbox-row">
          <input v-model="form.auto_fulfill_after_label_purchase" type="checkbox" />
          <span>Auto-fulfill orders after a label is purchased</span>
        </label>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Provider</h2></header>
      <div class="dashboard-card-body">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Provider <strong>*</strong></span>
            <select v-model="form.provider.name">
              <option value="">Select a provider…</option>
              <!--
                Only providers whose integration can actually be exercised are listed.

                Shippo and EasyPost put test mode in the API KEY, so a test token buys free labels against
                the production host -- they can be proven end to end without spending anything. ShipStation
                needs a real paid account before its `testLabel` flag can even be sent, and Easyship's
                sandbox story is unknown (the legacy adapter reads test_mode and never applies it to a
                request). Both are restored here when it is their turn to be tested:

                  <option value="easypost">EasyPost</option>
                  <option value="shipstation">ShipStation</option>
                  <option value="easyship">Easyship</option>

                The SCHEMA still accepts all five names, so restoring one is only this edit.
              -->
              <option value="shippo">Shippo</option>
              <option value="mock">Mock (testing)</option>
            </select>
          </label>
          <label class="offer-field">
            <span>Base URL</span>
            <input v-model.trim="form.provider.base_url" type="url" placeholder="Optional provider API base URL" />
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>API Key</span>
            <input v-model="form.provider.api_key" type="password" autocomplete="new-password" :placeholder="apiKeyPlaceholder" />
            <small>Your provider's API key. Stored encrypted and never shown again after saving.</small>
          </label>
          <label class="offer-field">
            <span>Connection Status</span>
            <input :value="statusLabel(rawDoc.provider?.connection_status || 'not_configured')" disabled />
            <small>{{ keyConfigured ? "A key is saved for this provider." : "No key saved yet." }}</small>
          </label>
        </div>
        <p v-if="providerChangedNeedsKey" class="keys-status-banner error">
          You changed providers — enter the new provider's API key. The previous key will not carry over.
        </p>

        <div class="offer-two-column">
          <div>
            <button class="secondary-action" type="button" :disabled="testing || !form.provider.name" @click="testConnection">
              {{ testing ? "Testing…" : "Test connection" }}
            </button>
            <small class="field-hint">Save first — the test uses the key that is stored, not the one typed above.</small>
          </div>
        </div>
        <div v-if="readiness.length" class="keys-status-banner">
          <strong>Before you can buy labels:</strong>
          <ul><li v-for="item in readiness" :key="item">{{ item }}</li></ul>
        </div>
        <p v-else-if="readinessKnown" class="keys-status-banner success">Ready to buy labels.</p>
        <p v-if="connectionResult" class="keys-status-banner" :class="connectionResult.status === 'connected' ? 'success' : 'error'">
          {{ connectionResult.message }}
          <span v-if="connectionResult.carriers?.length">
            Carriers available: {{ connectionResult.carriers.join(", ") }}.
          </span>
        </p>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Rate preference</h2>
        <p>Which rate we pick for you when you buy labels. You can always change it on an individual
          order before buying.</p>
      </header>
      <div class="dashboard-card-body">
        <div class="offer-two-column">
          <label>
            Prefer
            <select v-model="form.rate_options.prefer">
              <option value="cheapest">Cheapest</option>
              <option value="fastest">Fastest</option>
              <option value="best_value">Best value</option>
            </select>
          </label>
          <label>
            Must arrive within <span class="field-optional">optional</span>
            <input v-model.trim="form.rate_options.max_transit_days" type="number" min="1" placeholder="Any" />
            <small class="field-hint">Days. Set this if you promise a delivery speed — otherwise a slow
              service can be the cheapest one.</small>
          </label>
        </div>
        <div class="offer-two-column">
          <label>
            Preferred carrier <span class="field-optional">optional</span>
            <input v-model.trim="form.rate_options.preferred_carrier" type="text" placeholder="e.g. USPS" />
            <small class="field-hint">Used when it costs about the same as the cheapest.</small>
          </label>
          <label>
            Never pick a rate above <span class="field-optional">optional</span>
            <input v-model.trim="form.rate_options.max_auto_amount" type="text" placeholder="e.g. 25.00" />
            <small class="field-hint">We still show the rate — you just choose it yourself. A safety net,
              because buying labels in bulk spends money on every selected order at once.</small>
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Boxes</h2>
        <p>The boxes you pack into. Several items in one order share the smallest box they all fit in;
          with no boxes listed, every item ships in its own parcel, which usually costs more.</p>
      </header>
      <div class="dashboard-card-body">
        <!-- Boxes only help once the ITEMS have sizes of their own: the packer cannot choose a shared box
             for things whose dimensions it does not know. Advisory, never a blocker -- item dimensions are
             optional to create a product and the shipping module must not become compulsory sideways. -->
        <!-- THE WARNING IS THE FIX. `product_readiness` has named these products since 2026-09-24 and the
             count has not moved (2 of 15 dev, 0 of 4 prod measured). Fourteen empty forms was the
             obstacle, not one form -- so they are measurable here, where the gap is reported
             (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0d). -->
        <div v-if="unmeasuredProducts.length" class="keys-status-banner warning">
          <strong>Boxes can only be shared once items are measured.</strong>
          Measure them here — the product itself, out of any packaging.
        </div>
        <div v-for="row in unmeasuredProducts" :key="row.product_id" class="offer-item-editor">
          <header>
            <strong>{{ row.name }}</strong>
            <!-- A SUGGESTION, never a pre-fill: silently copying another product's measurements would
                 manufacture data that reads as measured and is not, which is what P0a exists to stop.
                 Accepting it is one click, and a deliberate one. -->
            <button v-if="row.suggestion" class="link-action" type="button" @click="useSuggestion(row)">
              Same as {{ row.suggestion.from_name }} ({{ row.suggestion.length_in }}×{{ row.suggestion.width_in }}×{{ row.suggestion.height_in }} in, {{ row.suggestion.weight_lb }} lb)
            </button>
          </header>
          <div class="modal-dimensions-grid">
            <label>Length (in)<input v-model.number="measurements[row.product_id].length_in" type="number" min="0" step="0.1" placeholder="—" /></label>
            <label>Width (in)<input v-model.number="measurements[row.product_id].width_in" type="number" min="0" step="0.1" placeholder="—" /></label>
            <label>Height (in)<input v-model.number="measurements[row.product_id].height_in" type="number" min="0" step="0.1" placeholder="—" /></label>
            <label>Weight (lb)<input v-model.number="measurements[row.product_id].weight_lb" type="number" min="0" step="0.1" placeholder="—" /></label>
          </div>
        </div>
        <button v-if="unmeasuredProducts.length" class="secondary-action" type="button"
                :disabled="measuringBusy || !completeMeasurements.length" @click="saveMeasurements">
          {{ measuringBusy ? "Saving…"
             : `Save ${completeMeasurements.length} measurement${completeMeasurements.length === 1 ? "" : "s"}` }}
        </button>
        <!-- All four or none. Three sides still cannot be rated, and a product that looks measured and
             is not is worse than one that is plainly blank. -->
        <p v-if="unmeasuredProducts.length" class="field-hint">
          All four are needed before a product can be rated. Leave a row blank to come back to it.
        </p>
        <p v-if="!form.boxes.length" class="field-hint">
          No boxes yet.
          <button class="link-action" type="button" @click="useStarterBoxes">Start with common sizes</button>
          — then edit them to match what you actually use.
        </p>
        <div v-for="(box, index) in form.boxes" :key="index" class="offer-item-editor">
          <header>
            <div><h4>{{ box.name || "Untitled box" }}</h4></div>
            <button class="secondary-action compact" type="button" @click="removeBox(index)">Remove</button>
          </header>
          <div class="offer-two-column">
            <label class="offer-field">
              <span>Name</span>
              <input v-model.trim="box.name" type="text" placeholder="e.g. Medium box" />
            </label>
            <label class="offer-field">
              <span>Type</span>
              <select v-model="box.kind">
                <option value="box">Box</option>
                <option value="soft_pack">Padded envelope or mailer</option>
              </select>
            </label>
          </div>
          <!-- CARRIER PACKAGING. The one container whose price is destination-independent, because the
               carrier says so — a tenant's own carton never is. Its dimensions belong to the carrier, so
               they are shown and locked rather than typed. -->
          <label v-if="parcelTemplates.length" class="offer-field">
            <span>Carrier packaging</span>
            <select :value="box.template || ''" @change="useParcelTemplate(box, $event.target.value)">
              <option value="">My own box — rated on size, weight and distance</option>
              <option v-for="tpl in parcelTemplates" :key="tpl.template" :value="tpl.template">
                {{ tpl.name }}
              </option>
            </select>
          </label>
          <div class="modal-dimensions-grid">
            <label>Length (in)<input v-model.number="box.length" type="number" min="0" step="0.1"
                                     :disabled="!!box.template" /></label>
            <label>Width (in)<input v-model.number="box.width" type="number" min="0" step="0.1"
                                    :disabled="!!box.template" /></label>
            <label>Height (in)<input v-model.number="box.height" type="number" min="0" step="0.1"
                                    :disabled="!!box.template" /></label>
            <label>Box weight (lb)<input v-model.number="box.empty_weight" type="number" min="0" step="0.01" /></label>
            <label>Max weight (lb)<input v-model.number="box.max_weight" type="number" min="0" step="0.1" placeholder="—" /></label>
          </div>
          <small class="field-hint">
            Inside measurements. Box weight counts — the carrier bills the cardboard too. Max weight is
            optional; leave it blank unless the box has a stated limit.
          </small>
          <!-- Only shown when a zone actually prices this way, so a tenant charging flat or live rates never
               sees a column they do not use. -->
          <div v-if="boxPricingUsed" class="box-prices">
            <span class="box-prices-title">What a buyer pays when their order fits this box</span>
            <div class="offer-three-column">
              <label v-for="code in boxPricingCountries" :key="code" class="offer-field">
                <span>{{ code }}</span>
                <input v-model.trim="box.prices[code]" type="text" inputmode="decimal" placeholder="—" />
              </label>
            </div>
            <small class="field-hint">
              Blank means this box has no price for that country, so an order needing it cannot be
              quoted — leave it blank only if you never ship that size there.
            </small>
            <!-- Typing a price per box is guessing at postage. It is kept for tenants with no carrier
                 connected, but it should never read as the recommended path when live rates exist. -->
            <small v-if="form.provider.name" class="field-hint">
              You have a carrier connected — a zone set to <strong>Live carrier rates</strong> prices
              each order from its real size, weight and destination instead, with nothing to type here.
            </small>
          </div>
          <small v-if="box.kind === 'soft_pack'" class="field-hint">
            Height is how thick it lies flat. An envelope stretches, so products marked
            <strong>“this item squashes”</strong> can go in one thicker than that — up to about three
            times. Anything rigid still has to fit the measurements above.
          </small>
        </div>
        <button class="secondary-action" type="button" @click="addBox">+ Add box</button>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Ship-From Address</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" :disabled="copyingBusiness" @click="copyBusinessAddress">
            {{ copyingBusiness ? "Copying…" : "Copy from business address" }}
          </button>
        </div>
      </header>
      <div class="dashboard-card-body">
        <AddressFields :address="form.ship_from_address" />
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Return Address</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" @click="copyShipFromToReturn">Copy from ship-from</button>
        </div>
      </header>
      <div class="dashboard-card-body">
        <AddressFields :address="form.return_address" />
      </div>
    </section>


    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Services</h2>
        <p>The delivery speeds you offer a buyer. A landing page can show fewer of these, never more — a
          customer cannot ask for overnight if you do not ship overnight.</p>
      </header>
      <div class="dashboard-card-body">
        <p v-if="carrierNote" class="field-hint">{{ carrierNote }}</p>
        <p v-if="!form.enabled_services.length" class="field-hint">
          No services yet.
          <button class="link-action" type="button" @click="useStarterServices">Start with common speeds</button>
        </p>
        <div v-for="(service, index) in form.enabled_services" :key="index" class="offer-item-editor">
          <header>
            <div><h4>{{ service.label || service.service_token || "Untitled service" }}</h4></div>
            <button class="secondary-action compact" type="button" @click="form.enabled_services.splice(index, 1)">Remove</button>
          </header>
          <div class="offer-three-column">
            <!-- The buyer-facing wording stays the TENANT's, even on an adopted service: it is how they talk
                 to their customers, not a fact about the carrier. -->
            <label class="offer-field">
              <span>Buyer sees</span>
              <input v-model.trim="service.label" type="text" placeholder="e.g. Ground (5–7 days)" />
            </label>
            <!-- Everything below came from the carrier and is LOCKED. A hand-edited service code is one that
                 can never be quoted, and nothing says so until a buyer sees no options. -->
            <label class="offer-field">
              <span>Service code</span>
              <input v-if="service.source === 'rate'" :value="service.service_token" type="text" readonly
                     class="locked-field" />
              <input v-else v-model.trim="service.service_token" type="text"
                     placeholder="e.g. usps_ground_advantage" />
            </label>
            <label class="offer-field">
              <span>Carrier</span>
              <input v-if="service.source === 'rate'" :value="carrierLabel(service.carrier)" type="text"
                     readonly class="locked-field" />
              <select v-else v-model="service.carrier">
                <option value="">Any carrier</option>
                <option v-for="carrier in carrierChoices" :key="carrier.key" :value="carrier.key">
                  {{ carrier.label }}
                </option>
              </select>
            </label>
          </div>
          <div class="offer-two-column">
            <label class="offer-field">
              <span>Fastest (business days)</span>
              <input v-if="service.source === 'rate'" :value="service.transit_days_min" type="text" readonly
                     class="locked-field" />
              <input v-else v-model.number="service.transit_days_min" type="number" min="0" step="1" />
            </label>
            <label class="offer-field">
              <span>Slowest (business days)</span>
              <input v-if="service.source === 'rate'" :value="service.transit_days_max" type="text" readonly
                     class="locked-field" />
              <input v-else v-model.number="service.transit_days_max" type="number" min="0" step="1" />
            </label>
          </div>
          <small v-if="service.source === 'rate'" class="field-hint">
            From a live carrier rate — the code, carrier and transit days are theirs. Remove it and adopt
            another from <strong>Try a rate</strong> to change them.
          </small>
          <small v-else class="field-hint">
            Typed by hand, so nothing has checked this code against a carrier. Adopt it from
            <strong>Try a rate</strong> to be sure it can be quoted.
          </small>
        </div>
        <button class="secondary-action" type="button" @click="form.enabled_services.push(emptyService())">Add service</button>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>What buyers pay</h2>
        <p>Shipping charges by destination, checked <strong>in order</strong> — the first zone that matches a
          buyer's country decides. An &ldquo;Everywhere else&rdquo; zone at the end covers the countries you
          have not listed; remove it and you ship only where you said. Amounts are in your store's default
          currency.</p>
      </header>
      <div class="dashboard-card-body">
        <div v-for="(zone, index) in form.zones" :key="index" class="offer-item-editor">
          <header>
            <div>
              <h4>{{ isCatchAllZone(zone) ? "Everywhere else" : (zone.name || "Untitled zone") }}</h4>
              <p class="field-note">{{ zoneSummary(zone) }}</p>
            </div>
            <div class="zone-actions">
              <button v-if="!isCatchAllZone(zone) && index > 0" class="secondary-action compact" type="button"
                      title="Move up" @click="moveZone(index, -1)">↑</button>
              <button v-if="!isCatchAllZone(zone) && index < form.zones.length - 2" class="secondary-action compact"
                      type="button" title="Move down" @click="moveZone(index, 1)">↓</button>
              <button class="secondary-action compact" type="button"
                      @click="form.zones.splice(index, 1)">Remove</button>
            </div>
          </header>

          <div v-if="!isCatchAllZone(zone)" class="offer-two-column">
            <label class="offer-field">
              <span>Zone name</span>
              <input v-model.trim="zone.name" type="text" placeholder="e.g. United States" />
            </label>
            <label class="offer-field">
              <span>Countries <em>(two-letter codes)</em></span>
              <input v-model.trim="zone.countries_text" type="text" placeholder="e.g. US" />
              <small v-if="zoneCountryError(index)" class="field-error">{{ zoneCountryError(index) }}</small>
            </label>
          </div>

          <div class="offer-two-column">
            <label class="offer-field">
              <span>Buyers here pay</span>
              <select v-model="zone.rule.type">
                <option value="free">Nothing — free shipping</option>
                <option value="flat">A flat amount</option>
                <option value="flat_rate_box">The price of the box it fits</option>
                <option value="live">Live carrier rates</option>
              </select>
            </label>
            <label v-if="zone.rule.type === 'flat'" class="offer-field">
              <span>Flat amount</span>
              <input v-model.trim="zone.rule.amount_text" type="text" inputmode="decimal" placeholder="e.g. 12.99" />
            </label>
          </div>

          <p v-if="zone.rule.type === 'flat_rate_box'" class="field-hint">
            Priced from the <strong>Boxes</strong> section below — give each box a price for
            {{ isCatchAllZone(zone) ? "these destinations" : (zone.countries_text || "these countries") }}.
          </p>
          <p v-if="zone.rule.type === 'flat_rate_box' && boxPricingGap(zone)" class="keys-status-banner warning">
            <strong>Buyers here are not charged for shipping.</strong>
            {{ boxPricingGap(zone) }} Checkout has no price to quote, and Stripe cannot ask again once the
            payment page opens — so these orders ship free until a box is priced.
          </p>
          <p v-if="zone.rule.type === 'live'" class="field-hint">
            Buyers here see real carrier prices for their own address. Your page needs a
            <strong>Shipping</strong> element so they can enter a postal code — without one there is no
            address to rate, and nothing is charged.
          </p>
          <p v-if="zone.rule.type === 'live' && liveZoneGap" class="keys-status-banner warning">
            <strong>Buyers here are not charged for shipping.</strong> {{ liveZoneGap }}
          </p>
        </div>
        <button class="secondary-action" type="button" @click="addZone">Add zone</button>
        <button v-if="!hasCatchAll" class="secondary-action" type="button" @click="addCatchAll">
          Add &ldquo;Everywhere else&rdquo;
        </button>
        <p v-if="!hasCatchAll" class="field-hint">
          You ship only to the countries listed above. A buyer anywhere else is not offered shipping and
          cannot check out &mdash; which is the point of removing it, but it is worth being sure.
        </p>

        <!-- P5: ONE DECISION, stated. Most sellers reward a bigger order with free shipping, which is
             only coherent if the cost was recovered in the price -- and adding one item to a parcel that
             is already going often costs little. The ledger records the real carrier cost either way, so
             `shipping_margin` reports what this costs rather than hiding it. -->
        <label class="switch-row">
          <input v-model="form.combined_shipping.extras_ship_free" type="checkbox" />
          <span>
            <strong>Extras ship free with the original order</strong>
            <small>Order bumps and post-purchase upsells are not charged postage. Often true — a second
              item in a parcel that is already going costs little — and it makes the offer stronger. Your
              shipping margin on the Ledger shows what it actually costs you.</small>
          </span>
        </label>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Try a rate</h2>
        <p>Pick what you would ship and see what each carrier charges. Adopting a rate copies its real
          service code into <strong>Services</strong> — the code a carrier recognises, which is not something
          you can type from memory.</p>
      </header>
      <div class="dashboard-card-body">
        <!-- AN OFFER IS THE SUBJECT, because an offer IS the cart a buyer gets -- its items, its
             quantities, its bump. Hand-picking products rated a basket nobody would ever buy: one product
             showed $6.57 while the three-item bundle shipped for $19
             (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0e). -->
        <label class="offer-field">
          <span>Offer</span>
          <select v-model="preview.offer_id" @change="preview.product_ids = []">
            <option value="">Choose an offer…</option>
            <option v-for="offer in offers" :key="offer.offer_id" :value="offer.offer_id">
              {{ offer.name || offer.offer_id }}
            </option>
          </select>
        </label>

        <!-- The SECONDARY path, kept because measuring a new product before it belongs to any offer is a
             real case. Making it the only case was the mistake. -->
        <details class="preview-adhoc" :open="!preview.offer_id && preview.product_ids.length > 0">
          <summary>Or rate individual products</summary>
          <div class="carrier-chips">
            <button v-for="product in previewProducts" :key="product.product_id" class="carrier-chip"
                    type="button" @click="togglePreviewProduct(product.product_id)">
              {{ product.name }} <span aria-hidden="true">×</span>
            </button>
            <span v-if="!previewProducts.length" class="field-hint">No products chosen yet.</span>
          </div>
          <select class="carrier-add" :value="''"
                  @change="preview.offer_id = ''; togglePreviewProduct($event.target.value)">
            <option value="">Add a product…</option>
            <option v-for="product in unselectedPreviewProducts" :key="product.product_id"
                    :value="product.product_id">{{ product.name }}</option>
          </select>
        </details>

        <div class="offer-three-column">
          <label class="offer-field">
            <span>Box</span>
            <select v-model="preview.box">
              <option value="">Let the packer choose</option>
              <option v-for="box in form.boxes" :key="box.name" :value="box.name">{{ box.name }}</option>
            </select>
          </label>
          <label class="offer-field">
            <span>Ship to country</span>
            <input v-model.trim="preview.country" type="text" maxlength="2"
                   :placeholder="form.ship_from_address.country || 'US'" />
          </label>
          <label class="offer-field">
            <span>Ship to postal code</span>
            <input v-model.trim="preview.postal_code" type="text"
                   :placeholder="form.ship_from_address.postal_code || '80204'" />
          </label>
        </div>
        <p class="field-hint">Leave the destination blank to rate against your own ship-from address.</p>

        <button class="secondary-action" type="button"
                :disabled="previewBusy || (!preview.offer_id && !preview.product_ids.length)"
                @click="runRatePreview">
          {{ previewBusy ? "Asking the carriers…" : "Get rates" }}
        </button>

        <p v-if="previewError" class="keys-status-banner warning">{{ previewError }}</p>
        <!-- Nothing measurable means nothing to charge (P0a), said here in the estimator's own terms
             rather than refused as a malformed request. -->
        <p v-if="previewShipsFree" class="keys-status-banner warning">
          <strong>This ships free.</strong>
          {{ previewUnmeasured.join(", ") }} {{ previewUnmeasured.length === 1 ? "has" : "have" }} no size
          and weight, so there is no parcel to rate and buyers are charged nothing for postage.
        </p>
        <!-- THE BREAKDOWN, not just a price: it shows the consequence of unmeasured goods far more
             plainly than a readiness list does. -->
        <p v-else-if="previewParcels.length" class="field-hint">
          Rated as <strong>{{ previewParcelSummary }}</strong>.
        </p>
        <p v-if="previewBumpDelta > 0" class="keys-status-banner warning">
          <strong>Your order bump adds {{ previewBumpDelta }}
            {{ previewBumpDelta === 1 ? "parcel" : "parcels" }}.</strong>
          A buyer who adds {{ previewBumpProducts.join(", ") }} on the payment page is not charged for it —
          Stripe fixes shipping when checkout opens and cannot reprice it after. Build it into the bump's
          price, make the bump digital, or take it as a cost of conversion.
        </p>

        <div v-for="rate in previewRates" :key="rate.rate_id || rate.service_token" class="offer-item-editor">
          <header>
            <div>
              <h4>{{ rate.carrier?.toUpperCase() }} — {{ rate.service }}</h4>
              <p class="field-note">
                {{ formatRateAmount(rate) }}
                <span v-if="rate.estimated_days"> · {{ rate.estimated_days }} business days</span>
                · code <code>{{ rate.service_token }}</code>
              </p>
            </div>
            <button class="secondary-action compact" type="button" @click="adoptRate(rate)">
              {{ hasService(rate) ? "Already added" : "Use this" }}
            </button>
          </header>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Rate &amp; Label Options</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Optional.</p>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Default Service Level</span>
            <input v-model.trim="form.rate_options.default_service_level" type="text" placeholder="e.g. usps_priority" />
          </label>
          <div class="offer-field">
            <span>Allowed Carriers</span>
            <div class="carrier-chips">
              <button v-for="code in form.rate_options.allowed_carriers" :key="code" class="carrier-chip"
                      type="button" @click="toggleAllowedCarrier(code)">
                {{ carrierLabel(code) }} <span aria-hidden="true">×</span>
              </button>
              <span v-if="!form.rate_options.allowed_carriers.length" class="field-hint">
                Any carrier you are connected to.
              </span>
            </div>
            <select class="carrier-add" :value="''" @change="toggleAllowedCarrier($event.target.value)">
              <option value="">Add a carrier…</option>
              <option v-for="carrier in unselectedCarriers" :key="carrier.key" :value="carrier.key">
                {{ carrier.label }}
              </option>
            </select>
          </div>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Label Format</span>
            <select v-model="form.label_options.format">
              <option value="pdf">PDF</option>
              <option value="png">PNG</option>
              <option value="zpl">ZPL</option>
            </select>
          </label>
          <label class="offer-field">
            <span>Label Size</span>
            <select v-model="form.label_options.size">
              <option value="4x6">4x6</option>
              <option value="8.5x11">8.5x11</option>
            </select>
          </label>
        </div>
      </div>
    </section>

    <footer class="config-save-bar">
      <button class="primary-action" type="button" :disabled="saving || loading" @click="save">
        {{ saving ? "Saving..." : "Save Shipping" }}
      </button>
    </footer>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { apiRequest, getTenantId } from "../api/client";
import { statusLabel } from "../utils/format";
import AddressFields from "./AddressFields.vue";
import { useProfileStore } from "../stores/profile";

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const rawDoc = ref({});
const testing = ref(false);
const connectionResult = ref(null);
const profileStore = useProfileStore();
const copyingBusiness = ref(false);
const form = reactive(defaultForm());

// A saved key comes back redacted (api_key_ref === "********"), so a truthy value means configured.
const keyConfigured = computed(() => Boolean(rawDoc.value.provider?.api_key_ref));
const apiKeyPlaceholder = computed(() => (keyConfigured.value ? "Saved — enter a new key to replace" : "Enter your provider API key"));
const providerChangedNeedsKey = computed(() =>
  Boolean(
    form.provider.name &&
    rawDoc.value.provider?.name &&
    form.provider.name !== rawDoc.value.provider.name &&
    keyConfigured.value &&
    !String(form.provider.api_key || "").trim(),
  ),
);

function emptyAddress() {
  return { name: "", company: "", street1: "", street2: "", city: "", state: "", postal_code: "", country: "US", phone: "", email: "", residential: false };
}

function defaultForm() {
  return {
    enabled: false,
    test_mode: true,
    auto_fulfill_after_label_purchase: false,
    provider: { name: "", base_url: "", api_key: "" },
    ship_from_address: emptyAddress(),
    return_address: emptyAddress(),
    // `markup_amount` and `free_shipping_threshold` are NOT edited here any more. They had inputs on this
    // screen, were saved, and were read by NOTHING -- rate_policy.py says in its own docstring that they
    // belong to charging the buyer, "which is a different question... untouched here". A control implying a
    // promise the system does not keep (plans/SHIPPING_ELEMENT.md). "What buyers pay" replaces them. Stored
    // values are preserved on save so nothing is destroyed for a tenant who set one.
    rate_options: { default_service_level: "", allowed_carriers: [],
                    prefer: "cheapest", max_transit_days: "", preferred_carrier: "", max_auto_amount: "" },
    label_options: { format: "pdf", size: "4x6" },
    boxes: [],
    enabled_services: [],
    combined_shipping: { extras_ship_free: false },
    // The catch-all is structural, not a choice: without it a buyer from an unlisted country reaches
    // undefined behaviour at the moment of purchase, and the validator refuses the save. So the UI always
    // keeps one last and does not let it be removed or renamed.
    zones: [catchAllZone()],
  };
}

// The carriers this tenant may pick from -- their CONNECTED ones when we can ask, else the standard registry.
// Never free text: a typo'd carrier is a carrier that never quotes (plans/SHIPPING_ELEMENT.md).
const carrierChoices = ref([]);
const carrierNote = ref("");

async function loadCarriers() {
  try {
    const body = await apiRequest("/shipping/carriers");
    carrierChoices.value = body.carriers || [];
    carrierNote.value = body.message || "";
  } catch (err) {
    // A picker that cannot load must not become a text box. Empty means "Any carrier" only, which is a
    // smaller failure than inviting the typo back.
    carrierChoices.value = [];
    carrierNote.value = "";
  }
}

function carrierLabel(code) {
  const match = carrierChoices.value.find((carrier) => carrier.key === code);
  return match ? match.label : String(code || "").toUpperCase();
}

const unselectedCarriers = computed(() =>
  carrierChoices.value.filter((carrier) => !(form.rate_options.allowed_carriers || []).includes(carrier.key)));

function toggleAllowedCarrier(code) {
  const value = String(code || "").trim();
  if (!value) return;
  const list = form.rate_options.allowed_carriers;
  const at = list.indexOf(value);
  if (at >= 0) list.splice(at, 1);
  else list.push(value);
}

// ---- Try a rate -------------------------------------------------------------------------------------
// A service DISCOVERY tool that happens to show prices. What "Use this" copies is the carrier and its real
// service token; the amount is context for setting a flat rate, never written into a zone, because a rate is
// destination-specific and stale within days while the token is stable (plans/SHIPPING_ELEMENT.md).
const catalogue = ref([]);
const preview = reactive({ offer_id: "", product_ids: [], box: "", country: "", postal_code: "" });
const previewRates = ref([]);
const previewParcel = ref(null);
const previewParcelCount = ref(0);
const previewParcels = ref([]);
const previewShipsFree = ref(false);
const previewUnmeasured = ref([]);
const previewBumpDelta = ref(0);
const previewBumpProducts = ref([]);
const offers = ref([]);

/** "3 parcels: Small x2, Medium x1" -- the consequence, in the form a tenant can act on. */
const previewParcelSummary = computed(() => {
  const counts = {};
  previewParcels.value.forEach((parcel) => {
    const name = parcel.box_name || "custom parcel";
    counts[name] = (counts[name] || 0) + 1;
  });
  const parts = Object.entries(counts).map(([name, n]) => (n > 1 ? `${name} x${n}` : name));
  const total = previewParcels.value.length;
  return `${total} ${total === 1 ? "parcel" : "parcels"}: ${parts.join(", ")}`;
});

/** Offers the estimator can rate. Silent on failure -- the ad-hoc product path still works without them. */
async function loadOffers() {
  try {
    const body = await apiRequest("/offers");
    offers.value = (body?.offers || []).filter((offer) => (offer.items || []).length);
  } catch {
    offers.value = [];
  }
}
const previewError = ref("");
const previewBusy = ref(false);

async function loadCatalogue() {
  try {
    const body = await apiRequest("/products");
    catalogue.value = (body.products || []).filter((product) => {
      const requires = product?.fulfillment?.requires_shipping;
      return typeof requires === "boolean" ? requires : product?.product_type === "physical";
    });
  } catch (err) {
    catalogue.value = [];
  }
}

const previewProducts = computed(() =>
  preview.product_ids.map((id) => catalogue.value.find((p) => p.product_id === id)).filter(Boolean));
const unselectedPreviewProducts = computed(() =>
  catalogue.value.filter((product) => !preview.product_ids.includes(product.product_id)));

function togglePreviewProduct(productId) {
  const id = String(productId || "").trim();
  if (!id) return;
  const at = preview.product_ids.indexOf(id);
  if (at >= 0) preview.product_ids.splice(at, 1);
  else preview.product_ids.push(id);
}

function formatRateAmount(rate) {
  const currency = String(rate.currency || "usd").toUpperCase();
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format((rate.amount || 0) / 100);
  } catch (err) {
    return `${((rate.amount || 0) / 100).toFixed(2)} ${currency}`;
  }
}

function hasService(rate) {
  return form.enabled_services.some((service) => service.service_token === rate.service_token);
}

async function runRatePreview() {
  previewBusy.value = true;
  previewError.value = "";
  previewRates.value = [];
  previewParcel.value = null;
  previewParcels.value = [];
  previewShipsFree.value = false;
  previewUnmeasured.value = [];
  previewBumpDelta.value = 0;
  previewBumpProducts.value = [];
  try {
    const to = {};
    if (preview.country) to.country = preview.country.toUpperCase();
    if (preview.postal_code) to.postal_code = preview.postal_code;
    const body = await apiRequest("/shipping/rate-preview", {
      method: "POST",
      body: {
        // The offer wins when one is chosen; products are the fallback for something not yet in an offer.
        offer_id: preview.offer_id || undefined,
        product_ids: preview.offer_id ? undefined : preview.product_ids,
        box: preview.box || undefined,
        to_address: Object.keys(to).length ? to : undefined,
      },
    });
    previewRates.value = body.rates || [];
    previewParcel.value = body.parcel || null;
    previewParcels.value = body.parcels || [];
    previewParcelCount.value = body.parcel_count || 0;
    previewShipsFree.value = !!body.ships_free;
    previewUnmeasured.value = body.unmeasured || [];
    previewBumpDelta.value = body.bump_parcel_delta || 0;
    previewBumpProducts.value = body.bump_products || [];
    // "Ships free" is an ANSWER, not a failure -- the banner says it, so the error line must not.
    if (!previewRates.value.length && !previewShipsFree.value) {
      previewError.value = "The carrier returned no rates for this parcel.";
    }
  } catch (err) {
    previewError.value = err.message || "Could not get rates.";
  } finally {
    previewBusy.value = false;
  }
}

/** Copy the SERVICE, not the price. */
function adoptRate(rate) {
  if (hasService(rate)) return;
  form.enabled_services.push({
    ...emptyService(),
    service_token: rate.service_token || "",
    carrier: String(rate.carrier || "").toLowerCase(),
    label: rate.service || "",
    // The carrier's own estimate becomes the window a buyer is shown, rather than a number anyone typed.
    transit_days_min: rate.estimated_days || "",
    transit_days_max: rate.estimated_days || "",
    // Provenance, and what locks the fields above: these values are the CARRIER's.
    source: "rate",
  });
}

function emptyService() {
  return { service_token: "", carrier: "", label: "", transit_days_min: "", transit_days_max: "",
           source: "manual" };
}

// Mirrors the Boxes convenience seed: a tenant should not have to invent service codes from nothing.
const STARTER_SERVICES = [
  { service_token: "ground", carrier: "", label: "Ground (5–7 business days)", transit_days_min: 5, transit_days_max: 7 },
  { service_token: "two_day", carrier: "", label: "2-day", transit_days_min: 2, transit_days_max: 2 },
  { service_token: "overnight", carrier: "", label: "Overnight", transit_days_min: 1, transit_days_max: 1 },
];

function useStarterServices() {
  form.enabled_services = STARTER_SERVICES.map((service) => ({ ...service }));
}

const hasCatchAll = computed(() => form.zones.some(isCatchAllZone));

function emptyZone() {
  return { name: "", countries_text: "", rule: { type: "flat", amount_text: "" } };
}

function catchAllZone() {
  return { name: "Everywhere else", countries_text: "*", rule: { type: "free", amount_text: "" } };
}

function isCatchAllZone(zone) {
  return String(zone?.countries_text || "").trim() === "*";
}

function addZone() {
  // Inserted BEFORE the catch-all, because a zone after it would never be reached -- but only when there
  // IS one. A tenant who removed it ships only where they listed, and a new zone belongs at the end.
  const last = form.zones[form.zones.length - 1];
  const before = isCatchAllZone(last) ? form.zones.length - 1 : form.zones.length;
  form.zones.splice(Math.max(0, before), 0, emptyZone());
}

function addCatchAll() {
  // Always last: every zone after a catch-all is unreachable, and the document validator refuses it.
  if (!hasCatchAll.value) form.zones.push(catchAllZone());
}

function moveZone(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= form.zones.length - 1) return;
  const [zone] = form.zones.splice(index, 1);
  form.zones.splice(target, 0, zone);
}

function zoneCountryCodes(zone) {
  return String(zone?.countries_text || "")
    .split(/[,\s]+/)
    .map((code) => code.trim().toUpperCase())
    .filter(Boolean);
}

/** The validator refuses a country claimed by two zones; say so here rather than on save. */
function zoneCountryError(index) {
  const zone = form.zones[index];
  const codes = zoneCountryCodes(zone);
  if (!codes.length) return "Add at least one country code, e.g. US.";
  const bad = codes.find((code) => code !== "*" && !/^[A-Z]{2}$/.test(code));
  if (bad) return `"${bad}" is not a two-letter country code.`;
  for (let other = 0; other < form.zones.length - 1; other += 1) {
    if (other === index) continue;
    const clash = zoneCountryCodes(form.zones[other]).find((code) => codes.includes(code));
    // First match wins, so the LATER zone is the dead one -- name it, because the tenant would otherwise
    // believe both were live.
    if (clash) return `${clash} is already in "${form.zones[other].name || 'another zone'}", which comes first.`;
  }
  return "";
}

function zoneSummary(zone) {
  const kind = zone?.rule?.type;
  if (kind === "free") return "Free shipping";
  if (kind === "flat") return zone.rule.amount_text ? `Flat ${zone.rule.amount_text}` : "Flat rate — no amount set";
  if (kind === "flat_rate_box") return "Priced by the box it fits";
  if (kind === "live") return "Live carrier rates";
  return "";
}

/** Which countries need a per-box price, i.e. those in a zone priced by box. */
const boxPricingCountries = computed(() => {
  const codes = [];
  form.zones.forEach((zone) => {
    if (zone?.rule?.type !== "flat_rate_box") return;
    zoneCountryCodes(zone).forEach((code) => {
      if (code !== "*" && !codes.includes(code)) codes.push(code);
    });
  });
  return codes;
});

const boxPricingUsed = computed(() => boxPricingCountries.value.length > 0);

/** What stops a live zone from quoting, or "" when nothing does.
 *
 * Only ever ONE sentence, and only when there is something the tenant must actually go and do. The
 * previous copy blamed a missing carrier unconditionally, which was simply wrong for a tenant who had
 * connected one -- and wrong advice is worse than silence because it sends them to the wrong screen.
 */
const liveZoneGap = computed(() => {
  if (!form.provider.name) return "Connect a carrier above to get live rates.";
  if (!form.enabled_services.length) {
    return "Add at least one service below — buyers can only choose from services you offer.";
  }
  return "";
});

/** Names what is missing, because a box-priced zone with no priced box cannot quote at all. */
function boxPricingGap(zone) {
  const codes = zoneCountryCodes(zone).filter((code) => code !== "*");
  if (!codes.length) return "";
  if (!form.boxes.length) return "No boxes are defined yet, so nothing has a price.";
  const unpriced = codes.filter((code) => !form.boxes.some((box) => String(box.prices?.[code] || "").trim()));
  return unpriced.length ? `No box has a price for ${unpriced.join(", ")} yet.` : "";
}

// Ordinary corrugated sizes, mirroring STARTER_BOXES in domain/shipping.py. A convenience seed so a tenant
// is not staring at an empty table -- NOT carrier packaging, which is fetched from the provider as parcel
// templates because hand-copied carrier dimensions go stale the moment a size is retired.
const STARTER_BOXES = [
  { name: "Small box (6x4x4)", kind: "box", length: 6, width: 4, height: 4, empty_weight: 0.15, max_weight: "" },
  { name: "Medium box (10x8x6)", kind: "box", length: 10, width: 8, height: 6, empty_weight: 0.35, max_weight: "" },
  { name: "Large box (14x11x8)", kind: "box", length: 14, width: 11, height: 8, empty_weight: 0.6, max_weight: "" },
  { name: "Extra large box (18x14x12)", kind: "box", length: 18, width: 14, height: 12, empty_weight: 1.0, max_weight: "" },
  { name: "Padded mailer (9x6x1)", kind: "soft_pack", length: 9, width: 6, height: 1, empty_weight: 0.05, max_weight: "" },
].map((box) => ({ ...box, prices: {} }));

function emptyBox() {
  // `kind` defaults to a box because rigid is the safe assumption: a mailer mistakenly treated as a
  // carton just oversizes a parcel, while a carton treated as a mailer sends an item the carrier refuses.
  //
  // `template` -- a carrier's own packaging identifier -- is deliberately NOT edited here. The schema
  // records why: carrier packaging is fetched from the provider as parcel templates, because hand-copied
  // carrier dimensions go stale the moment a size is retired. The packer and the adapter already pass one
  // through when a box carries it; asking a tenant to type "USPS_FlatRateEnvelope" would contradict that.
  // `prices` is UI-side only: country -> typed text. `buildPayload` converts it to the schema's
  // `flat_rate` (country -> cents), so a half-typed "12." never reaches the document.
  return { name: "", kind: "box", length: "", width: "", height: "", empty_weight: "", max_weight: "", prices: {} };
}

function addBox() {
  form.boxes.push(emptyBox());
}

function removeBox(index) {
  form.boxes.splice(index, 1);
}

function boxFormFromDocument(box) {
  const prices = {};
  Object.entries(box.flat_rate || {}).forEach(([code, cents]) => {
    prices[String(code).toUpperCase()] = (Number(cents) / 100).toFixed(2);
  });
  return { ...emptyBox(), ...box, prices };
}

const parcelTemplates = ref([]);

/** Carrier-supplied packaging, fetched once. Silent on failure: a picker that cannot populate leaves the
 * tenant with their own boxes, which is exactly where they were before it existed. */
async function loadParcelTemplates() {
  try {
    const body = await apiRequest("/shipping/parcel-templates");
    parcelTemplates.value = Array.isArray(body?.templates) ? body.templates : [];
  } catch {
    parcelTemplates.value = [];
  }
}

/** Adopting a template takes the carrier's dimensions with it — they are facts about the container, not
 * preferences, and a tenant who edits them is describing a box that does not exist. Clearing it hands the
 * dimensions back. */
function useParcelTemplate(box, token) {
  const tpl = parcelTemplates.value.find((t) => t.template === token);
  if (!tpl) {
    box.template = "";
    return;
  }
  box.template = tpl.template;
  box.name = tpl.name;
  box.length = Number(tpl.length) || box.length;
  box.width = Number(tpl.width) || box.width;
  box.height = Number(tpl.height) || box.height;
}

function useStarterBoxes() {
  form.boxes = STARTER_BOXES.map((box) => ({ ...box }));
}

// The profile stores a PostalAddress (street / locality / region) because it maps straight to
// LocalBusiness JSON-LD. A carrier wants street1 / city / state. Same place, two vocabularies -- so this
// is a translation, and spreading one into the other would silently fill nothing.
function businessAddressToShipFrom(business) {
  const address = business?.address || {};
  return {
    name: business?.name || "",
    street1: address.street || "",
    city: address.locality || "",
    state: address.region || "",
    postal_code: address.postal_code || "",
    country: (address.country || "US").toUpperCase(),
    phone: business?.phone || "",
  };
}

async function copyBusinessAddress() {
  error.value = "";
  message.value = "";
  copyingBusiness.value = true;
  try {
    // load(), not ensureLoaded(): the tenant explicitly asked for their CURRENT business address, and a
    // cached copy may predate an edit made on the Profile screen a moment ago -- changing the business
    // address and then copying it here is exactly when someone clicks this. A deliberate click is rare
    // enough that one request costs nothing next to copying an address they have already changed.
    await profileStore.load();
    const mapped = businessAddressToShipFrom(profileStore.business);
    // Nothing to copy is a CONFIGURATION answer, not a failure: say where to fix it rather than leaving
    // the tenant to wonder whether the button is broken.
    if (!mapped.street1 && !mapped.city && !mapped.postal_code) {
      error.value = "No business address is configured in your profile. Add one in Profile → Business, "
        + "then copy it here.";
      return;
    }
    Object.entries(mapped).forEach(([key, value]) => {
      if (value) form.ship_from_address[key] = value;
    });
    const missing = ["street1", "city", "state", "postal_code"].filter((key) => !form.ship_from_address[key]);
    message.value = missing.length
      ? `Copied what your profile has. Still needed: ${missing.join(", ")}.`
      : "Copied your business address.";
  } finally {
    copyingBusiness.value = false;
  }
}

function fillAddress(target, source) {
  const base = emptyAddress();
  Object.keys(base).forEach((key) => {
    target[key] = source?.[key] ?? base[key];
  });
}

/** Stored zones -> editor rows, always ending in exactly one catch-all the UI owns. */
function zonesFromDocument(zones) {
  const rows = (Array.isArray(zones) ? zones : [])
    .map((zone) => ({
      name: zone.name || "",
      countries_text: (zone.destinations || []).map((d) => String(d.country || "").toUpperCase()).join(", "),
      rule: {
        type: zone.rule?.type || "flat",
        amount_text: zone.rule?.amount ? (Number(zone.rule.amount) / 100).toFixed(2) : "",
      },
    }))
    .filter((row) => row.countries_text);
  const catchAll = rows.filter(isCatchAllZone);
  const specific = rows.filter((row) => !isCatchAllZone(row));
  // At most one, always last. Several are normalised to the first rather than refused -- the tenant sees a
  // valid set instead of an error about a shape they never typed.
  //
  // NONE is now a real answer rather than a gap to fill. It used to append one here, which made the
  // catch-all structurally mandatory: a tenant could remove it, save, and find it back on the next load
  // with nothing to explain why. Removing it is how a seller says "I ship to these countries and no
  // others", which the shipping element and Stripe's address form both honour (author, 2026-10-04).
  return catchAll.length ? [...specific, catchAll[0]] : specific;
}

function applyConfig(config) {
  rawDoc.value = config || {};
  const base = defaultForm();
  form.enabled = Boolean(config.enabled);
  form.test_mode = config.test_mode ?? true;
  form.auto_fulfill_after_label_purchase = Boolean(config.auto_fulfill_after_label_purchase);
  form.provider.name = config.provider?.name || "";
  form.provider.base_url = config.provider?.base_url || "";
  form.provider.api_key = ""; // never populate the actual key; it's redacted on read
  fillAddress(form.ship_from_address, config.ship_from_address);
  fillAddress(form.return_address, config.return_address);
  form.boxes = Array.isArray(config.boxes)
    ? config.boxes.map((box) => ({ ...boxFormFromDocument(box), max_weight: box.max_weight ?? "" }))
    : [];
  form.combined_shipping = {
    extras_ship_free: !!(config.combined_shipping || {}).extras_ship_free,
  };
  form.enabled_services = Array.isArray(config.enabled_services)
    ? config.enabled_services.map((service) => ({
        ...emptyService(), ...service,
        transit_days_min: service.transit_days_min ?? "",
        transit_days_max: service.transit_days_max ?? "",
        source: service.source === "rate" ? "rate" : "manual",
      }))
    : [];
  form.zones = zonesFromDocument(config.zones);
  const rate = config.rate_options || {};
  form.rate_options = {
    default_service_level: rate.default_service_level || "",
    // An ARRAY now, not a comma-separated string: the field is a chip list, so a stored string from before
    // this change is split once on load rather than being re-parsed on every save.
    allowed_carriers: Array.isArray(rate.allowed_carriers)
      ? rate.allowed_carriers.map((code) => String(code).trim().toLowerCase()).filter(Boolean)
      : String(rate.allowed_carriers || "").split(",").map((code) => code.trim().toLowerCase()).filter(Boolean),
    prefer: rate.prefer || "cheapest",
    max_transit_days: rate.max_transit_days ?? "",
    preferred_carrier: rate.preferred_carrier || "",
    // Stored in cents, shown in dollars -- the tenant types "25.00", not "2500".
    max_auto_amount: rate.max_auto_amount ? (Number(rate.max_auto_amount) / 100).toFixed(2) : "",
  };
  form.label_options = { format: config.label_options?.format || "pdf", size: config.label_options?.size || "4x6" };
  void base;
}

function copyShipFromToReturn() {
  fillAddress(form.return_address, form.ship_from_address);
}

function cleanAddress(address) {
  const result = {
    name: address.name.trim(),
    street1: address.street1.trim(),
    city: address.city.trim(),
    state: address.state.trim(),
    postal_code: address.postal_code.trim(),
    country: address.country.trim().toUpperCase(),
    residential: Boolean(address.residential),
  };
  ["company", "street2", "phone", "email"].forEach((key) => {
    const value = String(address[key] || "").trim();
    if (value) result[key] = value;
  });
  return result;
}

// What stops a SAVE, which is almost nothing: a tenant must be able to store a key and test it before
// they have an address to type. What stops a LABEL is a different question, answered by `readiness`.
function validationErrors() {
  const errors = [];
  if (!form.provider.name) errors.push("Provider");
  // A STARTED address must be finished -- half an address buys a label that cannot be delivered -- but an
  // untouched one is simply not set yet, which is a state the readiness list explains.
  [["Ship-from", form.ship_from_address], ["Return", form.return_address]].forEach(([label, addr]) => {
    const started = ["name", "street1", "city", "state", "postal_code"].some((f) => String(addr[f] || "").trim());
    if (!started) return;
    ["name", "street1", "city", "state", "postal_code", "country"].forEach((field) => {
      if (!String(addr[field] || "").trim()) errors.push(`${label} ${field.replace(/_/g, " ")}`);
    });
    const country = String(addr.country || "").trim();
    if (country && country.length !== 2) errors.push(`${label} country must be a 2-letter code`);
  });
  // Zones, checked here so the server's refusal is never the first the tenant hears of it. Each message names
  // what is wrong rather than saying "invalid zone" -- a duplicate country in particular is invisible
  // otherwise, because first-match-wins makes the LATER zone silently dead.
  form.zones.forEach((zone, index) => {
    if (isCatchAllZone(zone)) return;
    const problem = zoneCountryError(index);
    if (problem) errors.push(`Zone "${zone.name || index + 1}": ${problem}`);
    if (zone.rule?.type === "flat" && !String(zone.rule.amount_text || "").trim()) {
      errors.push(`Zone "${zone.name || index + 1}" is a flat rate with no amount`);
    }
  });
  return errors;
}

// What the SERVER says is still missing, never computed from the form. Computing it here meant the banner
// turned green the moment boxes were added on screen -- before any save -- so a save that failed still
// read "Ready to buy labels". One implementation, in domain/shipping.py, carried on every response.
const readiness = ref([]);
// Kept apart from `readiness` for the same reason the server sends them separately: that list blocks a
// label, this one only costs postage. Merging them would put "add a weight" under "before you can buy
// labels", which is untrue and would send tenants looking for a tape measure they do not need.
const productReadiness = ref([]);
const unmeasuredProducts = ref([]);
const measurements = reactive({});
const measuringBusy = ref(false);

/** One editable row per unmeasured product, kept in step as the list shrinks. */
watch(unmeasuredProducts, (rows) => {
  (rows || []).forEach((row) => {
    if (!measurements[row.product_id]) {
      measurements[row.product_id] = { length_in: "", width_in: "", height_in: "", weight_lb: "" };
    }
  });
}, { immediate: true });

/** Only rows with ALL FOUR. Three sides cannot be rated, and a half-measured product that looks
 *  measured is worse than one that is plainly blank. */
const completeMeasurements = computed(() => unmeasuredProducts.value
  .map((row) => ({ product_id: row.product_id, ...(measurements[row.product_id] || {}) }))
  .filter((row) => ["length_in", "width_in", "height_in", "weight_lb"]
    .every((field) => Number(row[field]) > 0)));

function useSuggestion(row) {
  const target = measurements[row.product_id];
  if (!target || !row.suggestion) return;
  ["length_in", "width_in", "height_in", "weight_lb"].forEach((field) => {
    target[field] = row.suggestion[field];
  });
}

async function saveMeasurements() {
  measuringBusy.value = true;
  error.value = "";
  try {
    const body = await apiRequest("/shipping/measure", {
      method: "POST",
      body: { measurements: completeMeasurements.value },
    });
    productReadiness.value = body.product_readiness || [];
    unmeasuredProducts.value = body.unmeasured_products || [];
    message.value = `Measured ${(body.saved || []).length} product${(body.saved || []).length === 1 ? "" : "s"}.`;
  } catch (err) {
    error.value = err.message || "Could not save measurements.";
  } finally {
    measuringBusy.value = false;
  }
}

// Whether the server has told us yet. An empty `readiness` means ready; an ABSENT one means unknown --
// the state of a tenant whose GET 404'd because they have saved nothing. Those must not look alike.
const readinessKnown = ref(false);

function applyReadiness(body) {
  if (Array.isArray(body?.readiness)) {
    readiness.value = body.readiness;
    readinessKnown.value = true;
  }
  if (Array.isArray(body?.product_readiness)) productReadiness.value = body.product_readiness;
  if (Array.isArray(body?.unmeasured_products)) unmeasuredProducts.value = body.unmeasured_products;
}

async function load() {
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    const body = await apiRequest("/shipping");
    applyConfig(body.shipping_config || {});
    // The GET has always carried readiness; only save applied it. So a saved config that was missing its
    // ship-from address loaded reading "Ready to buy labels" until the tenant happened to press Save.
    applyReadiness(body);
  } catch (err) {
    if (/not found/i.test(err.message)) {
      applyConfig({});
      message.value = "No shipping config saved yet. Complete the required fields and save.";
    } else {
      error.value = err.message || "Failed to load shipping config.";
    }
  } finally {
    loading.value = false;
  }
}

function buildPayload() {
  const doc = { ...rawDoc.value };
  doc.schema_version = "2026-05-29";
  doc.document_type = "shipping_config";
  doc.tenant_id = getTenantId();
  doc.enabled = form.enabled;
  doc.test_mode = form.test_mode;
  doc.auto_fulfill_after_label_purchase = form.auto_fulfill_after_label_purchase;

  // Provider: send a newly-typed key as plaintext (backend encrypts), the redacted
  // sentinel to keep an unchanged key, or nothing when no key is set. connection_status/
  // last_tested_at are managed by the backend, so don't carry the redacted copies back.
  const provider = { name: form.provider.name };
  if (form.provider.base_url) provider.base_url = form.provider.base_url;
  const enteredKey = String(form.provider.api_key || "").trim();
  if (enteredKey) {
    provider.api_key_ref = enteredKey;
  } else if (rawDoc.value.provider?.api_key_ref) {
    provider.api_key_ref = "********";
  }
  doc.provider = provider;

  // Boxes: drop blank rows rather than saving half a box, and omit max_weight when it is blank -- absent
  // means "no stated limit", which is the common case for a tenant's own carton.
  doc.boxes = form.boxes
    .filter((box) => String(box.name || "").trim() && Number(box.length) > 0
      && Number(box.width) > 0 && Number(box.height) > 0)
    .map((box) => {
      const entry = {
        name: String(box.name).trim(),
        length: Number(box.length), width: Number(box.width), height: Number(box.height),
      };
      // `kind` was COLLECTED BY THE FORM AND NEVER SENT. Live dev data shows a "Padded mailer" stored with
      // no kind, so the packer treated it as a rigid carton -- the schema warns in its own words that
      // "pricing one as the other is why an 8x5x2 pouch used to climb to a carton". Fixed here because it is
      // the same fault this screen is being rebuilt to remove: a control whose value is discarded.
      if (box.kind === "soft_pack") entry.kind = "soft_pack";
      if (Number(box.empty_weight) > 0) entry.empty_weight = Number(box.empty_weight);
      if (Number(box.max_weight) > 0) entry.max_weight = Number(box.max_weight);
      // A carrier's own packaging identifier, never typed here -- carried through when a stored box has one.
      if (String(box.template || "").trim()) entry.template = String(box.template).trim();
      // What a buyer pays when their order fits this box, per destination country. Only well-formed amounts
      // travel: a half-typed "12." must not become a price.
      const flat = {};
      Object.entries(box.prices || {}).forEach(([code, text]) => {
        const cents = Math.round(Number(String(text).replace(/[$,]/g, "")) * 100);
        if (Number.isFinite(cents) && cents >= 0 && String(text).trim()) flat[String(code).toUpperCase()] = cents;
      });
      if (Object.keys(flat).length) entry.flat_rate = flat;
      return entry;
    });

  // Only sent when ON: a stored `false` and an absent block mean the same thing, and writing the default
  // into every tenant's document makes a decision look taken when it was not.
  if (form.combined_shipping.extras_ship_free) {
    doc.combined_shipping = { extras_ship_free: true };
  }
  doc.ship_from_address = cleanAddress(form.ship_from_address);
  doc.return_address = cleanAddress(form.return_address);
  // default_parcel is deliberately NOT sent: it is read by nothing. A parcel comes from a box the items
  // are packed into, or from a product's own Package Dimensions. Any value saved before this stays on the
  // document untouched (doc starts as a copy of rawDoc).

  const rate = {};
  if (form.rate_options.default_service_level.trim()) rate.default_service_level = form.rate_options.default_service_level.trim();
  const carriers = (form.rate_options.allowed_carriers || []).map((code) => String(code).trim()).filter(Boolean);
  if (carriers.length) rate.allowed_carriers = carriers;
  // markup_amount and free_shipping_threshold are no longer EDITED here -- nothing ever read them, and "What
  // buyers pay" replaces them. A stored value is carried through rather than deleted: a tenant who set one
  // should not have data silently removed by a screen that stopped showing it. Retiring the fields properly
  // belongs with the handling-fee work (plans/SHIPPING_ELEMENT.md).
  const storedRate = rawDoc.value.rate_options || {};
  if (storedRate.markup_amount != null) rate.markup_amount = storedRate.markup_amount;
  if (storedRate.free_shipping_threshold != null) rate.free_shipping_threshold = storedRate.free_shipping_threshold;

  // The rate PREFERENCE. "cheapest" is the default the server falls back to anyway, so storing it would
  // only pin a choice the tenant never made.
  if (form.rate_options.prefer && form.rate_options.prefer !== "cheapest") rate.prefer = form.rate_options.prefer;
  const days = Number(form.rate_options.max_transit_days);
  if (days > 0) rate.max_transit_days = Math.floor(days);
  if (form.rate_options.preferred_carrier.trim()) rate.preferred_carrier = form.rate_options.preferred_carrier.trim();
  // Typed in dollars, stored in CENTS like every other amount in this codebase.
  const ceiling = Number(String(form.rate_options.max_auto_amount).replace(/[$,]/g, ""));
  if (ceiling > 0) rate.max_auto_amount = Math.round(ceiling * 100);

  if (Object.keys(rate).length) doc.rate_options = rate;
  else delete doc.rate_options;

  // Services the tenant offers a buyer. A row with no code cannot be matched to a carrier, so it is dropped
  // rather than saved as an unusable choice.
  const services = form.enabled_services
    .filter((service) => String(service.service_token || "").trim())
    .map((service) => {
      const entry = { service_token: String(service.service_token).trim(),
                      source: service.source === "rate" ? "rate" : "manual" };
      if (String(service.carrier || "").trim()) entry.carrier = String(service.carrier).trim();
      if (String(service.label || "").trim()) entry.label = String(service.label).trim();
      if (Number(service.transit_days_min) >= 0 && service.transit_days_min !== "") {
        entry.transit_days_min = Math.floor(Number(service.transit_days_min));
      }
      if (Number(service.transit_days_max) >= 0 && service.transit_days_max !== "") {
        entry.transit_days_max = Math.floor(Number(service.transit_days_max));
      }
      return entry;
    });
  if (services.length) doc.enabled_services = services;
  else delete doc.enabled_services;

  // Zones, in the tenant's order, catch-all last. Emitted as `destinations[{country}]` -- the shape that can
  // gain `regions` later without a second field (plans/SHIPPING_ELEMENT.md).
  const zones = form.zones
    .map((zone) => {
      const codes = zoneCountryCodes(zone);
      if (!codes.length) return null;
      const rule = { type: zone.rule?.type || "flat" };
      if (rule.type === "flat") {
        rule.amount = Math.max(0, Math.round(Number(String(zone.rule.amount_text || "").replace(/[$,]/g, "")) * 100) || 0);
      }
      const entry = { destinations: codes.map((country) => ({ country })), rule };
      if (String(zone.name || "").trim()) entry.name = String(zone.name).trim();
      return entry;
    })
    .filter(Boolean);
  // Only sent once the tenant has configured something beyond the UI's own catch-all. A lone catch-all is the
  // default the form starts with, and storing it would turn "not configured" into "everything ships free".
  const meaningful = zones.length > 1 || (zones.length === 1 && zones[0].rule.type !== "free");
  if (meaningful) doc.zones = zones;
  else delete doc.zones;

  doc.label_options = { format: form.label_options.format, size: form.label_options.size };
  doc.updated_at = Math.floor(Date.now() / 1000);
  return doc;
}

async function testConnection() {
  error.value = "";
  message.value = "";
  connectionResult.value = null;
  testing.value = true;
  try {
    const body = await apiRequest("/shipping/test", { method: "POST" });
    connectionResult.value = body.connection || null;
    applyReadiness(body);
    if (body.shipping_config) rawDoc.value = body.shipping_config;
  } catch (err) {
    // A failed test is an ANSWER, not an error: the backend returns 502 with the provider's own words,
    // and those words are how a tenant learns what is actually wrong with their key.
    connectionResult.value = { status: "failed", message: err.body?.connection?.message || err.message };
    applyReadiness(err.body);
    if (err.body?.shipping_config) rawDoc.value = err.body.shipping_config;
  } finally {
    testing.value = false;
  }
}

async function save() {
  error.value = "";
  message.value = "";
  const errors = validationErrors();
  if (errors.length) {
    error.value = `Please complete: ${errors.slice(0, 4).join(", ")}${errors.length > 4 ? ", …" : ""}.`;
    return;
  }
  saving.value = true;
  try {
    const body = await apiRequest("/shipping", { method: "PUT", body: buildPayload() });
    applyReadiness(body);
    applyConfig(body.shipping_config || buildPayload());
    message.value = "Shipping config saved.";
  } catch (err) {
    error.value = err.message || "Failed to save shipping config.";
  } finally {
    saving.value = false;
  }
}

load();
loadCarriers();
loadParcelTemplates();
loadOffers();
loadCatalogue();
</script>

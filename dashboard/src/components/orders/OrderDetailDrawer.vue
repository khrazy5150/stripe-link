<template>
  <div class="drawer-backdrop" @click.self="$emit('close')">
    <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="orderDrawerTitle">
      <header class="drawer-header">
        <h2 id="orderDrawerTitle">{{ shipment ? "Shipment detail" : "Order detail" }}</h2>
        <button type="button" class="modal-close" aria-label="Close" @click="$emit('close')">×</button>
      </header>

      <!-- The carrier banner, when there is a parcel. Tracking number first: it is what a tenant opens
           this panel to copy. -->
      <div v-if="shipment" class="drawer-banner">
        <div>
          <div class="drawer-carrier">{{ shipment.service || shipment.carrier || "Shipment" }}</div>
          <a v-if="shipment.tracking_url && shipment.tracking_number" class="drawer-tracking font-mono"
             :href="shipment.tracking_url" target="_blank" rel="noopener">{{ shipment.tracking_number }}</a>
          <span v-else-if="shipment.tracking_number" class="drawer-tracking font-mono">{{ shipment.tracking_number }}</span>
          <span v-else class="orders-secondary">No tracking number</span>
        </div>
        <button v-if="shipment.tracking_number" type="button" class="secondary-action"
                @click="$emit('copy', shipment.tracking_number)">Copy</button>
      </div>

      <!-- Not every order is a parcel, and saying so plainly beats an empty shipment panel. -->
      <div v-else class="drawer-banner drawer-banner-muted">
        <div>
          <div class="drawer-carrier">Not a shippable product</div>
          <p class="orders-secondary">{{ notShippableReason }}</p>
        </div>
      </div>

      <div class="drawer-body">
        <dl class="drawer-grid">
          <div><dt>Customer</dt><dd>
            {{ order.customer?.name || "—" }}
            <div v-if="order.customer?.email" class="orders-secondary">{{ order.customer.email }}</div>
          </dd></div>
          <div v-if="address"><dt>Ship to</dt><dd>
            <div v-if="address.street1">{{ address.street1 }}</div>
            <div v-if="address.street2">{{ address.street2 }}</div>
            <div>{{ [address.city, address.state].filter(Boolean).join(", ") }} {{ address.postal_code }}</div>
            <div>{{ address.country }}</div>
          </dd></div>
          <div v-if="shipment"><dt>Tracking status</dt><dd>{{ trackStatus }}</dd></div>
          <div><dt>Order</dt><dd>
            <!-- The reference, and only the reference. The 72-character Stripe id is internal: it is not
                 actionable for a tenant, and it is what ran through the column beside this one. It is
                 still what gets copied, because that is the value anything else would ask for. -->
            <button type="button" class="drawer-order-ref font-mono"
                    title="Click to copy the order reference"
                    @click="$emit('copy', order.short_ref || order.order_id)">
              {{ order.short_ref || shortOrderRef(order.order_id) }}
            </button>
            <div class="orders-secondary">{{ formatDate(order.created_at) }}</div>
          </dd></div>
          <div v-if="shipment?.shipped_at || shipment?.purchased_at">
            <dt>Ship date</dt><dd>{{ formatDate(shipment.shipped_at || shipment.purchased_at) }}</dd>
          </div>
          <div><dt>Status</dt><dd>
            <span class="product-status" :class="statusBadgeClass(orderStatus(order))">
              {{ statusLabel(orderStatus(order)) }}
            </span>
          </dd></div>
        </dl>

        <template v-if="order.address_validation">
          <h3 class="details-subheading">Address check</h3>
          <p>
            <span class="product-status" :class="addressBadge">{{ addressLabel }}</span>
            <span class="orders-place">checked {{ formatDate(order.address_validation.checked_at) }}</span>
          </p>
          <p v-for="note in order.address_validation.messages || []" :key="note" class="field-hint">
            {{ note }}
          </p>

          <!-- OFFERED, never applied. The buyer typed an address and is entitled to have it be the one
               used; a ZIP+4 is worth having, but not worth taking without being asked. -->
          <div v-if="order.address_suggestion" class="drawer-suggestion">
            <strong>The carrier would write it like this:</strong>
            <table class="drawer-lines">
              <tbody>
                <tr v-for="(change, field) in order.address_suggestion.changed" :key="field">
                  <td>{{ fieldLabel(field) }}</td>
                  <td><s class="orders-place">{{ change.was }}</s> → <strong>{{ change.suggested }}</strong></td>
                </tr>
              </tbody>
            </table>
            <p class="field-hint">
              We have not changed your order — this is what the carrier's own records say. A ZIP+4 can
              improve delivery, but the address on the label stays the one your customer entered.
            </p>
          </div>
        </template>

        <h3 class="details-subheading">Items</h3>
        <table class="drawer-lines">
          <tbody>
            <tr v-for="(line, index) in lines" :key="index">
              <td>{{ Number(line.quantity || 1) }} × {{ line.name || "Item" }}</td>
              <td class="orders-col-money">{{ formatMoney(line.amount_total, order.currency) }}</td>
            </tr>
            <tr class="drawer-total">
              <td>Order total</td>
              <td class="orders-col-money">{{ formatMoney(order.amount_total, order.currency) }}</td>
            </tr>
            <tr v-if="Number(order.amount_refunded) > 0">
              <td>Refunded</td>
              <td class="orders-col-money">−{{ formatMoney(order.amount_refunded, order.currency) }}</td>
            </tr>
          </tbody>
        </table>

        <template v-if="shipment?.cost?.amount">
          <h3 class="details-subheading">Postage</h3>
          <table class="drawer-lines">
            <tbody>
              <tr>
                <td>{{ shipment.service || shipment.carrier }}</td>
                <td class="orders-col-money">{{ formatMoney(shipment.cost.amount, shipment.cost.currency) }}</td>
              </tr>
            </tbody>
          </table>
          <p class="field-hint">
            What the carrier quoted. A carrier that re-weighs or re-measures the parcel bills the
            difference back to you later.
          </p>
        </template>

        <template v-if="order.fees">
          <h3 class="details-subheading">Fees</h3>
          <dl class="drawer-grid">
            <div><dt>Gross</dt><dd>{{ formatMoney(order.fees.tenant_keyed_amount, order.currency) }}</dd></div>
            <div><dt>Stripe</dt><dd>{{ formatMoney(order.fees.stripe_fee, order.currency) }}</dd></div>
            <div><dt>Platform</dt><dd>{{ formatMoney(order.fees.platform_fee, order.currency) }}</dd></div>
            <div><dt>Net payout</dt><dd>{{ formatMoney(order.fees.net_payout, order.currency) }}</dd></div>
          </dl>
        </template>

        <details class="product-json-details">
          <summary>Raw JSON</summary>
          <pre>{{ JSON.stringify(order, null, 2) }}</pre>
        </details>
      </div>

      <footer v-if="shipment?.label_url" class="drawer-footer">
        <a class="primary-action" :href="shipment.label_url" target="_blank" rel="noopener">Download label</a>
      </footer>
    </aside>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { formatMoney } from "../../stores/products";
import { formatEpochDate, statusLabel } from "../../utils/format";
import { orderStatus, shortOrderRef, statusBadgeClass } from "./orderDisplay";

const props = defineProps({ order: { type: Object, required: true } });
defineEmits(["close", "copy"]);

const formatDate = formatEpochDate;

const shipment = computed(() => props.order?.fulfilment?.shipment || null);
const address = computed(() => props.order?.shipping_address || null);

const lines = computed(() => {
  const items = props.order?.line_items;
  if (Array.isArray(items) && items.length) return items;
  const product = props.order?.product;
  return product?.name ? [{ name: product.name, quantity: 1, amount_total: props.order.amount_total }] : [];
});

// Why there is no parcel, in the order's own words where we have them. The gate already computed this;
// repeating the logic here would let the panel and the row disagree.
const notShippableReason = computed(() => {
  const reasons = props.order?.fulfilment?.reasons || [];
  if (reasons.length) return reasons.join(" ");
  return "This order has nothing to post — a download, a subscription or a service.";
});

const ADDRESS_LABELS = {
  deliverable: ["Deliverable", "active"],
  undeliverable: ["Carrier will not deliver here", "archived"],
  unknown: ["Could not be confirmed", "warning"],
};

const addressLabel = computed(() =>
  (ADDRESS_LABELS[props.order?.address_validation?.status] || ["Not checked", "inactive"])[0]);
const addressBadge = computed(() =>
  (ADDRESS_LABELS[props.order?.address_validation?.status] || ["Not checked", "inactive"])[1]);

const FIELD_LABELS = {
  street1: "Street", street2: "Street 2", city: "City",
  state: "State", postal_code: "Postal code", country: "Country",
};
const fieldLabel = (field) => FIELD_LABELS[field] || field;

const trackStatus = computed(() => {
  const status = shipment.value?.status;
  if (status === "purchased") return "Label bought — not yet scanned";
  if (status === "shipped") return "Marked shipped by you";
  return statusLabel(status || "unknown");
});
</script>

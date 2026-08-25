import { reactive, computed } from "vue";

// The Vue-side realization of the ConversionContext (plans/CONVERSION_CONTEXT.md). It mirrors the server:
// an OfferView projection (targets[]) + mutable page state + read-only `derived` values. Components
// display `derived` and change `page`; they never compute or look anything up.
//
// `targetsRef` is a Ref/computed of the OfferView targets — each: { product_id, price_id, headline,
// subheadline, hero_image, amount, compare_at, discount, currency }. (Same shape the server serializes
// into the conversion payload, so the two renderers stay in lockstep.)
export function useConversionContext(targetsRef) {
  const page = reactive({
    currentTargetIndex: 0,
    selectedPriceId: null,
    quantity: 1,
    couponCode: "",
    locale: null,      // visitor-scoped (geo/IP) — reserved for localized pricing
    currency: null,    // active display currency; may differ from the OfferView base
  });

  const targets = computed(() => (Array.isArray(targetsRef.value) ? targetsRef.value : []));

  const currentTarget = computed(() => targets.value[page.currentTargetIndex] || targets.value[0] || null);

  // Read-only derived values. Components display these and never recompute money.
  const derived = {
    currentTarget,
    unitPrice: computed(() => currentTarget.value?.amount || 0),
    compareAt: computed(() => currentTarget.value?.compare_at || 0),
    currency: computed(() => page.currency || currentTarget.value?.currency || "usd"),
    discountPercent: computed(() => currentTarget.value?.discount || 0),
    ctaLabel: computed(() => currentTarget.value?.cta_label || ""),
  };

  // Bound the index if the target list shrinks (e.g. items removed in the builder).
  const setTarget = (index) => {
    const max = targets.value.length - 1;
    page.currentTargetIndex = Math.max(0, Math.min(max < 0 ? 0 : max, index));
  };

  return { page, targets, derived, setTarget };
}

// Preferred source of truth: the SERVER's expand_offer() output (GET /offers/{id}?expand=1). Consuming it
// directly means the builder preview and the published page price items with ONE implementation — no Vue
// re-derivation that can drift (wrong compare field, sale-vs-default, empty selection -> $0). Maps the same
// ExpandedOffer shape the published conversion island reads.
export function offerViewTargetsFromExpanded(expandedItems) {
  return (expandedItems || []).map((item) => {
    const product = item.product || {};
    const single = (item.pricing || {}).single_unit_price || {};
    const amount = Number(single.unit_amount || 0);
    const compare = Number(single.compare_at_amount || 0);
    const discount = compare > amount && compare > 0 ? Math.round(((compare - amount) / compare) * 100) : 0;
    return {
      product_id: item.kind === "product" ? product.product_id || "" : "",
      service_id: item.kind === "service" ? product.product_id || "" : "",
      price_id: single.price_id || "",
      headline: product.headline || "",
      subheadline: product.subheadline || "",
      hero_image: product.hero_image || "",
      gallery: product.gallery || [],
      badges: product.badges || [],
      amount,
      compare_at: compare,
      discount,
      currency: single.currency || "usd",
    };
  });
}

// Vue mirror of the server's expand_offer() single-unit projection: turn the builder's offer item models
// into OfferView targets. `models` come from offerItemModels() (products + services, already resolved).
// Fallback only — used until the server's ExpandedOffer (offerViewTargetsFromExpanded) has loaded.
export function offerViewTargets(models) {
  return (models || []).map((model) => {
    const cards = [...(model.priceCards || [])];
    const single = cards.find((card) => (card.quantity || 1) <= 1) || cards[0] || {};
    const amount = single.unit_amount || 0;
    const compare = single.compare_at_unit_amount || 0;
    const discount = compare > amount && compare > 0 ? Math.round(((compare - amount) / compare) * 100) : 0;
    return {
      product_id: model.type === "product" ? model.id : "",
      service_id: model.type === "service" ? model.id : "",
      price_id: single.price_id || "",
      headline: model.name || "",
      subheadline: model.description || "",
      hero_image: model.image || "",
      amount,
      compare_at: compare,
      discount,
      currency: single.currency || "usd",
    };
  });
}

// What an order LOOKS like in a list, kept out of the component so the table and the details modal cannot
// describe the same order two different ways. Presentation only -- no fetching, no business rules.

/** `order_cs_test_a17LZKXREG...ThmpvX2VdSpm` -- the ends carry the meaning, the middle never does. */
export function elideId(value, head = 14, tail = 8) {
  const id = String(value || "");
  if (id.length <= head + tail + 1) return id;
  return `${id.slice(0, head)}…${id.slice(-tail)}`;
}

/** "2 × Creatine Gummies" for one line, a count for several -- a cell is not a receipt. */
export function itemsSummary(order) {
  const lines = Array.isArray(order?.line_items) ? order.line_items : [];
  if (!lines.length) {
    const name = order?.product?.name;
    return name ? String(name) : "—";
  }
  if (lines.length === 1) {
    const line = lines[0];
    const quantity = Number(line?.quantity || 1);
    const name = String(line?.name || "Item");
    return quantity > 1 ? `${quantity} × ${name}` : name;
  }
  const units = lines.reduce((total, line) => total + Number(line?.quantity || 1), 0);
  return `${units} items in ${lines.length} lines`;
}

/** City and state is what identifies a destination at a glance; the street never fits. */
export function destinationSummary(order) {
  const address = order?.shipping_address;
  if (!address) return "";
  const city = String(address.city || "").trim();
  const state = String(address.state || "").trim();
  const postal = String(address.postal_code || "").trim();
  const country = String(address.country || "").trim().toUpperCase();
  const locality = [city, state].filter(Boolean).join(", ");
  const line = [locality, postal].filter(Boolean).join(" ");
  // The country only earns its space when it is NOT the common case, which keeps the column narrow and
  // makes the exception -- the order we cannot label yet -- the thing that stands out.
  return country && country !== "US" ? `${line} (${country})` : line;
}

export function orderStatus(order) {
  return order?.payment_status || order?.status || "paid";
}

export function statusBadgeClass(status) {
  return {
    paid: "active",
    completed: "active",
    partially_refunded: "warning",
    refunded: "inactive",
    disputed: "archived",
    cancelled: "archived",
  }[status] || "inactive";
}

/** Sort comparators. `created_at` is a STRING of epoch seconds on an order, so compare it numerically. */
export const SORTERS = {
  created_at: (a, b) => Number(a?.created_at || 0) - Number(b?.created_at || 0),
  amount_total: (a, b) => Number(a?.amount_total || 0) - Number(b?.amount_total || 0),
  customer: (a, b) => String(a?.customer?.name || a?.customer?.email || "")
    .localeCompare(String(b?.customer?.name || b?.customer?.email || "")),
};

export function sortOrders(orders, key, direction) {
  const compare = SORTERS[key] || SORTERS.created_at;
  const sorted = [...(orders || [])].sort(compare);
  return direction === "asc" ? sorted : sorted.reverse();
}


/**
 * A short reference a person can actually say out loud — "order b13b4Un3".
 *
 * The SERVER computes the real one (domain/order_reference.py), across the tenant's whole set, so it can
 * guarantee uniqueness — which this cannot, seeing one order at a time. This stays as the fallback for an
 * order that reached a component without passing through the list endpoint.
 *
 * Derived, never stored: it is a SUBSTRING of the real id, taken from Stripe's own random part, so
 * pasting it into the search box still finds the order. A hash would be shorter and prettier and would
 * lose exactly that.
 *
 * The full id stays the record. This is the label on it.
 */
export function shortOrderRef(orderId) {
  const id = String(orderId || "");
  if (!id) return "";
  // order_cs_test_<random>  /  order_cs_live_<random>  /  order_in_<random>
  const match = id.match(/^order_(?:cs_(?:test|live)_|in_|pi_)?([A-Za-z0-9]+)/);
  const core = match ? match[1] : id.replace(/^order_/, "");
  const head = core.slice(0, 8) || id.slice(0, 8);
  // A post-purchase order shares its parent's session id, so without the suffix an upsell and the
  // purchase it followed would show the SAME reference.
  const upsell = id.match(/_upsell_(\d+)$/);
  return upsell ? `${head}-U${upsell[1]}` : head;
}

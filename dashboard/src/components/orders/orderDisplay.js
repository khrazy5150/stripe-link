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

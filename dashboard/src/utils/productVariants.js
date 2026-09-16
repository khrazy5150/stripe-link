/**
 * The shape of one size or colour variant row.
 *
 * Shared because two places create them and they must agree: the variants FIELD (a tenant adding a row) and
 * the form HYDRATION that reads a saved product back, where a legacy string variant is widened into the same
 * object. A second definition would drift the day one of them gains a field.
 *
 * `form_id` is a client-only key for `v-for` — variants have no server id, and keying on the label would
 * re-create every row the moment someone typed in one.
 */
export function variantFormId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function defaultSizeVariant() {
  return { form_id: variantFormId("size"), label: "", description: "" };
}

export function defaultColorVariant() {
  return { form_id: variantFormId("color"), label: "", hex_color: "#000000", description: "" };
}

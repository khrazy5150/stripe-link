// The glyph for a lead-capture action, shared by every screen that shows a lead-gen product.
//
// It lived inside Products.vue, so the Offers selector rendered the same product as a bare initial on a
// tinted square while the Products list showed an envelope or a share graph. The tenant then had to pick
// their product by remembering its first letter -- reported 2026-09-10 with a screenshot of the two
// screens side by side.
//
// The COLOUR is deliberately not here: it comes from idColorStyle(), keyed on the product, so two
// products sharing an action (two link-in-bio pages, say) stay distinguishable. Icon says WHAT the
// product does; colour says WHICH product it is.
import { h } from "vue";

const PATHS = {
  capture_email: "M4.5 6.75h15v10.5h-15V6.75Zm0 0L12 12l7.5-5.25",
  capture_phone: "M7.5 4.5h3l1.5 4-2 1.25a10 10 0 0 0 4.25 4.25l1.25-2 4 1.5v3a2 2 0 0 1-2.25 2c-7-.5-12.25-5.75-12.75-12.75A2 2 0 0 1 7.5 4.5Z",
  capture_email_phone: "M7.5 4.5h9v15h-9v-15Zm2.25 3h4.5m-4.5 3h4.5m-4.5 3h2.25",
  call_number: "M7.5 4.5h3l1.5 4-2 1.25a10 10 0 0 0 4.25 4.25l1.25-2 4 1.5v3a2 2 0 0 1-2.25 2c-7-.5-12.25-5.75-12.75-12.75A2 2 0 0 1 7.5 4.5Zm7.5 1.5a4.5 4.5 0 0 1 3 3m-3-5.25A6.75 6.75 0 0 1 20.25 9",
  external_url: "M8.25 8.25h-3v10.5h10.5v-3m-4.5-3 7.5-7.5m0 0h-4.5m4.5 0v4.5",
  // A calendar with a seat marked: registering is capturing, plus a date.
  register_event: "M6.75 3.75v3m10.5-3v3M4.5 8.25h15m-15 0v10.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V8.25m-15 0h15M9.75 13.5l1.5 1.5 3-3",
  // A numbered stack: rows with a leading marker, which is what a Roundup renders.
  roundup: "M4.5 6.75h2m-2 5.25h2m-2 5.25h2M9.75 6.75h9.75M9.75 12h9.75M9.75 17.25h9.75",
  social_redirect: "M7.5 12a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Zm13.5-5.25a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Zm0 10.5a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0ZM7.1 11l9.3-3.25M7.1 13l9.3 3.25",
};

export function leadActionIcon(action) {
  const d = PATHS[action];
  if (!d) return null;   // not a lead-gen product: the caller falls back to its initial
  return {
    render() {
      return h("svg", {
        fill: "none", stroke: "currentColor", viewBox: "0 0 24 24",
        class: "product-card-placeholder-icon", "aria-hidden": "true",
      }, [h("path", { "stroke-linecap": "round", "stroke-linejoin": "round", "stroke-width": "2", d })]);
    },
  };
}

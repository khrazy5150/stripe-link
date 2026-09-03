# Brand Marquee — text-or-logo social proof, with scroll and speed control

**Status:** PLANNED, not built. An ENHANCEMENT of the existing `client_marquee` element, not a new one.

## 1. What exists today

`client_marquee` is registered, rendered (`render_client_marquee`, html.py) and editable in the builder:
a heading plus rows of `{name, image_url}`, with a per-row logo upload.

Two behaviours are already right and must survive:

- **Auto-scroll at ≥5 logos**, static below. A sensible default that nobody has to configure.
- The row is duplicated with `aria-hidden` on the copy, so the scroll is seamless and screen readers hear
  the list once.

## 2. Gap 1 — text-only entries are silently DROPPED (a bug, not a missing feature)

    logos = [logo for logo in (section.get("logos") or []) if str(logo.get("image_url") or "").strip()]

A tenant who types "YouTube" and uploads nothing gets **nothing rendered and no warning**. The builder even
labels `name` as *"only visible by search engines"*, so the field reads as alt text rather than content.
The legacy stripe-cart marquee was text-only, so today's element cannot reproduce what it replaced.

**Fix:** `name` becomes the entry — it always renders. `image_url` becomes the optional upgrade that
renders *instead of* the text when present. An entry with neither is what gets dropped.

## 3. Gap 2 — scrolling should be a choice, in THREE states

`Auto (default) · Always scroll · Never scroll`.

Two states would force a migration decision that breaks something either way: default "scroll" and a page
with two logos starts crawling; default "static" and a page with eight stops. **`auto` preserves the ≥5
rule exactly, so no existing page changes** — the same reasoning as "no goal = old behaviour" in the
composition work.

## 4. Gap 3 — speed control, reusing the countdown's

The countdown banner already solved this and the pattern should be copied, not re-derived:

| Piece | Where it already lives |
|---|---|
| Stored value | `marquee_seconds` on the document, "lower = faster", renderer clamps 3–60 |
| CSS | a duration custom property consumed by the keyframe animation |
| UI | 🐢 — range — 🐇, with the slider INVERTED so left = slower (`MIN + MAX - seconds`) |

The inversion is the non-obvious part: a raw duration slider runs backwards to a human (dragging right
would slow it down). Reuse `MARQUEE_MIN_SECONDS`/`MARQUEE_MAX_SECONDS` and the same computed-getter trick.

**Watch for:** the countdown's keyframe was once named `sl-marquee` and collided with this element's,
silently breaking one of them. Whatever animation this uses must keep its own name.

## 5. Theming — text as wordmarks, not fake logos

`.sl-marquee-logo` sets `background:#ffffff` with padding and a shadow — a white card. That is right for a
logo and wrong for a name: a text entry in a white card looks like a logo that failed to load.

**Text renders as a themed wordmark** using the page's own tokens (weight, letter-spacing, `--sl-muted` or
the heading colour), so it belongs to the design rather than sitting on a foreign card.

### The open decision: what backs a LOGO

The white card exists for a reason — a dark logo on a dark preset (tiktok-dark, midnight-luxe) is invisible
without it. But the card clashes with the page's look, which is the author's objection.

Transparent PNGs **do not solve this**: transparency removes the box around the mark, it does not lighten
dark ink.

Recommended: a per-marquee **logo backing** choice — `Card (default) · None` — defaulting to today's card
so nothing changes for existing pages, with `None` for tenants whose logos suit their theme. Same
migration-safe shape as the scroll control.

Deferred: a `monochrome` treatment (grayscale + opacity, full colour on hover) is the common way sites
sidestep this entirely, and would make mixed rows uniform. Worth doing once the basics are in.

## 6. Guidance, not enforcement — transparent PNGs

The builder should **recommend** transparent PNG logos inline, near the upload control, because they are
what looks right across every preset. It must not enforce it: a tenant with a JPEG should still get a
working marquee, and blocking an upload over a file format would be a notice with no action behind it
(see the notices-only-when-actionable rule).

## 7. Build steps

1. **Renderer accepts text.** `name` renders as a wordmark; `image_url` renders instead when present; an
   entry with neither is dropped. Keep the duplicated-row + `aria-hidden` scroll structure.
2. **Wordmark styling** from theme tokens, and the `logo_backing` option (`card` default / `none`).
3. **`scroll_mode`** — `auto` (default, the ≥5 rule) / `always` / `never`.
4. **`marquee_seconds` + the 🐢/🐇 slider**, reusing the countdown's constants, inversion and clamp.
5. **Builder copy** — relabel `name` (it is content now, not just SEO alt text) and add the transparent-PNG
   recommendation by the upload button.
6. **Tests** — a text-only entry renders (the bug), a mixed row renders both kinds, `auto` still switches at
   5, `always`/`never` override it, and the speed slider round-trips through the inversion.

## 8. Relationship to the Page Ribbon

Both are social-proof / attention surfaces and will be built in the same pass, but they are different
things: the Ribbon **asks** (it carries a CTA — see ATTENTION_PRIMITIVE.md §4a), the Marquee **reassures**
(it carries no action). They should not be merged.

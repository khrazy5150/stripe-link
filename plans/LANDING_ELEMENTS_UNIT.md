# Landing elements unit — the build sequence and its shared step 0

**Status:** PLANNED, not built. Six elements to build as one unit.

## The unit

| # | Element | Job | Carries an action? | Plan |
|---|---|---|---|---|
| 1 | Page Ribbon | asks | **yes** — a CTA | ATTENTION_PRIMITIVE.md §4a |
| 2 | Price Highlight | reframes value | no | PRICE_HIGHLIGHT.md |
| 3 | Author Bio | establishes authority | no | AUTHOR_BIO.md |
| 4 | Bragging Points | quantifies the claim | no | AUTHOR_BIO.md §4a |
| 5 | Quote | lends a idea weight | no | §Quote below |
| 6 | Numbered List | enumerates (benefits OR steps) | no | §Numbered List below |
| 7 | Brand Marquee | reassures | no | BRAND_MARQUEE.md (enhancement) |

## ⭐ Step 0 — the section-scoped theme override

**FOUR of the six want to break the page preset**: Author Bio (background + image border), Bragging Points
(section background), Quote (background + vertical bar), and the Ribbon. Built per element that is four
implementations of one idea — the failure this codebase has produced with slug rules, funnel roles, entry
readers and chips, all within one session.

So it is step 0, not a per-element field.

### The Quote sharpens its shape

Author Bio and Bragging Points want a **background**. Quote wants a background AND an **accent** (the
vertical bar). So the override cannot be a `bg` field — it must be a **token map**:

    section.theme = { bg: "#1e1033", accent: "#f97316", border: "#ffffff" }

Any token the element declares may be overridden; anything absent falls through to the preset. That is the
same shape `plans/ADVANCED_COLOR_SETTINGS.md` proposes at page level, one scope down.

### The safety rule, restated because it applies to all four

**Foreground is DERIVED from the chosen background by luminance — never taken from the preset, never
authored.** The legacy offers background pickers with no text colour, so the ink keeps coming from the
theme: a dark background on a light-text preset makes the text invisible, silently. Deriving it makes the
tenant's choice a single decision that cannot produce an unreadable result, and is better than a
text-colour picker, which would let them choose black on black.

Default for every element: **follow the preset**, so nothing existing changes.

## Quote

A pull-quote with a vertical accent bar.

    ┃  "Marketing is no longer about the stuff that you make,
    ┃   but about the stories you tell."
    ┃                                        — Optional Attribution

- **Fields:** `text`, `attribution` (optional — the author's addition; the legacy has none), plus the
  optional `section.theme` overrides for background and bar.
- **Not repeatable.** A second pull-quote halves the weight of the first.
- **`free` placement.**

### It is not `testimonials`

`testimonials` carries a customer's endorsement — someone vouching for the product. A pull-quote carries an
**idea**: a maxim, a principle, the tenant's own line. Different jobs, and they should look different, so a
quote is not mistaken for an endorsement nobody gave. That is a styling obligation, not a warning: the
element already exists for endorsements.

## Numbered List (legacy: "Benefit List")

A section title plus an ordered list of authored lines, each on a card with a numbered badge.

    **What's Inside** The Course

    (1)  Learn All About Successful Social Media Marketing
    (2)  Implement the Knowledge for Yourself or Your Business
    (3)  Understand Secrets Behind Successful Influencers

- **Fields:** `heading`, `items[]` (plain strings), cap 12 as the legacy has.
- **Not repeatable** as an element; the list inside it is what repeats.
- **`free` placement.**
- The heading uses `render_headline_markup`, which **already** supports the legacy's two forms —
  `**coloured**` and `^^highlighted^^` — so there is no new parser and it behaves like every other heading.

### One element, not two — benefits AND steps

"How it works" steps were on the wanted-elements list separately. They are this component: a numbered badge
beside a line of authored text. The only difference is the title the tenant types — *What's Inside* versus
*How It Works* — which is content, not structure.

Building them separately means two visually identical elements and a tenant wondering which to pick. Same
argument as Bragging Points and the stats band, which was accepted. **Name it for the shape
(`numbered_list`), not for one of its uses**, so neither framing is privileged.

### Not `faq`, not `product_details`

`faq` is expandable Q&A — the visitor chooses what to open. This is a flat list they read. `product_details`
renders a gallery and badges from PRODUCT data; this is authored page copy. Checked, not assumed.

## Build order

0. **Section-scoped theme override** + derived foreground. Nothing visible ships; three elements depend on it.
1. **Price Highlight** — no override, no CTA. Smallest surface that exercises the derived-price path, so a
   wrong reading of the pricing model surfaces cheaply.
2. **Author Bio** — first override consumer.
3. **Bragging Points** — second consumer; near-free if step 0 is right, and the proof that it is.
4. **Quote** — third consumer, and the one that needs `accent` as well as `bg`.
5. **Numbered List** — no override, reuses the existing heading markup; the simplest of the six.
6. **Brand Marquee** — the silent text-drop bug, three-state scroll, speed slider.
7. **Page Ribbon** — largest, and the only one with CTA plumbing.

Risky decisions first, biggest element last, and each override consumer validates step 0 before the next
one depends on it.

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

## ⭐ Step 0 — the section-scoped theme override — **BUILT 2026-09-02**

`domain/section_theme.py` + `tests/test_section_theme.py`. Emits `--sl-section-bg` / `-accent` / `-border`
plus a DERIVED `--sl-section-ink`, namespaced so a section override can never collide with a page token and
an element must opt in explicitly (`var(--sl-section-bg, var(--sl-background))`). Unknown keys and
unparseable colours are dropped rather than echoed into a style attribute.

**Two things the measurements changed, neither visible in the code:**

- The first version thresholded luminance at 0.42 to choose the ink. It picked the WORSE ink for orange,
  mid-grey and green — three of ten test colours. Computing the contrast for both candidates and taking the
  higher is exact and has no number to tune.
- The ink pair was chosen for looks (`#111827` / `#f8fafc`) and the softened white dropped the worst case to
  **4.49:1** on mid-grey, just under WCAG AA. Pure white holds **4.83:1** and clears AA on every background
  tried, while the dark ink can stay near-black for free. Measured, not preferred.

The whole promise of this feature is "pick one colour, get readable text", so a pair that fails AA anywhere
would have quietly broken it.

**A third correction, found in review of Author Bio:** deriving an ink for the section BACKGROUND was not
enough. The name pill is painted with the BORDER colour and had its text hardcoded white, so a white photo
ring made the name invisible — the very failure this mechanism exists to prevent, reintroduced one surface
along. Every tenant-colourable surface now derives its own ink (`--sl-section-ink`, `-accent-ink`,
`-border-ink`), so an element that paints with `accent` or `border` gets readable text for free rather than
having to remember.

### Original design notes

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

- **Fields:** `text`, `attribution` (optional — the author's addition; the legacy has none), `title` and
  `image_url` (both optional, added 2026-09-03), plus the optional `section.theme` overrides.
- **Two presentations** (added 2026-09-03), `style: minimal | fancy`:
  - `minimal` (DEFAULT) — vertical bar, italic type. Quiet enough to sit inside body copy.
  - `fancy` — a coloured card, the image beside the quote, and a large opening quotation mark.
- **The override token means the same thing in both but paints a different surface**: `accent` is the BAR
  in minimal and the CARD in fancy. That is why `--sl-section-accent-ink` matters more in fancy, where
  text sits ON the accent: the reference design's white-on-pink falls out of the contrast maths, so a PALE
  card gets dark text instead of the white the reference happened to hardcode. Same for the opening
  quotation mark, which takes currentColor at low opacity rather than the reference's fixed blue.
- **No media query.** The fancy card is flex-wrap with a basis on each part, so the photo and the words
  stack themselves on a phone.
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
1. **Price Highlight** — ✅ BUILT 2026-09-02. Derived numbers, no CTA, `as low as` for tiers, renders
   without a strikethrough when there is no discount rather than rendering nothing.
2. **Author Bio** — ✅ BUILT 2026-09-02. First override consumer; the derived ink works end to end.
3. ~~**Bragging Points**~~ — **SHIPPED 2026-09-03.** Second consumer, and step 0 held: it colours a
   different surface (cards, not a photo ring) and inherited the derived-ink guarantee with no
   element-specific contrast code. Reflow is pure CSS — the grid caps at two columns and a lone trailing
   card spans the row, so 1 is one wide and 3 read 2 + 1 without the markup knowing the count.
4. ~~**Quote**~~ — **SHIPPED 2026-09-03.** Third consumer, and the first to use `accent` as a visible
   BAR rather than a background or a card fill. figure/figcaption so the attribution sits outside the
   blockquote; a typed dash is absorbed rather than doubled.
5. **Numbered List** — no override, reuses the existing heading markup; the simplest of the six.
6. **Brand Marquee** — the silent text-drop bug, three-state scroll, speed slider.
7. **Page Ribbon** — largest, and the only one with CTA plumbing.

Risky decisions first, biggest element last, and each override consumer validates step 0 before the next
one depends on it.


## Element descriptor refactor — DECLINED 2026-09-02

Considered collapsing the five per-element registration points (catalog, renderer, SECTION_REGISTRY,
`elementSection`, `elementsFromPage`) into one descriptor per element. **Not doing it.**

The failure it would prevent — forgetting a registration — is already caught by
`tests/test_element_registration.py`, which fails loudly on a miss and was verified against the real
`price_highlight` bug. What remains is ergonomics, and the refactor would mean touching working serializers
for eight live elements to buy it.

These elements are also used in exactly ONE builder. A registry abstraction earns its keep when several
consumers must agree; here there is one, and the builder is otherwise robust. Knowing where to register is
sufficient, and the test enforces that knowledge.

Generation was never the right target regardless: seven elements carry per-element emptiness policy, three
filter incomplete sub-items, and `content_block` expands one section into several elements on restore.
A schema expressing that would be a small programming language.

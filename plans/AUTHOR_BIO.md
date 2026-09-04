# Author Bio — credibility block, with an optional pattern break

**Status:** BUILT 2026-09-02. `render_author_bio` + registry entry `author_bio`, first consumer of
the step-0 section override. Bragging Points (§4a) SHIPPED 2026-09-03.

## 1. What it is

A fixed-structure credibility block, placed mid-scroll:

    ( photo )        ← circular, bordered, centred
    [ NAME ]         ← pill
    Credibility headline, **highlights** supported
    Paragraph

The structure is the element. Unlike `content_block` — image beside text, tenant-arranged — the order here
is fixed because it encodes the argument: *this is a person → here is their name → here is why they are
worth listening to → here is the detail.* Letting a tenant rearrange it would let them break it.

## 2. Distinct from the two nearby things — checked, not assumed

| Element | Job | Why not this |
|---|---|---|
| `seller_profile` (exists) | store identity on a STOREFRONT page | `ui: internal`, not tenant-addable to a landing page |
| `profile_avatar` (planned, SOCIALITE_PARITY.md) | a face overlaying the HERO on service offers | different placement, and it is an avatar not an argument |

**Composition note:** on a service page a tenant could enable both `profile_avatar` and Author Bio and show
the same face twice. Not a blocker and not worth a rule — worth a builder hint if it turns up in practice.

## 3. The pattern break — the interesting half

The element may override the page preset: a Rose Minimalist page (white) can carry a black Author Bio to
create contrast. **Default is to follow the preset**, so an existing page never changes and a tenant who
wants nothing gets the theme.

### Build it as a SECTION-scoped override, not two fields on this element

No section-level override mechanism exists today; overrides are page-level (`page.theme.overrides`, and
plans/ADVANCED_COLOR_SETTINGS.md extends that idea per token).

The temptation is two colour pickers hardcoded onto Author Bio. The second element that wants a pattern
break then gets its own pair, and there are two implementations of the same idea — the failure this
codebase has produced repeatedly (slug rules, funnel roles, entry readers, chips).

So: a small, general `section.theme` map that any element may carry, with Author Bio as its first consumer.
Cheap now, and the next pattern-breaking element is configuration rather than code.

### ⚠️ Overriding a background alone creates invisible text

This is the real hazard, and the legacy implementation has it. It offers **background** and **image border**
pickers but no text colour — so the text keeps coming from the preset. Set a dark background on a
light-text theme, or a light background on a dark-text theme, and the paragraph disappears. Nothing warns.

**The foreground must be DERIVED from the chosen background**, not left to the preset and not left to the
tenant. Compute the background's relative luminance and pick the light or dark ink accordingly — the same
WCAG contrast maths already used to size up the funnel badge colours (commit `c9750ad` era).

That makes the tenant's choice a single decision — "what colour is this block?" — that cannot produce an
unreadable result. It is also strictly better than exposing a text-colour picker, which would let them
choose black on black.

The image border stays a separate optional pick; it is decoration and cannot hide content.

## 4. Shape

- **Not repeatable.** One author per page. Two credibility blocks argue against each other.
- **`free` placement** — mid-scroll, tenant-dragged.
- **Fields:** `photo`, `name`, `headline` (supports `**highlight**` markup like other headings), `body`,
  and optionally `section.theme.bg` + `section.theme.border`.

## 4a. Bragging Points — a SEPARATE element (decided)

Repeatable `{value, label}` pairs rendered as cards that reflow: one wide, two side by side, three as
2 + 1. The value is large and accented, the label muted beneath it. The third example in the author's
screenshots — `Q-Media / Founder and CEO` — is not a number, so the pair is free text, not a metric type.

### Why separate, despite reading as an extension of the bio

The author called it an extension of Author Bio, and semantically it usually is. But the same component is
the **stats band** already on the wanted-elements list ("10,000 customers served") — a claim about the
product or business, with no author involved.

Locked inside Author Bio, a tenant who wants company stats and no bio cannot have them, and the stats band
gets built a second time. As its own element it serves both, and the common case — sitting directly under
Author Bio — is just where the tenant drags it.

**DECIDED 2026-09-02: standalone**, `repeatable: false` with a repeatable list of pairs inside it. It is the
stats band and the author's brag with one implementation; adjacency to Author Bio is the tenant's choice,
not a structural coupling.

### It is the SECOND consumer of the section-scoped theme override

The legacy gives Bragging Points its own **Section Background Color**, exactly as Author Bio has one. That
is the argument in §3 confirmed before a line is written: two elements wanting the same pattern-break
mechanism. Building it as two hardcoded colour fields would already have produced the duplication this
codebase keeps paying for.

Same derived-foreground rule applies — a background chosen without its ink is how text disappears.

### Layout

The reflow is the only structural decision: `1 → one wide`, `2 → two columns`, `3 → 2 + 1`, `4+ → rows of
two`. A CSS grid with `auto-fit` and a sensible min width does this without JavaScript and without the
element needing to know how many pairs it has.

## 5. Build steps

1. Registry entry (`ui: add`, `repeatable: false`, tokens for heading/text/pill).
2. `render_author_bio` — fixed structure, `render_headline_markup` for the headline so `**highlights**`
   behave as they do elsewhere.
3. Section-scoped `theme` override plumbing (general), applied as inline custom properties on the section.
4. Derived foreground from background luminance, with a test asserting a dark background yields light ink
   and vice versa — the property that makes the override safe.
5. Builder editor: photo upload, three text fields, and the optional background/border pickers behind a
   "break the page style" toggle so the default path stays one click away from nothing.
6. Tests: default follows the preset; an override changes only that section; contrast holds both ways.

## 6. Position in the unit

| Element | Job | Action? |
|---|---|---|
| Page Ribbon | asks | yes |
| Price Highlight | reframes value | no |
| Author Bio | establishes authority | no |
| Bragging Points | quantifies the claim | no |
| Brand Marquee | reassures | no |

Author Bio and Brand Marquee are both social proof, but of different kinds — *who made this* versus *who
else bought it* — and they are strongest apart on the page rather than adjacent.

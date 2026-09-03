# Author Bio — credibility block, with an optional pattern break

**Status:** PLANNED, not built. A NEW element.

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
| Brand Marquee | reassures | no |

Author Bio and Brand Marquee are both social proof, but of different kinds — *who made this* versus *who
else bought it* — and they are strongest apart on the page rather than adjacent.

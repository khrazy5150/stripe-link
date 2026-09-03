# Price Highlight — a standalone bargain block

**Status:** PLANNED, not built. A NEW element (legacy name: "Price & Urgency").

## 1. What it is

A display block that appears mid-scroll, after the visitor has read about the product, and does one thing:
show the bargain.

    Regular Price: $49          ← struck through, DERIVED
             $37                ← the sale price, DERIVED
          Today Only            ← main text, AUTHORED
        Lifetime Access         ← subtext, AUTHORED

**It carries no action.** That is deliberate and worth stating: `checkout_cta` is the ask, and this is a
pause that reframes value on the way there. Adding a button would make it a second CTA, and
`checkout_cta` is non-repeatable precisely because one ask converts better than two.

## 2. Why it is its own element, not part of `offer_price_selector`

The price selector is the interactive tier chooser wired to checkout. This is a static block of page copy
that happens to contain a number. Different job, different placement, different repeatability — the same
reasoning that keeps `content_block` separate from `hero`.

## 3. Where the numbers come from — DERIVED, never authored

Prices are catalog data. The tenant authors only the two lines of copy.

| Shown | Derived from |
|---|---|
| sale price | the offer's resolved `subtotal` — what the customer actually pays |
| regular price | sum of each resolved item's `compare_at_amount × quantity`, falling back to that item's line amount where it has no compare-at |

`resolve_offer` already normalizes `compare_at_amount` per item (pricing.py) — reading
`compare_at_unit_amount` with a legacy fallback — so no new pricing logic is needed, only the sum.

**Degradation, explicitly:** if the regular total is not greater than the sale total there is no bargain to
show, so the block renders the price and the copy **without** a strikethrough. It must never render
nothing — silently dropping content when a field is absent is the exact bug the Brand Marquee has today.

## 4. ⚠️ The open decision: tiered prices, and disagreeing with the selector

If the landing item is tiered, the price depends on which tier the visitor has selected — and this block is
static HTML. So a page carrying BOTH this block and the price selector can show two different prices at
once, which is worse than any styling problem.

Two options:

- **(a) Default tier, static.** Simple; the block can disagree with the selector the moment a visitor picks
  another tier.
- **(b) Sync with the selector.** The published page already carries `data-sale-amount` /
  `data-regular-amount` on each `.sl-price-option` and a price-context script, so the hook exists. The block
  subscribes and re-renders its two numbers on selection.

**Recommended: (b).** Two prices on one page is a correctness problem, not a polish one, and the machinery
is already there. Fall back to the default tier when the selector is not on the page.

## 5. Theming — reuse the price tokens, add none

"Match intelligently with the preset" is already solved: `offer_price_selector` declares
`price_amount`, `price_regular`, `price_title`, `price_description`, `savings_bg`, `savings_text`,
`savings_border`. **Reuse those.** Every preset already defines them, so this element is themed on day one
with no new token catalogue entries and no per-preset work — and it cannot drift from the price card
beside it, because they read the same values.

The authored lines map to `price_title` (main) and `price_description` (subtext); the numbers to
`price_amount` and `price_regular`.

## 6. Shape

- **Not repeatable.** One bargain block per page; two would read as a mistake.
- **`free` placement**, so the tenant drags it to where the argument has landed.
- **Fields:** `main_text`, `subtext`. Nothing else — the numbers are not the tenant's to type.

## 7. Build steps

1. Registry entry (`placement: free`, `ui: add`, `repeatable: false`, tokens reused from the price element).
2. `derived_bargain(offer, products)` — sale total, regular total, and a flag for whether a bargain exists.
   Pure, testable, no rendering.
3. `render_price_highlight` — strikethrough only when a bargain exists; copy always renders.
4. Builder editor: two text fields, plus a hint that the numbers come from the product's sale/regular
   prices and are not editable here.
5. Selector sync (§4b), with the default-tier fallback.
6. Tests: no compare-at renders without a strikethrough; a mixed bundle sums correctly; the tiered case
   agrees with the selector.

## 8. Relationship to the other new elements

Three surfaces, three jobs, deliberately not merged:

| Element | Job | Carries an action? |
|---|---|---|
| Page Ribbon | asks | yes — a CTA |
| Brand Marquee | reassures | no |
| Price Highlight | reframes value | no |

**Worth watching:** the page now has a countdown timer, a flash-sale context and this urgency copy. They
are not redundant — a timer is a deadline, this is a claim — but all three at once reads as pressure rather
than persuasion. A builder hint, not a rule; it is a taste call and the tenant's to make.

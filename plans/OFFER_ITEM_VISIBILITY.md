# Offer item visibility — cards and search

**Status:** PLANNED, not built. HIGH priority.

## 1. The problem, as a tenant hits it

A tenant adds a Protein Shaker Bottle as an order bump, then goes looking for it later. It is not on the
offer card, and search does not match it. The only way to find it is to open every offer and read its
Purchase Flow diagram. With a dozen offers that is tedious; with a hundred it is impossible.

The same is true of `Whey Protein`, which is a plain landing item — so this is not only about bumps.

## 2. What was verified (not assumed)

Reading the real `Workout Bundle` document out of `jb-offers-dev`:

    items[]                 -> 3 products (LANDING ONLY)
    purchase_opportunities  -> stage=landing        x3   group=main_offer
                               stage=checkout       x1   group=order_bump      (Protein Shaker)
                               stage=post_purchase  x1   group=upsell          (NAD, a duplicate)

So `items[]` is a landing-only projection. Anything reading it to answer "what is in this offer" will
under-report by design. `purchase_opportunities` is the complete list, and it carries `stage` + a
`placement.group` that names the role.

Search coverage today, measured:

| Screen | Searches | Misses |
|---|---|---|
| Offers | `name`, `slug`, `offer_type`, `product_intent` | every item name, landing or funnel |
| Landing Pages | `name`, `page_id`, `offer_id`, `route.slug`, template, `status` | the offer's NAME, and every item name |
| Products | its own name/tag/category/keyword | — (it IS the entity) |
| Services | its own name/description/id | — (it IS the entity) |

**The pattern:** a list screen searches the fields of its own document and never the entities that
document REFERENCES. Products and Services are fine because they are the entity. Offers and Landing Pages
both point at other things, and neither can see through the pointer. Fixing only the offer card would
leave the identical hole one screen over.

## 3. Card display

Do NOT flatten every stage into one list. `Creatine Gummies, NAD Supplement, Whey Protein, Protein Shaker
Bottle` reads as four products on the landing page, which is wrong exactly when the tenant is trying to
work out what the offer is. Landing items are the offer's primary meaning; bumps and upsells are
conditional on a purchase that has not happened yet.

    Items: Creatine Gummies, NAD Supplement, Whey Protein · 1 bump

- Names for landing items (already shipped: names, 3-name cap, 90-char backstop, dedupe, title tooltip).
- A role-labelled COUNT for non-landing stages, from `placement.group` (`order_bump` -> "bump",
  `upsell`/`downsell` -> "upsell"/"downsell").
- Count only products **not already named**. The NAD upsell is a duplicate of a landing item, so the
  Workout Bundle reads `1 bump`, never `2`.
- The hover title carries the full breakdown by role, so nothing is hidden, only collapsed.

## 4. Search

Extend `offerSearchText()` to include every item name across ALL stages plus the ids (an id is still a
legitimate thing to paste). Same for the Landing Pages filter: add the offer's name and its item names.

Then fix the placeholders, which currently promise less than they should deliver:
`Name, slug, type...` -> `Name, slug, product...`.

**Requires the catalog to be loaded client-side.** The Offers list now loads products + services on mount
(shipped with the card-names change; it also revived `offerImage`'s long-dead product-image fallback).
Landing Pages needs the same before its search can resolve names.

**Scaling limit, stated honestly:** this is client-side filtering over the full tenant list, which is how
every list screen here already works. It is fine at hundreds of offers and wrong at tens of thousands. The
day that matters, search moves server-side — that is a different plan, and nothing here blocks it.

## 5. Phases

1. **Card role counts.** Read `purchase_opportunities`, append the deduped role-labelled count. Offers only.
2. **Offer search through items.** `offerSearchText()` + placeholder.
3. **Landing Pages parity.** Load the catalog on mount; add offer name + item names to the filter.

Each phase stands alone and ships independently.

## 6. Deliberately out of scope

- Server-side search (see the scaling note).
- Showing funnel items in the offer card's IMAGE logic — the landing product is the right hero.
- Any change to `items[]` itself. It is a legitimate landing-only projection; the fix is to read
  `purchase_opportunities` when the question is "everything in this offer", not to redefine `items`.

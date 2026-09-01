# Goal seeding, placeholder content, and capability packs

**Status:** packs SHIPPED (paid_ads); placeholder seeding + publish guard NOT BUILT.

## 1. What already existed

Goal composition was already wired end to end before this plan: `composition_rules.json` maps
goal -> packs -> `seeds` (content elements pushed into builder state) and `sections` (governed sections
turned on). `seedGoalElements()` runs at page creation. `search_seo` already seeds an FAQ **and** turns on
`structured_data` — so "SEO needs FAQ + structured data" was done, not pending.

The only gap was that seeds are **empty scaffolds**. This plan is about filling them safely.

## 2. Placeholder seeding — the rule

Prefill **the tenant's own claims**. Never prefill **other people's**.

| Seed with placeholder copy | Never seed |
|---|---|
| `faq`, `content_block`, headline/subheadline scaffolds | `testimonials`, `rating`, `client_marquee` |

A fabricated testimonial that publishes unedited is not untidy, it is an FTC exposure
(16 CFR Part 465, in force since Oct 2024, explicitly covers testimonials from people who do not exist).
Fake client logos add a trademark problem. This also contradicts a rule this codebase already set: the
renderer emits derived Product/FAQPage JSON-LD but **never AggregateRating, because hand-typed = fabricated**.

### If social proof IS seeded anyway (the author's variant, and it is a good one)

Obviously-useless content — "Some Guy's Name", "Some cool testimonial that really stands out", and a
**generic non-photo avatar** (a stock photo of a real human is worse than the text: it fabricates a
likeness). This moves the risk from *legal* to *quality*: nobody is deceived, the page just looks
unfinished. Then add the guard:

- Seed those items with `placeholder: true`.
- Clear the flag on any tenant edit. **Use the flag, not string-matching the seed text** — matching breaks
  the moment someone changes one word, and the guard then fails silently.
- At publish: **hard-block** on `testimonials`/`rating` still flagged; **soft-warn** for everything else.
- Note that `builderSections()` currently drops still-empty elements on save. Filling them REMOVES that
  safety net — the flag is what replaces it.

### Warning copy

Shown once on first edit of a social-proof element, not nagging.

**Make it accurate, not inflated.** The real consequences are frightening enough, and an overstated
warning is worse than none: the first tenant who knows it is exaggerated discounts every warning the
product ever shows them. Specifically — **do not claim imprisonment.** FTC enforcement here is civil, and
a false legal threat is both wrong and corrosive to trust.

What is true and worth saying:
- Civil penalties **per violation**, in the tens of thousands of dollars (the FTC maximum is inflation-
  adjusted annually — look up the current figure at implementation time rather than hardcoding a stale one).
- Payment-processor termination for deceptive practices, and the chargebacks that precede it.
- **Suspension of the tenant's own account and payouts.** This is the most credible deterrent because it is
  the one WE control and can actually apply — but it requires a matching Terms of Service clause, which
  does not exist yet (see the deferred ToS item under Lead capture).

## 3. Packs

### Shipped

- **`ad_landing`** (goal `paid_ads`) — seeds `content_block` + `faq`; turns on `trust_badges` +
  `refund_policy`. Cold ad traffic needs the scannable "what you get" and objection handling. The two
  governed sections are the ad-platform compliance half: Google and Meta routinely disapprove landing
  pages with no refund/return policy.

### Deliberately NOT changed

- **`listicle` keeps its lean base.** Its omission of `trust_badges`/`refund_policy` is a DESIGN DECISION
  ("listicle pages strip the fluff", plans/LISTICLE_AND_CART.md; "hero + price cards + CTA only",
  plans/PAGE_COMPOSER.md), guarded by `test_listicle_hides_fluff_by_default`. It was briefly mistaken for
  an oversight during this work. The compliance sections reach a listicle through the **goal** instead —
  `listicle` + `paid_ads` gets them, `listicle` alone stays lean. That is what the goal axis is for.
- **`email_list` and `minimal` stay empty.** Both want *less* than the base — a warm audience skipping the
  proof stack, and a goal literally named for having no extras. Packs are **union-only** (they add, never
  remove), so there is nothing honest for them to add. Empty is the correct answer, not an unfinished one.

### The open architectural question

To make `email_list`/`minimal` meaningfully different, a pack would need to mark a section **default-off
for that goal only**. That preserves "no goal = unchanged" and needs no migration, but it changes the
union-only contract that the whole goal axis was built on. Worth a deliberate decision, not a drive-by.

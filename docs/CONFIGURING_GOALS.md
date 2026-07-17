# Configuring landing page goals and packs

Admin guide. How to change what a landing page **starts with** for each goal, without touching code.

The starter mapping (which goal enables which pack) is a **reasonable default, not a researched one** — the
plan calls it a "starter set (to refine)". It is meant to be iterated on as you learn what actually converts.
This document exists so you can do that on your own.

Design background: `plans/LANDING_PAGE_GOAL_COMPOSITION.md`.

---

## The one file

Everything lives in **`src/stripe_link/composition_rules.json`**, under two keys: `packs` and `goals`.

That single file is read by both renderers — Python (`domain/composition.py`) reads it in the Lambda bundle,
and the Vue builder imports it at build time. That is *why* the preview and the published page can never
disagree: they read the identical bytes. It also means **a change is not live until you deploy both.**

## The model in one paragraph

`offer_type` (what the page sells) sets the **base** sections. A `goal` (why its traffic comes) enables
**packs** on top. Packs only ever **add** — never remove. A pack has two halves:

| Key | Means | Use for |
|---|---|---|
| `seeds` | Content elements the create wizard drops in as **empty scaffolds** for the tenant to fill | `faq`, `testimonials`, `rating`, `client_marquee` — anything that renders nothing until someone writes it |
| `sections` | Governed sections the goal switches **on** | Derived output needing no human input (`structured_data`, `llms_txt` — Phase 3). **Empty today.** |

Seeded elements become the tenant's the moment they're created. Changing a page's goal later never deletes
copy someone wrote.

---

## Recipe: change what a goal starts with

Point a goal at different packs.

```jsonc
"goals": {
  "paid_ads": { "label": "Paid ads", "note": "...", "packs": [] },
  // give Paid ads social proof too:
  "paid_ads": { "label": "Paid ads", "note": "...", "packs": ["social_proof"] }
}
```

**Update the `note` to match.** It's the sentence the tenant reads in the wizard, and it must stay true —
see "Notes must promise addition" below.

## Recipe: add a pack

```jsonc
"packs": {
  "urgency": { "label": "Urgency", "seeds": ["countdown_timer"], "sections": [] }
}
```

`seeds` entries must be **element keys that exist** in the `elements` catalog at the top of the same file,
and should be elements with `"ui": "add"` (the tenant can add/remove them). Then reference the pack from a
goal's `packs` list.

## Recipe: add a goal

```jsonc
"goals": {
  "affiliate": {
    "label": "Affiliate",
    "note": "Traffic from partner sites. Adds social proof to build trust fast.",
    "packs": ["social_proof"]
  }
}
```

It appears in the wizard, the composer, and the page validator automatically. **Also add the key to the
`goal` enum in `schemas/Page.schema.json`** — that file is reference documentation, not enforced at runtime,
so a stale enum breaks nothing, but it should stay accurate.

## Recipe: retire a goal — NEVER delete it

```jsonc
"social": { "label": "Social", "note": "...", "packs": ["social_proof"], "deprecated": true }
```

**Do not remove a goal from the file.** Pages that already stored it would fail validation — they could no
longer be saved *or* re-rendered/republished. It is a live-page outage, and it surfaces late (the next time
something republishes), which makes it painful to trace.

`"deprecated": true` is the safe retirement: the goal vanishes from the wizard so no new page can pick it,
while every existing page keeps validating and composing exactly as before. Same rule for **renaming** —
a rename is a delete plus an add. Add the new key, deprecate the old one.

---

## Deploying a change

Both, because both renderers embed the file:

```bash
./deploy/deploy.sh dev            # Lambda (Python composer + validator)
./deploy/deploy-dashboard.sh dev  # builder (Vue composer + wizard)
```

Then the same with `prod`. Verify with:

```bash
python3 -m pytest tests/test_composition.py -q
```

---

## What you cannot do from this file

- **Make a goal remove a base section.** Packs are union-only. `trust_badges`, `refund_policy` and
  `brand_label` come from the `offer_type` base, so no goal can strip them. A `hides` list was raised and
  deliberately deferred (see the plan's Open decisions) — it needs a small composer change.
- **Change a goal per tenant.** The rules ship with the code; there is no per-tenant override.
- **Change it at runtime.** No admin UI, no config table. Edit + deploy is the workflow, on purpose:
  build-time embedding is what guarantees both composers read identical bytes.

## Notes must promise addition, not subtraction

Because goals can only add, a `note` must never imply a leaner page. "Just the offer, nothing else" is false
— that goal renders the same brand label, trust badges and refund policy as every other one. Write
"Adds nothing extra" instead. The wizard also shows each goal's seeds verbatim ("Starts with: FAQ"), which is
generated from `packs` and is always true, so the `note` is the only part that can lie.

## Gotchas

- **`packs` and `goals` are order-sensitive in the UI.** The wizard lists goals in file order; `seeds` are
  applied in pack order, deduped.
- **An unknown goal composes as base-only**, so a typo in a *page* fails validation loudly (good), but a typo
  in a *pack name* inside `goals[].packs` fails silently — the pack simply contributes nothing. Check the
  wizard shows the "Starts with:" line you expect.
- **`sections` is empty in every pack today.** That is deliberate: the union mechanism is wired and
  tested-inert until Phase 3 adds derived `structured_data` / `llms_txt`. Putting a governed section there
  now would work, but think twice — it changes composition for every page on that goal.

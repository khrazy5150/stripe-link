# The Page Brief — design note for review

**Status:** for the author's review, nothing built · **Scope:** AI_AND_COMMERCE Part A, §A.3 step 1
· **Written:** 2026-09-27

This settles the *contract* before any of the pipeline is built, because four things meet at it: the
wizard writes it, the §A.7 floor grounds against it, the Product and Offer are derived from it, and
the Phase-2 URL adapter fills it. Get the brief right and everything downstream is small; get it
wrong and every piece has to be reworked.

---

## 1. The thing that decides how long the wizard is

Slice 2 changed the arithmetic here, and it is the one idea worth reading twice:

> **Every question we do not ask is a fact the AI is not allowed to assert.**

`domain/ai_floor.py` rejects any claim in a governed class that the brief does not license. So a
three-question brief does not produce a shorter page — it produces a *thin and cautious* one, because
the floor blocks the interesting sentences. Measured on 2026-09-27: the brief that produced good,
grounded FAQ answers carried seven facts.

This reframes "how many questions" from an annoyance tradeoff into a quality dial the tenant controls.
It also answers "can the AI just do everything?" — it can, about things it has been told. The
alternative is not a cleverer model; it is a model permitted to invent, which is what slice 2 exists
to prevent.

**Consequence for the UI:** few REQUIRED questions, many OPTIONAL ones, and show what each unlocks.
Not "fill in 12 fields", but "add your guarantee → we can write about your guarantee."

---

## 2. The brief

Flat and boring on purpose: it has to be writable by a form, by a URL scraper, and eventually by an
API caller, and readable by a grounding check that does substring matching.

```jsonc
{
  "schema_version": "2026-09-27",
  "document_type": "page_brief",
  "tenant_id": "...",
  "brief_id": "...",
  "source": "wizard | url | api",        // provenance; a scraped brief is UNTRUSTED (§A.6)
  "source_url": "",                       // set only when source == "url"

  // ---- REQUIRED. Four questions. Nothing generates without these. ----
  "name": "Poliaxis Creatine Gummies",
  "what_it_is": "Creatine monohydrate in a chewable gummy, sold as a monthly subscription.",
  "price": { "unit_amount": 3291, "currency": "usd",
             "pricing_model": "recurring", "recurring_interval": "month" },
  "audience": "Lifters in their 20s-40s who dislike swallowing powder or pills.",

  // ---- OPTIONAL. Each one licenses a class of claim, and nothing else does. ----
  "facts": ["5g creatine monohydrate per serving", "60 gummies per tub",
            "third-party lab tested", "made in the USA"],   // free-form, one per line
  "guarantee": "30-day money-back guarantee",
  "shipping": "Ships free in the US",
  "terms": "",                       // cancellation / renewal, in the tenant's own words
  "usage": "",                       // directions, dosage, how to use
  "certifications": [],              // only ones the tenant actually holds
  "evidence": "",                    // studies or results they can stand behind
  "tone": "direct",                  // direct | warm | playful | technical | premium
  "category": "supplement",          // drives the palette shortlist (resolve_preset)
  "brand": "",                       // resolved from the business if blank; never invented
  "images": [],                      // existing asset URLs; the AI never invents one
  "must_say": [],                    // lines to include verbatim
  "must_not_say": []                 // claims the tenant forbids
}
```

### Why these fields and not others

`facts[]` is one list rather than `benefits[]` + `features[]` as §A.3 originally sketched. Tenants do
not reliably distinguish the two, the split produced empty boxes in testing of similar forms
elsewhere in this product, and the generator does not need it — the *model* is better at deciding
what is a benefit than the tenant is at classifying it. One list, one question, richer answers.

`must_say[]` / `must_not_say[]` exist because they are the cheapest possible escape hatch. A tenant
who needs one sentence exactly right should not have to fight the generator for it, and a tenant with
a legal reason to avoid a word should be able to say so once.

`evidence` is deliberately narrow and deliberately scary-sounding. It is the ONLY thing that licenses
an efficacy claim, and it should read as a commitment.

---

## 3. What each answer unlocks

This is the table the wizard should surface, because it is the argument for answering more. Claim
classes are `domain/ai_floor.py CLAIM_CLASSES`; sections are `domain/ai_schema.py SECTION_SHAPES`.

| Brief field | Unlocks (claim class) | Without it, the AI cannot say |
| --- | --- | --- |
| `name`, `what_it_is` | — (required) | anything at all |
| `price` | — | the price, the interval, "subscription" |
| `audience` | — (steers tone, not permission) | who it is for, in their language |
| `facts[]` | the substance of `bragging_points`, `numbered_list`, most of `faq` | any specific number, material, size, count |
| `guarantee` | `guarantee` | "money-back", "refund", "risk-free", any N-day window |
| `shipping` | `shipping` | "free shipping", "ships in N days" |
| `terms` | `cancellation` | "cancel anytime", "no lock-in", "no fees" — **the single most common invention measured** |
| `usage` | `dosage` | "take one daily", "per serving", any dose |
| `certifications[]` | `certification` | "FDA", "GMP", "organic", "certified" anything |
| `evidence` | `efficacy` | "clinically proven", "you'll notice", "improves strength" |
| `tone` | — | (changes voice, never permission) |
| `category` | — | narrows the palette shortlist |
| `images[]` | — | `hero_media` stays floored either way; images are attached, never invented |

Two lines in that table are worth the author's attention. **`terms` is the highest-value optional
field** — "can I cancel anytime?" is a question buyers ask and models answer, and it was the invention
two of four models volunteered unprompted. And **`evidence` is the highest-risk** — it is the field
that turns marketing copy into a regulated claim, so the wizard should ask for it last, phrase it as
a commitment, and default to empty.

---

## 4. The questions

Nine steps, only four of which can block. Reuses the `ServiceWizard.vue` idiom: one `steps` list, a
review step, and explicit skip affordances so "leave it" is a click rather than a guess.

| # | Step | Asks | Required |
| --- | --- | --- | --- |
| 1 | What are you selling | `name`, `what_it_is` | ✅ |
| 2 | Price | `price` (amount, currency, one-off or recurring) | ✅ |
| 3 | Who is it for | `audience` | ✅ |
| 4 | What should people know | `facts[]` — one per line, 3+ encouraged | ✅ (≥1) |
| 5 | Promises you make | `guarantee`, `shipping`, `terms` | skip |
| 6 | How it is used | `usage`, `certifications[]`, `evidence` | skip |
| 7 | Voice | `tone`, `category` | skip (defaults) |
| 8 | Anything exact | `must_say[]`, `must_not_say[]` | skip |
| 9 | Review | the brief, plus **what we will and will not be able to say** | — |

Step 9 is the one that earns its place. Showing "we will not mention cancellation because you did not
tell us your terms" *before* generating is the difference between a tenant who understands a thin page
and a tenant who thinks the AI is bad. It is the same list as §3's right-hand column, filtered to
what is empty.

**The 30-second path:** steps 1-4 only, then Generate. That is the "AI does everything" experience,
and it honestly produces a decent, factual, slightly plain page. Steps 5-8 are where it gets good.

---

## 5. Brief → Product → Offer, deterministically

§A.3 step 2, and the rule is that **the platform owns every id**. The AI assists copy; it never
invents a reference that has to resolve.

| Created | From | Never from the AI |
| --- | --- | --- |
| `Product.name` | `brief.name` | — |
| `Product.description` | `brief.what_it_is` | — |
| `Product.product_category` | `brief.category` | — |
| `Product.product_type` | derived from fulfilment answer (physical/digital/service) | — |
| `Product.prices[0]` | `brief.price` | the amount, ever |
| `product_id` / `price_id` / `stripe_product_id` | platform + Stripe sync | **all ids** |
| `Offer.name` / `slug` | `brief.name` via the existing slug generator | — |
| `Offer.offer_type` | `single` | — |
| `Page.theme.preset` | `resolve_preset(category=…)` shortlist | an open hex value |
| `Page.sections[]` | `generate_structured` against the §A.7-floored schema | policy, legal, price, proof |

Everything in that left column already exists — this is wiring, not new machinery. The one genuinely
new decision is **what happens on partial failure**: if the Product saves and Stripe sync fails, the
tenant must not be left with a half-made thing they cannot see. Proposal: create everything as
`status: draft`, and make the job's failure path leave a draft Product the tenant can finish by hand.

---

## 6. Open questions for the author

1. **Nine steps, or fewer?** The argument for nine is §1 — more answers, better page. The argument
   against is that a tenant who wanted "AI does everything" is looking at a form. The 30-second path
   (steps 1-4) is the compromise; is it enough of one?
2. **Should `evidence` exist at all in v1?** Leaving it out means the AI can never make an efficacy
   claim, which is the safest possible default and removes the riskiest field from the product.
3. **Fulfilment type** — ask it (a tenth question), or infer it from `what_it_is` and let the tenant
   correct it on the review step? Inferring is friendlier and occasionally wrong; the Products wizard
   asks outright.
4. **What does "Generate" cost against the quota when it fails?** Current `ai_usage` releases the slot
   on provider error. Should a page the tenant *dislikes* be free to regenerate, or does every
   generation count? (Recommendation: count it; releasing on taste is unbounded.)
5. **URL adapter (Phase 2) — whose page?** Extracting facts from the tenant's own listing elsewhere is
   the good case. The design answer that makes it defensible: **extract facts, generate original
   copy, never reproduce their prose** — which is also better SEO, since duplicate copy does not rank.
   Worth deciding now, before the feature invites the other use.

# The Page Brief — design note for review

**Status:** REVIEWED — all five questions answered 2026-09-27; nothing built yet · **Scope:** AI_AND_COMMERCE Part A, §A.3 step 1
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

**Revised after review (author, 2026-09-27): the brief is a CORE plus a KIND block.** "Number of steps
matters less than smart steps — a service wizard has more steps than a product wizard." So `kind` is
asked once, early, and everything downstream derives from it. It is also the fulfilment question,
asked in plain language and never asked twice: a download has nothing to ship, so it is never asked
about shipping.

```jsonc
{
  "schema_version": "2026-09-27",
  "document_type": "page_brief",
  "tenant_id": "...", "brief_id": "...",
  "source": "wizard | url | api | existing_product",
  "source_url": "", "source_product_id": "",

  // ---- CORE. Asked for every kind. ----
  "kind": "physical | digital | service",   // one question; removes several later
  "name": "Poliaxis Creatine Gummies",
  "what_it_is": "Creatine monohydrate in a chewable gummy, sold as a monthly subscription.",
  "price": { "unit_amount": 3291, "currency": "usd",
             "pricing_model": "recurring", "recurring_interval": "month" },
  "audience": "Lifters in their 20s-40s who dislike swallowing powder or pills.",
  "facts": ["5g creatine monohydrate per serving", "60 gummies per tub",
            "third-party lab tested", "made in the USA"],

  // ---- PROMISES. Every kind, but the wording differs by kind (see §4). ----
  "guarantee": "30-day money-back guarantee",
  "terms": "",                       // cancellation / renewal, in the tenant's own words
  "certifications": [],
  "evidence": "",                    // KEPT in v1 (author). The only licence for an efficacy claim.

  // ---- VOICE. Every kind. ----
  "tone": "direct", "category": "supplement", "brand": "",
  "images": [], "must_say": [], "must_not_say": [],

  // ---- KIND BLOCK. Exactly one of these, and the wizard only ever shows one. ----
  "physical": {
    "shipping": "Ships free in the US",
    "usage": "",                     // directions / dosage
    "materials": "", "dimensions": ""
  },
  "digital": {
    "format": "PDF, 48 pages",       // what they actually receive
    "delivery": "Instant download after checkout",   // usually derivable; see §4
    "access": ""                     // licence, device limits, updates
  },
  "service": {
    "duration_minutes": 60,
    "location_mode": "in_person | remote",
    "performed_by": "",              // "me" or a named team
    "booking": "scheduled | no_booking",
    "what_happens": ""               // the session itself -- the service analogue of `usage`
  }
}
```

### Why these fields and not others

`facts[]` is one list rather than `benefits[]` + `features[]` as §A.3 originally sketched. Tenants do
not reliably distinguish the two, the split invites empty boxes, and the generator does not need it —
the *model* is better at deciding what is a benefit than the tenant is at classifying it.

`must_say[]` / `must_not_say[]` are the cheapest possible escape hatch. A tenant who needs one
sentence exactly right should not have to fight the generator, and one with a legal reason to avoid a
word should say it once.

`evidence` is deliberately narrow and deliberately scary-sounding. **Kept in v1 at the author's
direction.** It is the ONLY thing that licenses an efficacy claim, so it should read as a commitment.

The kind blocks mirror documents that already exist: `physical.*` maps onto `Product.fulfillment`,
and `service.*` onto the `Service` document's `duration_minutes`, `location_mode` and
`fulfillment_mode`. That is deliberate — the wizard should not invent a vocabulary the rest of the
product does not use.

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

**Two entry points**, because the smartest step is the one already answered:

- **From an existing product** — `kind`, `name`, `price` and often `facts` are already known. The
  wizard opens on the first genuine gap and shows the rest as already-answered. A tenant with a
  catalogue should never retype it.
- **From scratch** — the full flow below, which also creates the Product and Offer (§5).

**The step list is derived, not fixed** — one `steps(kind)` computed, the `ServiceWizard.vue` idiom,
so the rail, the labels and the bounds all read the same source. (`LandingPages.vue`'s rail is the
scar that says what happens when three calculations each decide how long a conditional wizard is.)

| # | Step | physical | digital | service | Required |
| --- | --- | :-: | :-: | :-: | --- |
| 1 | What are you selling — `kind`, `name`, `what_it_is` | ● | ● | ● | ✅ |
| 2 | Price | ● | ● | ● | ✅ |
| 3 | Who is it for | ● | ● | ● | ✅ |
| 4 | What should people know — `facts[]` | ● | ● | ● | ✅ (≥1) |
| 5a | Shipping & use — `shipping`, `usage`, `materials`, `dimensions` | ● | — | — | skip |
| 5b | What they receive — `format`, `access` | — | ● | — | skip |
| 5c | The session — `duration_minutes`, `location_mode`, `performed_by`, `booking`, `what_happens` | — | — | ● | **✅ duration + location** |
| 6 | Promises — `guarantee`, `terms`, `certifications`, `evidence` | ● | ● | ● | skip |
| 7 | Voice — `tone`, `category` | ● | ● | ● | skip (defaults) |
| 8 | Anything exact — `must_say`, `must_not_say` | ● | ● | ● | skip |
| 9 | Review | ● | ● | ● | — |

**Correction (2026-09-27, while implementing):** an earlier draft of this note claimed "a download
is 7 steps". It is not — the table above gives every kind the same nine-step frame. The count was
wrong and the claim is withdrawn.

What actually differs is the *content and the weight* of the kind step, which is the part that
matters. A **download never sees a shipping or dosage question**, and its whole kind step is optional
— skippable in one click. A **service's kind step has two required fields**, because a service page
that cannot say how long it takes or whether it is remote is not worth generating. That is the
author's rule — ask the fulfilment question only when it is not obvious — applied by making `kind`
carry it, and it shows up as what is asked rather than as a shorter rail.

**What is never asked because it is derivable:**
- `digital.delivery` — a digital product is delivered by download; only asked if they say otherwise.
- `physical.requires_shipping` — implied by `kind`.
- `service.booking` — defaults to `scheduled`; the `no_booking` case is a checkbox on 5c, not a step.
- `brand` — resolved from the business profile (`resolve_brand`), asked only if there is none.

Step 9 earns its place by showing **what we will not be able to say**: "we will not mention
cancellation because you did not tell us your terms." Shown *before* generating, it is the difference
between a tenant who understands a thin page and one who thinks the AI is bad. Same list as §3's
right-hand column, filtered to what is empty.

**The 30-second path:** steps 1-4 (plus 5c for a service), then Generate. That is the "AI does
everything" experience, and it honestly produces a decent, factual, slightly plain page.

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

**All five answered by the author, 2026-09-27.** Recorded as decisions, with what each one changed.

1. **Steps.** *"Number of steps doesn't matter as much as smart steps — a service-based wizard will
   have more steps than a product-based wizard."* → The brief became core + kind block, and the step
   list is derived from `kind` (§2, §4). This is the revision that reshaped the note.
2. **`evidence` stays in v1.** It remains the only licence for an efficacy claim, asked last and
   phrased as a commitment.
3. **Fulfilment is asked only when not obvious.** *"A downloadable product requires no fulfillment
   question."* → `kind` is asked once in plain language and carries it; digital never sees shipping.
4. **A disliked generation still counts against the quota.** Releasing on taste is unbounded. The
   slot is released only on provider error or unusable output — our failure, not their preference.
5. **Always generate original copy.** Settled for the Phase-2 URL adapter and as a general rule: we
   extract FACTS — price, dimensions, materials, specs — and never reproduce a source's prose. Better
   SEO besides, since duplicate copy does not rank.

### Still open (implementation, not design)

- **Partial failure.** If the Product saves and Stripe sync fails, the tenant must not be left with a
  half-made thing they cannot see. Proposal: create everything `status: draft`, and let a failed job
  leave a draft Product they can finish by hand.
- **Does a service brief create a `Service` document or a `Product` with `product_type: service`?**
  Settled elsewhere — plans/SERVICE_WIZARD.md §3 chose the Service document with
  `fulfillment_mode`, and `Products.vue` already hands off to `ServiceWizard` on that basis. The AI
  wizard must hand off the same way rather than inventing a third path.

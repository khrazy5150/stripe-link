# The Page Brief — design note for review

**Status: v2 — REVISED 2026-09-29.** v1 specified a standalone nine-step AI wizard. The author's verdict on
seeing it built (`AiPageWizard.vue`, 370 lines) was that **it duplicates the product wizard**. v2 replaces the
wizard with a FORK off the existing one. §4 and §5 are rewritten; everything else in this note survived.
· **Scope:** AI_AND_COMMERCE Part A, §A.3 steps 1–2 · **Written:** 2026-09-27

This settles the *contract* before any of the pipeline is built, because four things meet at it: the
wizard writes it, the §A.7 floor grounds against it, the Product and Offer are derived from it, and
the Phase-2 URL adapter fills it. Get the brief right and everything downstream is small; get it
wrong and every piece has to be reworked.

---

## 1. The thing that decides how much the AI may say

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
Not "fill in 12 fields", but "add your guarantee → we can write about your guarantee." v2 sharpens this:
anything already known — from the Product or from tenant config — is *read*, so the only things asked are the
ones nothing else can supply (§4).

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

## 4. The fork, not a wizard

**v1 was wrong about the shape.** It specified nine steps and shipped as `AiPageWizard.vue`, and the author's
objection is the correct one: almost every question it asks, the product wizard has already asked. Measured
against `Products.vue`:

| Product wizard step | What the v1 brief asked AGAIN |
| --- | --- |
| purpose (intent) | `kind` |
| details (name, description, category) | `name`, `what_it_is`, `category` |
| pricing | `price` |
| identifiers | — |
| image | — |

And two more the brief asked that should be **read, not asked**: `guarantee`/`terms` come from the tenant's
`refund_policy`, and shipping from `ShippingConfig`. `domain/ai_floor.py` already said so — it lists
`refund_policy` as a governed class because *"a refund window is a contract term; it comes from the tenant's
policy"*. The floor and the v1 brief contradicted each other, and the floor was right.

**What is left once duplicates and derivable answers are removed is one step.**

### Where it forks from — DECIDED 2026-09-29

**Both:** offered as the next action when the product wizard finishes, and as an action on any existing
product. One fork component, two call sites. The second call site is not a nicety — every product that exists
today got there without ever seeing this flow, and a tenant with a catalogue must never retype it.

**Consequence: the AI flow never creates a Product.** Every generation starts from one that already exists.

**BUILT 2026-09-29.** `_persist` takes `existing_product_id` and, under the fork, creates only the Offer and
the Page, pointed at the product's DEFAULT price — not the first in its list, since a product with a sale
price and a full price carries both and generating copy around whichever came first puts the wrong number on
the page.

**Still to remove:** `ai_provision.product_document`. It has exactly one caller left — the branch that runs
when no `product_id` is supplied — and no UI reaches it now that the standalone wizard is gone. Deleting it
means requiring `product_id` and rewriting the ~8 tests that exercise brief→Product (fulfilment mapping,
price, id ownership). A pure refactor with no user-visible change, deliberately sequenced after the deadline
rather than done at speed. Until it goes, a second way to create catalogue rows technically exists via the
API, which is the duplication this rework set out to remove.

### The one step — DECIDED 2026-09-29

**Two required, the rest optional and collapsed**, each labelled with what it unlocks:

| Field | Required | Unlocks |
| --- | :-: | --- |
| `audience` — who it is for | ✅ | Every benefit sentence; without it the copy addresses nobody |
| `facts[]` — what people should know | ✅ (≥1) | The substance of the page; the floor licenses nothing else |
| `evidence` | — | Any efficacy claim at all |
| `certifications` | — | Trust badges and compliance statements |
| `tone` | — | Voice; defaults to the category's |
| `must_say` | — | Exact phrasing the tenant needs present |
| `must_not_say` | — | Phrasing the tenant needs absent |

This keeps §1's principle intact — *every question we do not ask is a fact the AI is not allowed to assert* —
while honouring the author's rule that the fork must not feel like a second form. The 30-second path is now
genuinely two fields.

**Review still happens, and still earns its place** by showing what the page will NOT be able to say: "we will
not mention your refund window because your policy is not set." That list now draws on config as well as the
step, which makes it actionable in a way v1's could not be — the fix is a settings link, not a retype.

## 5. Product → Brief → Offer + Page

v1 had this backwards because it assumed the AI flow created the catalogue. It does not. The Product is an
input; the Offer and the Page are the outputs.

### The brief is PROJECTED, and snapshotted — DECIDED 2026-09-29

Built fresh at generate time from Product + tenant config + the one step, then **stored on the generation
job**. Both halves matter and for different reasons:

- **Projected** so current policy always wins. A tenant who fixes their refund policy and regenerates gets a
  page that reflects it. A stored, tenant-edited brief would snapshot the terms and silently stop propagating —
  the same failure mode as the stale `global_billing_config.json` fee table.
- **Snapshotted onto the job** so there is an immutable record of what the AI was licensed to assert for any
  given page. That is what answers "why did it say that?" months later, and it is exactly what the floor was
  checked against. Without it the grounding decision is unreproducible.

### What is derived from where

| Created | From | Never from the AI |
| --- | --- | --- |
| *(Product)* | **already exists — the fork's input** | — |
| `brief.name` / `what_it_is` / `category` / `price` / `kind` | the Product | — |
| `brief.guarantee` / `terms` | tenant `refund_policy` | — |
| `brief.shipping` | `ShippingConfig` | — |
| `brief.audience` / `facts[]` / `evidence` / `tone` / `must_*` | **`Product.ai_context`**, edited by the one step | — |
| `Offer.name` / `slug` | Product name via the existing slug generator | — |
| `Offer.offer_type` | `single` | — |
| `Page.theme.preset` | `resolve_preset(category=…)` shortlist | an open hex value |
| `Page.sections[]` | `generate_structured` against the §A.7-floored schema | policy, legal, price, proof |

Everything in the left column already exists **except `Product.ai_context`, added 2026-09-29.** The gap: those
six answers lived only in the transient brief, so a tenant regenerating would have retyped every one of them.
They belong to the PRODUCT rather than the page, because they describe the thing being sold — a second page
for it, an A/B variant or a seasonal landing page, inherits them instead of asking again. It also makes §1's
principle durable: a product accumulates the facts the AI is licensed to assert, and the page is just what was
built from them at one moment.

Optional in full: a product with no `ai_context` produces a thinner, more cautious page rather than an error.
Bounded in every field, because each entry is a sentence a generated page is then licensed to write, and an
unbounded list is both a prompt-size problem and an unreviewable one.

**v1 is PRODUCTS ONLY** (decided 2026-09-29). Services are a separate document with their own wizard and a
booking CTA; the brief already models a service `kind`, so the groundwork is there, but the fork proves itself
on the simpler case first rather than debugging two page shapes at once.

The rest is wiring.

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

- **Partial failure — CLARIFIED 2026-09-29.** v1's "create everything as draft" was poorly phrased and read
  as applying to the catalogue; the author's intent was **landing pages are created as drafts**. That is also
  the only reading the schemas allow: `Page.status` has `draft`, `Product.status` is `["active","archived"]`
  and has none. Under the fork model the question largely dissolves — the AI flow no longer creates Products,
  so there is no half-made catalogue row to strand. **What remains:** the Offer and Page it *does* create, and
  a Stripe sync that fails on the pre-existing Product is the product wizard's problem, not this flow's.
- **Does a service brief create a `Service` document or a `Product` with `product_type: service`?**
  Settled elsewhere — plans/SERVICE_WIZARD.md §3 chose the Service document with
  `fulfillment_mode`, and `Products.vue` already hands off to `ServiceWizard` on that basis. The AI
  wizard must hand off the same way rather than inventing a third path.

- **Correction capture — NOT YET DESIGNED (author's idea, recorded 2026-09-29).** When a tenant edits a
  generated element in the builder, that edit is the highest-quality training signal the platform will ever
  get: a before/after pair on a real page, with the brief that licensed it. Nothing records it today. Cheap
  while the builder is already being touched for this feature and expensive to reconstruct afterwards — the
  same shape as the audit-trail argument in TODO's backup entry. Needs its own design: what is stored, for how
  long, whether it is tenant-private, and what it is actually used for (few-shot examples, policy tuning, or
  just a quality metric). **Do not build it blind into this phase**; decide the purpose first, because that
  decides the schema.

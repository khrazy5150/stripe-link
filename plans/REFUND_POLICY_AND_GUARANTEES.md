# Refund Policy II — the promises the vocabulary cannot make

**Status: P1–P3 SHIPPED dev 2026-10-30 · P4–P7 planned · Written 2026-10-27 · Follows `plans/REFUND_POLICY.md`,
which is shipped.**

**P1 done.** Three conditions (`working_condition`, `complete_in_packaging`, `any_value_adjusted`), a
`90_days` window, and `return_shipping` on the policy. The schema-parity test was widened FIRST, as this
phase instructs — it walks all four schemas by SHAPE rather than by a list of paths, finds the six policy
blocks and proved them already in step before the vocabulary grew. `return_shipping` renders with the
return note rather than inside `full_policy`, keeping the one-source rule that exists because the two were
once both printing the note. Defaults are the status quo (`buyer_pays` for a real return, `not_applicable`
wherever nothing travels back), so no stored policy gains a promise nobody made.

**P2 and P3 shipped together**, as P3 required. `platform_default()` is gone, `tenant_policies()` returns
only the classes the tenant set, and `resolve()` answers `mode: "unset"` with no policy at all.
`apply_to_product` stamps nothing: `Product.refund_policy` is the override channel only, and the promise is
composed at publish from the live default — so a Configuration change now reaches every page at its next
publish with no product edited, which is the fault P3 existed to remove.

Both dangerous readers moved in the same change: `returns.return_requirement` and `refunds._keep_it_below`
resolve rather than reading the stamp. **A physical good with NO resolved policy now requires its return** —
the old fallback answered "customer keeps" there, which is how a shipped item could be refunded with nothing
coming back on a policy nobody chose. Requiring it is the recoverable direction: one click waives it, while a
return wrongly skipped is goods AND money gone with nothing to click.

The money-back badge is SUPPRESSED, not relabelled, when there is no policy — the old "Money-back guarantee"
fallback becomes a guarantee badge over no guarantee the moment the platform stops standing one in.

Configuration names the unset classes and says what happens at the next publish. `CLASS_DEFAULTS` survives,
renamed `CLASS_FORM_SEEDS` and used for two things that are not promises: seeding the three selects when a
tenant first enables a class, and coercing a single bad field inside a policy that DOES exist. A DEVIATION
from this phase's wording ("CLASS_DEFAULTS go"), taken because the settings screen already models "not set"
with its own per-class toggle, so the values can start a form without ever reaching a page.

The first plan stopped a lie: a hardcoded JavaScript literal was authoring every product's refund promise.
It succeeded — the vocabulary is data, the sentence is generated server-side, and a screen exists. This plan
is about what that screen cannot yet say, and about the fact that nothing a tenant says there currently
reaches a published page.

## What the author found

Two screenshots, 2026-10-27, and they are separate faults.

**1. The condition list cannot express the ordinary physical-goods rule.** The options are
`any / unused / unopened / defective_only / not_downloaded / custom`. There is no *in working condition* —
the clause that makes damage caused by the customer ineligible. `unused` is stricter than most sellers mean
and `any` gives away the only protection they have, so a tenant selling anything mechanical has no honest
option and picks one of the two wrong ones.

**2. A published page contradicted the screen above it.** The page said *"This item doesn't need to be
returned. The customer may keep the item and dispose of it in a responsible way"* while Configuration showed
**Return handling: Customer returns the item**.

## What discovery found, which is worse than the report

The renderer is innocent — `refund_policy_return_note` reads `return_method` correctly. The data is what
says it. Live dev product `local_W25lZGBWwmz` ("Security Mini Cam") stores:

    source: platform_default · 30_days · unused · no_return_customer_keeps

Then the tables:

    jb-platform-config-dev    ItemCount 0, 0 bytes, scan returns 0 items
    jb-platform-config-prod   ItemCount 0, 0 bytes, scan returns 0 items

**No tenant has ever saved a refund policy, on either environment.** The settings screen shipped a month ago
and the document it writes does not exist anywhere. So every refund sentence on every live page is the
platform's fallback, and that fallback — for *physical goods* — promises the buyer keeps the item **and** may
have their money back. Nobody chose it. That is the first plan's own bug wearing a different hat: it looks
configured.

And it would not have helped if the tenant had saved. `apply_to_product` runs on product **write** only
(`handlers/products.py:86`, `handlers/ai_generate.py:748`); `handlers/config.save_config` touches no product
and republishes no page. A tenant can set their policy, press Save, and watch nothing change — forever, until
each product happens to be edited for some other reason.

**3. The Temu example is a different axis.** Items 2–6 of it — price match, delay credit, damaged in transit,
no-tracking-update refund, non-delivery refund — are not rules about returning an item. They are promises
about *things going wrong*, and no amount of window/condition/return-method vocabulary can express one.

## Decisions (author, 2026-10-27)

| | Decision |
| --- | --- |
| Guarantees | **Two primitives.** `refund_policy` keeps the returns mechanics; a new `buyer_guarantees` carries the delivery and price promises. |
| Propagation | **Resolve at publish time.** The product stops carrying a policy snapshot. |
| Platform fallback | **Removed.** No policy chosen means the page says nothing about refunds. |

The fallback decision is the first plan's own stated principle, finally applied to itself:

> *"where there is no answer the page says **nothing** — silence is recoverable, a false promise is a
> dispute."*

---

## P1 — Vocabulary the mechanics actually need

**Conditions.** Three added, each earning its place by naming a rule a seller really uses:

| value | clause |
| --- | --- |
| `working_condition` | `in working condition` |
| `complete_in_packaging` | `unused, in its original packaging, with all parts and accessories` |
| `any_value_adjusted` | `in any condition — the refund is reduced to reflect any loss of value` |

`any_value_adjusted` is the example's own rule and is the honest middle ground between `any` and `unused`.
**It changes the sentence only.** No refund arithmetic is implied: `handlers/refunds.py` already supports a
partial amount and the merchant decides it, exactly as today. Promising an automatic deduction we do not
compute would be a new implicit promise, which is the thing this family of plans exists to stop.

**Windows.** Add `90_days`. The example's headline is a 90-day return window and we cannot express it.

**Who pays the postage.** New field `return_shipping` on the policy:

    seller_pays | buyer_pays | not_applicable

This is the missing half of *"Free returns"*, and it is the single most commercially significant fact a
returns policy states. `domain/ledger.return_shipping_cost_entry` has recorded who **bore** this cost since
the shipping work; nothing has ever recorded who was **promised** to. Default `not_applicable` for
`digital_revoke_access` and `no_return_customer_keeps` — nothing ships back, so the question does not arise.

**Schema parity.** The condition enum is duplicated in **four** schema files — `Product`, `Page`, `Offer`,
and `TenantConfig` (three times). `tests/test_refund_policy.py:323` pins the module's tables to
`Product.schema.json` **only**, so the other three can drift silently. Widen that test to all four before
touching the enum, or this phase ships a document some validator refuses.

## P2 — Delete the platform fallback

`platform_default()` and `CLASS_DEFAULTS` go. `tenant_policies()` returns only the classes the tenant set;
`resolve()` returns `{}` with `mode: "unset"` when there is nothing to resolve.

Consumers, each of which currently assumes a policy always exists:

- **`runtime/html.render_refund_policy`** — already returns `""` for an empty policy. Correct by accident;
  pin it with a test so it stays correct on purpose.
- **`ai_provision.chosen_badges`** — today an enabled money-back badge with no policy falls back to the
  label *"Money-back guarantee"*. With no fallback policy that becomes a **fabricated claim on a public
  page**: a guarantee badge over no guarantee. The badge must be suppressed entirely when the policy is
  unset, not relabelled.
- **`ai_floor`** — `refund_policy` is already listed as tenant-owned and unauthorable. Confirm an unset
  policy licenses *nothing* rather than falling through to an unlicensed claim. (`feedback_absence_reads_as_safety`
  is the exact failure shape to watch for here: a gate built from absences passes anything that does not exist.)
- **`domain/returns.py` / `handlers/refunds.py`** — see P3; they read the snapshot and must resolve instead.

**The consequence must be stated to the tenant, not discovered by them.** Every existing product carries a
stored `platform_default` policy, and under P3 that snapshot stops being read. Those pages lose their refund
section on their next publish. Configuration therefore needs an actionable notice — *"Your pages currently
show the platform's old default. Set a policy, or the refund section disappears when a page is next
published."* — with the product count. A notice with an action the tenant must take is the only kind worth
showing (`feedback_notices_only_when_actionable`).

## P3 — Resolve at publish, not at write

`apply_to_product` stops stamping a resolved policy onto the product document. `Product.refund_policy`
survives as **the override channel only**: present when the tenant deliberately overrode this product
(`product_override`) or when `tip_jar_provision` wrote one, absent otherwise.

- **Publish** composes the policy from the live tenant default plus any override and bakes it into the
  rendered artifact. `publish_page_document` gains a config repository the way `_bnpl_messaging_config`
  already takes `stripe_keys_repository`. The artifact is static, so it still holds a snapshot — but one
  refreshed on every publish from the current default, which is the whole point.
- **Nothing is written back to the product table.** The author's rule holds: nothing alters old data.
- **`domain/returns.return_requirement` and `handlers/refunds._keep_it_below` must resolve too.** They read
  `product.refund_policy.return_method` and `.keep_it_below` off the stored document today. This is the real
  cost of the decision and the place it can go quietly wrong: a product with no override would read an empty
  policy, `return_requirement` would find no `return_required`, and **every physical refund would be released
  without the goods coming back**. Both call sites move to `resolve(tenant_config=, product=, price=)` in the
  same change that removes the stamp, not after it.
- **`returns.policy_snapshot` is unchanged and is why this is safe.** It freezes the terms when a refund is
  requested, so a tenant editing a default never alters a return already in flight. That is the one place
  freezing is genuinely needed, and it already exists.

## P4 — `buyer_guarantees`, a second primitive

`legal_defaults.buyer_guarantees` on TenantConfig — the same document, beside the refund policies. A new
`domain/buyer_guarantees.py` owns the vocabulary, the parameters and the **generated copy**, server-side, for
the reason the first plan established: a browser is not allowed to author a commercial promise.

| key | parameter | promise |
| --- | --- | --- |
| `damaged_in_transit` | — | Lost or damaged on the way: full refund. |
| `no_delivery_refund` | days (20) | Not delivered N days after shipment: refund or reshipment. |
| `no_tracking_update_refund` | days (15) | No tracking movement for N days: refund or reshipment. |
| `price_match` | days (30) | Found cheaper elsewhere within N days: refund the difference. |
| `price_adjustment` | days (30) | Our own price drops within N days: refund the difference. |

Each is independently enabled. A tenant who wants none is unaffected and the section does not render.

**Free returns is deliberately NOT here.** It is `return_shipping: seller_pays` from P1. Two places to say
one thing is the duplicate-source fault this repo keeps paying for.

**These are the tenant's promises, not the platform's.** Temu's list works because Temu is a marketplace
guaranteeing on its sellers' behalf; here the tenant *is* the merchant. The generated copy must read in the
tenant's voice and must never imply that Junior Bay backs the promise, because it does not.

**Honouring them is manual in this phase, and the plan says so rather than implying otherwise.** Enabling
`no_delivery_refund` publishes a promise; the merchant still handles the request, exactly as with every
refund today. `delivery_status` already exists, so automatic detection is a credible later phase — but
shipping the promise and the automation together would hold the promise hostage to the harder half.

**`late_delivery_credit` from the example is excluded, and the reason is structural.** A store credit needs a
buyer balance, and this platform has no buyer accounts at all (the tip-jar work settled that deliberately).
A credit we cannot issue is a promise we cannot keep. Recorded under Open.

## P5 — Configuration UI

A "Buyer guarantees" card below Refund Policy: one row per guarantee, a toggle, its number, and the
server-generated sentence previewed read-only. Same discipline as the refund card — the preview arrives from
`/config?refund_options=1` (widened, or a sibling flag), never composed in JavaScript.

P1's new fields join the existing card: the three conditions and `90_days` appear automatically from the
server vocabulary, which is what that indirection was for. `return_shipping` needs a new select, shown only
when `return_method` is `return_required`.

## P6 — Rendering

A `buyer_guarantees` section: a numbered list, one entry per enabled guarantee, in the module's canonical
order so two tenants' pages are comparable. `composition_rules.json` gains it — and because composition is a
layer both renderers obey (`plans/PAGE_COMPOSER.md`), that one entry governs the builder palette and the
published page together.

It is a trust element, so `ai_floor` must list it as tenant-owned: a generated page may not author a
guarantee any more than it may author a refund window.

## P7 — Consumers

Covered in place above (P2 for the badge and the floor, P3 for returns and refunds). Listed as its own phase
only so that "the consumers were updated" is a tickable item rather than an assumption — the first plan's
step 5 found a second write path quietly disagreeing with the first, and that is how the original literal
survived a year.

---

## Definition of done

- A tenant can express *in working condition*, a 90-day window, and who pays return postage.
- A tenant who has set nothing publishes **no** refund sentence and **no** money-back badge.
- Changing a default in Configuration changes what every affected page says at its next publish, with no
  product edited.
- A physical refund still waits for the goods when the resolved policy requires a return — proven by a test
  that resolves from a tenant default with **no** product-level policy present.
- The guarantees a tenant enables render as a numbered list, in the tenant's voice.
- `tests/test_refund_policy.py` pins the vocabulary against all four schemas, not one.

## Open

- **`late_delivery_credit` needs a credit mechanism** the platform does not have. Revisit only if buyer
  balances ever exist; a coupon code issued by hand is the nearest honest substitute and is not the same
  promise.
- **A custom window still has nowhere to put a number** (carried over from the first plan). `90_days` reduces
  the pressure; it does not remove it.
- **Window basis for physical goods is "of delivery"; the example promises "from the date of purchase".**
  Both are defensible and they are materially different for a slow-shipping seller. A per-class basis
  override is the fix, and it is deliberately not in this plan — it widens the generated-sentence matrix and
  nobody has asked for it yet.
- **`any_value_adjusted` describes a deduction nothing computes.** If tenants use it heavily, a structured
  reduction on the refund request is the follow-on.
- **Automatic honouring of the delivery guarantees** via `delivery_status`. The promise ships first.

# Form Builder

Status: PLANNED, not built. Designed 2026-08-30.
Related: `LEAD_CAPTURE.md` (the ingest/consent/retention rail this rides on), `SOCIAL_MEDIA_PAGES.md`,
`PAGE_COMPOSER.md` § *Cardinality*.

---

## 1. What already exists (this is an EXTENSION, not a new subsystem)

`lead_capture.fields[]` is already a field-declaration mechanism, already validated, already rendered:

| Piece | State |
|---|---|
| `fields[]` shape `{name, type, required?}` | validated, `documents.py:604-612` |
| inline form rendering | built, `html.py:4220` (`render_email_cta`) |
| ingest, honeypot, dual GDPR consent, idempotency | built, `handlers/leads.py` + `LEAD_CAPTURE.md` |
| `lead_submission.fields` storage | free-form dict (`documents.py:1639`) — **richer forms need NO storage change** |
| leads list / status workflow | built |

So the builder is a **UI plus a richer field vocabulary over machinery that is two-thirds there.** Do not
design a parallel forms subsystem.

## 2. What is missing or wrong today

1. **`field.type` is not an enum.** `require_string(field, "type")` accepts any string; the renderer maps
   through `LEAD_FIELD_INPUT_TYPES = {email, phone, tel, number}` and silently falls back to `"text"` for
   everything else. A typo'd type is accepted and renders as a text box.
2. **Every field renders as `<input>`.** No `<textarea>`, `<select>`, checkbox or radio.
3. **No labels — and this is an accessibility DEFECT in shipped code, not just a missing feature.** The
   placeholder is derived from the field name (`name.replace("_", " ").title()`), and a placeholder is not
   a label: it disappears on focus, screen readers treat it inconsistently, and it measurably hurts
   completion. This affects the email capture that is live today.
4. **No dashboard UI.** `stores/products.js:469-473` hardcodes the field list per action
   (email → `[email]`, phone → `[phone]`, both → `[email, phone]`). A tenant cannot add a field.
5. **Submissions are not validated against the declared fields.** `lead_submission.fields` only has to be
   a non-empty dict. `required: true` is enforced client-side only, so it is trivially bypassable, and a
   submission may contain fields the form never declared. VERIFY the exact behaviour in
   `leads.ingest_lead` before building — this is a data-integrity gap, not just a nicety.
6. **`open_form` is inert.** It requires a `form_id` that nothing reads, and falls through to a generic
   `email` CTA.

## 3. Key decision: NO `Form` entity

A form is **not** its own document type. Reasons:

- **The Product already IS the reusable unit.** A "Job Application" lead_gen product carrying its fields is
  reusable across many offers — exactly what a `Form` entity would provide, with no new table, repository,
  CRUD handlers, permissions or migration.
- **It matches the rule this codebase just settled** (`LEAD_CAPTURE.md`, offer/product split):
  **Product declares WHAT is collected. Offer declares HOW it converts.** A field list is definitionally
  "what is collected", and it already lives on the product.
- There is no evidence yet of a reuse need that Product does not serve. Revisit only if one appears.

Consequence: `form_id` and `open_form` are retired (§7), not implemented.

**The one wart this inherits:** `validate_product_document` requires `default_price_id` unconditionally
(`documents.py:637`), so a pure form product still carries a $0 price row. Same open decision as
`SOCIAL_MEDIA_PAGES.md` §9.1 — exempt `product_intent: lead_gen`, or formalise the $0 price. Decide once,
for both.

## 4. Field vocabulary (P0)

Replace the free-string `type` with a closed enum, and pin it with a test — a hand-maintained list that
the renderer must agree with is exactly the drift shape logged in `TODO.md` § *silent agreement failures*.

```jsonc
{
  "name": "role",                    // storage key; unique within the form
  "type": "select",                  // ENUM (below)
  "label": "What role are you applying for?",   // REQUIRED — never derive from name again
  "required": true,
  "placeholder": "",                 // optional, and never a substitute for label
  "help": "",                        // optional hint under the field
  "options": [                       // REQUIRED for select | radio; forbidden otherwise
    { "value": "eng", "label": "Engineering" }
  ],
  "max_length": 500                  // optional, text/textarea only
}
```

Enum: `text` · `textarea` · `email` · `tel` · `number` · `url` · `date` · `select` · `radio` · `checkbox`

**Out of scope for v1:** file upload (needs storage, size limits and virus scanning — and the video-upload
infrastructure it would share does not exist yet, see the media-parity item), payment fields (that is
checkout), and conditional/branching logic (see §8).

## 4a. Multi-step is FIRST-CLASS, not a later mode (author, 2026-08-30)

The target shape is a **quiz funnel**: one question per screen, large tap targets, a visible progress
indicator, contact details last. This is the dominant lead-gen pattern in education, insurance and
home-services precisely because it out-converts a flat form, and it is mobile-first by nature — the same
"effectively all traffic is a phone" constraint as `SOCIAL_MEDIA_PAGES.md`.

An earlier draft of this plan deferred multi-step. That was wrong: building a flat renderer first and
retrofitting steps means rebuilding it. Get the SHAPE right in P0 even if step rendering ships later —
nesting is cheap now and expensive to retrofit.

### Shape — a flat form is ONE STEP, not a separate mode

```jsonc
"lead_capture": {
  "action": "capture_email",
  "steps": [
    { "title": "When would you like to start?",
      "fields": [{ "name": "timeframe", "type": "radio", "display": "cards",
                   "advance_on_select": true,
                   "options": [{ "value": "now", "label": "Immediately" },
                               { "value": "1_3", "label": "1-3 Months" }] }] },
    { "title": "Where are you located?", "fields": [{ "name": "zip", "type": "text" }] },
    { "fields": [{ "name": "email", "type": "email", "required": true }] }   // contact LAST
  ]
}
```

One shape, no mode flag. **`fields[]` stays valid** and normalizes to `steps: [{ fields }]` on read, so
existing products need no migration and flat forms stay trivial to author.

### Two additions to the field vocabulary (§4)

- `display: "cards"` on `radio` — renders options as large tappable cards rather than radio dots. This
  is a presentation hint, not a new type; the data is still a single-select.
- `advance_on_select: true` — a single-select step advances on tap, with no Next button. Removing that
  tap is a meaningful share of the conversion gain, and it only applies to single-select steps.

### Rendering

- One `<form>` for the whole funnel; only the final step submits. Steps are shown/hidden client-side,
  so there is no navigation and no per-step round trip.
- Progress indicator (the dots in the reference), plus a Back control.
- Per-step client validation gates advancing. It is **UX only** — the server still validates the whole
  submission against every declared field (§7), which is unchanged by steps.

### DECISION — when is the lead recorded?

**v1: once, at the end, after contact details and consent.** Answers are held client-side until then.

The alternative — recording progressively per step — is tempting because it captures abandoners, but it
means storing answers before the visitor has consented or identified themselves, which puts the dual
GDPR opt-in in `LEAD_CAPTURE.md` §6 in the wrong place. Note the reference funnel asks *"when would you
like to start?"* before it asks for an email, so most steps carry no PII at all — the value of
progressive capture is lower than it looks.

Worth building **later**, and consent-clean: an *abandoned-funnel* capture that fires only AFTER the
contact+consent step, so someone who gives their email and then drops on a later step still becomes a
lead. That is the case with real value, and it reuses the abandoned-cart sweep pattern.

### DECISION — resilience and "continue later": a CLIENT-SIDE draft

Requirement (author, 2026-08-30): a dropped connection or a visitor who wants to finish later must not
lose their answers. Agreed — but do it on the device, not the server.

```
localStorage  key: sl_form_{tenant_id}_{page_id}   TTL ~7 days   cleared on submit
```

This covers a dropped connection, a refresh, an accidental back-swipe and "I'll finish tonight" — the
overwhelming majority of real cases. It needs no lawful basis: it is storage on the visitor's own device,
strictly necessary for a service they actively requested, and it never reaches us, so it cannot become a
breach or a subject-access request.

**Why NOT server-side partials.** "Save it but don't use it" does not work under GDPR: storage IS
processing (Art. 4(2)), so an incomplete submission needs a lawful basis whether or not anything reads
it. Once it is server-side alongside a session id or IP it is pseudonymous personal data (online
identifiers, recital 30), which drags retention and erasure obligations with it. Operationally it is also
messy — partial rows would pollute the leads list, lead counts and the `lead_capture` entitlement gate.
(Reasoning from the regulation; not legal advice.)

**Cross-device resume needs no special case.** Resuming on a different device requires identifying the
person, which means you already hold their email — which is precisely where consent lands. So the only
scenario that genuinely needs server state is the abandoned-funnel capture above, which is already
consent-clean.

**DEPENDENCY — namespacing is REQUIRED, not optional.** The risk lives on the PUBLISHED page at runtime,
not in authoring: a visitor loads `jbay.page/{username}` and the inline JS from `runtime/html.py` runs in
their browser at the `jbay.page` origin — shared by every creator page (path-on-apex,
`SOCIAL_MEDIA_PAGES.md` §9.4). A visitor who taps two creators' links from Instagram gives both pages'
scripts access to the same `localStorage`. So form drafts MUST be namespaced by tenant, exactly like the
`sl_cart_id_*` keys, and a half-typed email in an abandoned draft is more sensitive than a cart id.
Publishing does not isolate this — it is what creates the shared origin.

### Consent placement

The dual opt-in must render on the step that collects contact details — where it is today. Do not hoist
it to step 1: consent obtained before the visitor knows what they are giving is not meaningful consent,
and in the regulated verticals this pattern targets (the reference page carries outcome disclaimers and
a submission disclosure) that matters legally, not just ethically.

## 5. Rendering (P1)

Extend `render_email_cta` — do not fork it. It already owns the honeypot, the dual consent checkboxes and
the submit wiring, all of which must apply identically to every form.

- `<textarea>`, `<select>`, radio group, single checkbox, alongside the existing `<input>`.
- **A real `<label for>` for every field.** Fixes §2.3 for existing forms too.
- `aria-describedby` for `help` text; `aria-invalid` + an inline error node per field.
- Preserve exactly: honeypot, both consent checkboxes, `POST /leads`, and the ordering rule that the lead
  is recorded BEFORE any `on_success` redirect fires (`LEAD_CAPTURE.md`).

## 6. Builder UI (P2)

In the product editor, replacing the hardcoded list in `stores/products.js`:

- add / remove / **reorder** fields — reorder shares the ⭐ HIGH drag-reorder work already queued;
- per-field settings panel driven by the enum (options editor appears only for `select`/`radio`);
- live preview comes free — the builder already renders through `POST /pages/render`, so there is no second
  renderer to keep in sync (`PAGE_COMPOSER.md`);
- guard rails in the UI: warn past ~6 fields (completion falls off a cliff), and require a label.

## 7. Server-side validation (P3) — do not skip this

Once tenants can declare arbitrary fields, `POST /leads` must validate the submission **against the
declared fields of that offer's product**:

- reject fields the form never declared (prevents junk and payload stuffing);
- enforce `required` server-side — today it is a client-side attribute and nothing more;
- enforce `max_length` and type coercion (`number`, `date`, `email` shape);
- keep the honeypot's silent accept-and-drop behaviour unchanged.

This is a **prerequisite** for shipping the builder, not a follow-up: the moment a tenant can define a
form, the client-only guarantees become worthless.

## 8. Retire `open_form` — and with it, `form_id`

**`form_id` is inert.** `documents.py:626` requires it, `stores/products.js:482` writes it, and NOTHING
reads it. The product editor currently prompts the tenant to type one, which is why it feels broken.

Do NOT auto-generate a value for it. Auto-generating fills a field no code consumes, on an action this
plan removes, and leaves a second identifier that must agree with `product_id` forever after. **Remove
the prompt and the field.** If a form ever needs a stable identifier — for analytics, or to reference it
externally — `product_id` already is one, and under the no-`Form`-entity decision (§3) the product *is*
the form.



`open_form` was "link to a quiz, application, or survey". After this plan it is covered twice over and
should be removed along with `form_id`:

- an **internal** quiz/application/survey is just a capture action with more fields — this plan;
- an **external** one is `on_success: { type: "redirect" }` — `LEAD_CAPTURE.md`.

Together with retiring `social_redirect` (`SOCIAL_MEDIA_PAGES.md` §10), the action vocabulary drops from
seven to five, both by removal.

## 9. Deferred, deliberately

- **Conditional / branching logic** (show step 4 only if step 2 was "Immediately"). Multi-step itself is
  now core (§4a); branching is the part still deferred — it needs a rules language and a way to preview
  every path. Revisit once flat multi-step is in tenants' hands.
- **A standalone `/forms/{id}` page.** Only if a form must exist without an offer. Today every form is
  reached through an offer's page, which the cardinality rule already covers.
- **Per-form analytics** (views, starts, completion, drop-off field). High value — form completion is the
  whole game — but it belongs with the per-link analytics work in `SOCIAL_MEDIA_PAGES.md` §11 so one
  event pipeline serves both.

## 10. Phasing

1. **P0** — field enum + `label`/`options`/`help`/`max_length`, **and the `steps[]` shape** (§4a), with
   `fields[]` normalizing to one step. Pinned by a test. Get the nesting in now.
2. **P1** — renderer: new control types, real labels, a11y attributes. Flat (single-step) first.
3. **P1b** — multi-step rendering: step navigation, progress indicator, `display: "cards"`,
   `advance_on_select`. Same renderer, no fork.
4. **P2** — builder UI in the product editor: fields, steps, reorder.
5. **P3** — server-side submission validation. **Must ship with or before P2 is exposed to tenants.**
6. **P4** — retire `open_form` + `form_id`; drop the prompt, migrate any existing rows.

P0/P1 fix the live accessibility defect on their own, before any builder UI exists.



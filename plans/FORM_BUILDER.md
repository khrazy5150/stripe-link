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

## 8. Retire `open_form`

`open_form` was "link to a quiz, application, or survey". After this plan it is covered twice over and
should be removed along with `form_id`:

- an **internal** quiz/application/survey is just a capture action with more fields — this plan;
- an **external** one is `on_success: { type: "redirect" }` — `LEAD_CAPTURE.md`.

Together with retiring `social_redirect` (`SOCIAL_MEDIA_PAGES.md` §10), the action vocabulary drops from
seven to five, both by removal.

## 9. Deferred, deliberately

- **Multi-step / conditional logic.** Real demand exists for applications, but it changes the storage
  shape (steps, visibility rules) and the renderer (client-side state). Ship flat forms first; revisit
  with evidence.
- **A standalone `/forms/{id}` page.** Only if a form must exist without an offer. Today every form is
  reached through an offer's page, which the cardinality rule already covers.
- **Per-form analytics** (views, starts, completion, drop-off field). High value — form completion is the
  whole game — but it belongs with the per-link analytics work in `SOCIAL_MEDIA_PAGES.md` §11 so one
  event pipeline serves both.

## 10. Phasing

1. **P0** — field enum + `label`/`options`/`help`/`max_length` on the schema, pinned by a test.
2. **P1** — renderer: new control types, real labels, a11y attributes.
3. **P2** — builder UI in the product editor.
4. **P3** — server-side submission validation. **Must ship with or before P2 is exposed to tenants.**
5. **P4** — retire `open_form` + `form_id`; migrate any existing rows.

P0/P1 are independently shippable and fix the live accessibility defect on their own, before any builder
UI exists.

# Page Ribbon — what the button does (A-P1.5)

**Status:** planned, not built. Author's spec 2026-09-04, five actions. Written after checking what already
exists, because three of the five are mostly assembly and two are not.

## 0. The one thing to build first: ONE click event

The five actions differ in what happens *after* the click. They all need the same thing *at* the click: a
record that this ribbon, on this page, was acted on. Building that five times is how this codebase produces
the failures it keeps producing.

`ATTENTION_PRIMITIVE.md` already argues for this — *"Ship Ribbon attribution with the Ribbon"* (A-P2). It is
now load-bearing rather than nice-to-have, because **call tracking is nothing but this** (see §5).

One beacon, fired on click, carrying `{page_id, section_id, action, purpose}`. The published page already
emits Google Tag / Meta Pixel tags (`render_analytics_tags`), so the same click can push a custom event
there for tenants who use them, plus a first-party POST so the tenant sees it without a third party.

## 1. Promote another of my pages — **buildable now**

Visual single-select of the tenant's OTHER published landing pages; the control resolves the published URL
and embeds it.

| Needs | Exists? |
|---|---|
| list of the tenant's pages | yes — the builder already loads them |
| published URL for a page | yes — `runtime/publishing.py` `artifact_paths` / `public_url` |
| visual picker | yes — the Offers modal's product selector, to be reused single-select |

Note it must exclude the CURRENT page, and must handle "selected page later unpublished" — a ribbon
pointing at a 404 is worse than one with no button.

## 2. Download a file — **buildable now, most parts exist**

| Needs | Exists? |
|---|---|
| tenant uploads a file | **yes** — `POST /downloads/upload-url` presigns an S3 PUT to the media bucket and returns `digital_asset` metadata |
| filename safety, bucket keys | **yes** — `domain/downloads.py` `sanitize_filename`, `asset_bucket_key` |
| short-lived signed GET | **yes** — `GET /download` 302s to a presigned URL |
| leads storage + public endpoint | **yes** — `LeadsTable`, `POST /leads` |
| **lead-GATED download** | **no** — today's `/download` requires a *paid order*. This needs a sibling that gates on a lead instead, or on nothing |
| inline modal on the page | **no** — and the page is a static S3 artifact, so this is a small client-side script, not server rendering |

Optional `collect email` / `collect phone`; neither ticked means the file downloads immediately. Ticked
fields are required and recorded as a lead.

## 3. Email a file — **the spec needs one correction**

> Author: *"limit the file to a reasonable size… my gut tells me 50Mb"*

**SES cannot send a 50MB attachment.** The v2 API caps a message at **40MB including MIME/base64 encoding**,
and base64 inflates binary by ~37% — so 40MB of message is roughly **29MB of actual file**. There is also no
attachment path in the codebase today: `mailer.py` uses `sesv2` and the app only ever sends HTML/text.

More to the point, **attachments are the wrong mechanism** at any size: they trip spam filters, bounce
against mailbox quotas, cannot be revoked, and give the tenant no delivery signal.

**Recommendation: email a LINK, not a file.** It removes the size limit entirely, reuses the exact presigned
machinery from §2, lets the link expire, and is what every vendor in this space does. The tenant experience
is unchanged — they upload a file, the prospect gets it by email — and the lead is recorded identically.

If an actual attachment is wanted later, it needs `SendRawEmail` plus a hard ~25MB cap, and should be a
deliberate choice rather than a surprise at 30MB.

## 4. External URL — **already built**

Ships in A-P1: `safe_href` refuses `javascript:`/`data:`/protocol-relative, and external links already carry
`target="_blank"` with `rel="noopener"` — the "don't lose my landing page" requirement is met, and `noopener`
is what stops the opened tab reaching back into the opener.

## 5. Call a number — **two different features wearing one name**

**(a) Click tracking — buildable now.** Fire the §0 beacon on tap. On mobile a `tel:` tap is a strong
intent signal, and it is the same mechanism every other action needs. This is most of the funnel value.

**(b) True call tracking — a real telephony project, not a ribbon feature.** Knowing whether the call
*connected*, and for how long, requires a **tracking number that forwards to the tenant's real number**, so
the platform sits in the call path.

What exists here: **outbound SMS only** — `sms-voice:SendTextMessage` and an origination-number secret. There
is no voice capability, no inbound handling, and no number provisioning. Building (b) means:

- a telephony provider (Amazon Connect / Twilio) and **per-number monthly cost, per tenant**
- provisioning, releasing and reclaiming numbers as tenants come and go
- call records, and a place to show them
- consent/recording law if calls are ever recorded — varies by state, and two-party-consent states make
  recording a legal question rather than a technical one

That is worth doing when tenants ask for attributable phone leads. It is not worth blocking a ribbon on.

## Recommended order

1. **§0 the click beacon** — unblocks call tracking (5a) and gives every action attribution.
2. **§1 promote another page** — pure assembly of things that exist.
3. **§2 download, with the lead gate** — the biggest new capability, and the modal is reusable by §3.
4. **§3 email a link** — reuses §2 end to end once the correction above is accepted.
5. **§5b true call tracking** — separate project, separate decision.

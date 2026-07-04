# Custom Domain Setup — Beginner-Friendly Wizard (Reference Design)

## Status

This is a **design reference, not yet implemented**. The first stripe-link custom domain
implementation ports legacy `stripe-cart` behavior functionally (one subdomain → one
published page, Cloudflare for SaaS + DNS TXT verification) without this improved UX.
Build the wizard described here as a follow-up pass once the backend is in place, using
this document as the spec instead of re-deriving it from scratch or copying the legacy
dashboard flow as-is.

## Why the legacy wizard needs replacing

The legacy `stripe-cart` dashboard (`dist/dashboard/js/custom-domains.js`) technically
works, but is not beginner-friendly. Concrete problems, in order of how much confusion
they cause:

1. **Two DNS records are revealed at two different times.** The wizard shows a CNAME
   record during setup; a second, required TXT record only appears *after* the domain is
   already added, in a different part of the screen. A beginner adds the CNAME, believes
   they're done, and is confused when the domain never goes live.
2. **Three distinct pending states collapse into one label**, "Pending Verification"
   (`pending_dns`, `pending_ssl`, `pending_verification` all show identically). A user who
   did everything right and one who did nothing see the same status and get no signal
   about what's actually missing.
3. **No propagation time expectation is ever shown.** DNS changes can take anywhere from a
   few minutes to 48 hours; the legacy wizard never says so, so a user who checks status
   immediately and sees "pending" has no idea whether to wait 2 minutes or 2 days.
4. **Jargon is used without explanation** — CNAME, TXT, apex domain, SSL, ownership
   verification — with no plain-language definitions anywhere in the flow.
5. **No guidance on *where* to make the change.** The copy says "log in to your domain
   provider," but names no registrars, shows no screenshots, and gives no pointer to where
   DNS settings typically live in a registrar's dashboard.
6. **Two competing entry points do the same thing differently.** A "guided" wizard and a
   separate collapsed "Advanced setup" raw form both create the same domain record, but
   only the guided path shows any DNS help at all — a beginner who stumbles into the
   advanced form gets zero guidance.
7. **No visual separation between "you do this" and "we do this automatically."** DNS
   record entry and automated verification checks are both presented as plain paragraphs,
   so it's unclear which steps require the user to leave the dashboard and which don't.
8. **Failures give no remediation.** A failed check shows a raw error string
   (`last_error`) with no suggested next action.

## Design principles

- **Show all required DNS records together, once**, not staggered across separate steps.
- **Every state has distinct, specific guidance.** No two different situations should ever
  show the same status text.
- **Always state the expected wait time** next to anything DNS-related.
- **Define jargon inline**, the first time each term appears, in plain language.
- **One flow, not two.** A single wizard serves both beginners and power users; a power
  user can expand "enter values directly" within the same flow instead of being routed to
  an entirely separate, less-helpful form.
- **Visually separate "what you do" from "what we check automatically.**"
- **Every failure state suggests a concrete next action**, never a raw error string alone.

## The improved flow

### Step 0 — Before you start (requirements screen)

Shown before asking for any domain, so expectations are set upfront:

- "You'll need a domain name you already own (like `yourbusiness.com`). Don't have one
  yet? [Get one from a registrar]." (link out, not a dead end with only a Back button
  like legacy's `need-domain` step)
- "We currently support **subdomains** (like `shop.yourbusiness.com`), not bare root
  domains (`yourbusiness.com`) directly." — stated once, upfront, for everyone, not buried
  in an advanced-only helper text.
- "You'll need access to your domain's DNS settings — wherever you bought the domain
  (GoDaddy, Namecheap, Google Domains, Cloudflare, etc.) has a DNS management page."
- "Setup takes about 5 minutes, but DNS changes can take anywhere from a few minutes up to
  48 hours to take effect. You can leave and come back — nothing is lost."

### Step 1 — Choose your subdomain and destination

- Two inputs shown together with a live preview: apex domain (`yourbusiness.com`) +
  subdomain prefix (`shop`) → preview text updates live: **`shop.yourbusiness.com`**.
- Destination: a dropdown of the tenant's *published* pages. If none are published yet,
  show that inline ("You don't have a published page yet — [publish one first]") instead
  of letting the user proceed into a dead end.
- One-line note: "You can't rename this subdomain later without creating a new one."

### Step 2 — Add your DNS records (both, together)

Show **both** records the user needs, in one table, at the same time — never stagger
them:

| # | What it's for | Type | Name | Value |
|---|----------------|------|------|-------|
| 1 | Points your subdomain to us | CNAME | `shop` | `domains.jbay.uk` |
| 2 | Proves you own this domain, so we can issue your SSL certificate | TXT | (from Cloudflare) | (from Cloudflare) |

Each row has its own copy-to-clipboard button per field (matching the one genuinely good
part of the legacy UI). Below the table:

- **"What you do:"** "Log in to your domain registrar's dashboard, find DNS settings (also
  called 'DNS management' or 'Zone editor'), and add both records above exactly as shown."
- **Registrar pointers** (short, not full walkthroughs): "GoDaddy: *My Products → DNS →
  Manage Zones*. Namecheap: *Domain List → Manage → Advanced DNS*. Cloudflare: *DNS* tab.
  Google Domains: *DNS → Manage custom records*."
- **"What we do automatically:"** "Once you've added both records, click Check Status
  below. We'll verify the records and request an SSL certificate — this can take a few
  minutes."
- Explicit reminder: "DNS changes can take a few minutes up to 48 hours to spread across
  the internet. If Check Status doesn't find your records right away, wait a bit and try
  again."

### Step 3 — Verify (one button, distinct states)

A single "Check Status" action drives one visible state at a time, each with a specific
next action — no state ever reuses another state's copy:

| State | Copy shown | Next action for the user |
|---|---|---|
| Checking | "Checking your DNS records…" | none, wait |
| Neither record found | "We haven't found either DNS record yet. Double-check you saved your changes at your registrar." | re-add records, recheck later |
| CNAME found, TXT missing | "Found your CNAME record. Still waiting on the TXT record — make sure you added it as **TXT**, not CNAME." | add/fix the TXT record |
| TXT found, CNAME missing | "Found your TXT record. Still waiting on the CNAME record." | add/fix the CNAME record |
| Both found, SSL pending | "Both records found — we're issuing your SSL certificate now. This usually takes a few minutes." | wait, recheck shortly |
| Active | "🎉 `shop.yourbusiness.com` is live. [Visit your page]" | done |
| Check failed (our side, e.g. API error) | "We couldn't run this check right now — this is on our end, not yours. Try again in a minute." | retry, distinct from "you did something wrong" |

Also poll automatically in the background at a slow interval (e.g. every 30–60 seconds)
while the wizard is open, so most users never have to click Check Status manually at all
— reserve the manual button for "I just fixed something, check right now."

### Step 4 — Done

Confirmation with a working link to the live domain, and a clear path to add another
domain or reassign the destination page later.

## Explicitly out of scope for this document

- The Site-based "one domain, many pages" flow (`schemas/Site.schema.json`) is a separate,
  later feature for a different tenant segment. This document only covers the simple
  one-subdomain-per-page flow (`TenantConfig.custom_domains`). Reuse the design
  principles above when that wizard is built, but it needs its own step sequence (choosing
  which pages live at which paths under the domain).
- Apex/root domain support is not addressed here since it isn't supported yet either in
  legacy or in the current stripe-link plan.

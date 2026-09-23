# The standard transactional email

**Status: identity + shell SHIPPED 2026-09-23. Not deployed.**

## What was wrong

Two messages from one shop, in one real inbox, on the same evening:

| | From | Reply-To |
|---|---|---|
| review invite | `Poliaxis Nutrition <support@juniorbay.net>` | **none** |
| order receipt | `support@juniorbay.net` | **none** |

The same business, named on one message and anonymous on the next, and neither reachable. A customer
answering either wrote to the platform's support box, which is not the merchant and cannot help them.

**None of this was a missing capability.** `mailer.send_email` has taken `from_name` and `reply_to` since
it was written, and its docstring promised both. The callers simply did not pass them:

- **four of nine** senders passed a display name; **three** passed a Reply-To;
- the two that resolved a name read **different fields** — the review invite `Site.organization.name`,
  the receipt `TenantProfile.business_name`;
- `TenantProfile.business_name` was **empty on every tenant that has ever existed** (0 of 2 prod, 0 of 4
  dev, measured 2026-09-23), so the receipt's only source was always blank. The bare From was the norm,
  not an edge case;
- `platform_config` — the receipt's only Reply-To source — had **zero rows in either environment**.

The canonical business identity was sitting in `UserProfile.business` (`{name, email, address}`) the whole
time, populated, and read by exactly one sender (`downloads.py`).

## The fix, in two parts

### 1. Identity is resolved at the choke point, not by callers

`mailer.send_email` fills in `from_name` and `reply_to` from the tenant's own profile whenever a
`tenant_id` is given and the caller did not state them. Explicit values always win.

```
business_name   business.name -> display_name -> first + last -> ""      (sender_display_name)
reply_to        VERIFIED business.email -> signup email -> ""            (reply_to_address)
```

**Why the signup email is a legitimate fallback and not a hole.** `verified_email` exists because SES will
mail from any Reply-To a tenant types, so the platform must prove the address belongs to them. A Cognito
account email is proof of exactly that, obtained by a stronger flow. And the alternative is what shipped:
no Reply-To at all, because **no tenant has ever completed business-email verification**.

**Platform-authored mail passes no `tenant_id`**, so a Junior Bay verification code still comes from Junior
Bay rather than from the shop the recipient happens to own.

The choke point is the point: nine emitters each had to remember, and six did not. One place cannot be
forgotten by the tenth.

### 2. One shell, identical for every tenant

`domain/email_layout.py`. Before it, each emitter built its own HTML and they agreed about nothing a
recipient notices — a 32rem column in `-apple-system, Segoe UI, Roboto` on `#1f2937` for the review invite,
a 520px column in `system-ui, Arial` on `#111` for the abandoned cart, a third set of greys for the
invoice. None named the business in the body at all.

```
render_email(business_name, title, body, preheader, reply_to, footer_note, footer_html)
paragraph(text, muted)   button(label, url)   rows_table(rows, total)
```

Constraints it is written against, which explain the odd choices:

- **Tables and inline styles.** Outlook renders with Word's HTML engine: no flexbox, no grid, `<style>`
  blocks unreliable.
- **Images are blocked by default**, so nothing meaningful may live in one. The business name is TEXT —
  which is also why this works for a tenant with no logo, i.e. all of them.
- **A preheader is the second line in an inbox list.** Unset, the client scrapes the first text it finds.
- **Dark mode inverts unstyled backgrounds**, so every surface states its own background and colour.
- **The reply line is part of the template**, because a Reply-To nobody is told about is a Reply-To nobody
  uses.

Deliberately the same for every tenant. Per-tenant theming — a brand colour, a logo — is a Business Profile
question, not a job for the layer whose purpose is to stop emitters disagreeing.

## Covered

`receipt` · `review invite` · `abandoned cart` · `invoice` · `purchase manage link` ·
`fulfiller notification`. Platform-to-tenant mail (verification codes, support contact) deliberately keeps
its own plain styling and platform identity.

## Open

- **Per-tenant branding** — accent colour and logo from the Business Profile, once that lands.
- **`support.email` is still read** by the receipt path for its footer line, and `platform_config` is
  empty everywhere. Harmless (the footer is omitted), but the field should either be populated from the
  Business Profile or removed.
- **A real send has not been eyeballed in a client.** The templates are verified by tests and a rendered
  preview, not by Litmus or an actual Outlook.
- **The footer mark is 30KB for a 20x20 render** — and it is the same file every published page links as
  its favicon, so this is page weight, not an email detail. Raised to ⭐⭐ HIGH in `plans/TODO.md`. `images.juniorbay.com/icon/favicon.png` is a 200x200 PNG
  (confirmed live 2026-09-23, HTTP 200), served at `width="20"` — roughly 10x the density needed, and
  fetched by every recipient whose client loads images. The CDN ignores resize query parameters
  (`?w=40` returns the same 30115 bytes) and no smaller variant is published, so shrinking it means
  publishing a ~2KB 40x40 asset from the sibling `image-processing` repo. Out of scope here; worth doing
  when that repo is next touched. The URL is pinned by a test so it cannot drift silently in the meantime.

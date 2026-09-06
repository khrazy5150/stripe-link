# Tenant sender identity — verified business email before any tenant-triggered send

**Status:** planned, not built. Author's requirement 2026-09-05, raised when the ribbon's email action
shipped sending from a generic identity.

## 1. The rule

Every email the platform sends *on a tenant's behalf* must carry:

| Header | Value |
|---|---|
| From | `"{Business name}" <support@juniorbay.com>` |
| Reply-To | the tenant's **verified** business email |
| Subject | the **offer name**, so it matches what the customer clicked |

And the hard gate: **no tenant may send through Junior Bay's SES account without a verified reply-to.**
Junior Bay is out of the SES sandbox and can mail anyone — which is exactly why the platform, not SES, has
to be the thing that refuses.

## 2. What already exists

Better than expected. Three of the four pieces are in place:

- **`business.email` is already on the user_profile** (`validate_business_identity`, documents.py) —
  optional, free text, and **unverified**. It is the field this plan makes trustworthy.
- **`send_email()` already accepts `from_name` and `reply_to`** (mailer.py) and sets `ReplyToAddresses`.
  So the header shape above needs no mailer change at all.
- **A single verified platform identity** (`EMAIL_FROM_ADDRESS`) is already how everything sends.

What does **not** exist: any verification flow for `business.email`, and any email-validation vendor.

⚠️ **Check before building:** the mailer's default is `support@juniorbay.net`, and the requirement says
`support@juniorbay.com`. The deployed value comes from the `EmailFromAddress` parameter, so confirm which
domain is actually verified in SES before changing anything — a From address on an unverified domain fails
every send.

## 3. Verification flow (new)

Changing `business.email` sets it to **pending** and emails a 6-digit code to the NEW address. Five-minute
expiry, as specified.

- The address is not usable as a reply-to until confirmed — pending is not verified.
- The OLD verified address stays in force until the new one confirms, so a typo does not silently disable
  every tenant email.
- Store `{code_hash, expires_at, attempts}` — hashed, because a code is a credential; rate-limited, because
  6 digits is 10^6 and unlimited attempts is no security at all.
- A new short-TTL table, or the existing profile document with a TTL field. Table-per-entity says table.

## 4. Real-time validation at entry — **one part needs a decision**

The requirement: reject **disposable, invalid, or catch-all** addresses before the form submits.

Disposable and invalid are uncontroversial. **Catch-all is not, and I would push back on it.**

A catch-all domain accepts mail to any local part, so a validator cannot prove a specific mailbox exists —
it returns "unknown", not "bad". Plenty of legitimate small businesses run catch-all domains, and some
providers (including common small-business hosting) are catch-all by default. **Rejecting them would refuse
real customers with real addresses, and the failure is invisible to us — they just cannot sign up.**

Since this address must survive a confirmation code anyway, a catch-all address that is fake will fail at
that step regardless. The code IS the proof of existence; the validator is only there to catch the obvious.

**Recommendation:** hard-reject disposable and syntactically/DNS invalid. Treat catch-all as a soft warning
that still allows submission, with the code doing the real work.

**Vendor is an open decision** — ZeroBounce, NeverBounce, Kickbox, AbstractAPI are the usual candidates.
Each is a new external dependency, a secret to manage, a per-check cost, and a request in the signup path
that must fail *open* (if the validator is down, do not block a legitimate tenant; the code still gates).

## 5. Enforcement — "universally" needs a defined edge

The gate belongs where the send happens, not in each feature's UI, or the next feature to send email will
forget it. One check, called by every tenant-triggered send.

Affected today:
- the Page Ribbon's `email_file` action (the only one shipping now)
- any later tenant→customer mail: order receipts, abandoned-cart recovery, review invites, invoices

⚠️ **Decide explicitly:** do transactional emails the tenant did not compose — order receipts, refund
notices — also require a verified business email? Gating those would mean an unverified tenant's *customers*
stop getting receipts, which punishes the wrong person. My recommendation is to gate **tenant-authored
sends** (lead magnets, campaigns) and let platform-authored transactional mail continue from the platform
identity with no tenant reply-to.

## 6. Builder-side message

When unverified, the ribbon's email action shows exactly what was asked for:

> You must first enter a valid business email address before using this feature! Go to your Profile page to
> enter a business email.

It should be a *blocking* state on the action, not a warning after the fact — the same lesson as the page
picker, where offering a choice and then rejecting it was worse than not offering it.

## 7. Build order

1. `business.email` verification: pending state, code send, confirm endpoint, 5-minute expiry, attempt caps.
2. The send-time gate + the builder's blocking message.
3. From/Reply-To/Subject shape on the ribbon's send (no mailer change needed).
4. Validation vendor, once chosen — and only ever fail open.

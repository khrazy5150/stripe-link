# Distinct branding for the TEST Connect onboarding

Part of the live-first onboarding streamline (see `plans/TODO.md` → "Streamline Connect
onboarding"). This is a **no-code** Stripe Dashboard configuration — nothing to deploy.

## Why

New tenants onboard their **live** Stripe account through the Junior Bay platform's **live**
Connect OAuth application. Only tenants who opt into a sandbox ("Set up a sandbox for your
funnels" on the Payments screen) ever hit the **test** Connect OAuth application. Giving the
test app visibly different branding (name/color) makes it obvious, on Stripe's own consent
screen, that the tenant is authorizing a **sandbox / test** connection — not their real payout
account. It's a cheap guard against a tenant wiring up test when they meant live, or vice-versa.

## The two Connect applications

Junior Bay uses two separate Stripe Connect OAuth clients (one per mode):

| Mode | Env var                  | Client ID (as of 2026-08) |
|------|--------------------------|---------------------------|
| Live | `STRIPE_CLIENT_ID_LIVE`  | `ca_TbP9vsLxUbwOhpla1zfMNxNjBUbOpkh4` |
| Test | `STRIPE_CLIENT_ID_TEST`  | `ca_TbP9X8xdC1FYAAoMB15aLTi9fJmIC0J4` |

The OAuth consent screen's name, icon, and brand color come from the platform account's Connect
settings **in the matching mode** — test-mode settings render on the test client's consent
screen, live-mode settings on the live client's.

## Steps (Stripe Dashboard, platform account)

1. Toggle the Stripe Dashboard into **Test mode** (top-right).
2. Go to **Settings → Connect → Onboarding options → OAuth** (a.k.a. the Connect "Branding"
   / platform settings for OAuth).
3. Set a **distinct name** for the test app — e.g. append `(Sandbox)` or `(Test)` to the
   platform name so the consent screen reads clearly as a sandbox authorization.
4. Set a **distinct brand color** and/or icon so it's visually unmistakable versus live.
5. Save. Switch back to **Live mode** and confirm the live app keeps the normal production
   branding (do not change live).

## Verify

- On the Payments screen click **Set up a sandbox** → the Stripe consent screen should show
  the test branding (sandbox name/color).
- A fresh live onboarding (default flow) should still show the normal live branding.

No code changes accompany this; it is purely the platform account's mode-scoped Connect
settings.

## ⚠️ Rehearsing tenant onboarding as the platform owner (learned 2026-08-28)

Stripe attaches a **newly created** connected account to whichever **Stripe login holds the browser session** —
NOT to the Junior Bay login you're signed in as. So if you're signed into Stripe as the platform
(`keith@juniorbay.net`) and rehearse onboarding for a test tenant, clicking **"Create a new account"** silently
creates an account owned by the *platform* login. (That's exactly how the stray "Facebook" account appeared under
a yahoo-email tenant; the duplicates cost an hour of cleanup.)

**Rules for rehearsals:**
1. Use a **separate browser profile or an incognito window** — never the window where the platform Stripe
   dashboard is open.
2. On Stripe's screen, **pick the existing account** from the chooser. Verified 2026-08-28: the chooser reuses
   correctly and creates nothing. Only **"Create a new account"** mints a new one.
3. Rehearse in **Test mode**. Live-mode rehearsals leave real, abandoned accounts behind, and a pile of those is
   a risk signal Stripe associates with you as a person.
4. After connecting, confirm the account on the **"Payouts will go to this account"** card (and the avatar pill)
   before doing anything else — that's the cheap catch for a wrong-account connect.

This is a **platform-owner edge case**: ordinary tenants either have their own Stripe session (chooser → their
account) or none (create → correctly theirs).

# Google Ads Phase 0

Started November 23, 2026. Documentation review and the live Sandbox suite passed. Google's confirmation of the hosted production workflow is pending.

## Access and scope

- Google grants Test access when the Ads API is enabled on the OAuth client's Google Cloud project. Start the test with that project and an Ads test client. This probe uses the current v26 REST endpoint and project-based access. [Access levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels) · [REST authorization](https://developers.google.com/google-ads/api/rest/auth) · [Version schedule](https://developers.google.com/google-ads/api/docs/sunset-dates)
- Explorer supports production access and restricts API account creation and linking, keyword planning, and billing. Evaluate it for an existing-account Search pilot with Google-managed billing and tenant-entered keywords. Confirm the required tier and its usable operations before the pilot. [Explorer access](https://developers.google.com/google-ads/api/docs/api-policy/access-levels#explorer)
- Google's policy calls for advertiser or agency Cloud access and manual user sign-in to make changes. Use advertiser-owned access as the planning baseline. Ask Google to confirm the exact requirements for Junior Bay's hosted dashboard and any jobs that run after the advertiser signs out. [Developer policies](https://support.google.com/adspolicy/answer/6169371)

## Test OAuth and account selection

On November 23, 2026, the operator ran the read-only probe with a Sandbox OAuth access token. Google Ads discovered manager `300-995-1352` and verified it as a test account with currency `USD` and timezone `America/Denver`. The discovery request ID was `9GSDxBnZ9l-l8oUG02Vl0g` and the verification request ID was `enPHEzW8LRwlH5LL35p-kw`.

1. Enable Google Ads API in the dev Google Cloud project. Configure a test OAuth client and sign in with a Google user who can access the Ads test account. Obtain a short-lived access token for `https://www.googleapis.com/auth/adwords` using that client's OAuth flow. [Google quickstart](https://developers.google.com/google-ads/api/docs/get-started/make-first-call) · [User authorization](https://developers.google.com/google-ads/api/rest/auth#user_authentication)
2. Use a Google Ads test client. If using a test manager, pass its ID to route the client read through it. Google lists directly accessible accounts in discovery, so a manager-routed check expects the manager there and verifies the client in the next request. [Test accounts](https://developers.google.com/google-ads/api/docs/best-practices/test-accounts) · [Account discovery](https://developers.google.com/google-ads/api/reference/rpc/v26/CustomerService/ListAccessibleCustomers)
3. Run the probe and enter the access token at its hidden terminal prompt. Omit `--manager` for direct access.

   ```sh
   python3 scripts/google_ads_phase0.py --customer TEST_CLIENT_ID --manager TEST_MANAGER_ID
   ```

   To verify an existing manager before creating a test client, use the same OAuth sign-in and run:

   ```sh
   python3 scripts/google_ads_phase0.py --verify-manager TEST_MANAGER_ID
   ```

4. Record the outcome, request IDs, verified test status, currency, and timezone. The probe checks discovery and requires a test account of the requested type. Keep tokens and credentials out of the record. Serving, billing, and production reporting require separate evidence. [Test account limitations](https://developers.google.com/google-ads/api/docs/best-practices/test-accounts)

## Two-advertiser Sandbox suite

The suite verifies manager `3009951352`, discovers direct child accounts `6271196703` (Tenant A) and `5993800994` (Tenant B), and requires both to be test advertisers with USD and `America/Denver` before any write. Use a public HTTPS Junior Bay landing page that fits the Search ad copy.

```sh
python3 scripts/google_ads_phase0.py --sandbox-suite --manager 3009951352 \
  --tenant-a 6271196703 --tenant-b 5993800994 --final-url 'https://juniorbay.com/'
```

The suite validates the request, creates a uniquely named paused Search campaign in Tenant A, and reads back the campaign and its $5 average daily budget. Creation is atomic and includes a Search ad group, two exact-match keywords, and a paused responsive search ad. The suite enables the campaign and confirms the status, then pauses it and confirms the final status. Each run creates a new campaign, so look up the printed name before rerunning after an uncertain response. [Google Search campaign guide](https://developers.google.com/google-ads/api/docs/campaigns/search-campaigns/getting-started)

The fixture attempts to pause Tenant A's campaign as Tenant B and requires the script's ownership check to reject it before a provider call. This exercises the local boundary with the supplied advertiser IDs. The deployed Junior Bay authorization check is a separate result recorded under Step 8 in the Advertising Primitive plan. The Ads manager's OAuth grant spans both Sandbox advertisers.

### Live results

The operator reported a successful Sandbox run on November 23, 2026. Google returned both advertisers as direct children of the test manager. Each advertiser was verified with `test_account = true`, `manager = false`, `USD`, and `America/Denver`. Tenant A's campaign `Junior Bay Sandbox Promo 13f8efea57e7` is `customers/6271196703/campaigns/24534976743`.

| Check | Result | Google request ID |
| --- | --- | --- |
| Discover both advertisers | Passed | `41Z7sYNLRiTyGvg8A-Bc8g` |
| Verify Tenant A and Tenant B | Passed | `8QrqzVqQZivnFn6Zs-qpA`, `XwMD98cDCrMzSVHT8j4N4A` |
| Validate Search campaign request | Passed | `4QroOatPlxsHLC0O3uSNDA` |
| Create paused campaign, budget, ad group, two keywords, and responsive search ad | Passed | `RwtqIgJpoE3UH1e5mrFF3A` |
| Read back initial paused status and $5 average daily budget | Passed | `8M0Rcgk5a0_UrX-37AYf8A` |
| Block Tenant B's attempt to pause Tenant A's campaign | Passed in the local fixture | No provider request |
| Enable campaign and read back enabled status | Passed | `0dYgzr9Pcotn_kPGSoTtrg`, `ulXRiCJekofwEGaW2Yguzg` |
| Pause campaign and read back paused status and $5 average daily budget | Passed | `7elt5qq45zOdSvCTSazTYg`, `7G7Qn0b5tq4Cl0Wy-xpl-A` |

The campaign finished paused and the ad stayed paused throughout.

## Draft for Google Ads API Compliance

Junior Bay is preparing a hosted dashboard for merchants who want to promote their published landing pages. The initial pilot uses existing advertiser accounts and Google Search campaigns. Each advertiser signs in directly with Google, selects an authorized Ads account, and approves the exact campaign, destination, budget, and end date in Junior Bay. Google bills the advertiser for media spend. Junior Bay displays Google Ads cost and performance and lets the advertiser disconnect access.

Could you confirm the Google Cloud project ownership, OAuth and consent verification, production API access tier, and Required Minimum Functionality for this workflow? We also want to confirm whether Junior Bay may execute a signed-in advertiser's approved create, enable, or pause request through a background worker. Please clarify whether an approved native campaign end date can be supplemented by a scheduled pause and status reconciliation when the advertiser has signed out, and whether any of those operations require separate review. Junior Bay uses its own dashboard for the workflow and keeps the Google Ads integration private to the service.

Submission is pending. Google's published compliance contact form currently requests a manager customer ID. [Google Ads API Compliance contact](https://support.google.com/adspolicy/contact/contact_ads_api)

# Advertising Primitive

**Status** — Sandbox OAuth verification passed. Campaign workflow, Promo Mode, and experiment lifecycle deployed to dev. Step 8 end-to-end Sandbox acceptance passed on November 25, 2026. Next gate: Google's production policy confirmation, then the controlled live beta.

**Dashboard** — Attention → Ad Campaigns

**First provider** — Google Ads Search

Junior Bay helps a tenant turn a published Site page and offer into a paid Search campaign, approve a budget, and see what the campaign delivered. Start with existing tenant-owned Google Ads accounts. Google bills the tenant for media directly. Junior Bay owns the campaign workflow, approval records, and the connection between advertising and commerce outcomes.

## 1. Product scope

Use the existing **Ad Campaigns** menu entry. The pilot needs a campaign list, an account connection flow, a launch wizard, and campaign details with reporting and pause controls. Add more navigation when those workflows need it. Keep organic scheduling in **Media Poster** and use the Video Gallery for tenant-owned creative in later campaign formats. References to a video identify the asset by its durable job or asset ID. The gallery's signed playback URL is temporary.

Pilot with one USD Search campaign per tenant, one ad group, one responsive search ad, phrase and exact keywords, negatives, and explicit location targeting. Bind each campaign to an existing tenant-owned published page and its offer or Site. Start with lead capture and purchases as objectives. A booking or webinar page can be the destination when the corresponding confirmation can be measured reliably. Show the approved destination, responsive ad assets, geography, bidding, budget, and measurement status together. Keep AI copy suggestions editable and include them in the approval preview. Limit the pilot to supported advertiser categories and targeting options. Set network and location-presence options explicitly, and verify objective-specific bid settings in the test account. Use conversion-based bidding only after the conversion action has been validated. [Google Search campaign guide](https://developers.google.com/google-ads/api/docs/campaigns/search-campaigns/getting-started)

Shopping is the next candidate for stores with a ready catalog. Plan a Merchant Center connection, Merchant API product synchronization, shipping and returns data, website verification where applicable, and a diagnostics workflow before selecting a campaign type. Evaluate Performance Max and YouTube campaign creation independently. Treat Maps as an eligible placement and Local Services Ads as a separate eligibility and API investigation. Reassess Meta, TikTok, LinkedIn, Pinterest, Quora, and Reddit when pilot data identifies a second provider. [Merchant API](https://developers.google.com/merchant/api)

### Guided Promo Mode

The tenant picks a published page, confirms the goal and service area, and chooses a test duration. Junior Bay uses the page, offer, Site location or shipping coverage, and offer semantic model to draft the ad. Prepare suggested keywords and negatives, responsive headlines and descriptions, targeting, bidding settings, and the proposed conversion action. Ask for missing facts, and flag settings or measurement that need attention. For example, a tenant promoting a massage booking page can confirm Google Search, bookings, and St. George, Utah, then review the prepared campaign.

Show the ad preview, destination, target area, planned end, nominal test spend, usual Google spending limits, and tracking readiness in a single approval review. Label the Google setting **$5 average daily budget** throughout setup, approval, and reporting. Explain next to the setting that Google can spend more than $5 on an individual day. The estimate is budget multiplied by days and actual spend can vary. Make suggestions editable and show detailed settings in the review. Save the exact configuration the tenant approves, including the stop date. Revalidate edits and require renewed approval when changed settings affect what can serve or spend.

The Step 6 Test-mode interface lets a tenant select a connected USD test advertiser and a published landing page with a linked offer, save and edit Search creative, and approve a specific draft revision for paused creation. Launch, pause, and uncertain-operation reconciliation use the existing campaign workflow. The budget review uses a 7-, 14-, or 30-day estimate with 14 days selected initially. Step 7 adds approved date ranges, scheduled stops, first-party attribution, and provider reporting. Test campaigns cannot serve and Junior Bay management fee collection is disabled.

### Advertiser onboarding

Keep the controlled pilot on existing tenant-owned accounts. Before the Growth commercial release, provide a resumable checklist for first-time advertisers covering account creation in Google, direct billing setup, advertiser verification, account connection, and readiness checks. Link to the relevant Google steps, explain pending or failed checks, and allow tenants to return and recheck after finishing in Google. Keep the campaign draft available during setup. Enable launch once required account checks pass. Explore account provisioning through APIs separately when production access and the approved operating model support it.

## 2. Junior Bay architecture

| Owner | Responsibility |
| --- | --- |
| `stripe-link` dashboard | Render Ad Campaigns and use the existing authenticated API client. Resolve the sibling API by release channel through the existing Attention configuration. |
| `../attention` | Host Advertising Core, a private provider registry, and the Google Ads adapter. Paid campaigns own their records, worker, queue, permissions, and schedules separately from organic publishing. |
| `stripe-link` commerce | Own Sites, Pages, Offers, leads, orders, and booking or webinar confirmations. Extend Attention's scoped, read-only integration for destination validation. Export verified commerce outcomes through a narrow internal event contract when provider measurement is added. |
| `stripe-link` platform billing | Own Junior Bay subscription entitlements, invoice issuance, and payment status. Use the platform's Stripe customer and billing flow. |
| Google Ads | Own advertiser accounts, media billing, review, serving, budgets, and provider reporting. |

This placement follows the existing Attention service boundary and keeps Google calls and their workers out of the commerce runtime. Use shared Cognito identity for the dashboard and resolve tenant ownership from verified claims. Add an explicit Ads beta capability and check it on the API and worker before actions that enable or increase spend. Keep a stop path for authorized account owners after downgrades and feature shutdowns. Apply restrictive defaults if identity, entitlement, or account state cannot be verified. [Attention service boundary](ATTENTION_PRIMITIVE.md) · [Platform entitlement model](SAAS_BILLING_PAYWALL.md)

Keep the AWS release channel distinct from the dashboard's Test/Live data mode. In dev and in Test mode, require a provider-verified Google test account and recheck that condition before mutations. Permit real serving only from the production release in Live mode with a pilot grant, a verified live customer, and an approved launch revision. Key records and background jobs by tenant and mode within each release. Use separate Google Cloud OAuth projects and credentials for dev and prod. [Google Ads test accounts](https://developers.google.com/google-ads/api/docs/best-practices/test-accounts)

### Advertising Core and provider registry

Advertising Core owns campaign state and approval, budgets and experiment schedules, entitlements, the spend ledger and fee calculation, reporting, and conversion routing. The private registry selects an adapter by provider key. Register Google Ads first and expose only supported capabilities for the connected account. Keep provider calls behind a typed internal contract. Each adapter owns authorization, native configuration schemas, provider validation, resource translation, and error mapping.

| Contract area | Required operations |
| --- | --- |
| Capabilities and connections | `get_capabilities`, `begin_connection`, `complete_connection`, `list_accounts`, `get_account_status`, `disconnect` |
| Campaign preparation | `validate_campaign`, `create_paused_campaign`, `update_campaign` |
| Serving and reconciliation | `launch_campaign`, `pause_campaign`, `get_campaign_status`, `reconcile_operation` |
| Reporting and measurement | `get_campaign_metrics`, `get_spend`, and supported conversion configuration or delivery through the appropriate provider API |

Resolve capabilities for the connected account and campaign type. Include supported objectives, configuration schema version, creative formats, targeting options, currency and budget semantics, minima, end-date support, conversion methods, reporting granularity, and allowed operations. Surface unsupported operations explicitly. Use a common operation context with tenant, mode, account, campaign revision, and idempotency key. Normalize outcomes such as applied, rejected, retryable, and unknown, while retaining the provider request ID and redacted diagnostics.

Store the common campaign separately from its versioned provider configuration. Common fields cover ownership, destination, objective, schedule, approved budget and currency, and lifecycle state. A Google Search configuration can hold keywords, negatives, and responsive search ad assets. A future Meta configuration can hold audiences, placements, and Meta creative. During Phase 1, run the core contract suite with a test adapter that requires audience and creative fields. The test should prove a second provider can use campaign approval, entitlements, fees, and reporting through the same core contracts.

### Internal API and records

Use authenticated routes under `/me/ads` for connections, account selection, validation, campaigns, approvals, pause/resume, and reporting. The provider callback consumes a short-lived, single-use OAuth state bound to the tenant, initiating user, release, mode, and redirect. Keep OAuth credentials and provider access on the server. Keep the provider adapter private to the service and expose Junior Bay operations on approved destinations through the dashboard. Limit any later programmatic surface to a separately reviewed use case. [Google Ads developer policies](https://support.google.com/adspolicy/answer/6169371)

Use `https://prod.juniorbay.com/ads/google/callback` as the exact OAuth redirect URI for **Junior Bay Ads Prod**. In step 3, route the public callback to Attention and verify the deployed route with the registered URI before testing the connection. Use the `/ads/{provider}/callback` convention for future providers, such as `/ads/meta/callback` and `/ads/tiktok/callback`. Maintain separate redirect configuration for Sandbox.

The Sandbox web OAuth client uses `https://dev.juniorbay.com/ads/google/callback`. The Attention stack maps the `ads` base path on each existing API custom domain to its release stage. Configure `GoogleAdsOAuthSecretArn` with the release-specific Secrets Manager secret containing `client_id` and `client_secret`; the template provisions a KMS key for encrypted tenant grants. The dev deployment must have the API custom domain in place and a pilot tenant with an explicit Ads beta grant. [API Gateway base path mappings](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-mappings.html)

The dashboard starts OAuth from Test mode, opens Google consent, and finishes the connection from the original dashboard tab. The callback consumes expiring state and uses PKCE. The finish request requires the initiating Cognito subject, tenant, mode, and a one-time proof held in that tab. The dashboard can discover test advertisers directly accessible to the Google identity or under its test manager, select a verified advertiser, and disconnect the local grant. Disconnect removes Junior Bay's encrypted token and disables operation authorization for that connection while preserving the account ownership record for reconnect. Reconnect permits the same tenant to rebind a verified account to its new connection. Only Test mode is enabled during this implementation slice.

Dev deployment smoke checks confirmed that the Sandbox dashboard serves the updated build, the public callback reaches Attention, and both Ads connection routes allow the dashboard's exact CORS preflight headers, including `X-Stripe-Mode`. The browser can read the 401 response if the request lacks a Cognito token. On November 24, 2026, Google accepted both distinct Ads OAuth client credential pairs at its token endpoint. A synthetic authorization code returned `invalid_grant` for each stored pair and an incorrect-secret control returned `invalid_client`. The dev callback rejected missing and unknown OAuth state with 400. The signed-in dev pilot completed Google consent, token exchange, and dashboard confirmation. The dashboard then discovered both test advertisers and selected `6271196703`. A scoped database read verified the active connection and the selected advertiser's test status, USD currency, and `America/Denver` timezone. Advertiser `5993800994` remains unbound for the separate-tenant acceptance test. The pilot disconnected and reauthorized through the dashboard, then reselected the same advertiser. A scoped database read verified that the original connection was disconnected and advertiser `6271196703` was bound to the new active connection. The live Sandbox OAuth reconnect check passed. The production callback is undeployed.

| Record | Data to keep |
| --- | --- |
| Connection and account | Encrypted refresh token reference, consented scopes, customer and optional manager IDs, currency, timezone, provider test-account flag, last verified access. Store OAuth app secrets in Secrets Manager and use KMS encryption with scoped permissions for tenant grants. |
| Campaign and approval | Destination IDs and URL, normalized objective, schedule, immutable approved revision, approver and time, and desired and observed state. |
| Provider configuration and resources | Provider key, schema version, native configuration, and native resource IDs keyed to the campaign and provider account. |
| Operation and audit | Tenant-scoped idempotency key, expected campaign revision, attempt and outcome, Google request ID, redacted error, ordered transition log, and reconciliation status. |
| Daily metrics | Provider account-local day, campaign ID, impressions, clicks, integer cost micros, reported conversions and value, sync time, and source. Keep Google-attributed metrics and Junior Bay-observed outcomes separately labeled. |
| Spend ledger and management terms | Provider-reported media spend, management period, versioned fee terms, adjustments, reconciliation and invoice references. See section 6. |

Use conditional writes to reserve the pilot's one active or launching slot and prevent two concurrent launches. Keep it reserved until provider state confirms the campaign cannot serve. Configure retries with bounded backoff, a dead-letter queue, and alerts for unresolved operations. Built on dev November 25, 2026: the `jb-attention-ads-alerts-<env>` SNS topic, with an email subscription set by the `AdsAlertEmail` deploy parameter, receives alarms for the failure queue, unexpected worker errors, jobs ending in reconciliation, provider drift, and scheduled stops unconfirmed 30 minutes after the approved end. Encrypt and redact secrets and click identifiers. Use a controlled, audited association for each provider customer under a tenant. Design any agency or shared-account ownership model separately.

The first Ads storage slice uses a dedicated Attention DynamoDB table. Its tenant partition includes the explicit data mode. A transactional ownership record reserves each provider customer once per release. Store writes conditionally check account ownership and campaign revision, and operation authorization rechecks the reserved operation, current revision, approval, and binding before dispatch. The initial Cognito-protected account and campaign read routes require an explicit Ads pilot grant and Test mode. Read responses expose the tenant's review configuration and campaign state. Provider credentials and native campaign resource IDs stay internal.

Step 5 adds the Sandbox campaign write routes and a worker driven by the Ads table stream. Drafts derive their destination from the tenant's published offer page on the release's test host. Approval records the exact revision and atomically queues paused creation. Launch and pause use separate jobs. The worker claims each campaign conditionally, rechecks current entitlement and destination, and confirms Google's campaign status. Launch checks the approved creative, keywords, and dedicated average daily budget before enabling the campaign and its reviewed ad. A queued pause supersedes a stale launch, and a confirmed stop releases capacity. Uncertain creation uses the original operation marker for read-only reconciliation. The connection stays available for pause while campaigns hold capacity. [DynamoDB stream filtering](https://docs.aws.amazon.com/lambda/latest/dg/with-ddb-filtering.html) · [Google Ads status updates](https://developers.google.com/google-ads/api/rest/common/mutate)

## 3. Google access and launch

1. Enable the Google Ads API in Google Cloud. The September 9, 2026 migration moved access levels to the OAuth application's Cloud project. Use Test access for development and apply for Explorer or a higher level as the pilot's operations and quotas require. An MCC, Google's manager account, is optional for directly authorized existing customers. Use `login-customer-id` when calling through an authorized manager. Explorer restricts account creation/linking, keyword planning, and billing operations, so the pilot relies on existing accounts and tenant-entered or Junior Bay-suggested keywords. [Developer token migration](https://developers.google.com/google-ads/api/docs/api-policy/developer-token) · [Access levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels) · [Authorization and headers](https://developers.google.com/google-ads/api/rest/auth)
2. Use user OAuth with `https://www.googleapis.com/auth/adwords`. Plan for advertiser-owned Google Cloud access and direct advertiser sign-in, pending Google's review of Junior Bay's hosted workflow. Confirm brand and consent verification, permitted operations, and the applicable Required Minimum Functionality with Google. Document the confirmed setup and reflect it in onboarding before using external production accounts. [Developer policies](https://support.google.com/adspolicy/answer/6169371) · [OAuth setup](https://developers.google.com/google-ads/api/docs/oauth/cloud-project)
3. Discover accounts and verify write access, customer currency, provider mode, account status, and the selected destination. Check billing and advertiser verification through the fields available to the approved access level and guide the tenant to Google for any remaining steps. Validate the public HTTPS page, CTA, identity, privacy disclosures, and relevant offer terms. Surface policy review and serving status separately from the campaign's configured status.
4. Record approval against the exact campaign revision. Use `validate_only` and then a single atomic Google Ads mutation with partial failure disabled for budget, campaign, group, criteria, and ad creation. Give the campaign and budget a stable Junior Bay operation marker and create the campaign paused. Persist native IDs, reconcile the paused configuration, and recheck the approval before enabling in a separate step. An ambiguous creation response moves to reconciliation. Look up the operation marker and leave unresolved cases for review before retrying. Serialize operations per campaign, and give pause precedence over stale launch or resume work. [Atomic Search creation](https://developers.google.com/google-ads/api/docs/campaigns/search-campaigns/getting-started) · [Mutate reference](https://developers.google.com/google-ads/api/reference/rpc/v26/GoogleAdsService/Mutate)

Pin a supported API version during the spike and assign responsibility for upgrades and quota monitoring. Use provider request IDs for support. The same account and campaign should be inspectable in Google Ads.

## 4. Budget and reporting

The pilot proposes **$5 USD average daily budget** on a dedicated, non-shared campaign budget. For most campaigns at an unchanged $5 average, Google's usual limits are $10 on an individual day and $152 over a full month. Label these as Google budget rules, and keep the proposal's $150 figure solely as a potential management-fee allowance. Disclose the impact of budget changes, reporting lag, and delayed pauses before approval. [Google Ads budget guidance](https://support.google.com/google-ads/answer/6385083)

Poll managed account and campaign settings on a quota-aware schedule. External edits remain visible. If a native budget increase invalidates approval, alert the tenant and follow their expressly authorized pause preference. Track a requested pause until Google confirms it. On a failed pause or loss of access, show the unresolved status and link to the campaign in Google Ads. A disconnect prompt offers pause and confirmation before revocation, reports the outcome, and explains that ads can continue serving in Google. Keep unrelated native campaigns out of managed mutations and fee calculations.

Built on dev November 26, 2026. A launch creates a watch record on the due-work index. The scheduler re-reads Google's campaign status and budget every 15 minutes while the campaign can serve, then every 6 hours after the pause, until the 7-day report settling window ends. It records drift when the budget is raised above the approved amount, the budget is replaced or shared, the campaign is re-enabled after Junior Bay paused it, or access is revoked. The drift record mirrors the latest successful read: a clean read clears it, and a failed read leaves it unchanged. Approval carries an opt-in `auto_pause_on_change`. When it is set, new drift queues a pause, except for lost access, which cannot be paused from Junior Bay. Each new drift code emails the tenant owner once from the platform SES sender and fires an ops alert. A failed email is retried on the next read. Drift blocks relaunch, and the dashboard shows what changed on the campaign and in the list.

### Promo experiment lifecycle

Offer finite test durations and default to 14 days. Show the nominal estimate alongside Google's budget disclosure.

| Approved duration | Nominal spend at $5 per day |
| --- | ---: |
| 7 days | $35 |
| 14 days | $70 |
| 30 days | $150 |

These estimates use budget × approved days. Actual charges and serving time depend on Google. Record the approved start and end using the advertising account's timezone. Confirm inclusive provider date semantics and show the actual planned dates before approval. Use the provider's native end date when its behavior has been verified. Schedule a durable stop and reconciliation in Junior Bay, track the result until the provider confirms serving has stopped, and notify the tenant if confirmation fails. Report time lost to review or delayed serving. Require explicit approval for an extension or a new run.

At completion, show actual spend, serving dates, impressions, clicks, measured outcomes, and tracking or reporting gaps. Refresh the summary when delayed metrics arrive. Explain when the data is insufficient and suggest a next action suited to what was observed. Keep the campaign paused until the tenant approves another run. Offer Scale when the observed results support additional investment.

Report clicks, impressions, provider cost, CTR and CPC when available. Add conversion rate, CPA and ROAS only once conversion tracking and value are reliable. Show account-local dates, last sync, partial or stale data, and the basis of each measurement. Compare Google Ads reporting to Google Ads source data and keep Junior Bay orders and leads visible separately. [Google Ads conversion reporting](https://developers.google.com/google-ads/api/docs/conversions/reporting)

Step 7 stores the approved advertiser-local start date and last day with the immutable draft revision. Launch is manual within the approved window. Junior Bay arms the stop before queuing launch and requests pause at midnight after the last day using a recurring five-minute worker. A pending or ambiguous pause stays visible until Google confirms it. The worker retries recoverable stops and the dashboard links to Google Ads for manual follow-up. Another experiment requires a new approved campaign. Native end dates remain a Sandbox acceptance item.

The results show Google activity by account-local date, sync status, actual impression dates when present, and confirmed activation and pause times. The worker refreshes recent reports after confirmation to capture revisions and imports post-stop provider cost into the spend ledger. Fee attribution remains held where the billing timezone or management boundary is unresolved. Campaign links use a unique Junior Bay source to report landing page arrivals and attributed paid orders separately from Google activity. Google conversion actions, lead and booking attribution, and performance-based recommendations remain behind live measurement verification.

### Advertising recommendations

Keep a place for future advisory recommendations in campaign details. Derive them from synced metrics, conversion diagnostics, destination checks, and catalog readiness. Record evidence, data freshness, and the proposed action. Initial examples include checking a misconfigured conversion action, reviewing a landing page after enough traffic, or evaluating Shopping readiness. A budget-increase recommendation requires sufficient conversion and value data, and any increase uses the existing approval workflow. Defer automated optimization and provider writes from recommendations.

## 5. Conversion measurement

Reuse Attention's `?src=` attribution for Junior Bay reporting by assigning an opaque campaign source to the final URL. Use the existing published page and checkout attribution path to connect arrivals to orders. Confirm lead and appointment attribution in the pilot, including across custom domains and checkout redirects. Treat the source marker as first-party campaign attribution. Use Google conversion actions and an individually verified measurement path for bidding. [Attention attribution, section 8](ATTENTION_PRIMITIVE.md)

Start with a tenant-configured Google website conversion action or a verified GA4 import. Confirm the correct action and that it records the intended outcome, then use the Paid ads page goal and the page's existing analytics surface where appropriate. Source purchase success from a confirmed paid order and use saved lead or confirmed booking or webinar records as the event source. Define one primary conversion action per objective. Retain permitted click identifiers only with the applicable consent and retention limits. Keep private lead fields, booking details, and contact data out of the initial export. [Landing-page goals](LANDING_PAGE_GOAL_COMPOSITION.md)

New Google offline conversion imports use the **Data Manager API**. Validate authorization, identifiers, destination and consent before implementing transfers, deduplicate by the stable event or order ID and conversion action, and track asynchronous diagnostics and adjustments. Review enhanced conversions and any customer-data sharing as a separate privacy decision. [Google offline conversion migration](https://developers.google.com/google-ads/api/docs/conversions/upload-offline) · [Data Manager API](https://developers.google.com/data-manager/api/devguides/events/google-ads/offline)

## 6. Entitlements and spend ledger

Build entitlement resolution, spend capture, fee calculation, and invoice reconciliation records in step 4. Keep media payment direct to each provider. Give pilot tenants explicit, expiring beta grants through the existing entitlement mechanism. Run the ledger and fee calculation during the pilot for internal reconciliation, with management fee collection disabled. Invoicing requires separately enabled collection and accepted commercial terms.

### Configurable entitlements

Resolve effective Ads permissions server-side from the tenant's configured platform entitlements and any time-limited beta grant. Enforce them at request and execution time. Plan names are display and packaging choices. Store budget and allowance in USD micros and fee rates in basis points. Provider constraints and operational limits apply in addition to the entitlement.

| Proposed configuration | Starter | Growth | Scale |
| --- | --- | --- | --- |
| Monthly price | $19 | $49 | $99 |
| Advertising access | No | Yes | Yes |
| Promo Mode | No | Yes | Yes |
| Active or launching campaigns | 0 | 1 | Provider and operational limits |
| Average daily budget limit | — | $5 | Configurable |
| Monthly fee allowance | — | $150 | $150 |
| Management fee above allowance | — | 0% | 10% |
| Advanced campaign types | No | No | Yes, when supported |

Set `entitlements.ads` on the platform plan and configure `ads.mode`, `max_active_campaigns`, `max_average_daily_budget_micros`, `monthly_fee_allowance_micros`, `management_fee_bps`, and `advanced_campaign_types` in its Ads policy. The subscription webhook copies the settings to the tenant's `ads_subscription` snapshot, preserving the effective date when the terms are unchanged. Attention checks the current paid snapshot or an explicit `ads_pilot_expires_at` grant when reserving or authorizing a launch. A legacy Sandbox grant still allows discovery and account selection. It needs an expiry to reserve campaign capacity. Treat prices and any add-on as packaging proposals. Evaluate them alongside the existing $29 Pro tier and pilot economics before creating SKUs.

### Provider-independent spend ledger

Record tenant, mode, provider, account, campaign, currency, provider reporting day and timezone, billing period, source revision, and media cost. Associate spend with an authorized management period and a snapshot of the applicable fee terms. Record eligible spend, credits and adjustments, reconciliation status, and any invoice reference. Keep source cost, taxable or non-media charges, and Junior Bay fees distinct. Restrict fee calculations to USD and authorized managed spend. Apply an upgrade from its effective time, and keep earlier Growth spend outside Scale fee calculations.

Upsert provisional spend idempotently by provider, account, campaign, currency, and reporting day. Retain revision and adjustment history. At month close, reconcile provider totals, apply one allowance per tenant, and record the calculation and source revisions used. Resolve the billing timezone and provider day-boundary rule before invoicing, and hold unresolved boundary or attribution rows for review. Preserve issued records and apply late corrections as linked adjustments. Use a tenant-and-period idempotency key when the platform Stripe billing flow issues an approved invoice. Design payment failure, notification, and pause handling before enabling charging.

For example, $500 in Google Ads, $300 in Meta, and $200 in TikTok yield $1,000 of eligible Scale spend. A single $150 allowance leaves $850, so the proposed 10% fee is $85. With a $99 subscription, Junior Bay revenue would be $184, excluding taxes and costs. Show the fee separately from provider media cost, disclose it in writing before the first purchase, and itemize it on the invoice. Include the applicable advertiser disclosures. [Google third-party transparency requirements](https://support.google.com/adspolicy/answer/16489093)

The internal ledger keeps the raw spend and credits, current report revision, immutable prior revisions, and reconciliation calculations. It holds rows that cross an unresolved billing or management boundary. Reconciliation compares gross spend by provider and currency with source totals. A single monthly allowance applies across fee-bearing USD spend in provider-day order, with a stable provider and campaign order for ties. Adjustments link to earlier calculations and use the last reconciled fee as their baseline. Reconciliation records carry `collection_enabled: false` and no invoice ID. Step 5 wires campaign activation and confirmed stops to the capacity and management records. Step 7 wires provider reporting into the ledger.

## 7. Implementation sequence and release gates

| Phase | Deliverable and exit criteria |
| --- | --- |
| 0 | **Google access and policy verification.** Test OAuth and account selection succeed. Confirm the production access, tenant authorization, and supported Search management model with Google. [Phase 0 verification record](ADS_PHASE_0.md) |
| 1 | **Advertising Core and provider contract.** Implement the private registry, typed operations, and Google Search adapter. Exercise the contract with a second test adapter carrying its own configuration. Verify capability checks, average daily budget semantics, redacted provider outcomes, and reconciliation of ambiguous writes. |
| 2 | **Database models and tenant authorization.** Store tenant- and mode-scoped connections, campaigns, bindings, approvals, and operations. Resolve identity from verified claims and check ownership at both API and worker boundaries. Verify conditional writes and rejection of mismatched account, tenant, mode, and revision. |
| 3 | **Native Google OAuth.** Connect and disconnect from Junior Bay using single-use state and encrypted tenant grants. Verify account discovery, access, revocation, and reconnect in Sandbox. |
| 4 | **Subscription entitlements and monetization.** Implement entitlement checks, campaign slot reservation, idempotent spend import, cross-provider fee calculation, and invoice reconciliation with collection disabled. |
| 5 | **Campaign creation and approval.** Draft from a published page and offer. Require approval of an immutable revision, reconcile paused creation, and verify launch and pause. Test conflicting revisions, simultaneous launches, wrong-mode accounts, and ambiguous timeouts. |
| 6 | **Promo Mode interface.** Verify the review, approval, and campaign detail screens label the Google setting as an average daily budget and explain spend can exceed the configured average on a particular day. Label duration-based totals as estimates. |
| 7 | **Experiment lifecycle and reporting.** Verify planned stop, stop confirmation, timeout recovery, tracking, reporting, and experiment summary. |
| 8 | **End-to-end Sandbox acceptance.** Use two signed-in tenant identities against deployed Attention routes. Verify each can access its own Ads data and that Tenant B cannot read or mutate Tenant A's resources or enqueue a provider job for them. Verify the authorized $5 average daily budget readback and tenant-facing copy. |

Record the script-level cross-tenant result and the deployed check separately. The Phase 0 fixture proved the script blocked Tenant B before calling Google. The deployed acceptance evidence must exercise verified Junior Bay identity, persisted account ownership, and operation dispatch. Google’s Sandbox readback confirms a 5,000,000-micros USD average daily budget setting. It provides no evidence of a hard daily spend limit or of actual charges. [Phase 0 results](ADS_PHASE_0.md#live-results)

### Step 8 deployed Sandbox acceptance

On November 25, 2026, the dev Attention stack and dashboard were updated. The deployed health endpoint, CORS preflight, unauthenticated list and pause denial, and callback rejection without OAuth state passed. The served dashboard bundle matched the local build, and the dev scheduler index is active and queryable. Tenant A had an existing advertiser binding and received a seven-day dev pilot grant. The current Tenant B fixture resolves to a separate confirmed Cognito login with a dev tenant profile. Both tenants have active dev pilot grants. Tenant B has a connected Stripe test account. Advertiser `5993800994` is bound to Tenant B. Both tenants have eligible published Test-mode pages and saved Search drafts at 5,000,000 USD micros average daily budget. The first approval jobs rejected the stored bids before a Google request. The Google adapter now handles whole-number DynamoDB decimals, covered by an adapter test with a storage round trip. The rejected revisions remain in audit history. Both tenants saved new revisions and exercised the approved launch and pause in Junior Bay. The worker confirmed each $5 average daily budget during activation.

| Tenant | Google advertiser | Google campaign | Confirmed pause request ID |
| --- | --- | --- | --- |
| A | `6271196703` | `24556290874` | `3pOkkG4XbkX-dQP3SIImXQ` |
| B | `5993800994` | `24550107803` | `V07KXYDhR1eV1XSq0YxZ4A` |

The signed-in deployed check passed in both directions on November 25. Both tenants could access their own account and campaign. Each was denied when reading or pausing the other tenant's campaign. Strongly consistent dev table reads found no workflow job for either denied pause. The dashboard showed $5 as an average daily budget and $70 as the 14-day estimate. The full acceptance runner then passed, including independent Google readback: both campaigns are paused with a dedicated, unshared 5,000,000-micros USD average daily budget. Step 8 is complete.

The dashboard currently hides the Live/Test data-mode switch and restores Live mode without test Stripe configuration. That also hides Ad Campaigns, even though the Google Ads Sandbox requires an Ads entitlement and a Google test advertiser. A product follow-up should give eligible tenants access to Ads Test mode independently of Stripe onboarding, while keeping checkout and payment actions gated on Stripe configuration.

To reproduce the setup, use the dev dashboard in Test mode with separate signed-in Junior Bay tenants. Assign Google advertiser `6271196703` to Tenant A and `5993800994` to Tenant B. Each tenant needs an active Test-mode Ads pilot grant and a published test landing page linked to an offer. Approve and launch the $5 Search campaign for each tenant. Confirm a pause through Junior Bay and capture the budget wording and Google result from campaign details.

To repeat the acceptance, run `python3 scripts/google_ads_sandbox_acceptance.py` from the Junior Bay repository once both campaigns are paused. Use `--sign-in` to use Junior Bay dev sign-in with hidden password prompts. Without it, enter the two ID tokens at hidden prompts. Pass `--isolation-only` to run the tenant boundary check separately from the Google readback. It verifies independent account and campaign lists, cross-tenant detail and pause rejection despite a claimed tenant in the request, absence of each rejected request's workflow records through strongly consistent dev table reads, and Google’s dedicated $5 average daily budget on both campaigns. AWS permissions are read-only for this runner. Record the authenticated result and UI evidence separately from the Phase 0 fixture.

After Sandbox acceptance and Google’s production policy confirmation, run a controlled live beta with fee collection disabled. Verify billing and advertiser onboarding, tracking, reporting, spend drift, revoked access, failed pause, and queue recovery. Validate pricing and onboarding before Growth release, then validate commercial terms, upgrades, credits, and payment failure handling before Scale fee collection. Evaluate Shopping, additional Google formats, other providers, and advisory recommendations after the Search pilot.

Track time to first approved campaign, onboarding abandonment, rejection and tracking failure rates, time to confirm pause, support effort, and tenant outcomes against their own goals. Choose thresholds once pilot baselines exist.

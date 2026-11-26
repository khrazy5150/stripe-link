"""Verify Sandbox OAuth, account selection, and test Search campaign operations."""

import argparse
import getpass
import http.client
import json
import re
import sys
import time
import uuid
from urllib.parse import urlsplit


API_VERSION = "v26"
PROMO_BUDGET_MICROS = 5_000_000
EXPECTED_CURRENCY = "USD"
EXPECTED_TIME_ZONE = "America/Denver"
CUSTOMER_QUERY = (
    "SELECT customer.id, customer.test_account, customer.manager, "
    "customer.currency_code, customer.time_zone FROM customer LIMIT 1"
)


class TenantAccessDenied(PermissionError):
    """The Sandbox actor's account does not own the requested campaign."""


def customer_id(value):
    normalized = value.replace("-", "")
    if not re.fullmatch(r"[0-9]{10}", normalized):
        raise argparse.ArgumentTypeError("Expected a ten-digit Google Ads customer ID")
    return normalized


def ads_request(token, path, *, manager=None, query=None, payload=None):
    headers = {"Authorization": f"Bearer {token}"}
    method = "GET"
    body = None
    if manager:
        headers["login-customer-id"] = manager
    if query is not None:
        payload = {"query": query}
    if payload is not None:
        method = "POST"
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload)

    connection = http.client.HTTPSConnection("googleads.googleapis.com", timeout=20)
    try:
        connection.request(method, f"/{API_VERSION}/{path}", body=body, headers=headers)
        response = connection.getresponse()
        request_id = response.getheader("request-id", "unavailable")
        if response.status != 200:
            raise RuntimeError(f"Google Ads returned HTTP {response.status} (request ID {request_id})")
        return json.load(response), request_id
    finally:
        connection.close()


def verify_account(token, customer, manager, *, expect_manager=False, check_discovery=True):
    if check_discovery:
        verify_discovery(token, manager or customer)

    response, selection_id = ads_request(
        token, f"customers/{customer}/googleAds:search", manager=manager, query=CUSTOMER_QUERY
    )
    rows = response.get("results", [])
    account = rows[0].get("customer", {}) if rows else {}
    # Protobuf JSON can omit false-valued booleans.
    account_type = "manager" if expect_manager else "client"
    if (
        str(account.get("id")) != customer
        or account.get("testAccount") is not True
        or account.get("manager", False) is not expect_manager
    ):
        raise RuntimeError(f"Expected a test {account_type} account (request ID {selection_id})")
    print(
        f"Verified test {account_type} {customer} with currency {account.get('currencyCode')} "
        f"and timezone {account.get('timeZone')} (request ID {selection_id})."
    )
    return account


def verify_discovery(token, customer):
    accessible, discovery_id = ads_request(token, "customers:listAccessibleCustomers")
    expected_resource = f"customers/{customer}"
    if expected_resource not in accessible.get("resourceNames", []):
        raise RuntimeError(f"Expected account is absent from OAuth discovery (request ID {discovery_id})")
    print(f"OAuth discovery returned {expected_resource} (request ID {discovery_id}).", flush=True)


def verify_advertisers(token, manager, customers):
    verify_account(token, manager, None, expect_manager=True)
    query = (
        "SELECT customer_client.id FROM customer_client WHERE customer_client.level = 1 "
        f"AND customer_client.id IN ({', '.join(customers)})"
    )
    response, request_id = ads_request(token, f"customers/{manager}/googleAds:search", query=query)
    discovered = {str(row["customerClient"]["id"]) for row in response.get("results", [])}
    if discovered != set(customers):
        missing = ", ".join(sorted(set(customers) - discovered))
        raise RuntimeError(f"Expected direct advertiser accounts are missing: {missing} (request ID {request_id})")
    print(f"Discovered both advertisers: {', '.join(customers)} (request ID {request_id}).")
    for customer in customers:
        account = verify_account(token, customer, manager, check_discovery=False)
        if (account.get("currencyCode"), account.get("timeZone")) != (EXPECTED_CURRENCY, EXPECTED_TIME_ZONE):
            raise RuntimeError(f"Advertiser {customer} must use {EXPECTED_CURRENCY} and {EXPECTED_TIME_ZONE}")


def search_campaign_operations(customer, name, final_url):
    base = f"customers/{customer}"
    budget = f"{base}/campaignBudgets/-1"
    campaign = f"{base}/campaigns/-2"
    ad_group = f"{base}/adGroups/-3"
    return [
        {"campaignBudgetOperation": {"create": {
            "resourceName": budget,
            "name": name,
            "amountMicros": str(PROMO_BUDGET_MICROS),
            "deliveryMethod": "STANDARD",
            "explicitlyShared": False,
        }}},
        {"campaignOperation": {"create": {
            "resourceName": campaign,
            "campaignBudget": budget,
            "name": name,
            "advertisingChannelType": "SEARCH",
            "status": "PAUSED",
            "manualCpc": {},
            "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": True},
            "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
        }}},
        {"adGroupOperation": {"create": {
            "resourceName": ad_group,
            "campaign": campaign,
            "name": "Junior Bay Sandbox Search",
            "status": "ENABLED",
            "type": "SEARCH_STANDARD",
            "cpcBidMicros": "1000000",
        }}},
        *[
            {"adGroupCriterionOperation": {"create": {
                "adGroup": ad_group,
                "status": "ENABLED",
                "keyword": {"text": keyword, "matchType": "EXACT"},
            }}}
            for keyword in ("junior bay", "junior bay landing pages")
        ],
        {"adGroupAdOperation": {"create": {
            "adGroup": ad_group,
            "status": "PAUSED",
            "ad": {
                "finalUrls": [final_url],
                "responsiveSearchAd": {
                    "headlines": [
                        {"text": "Explore Junior Bay"},
                        {"text": "Build a Landing Page"},
                        {"text": "Share Your Offers Online"},
                    ],
                    "descriptions": [
                        {"text": "Learn how Junior Bay helps businesses publish landing pages."},
                        {"text": "Explore tools for building pages and sharing your offers online."},
                    ],
                },
            },
        }}},
    ]


def mutate(token, manager, customer, operations, *, validate_only=False):
    return ads_request(
        token,
        f"customers/{customer}/googleAds:mutate",
        manager=manager,
        payload={"mutateOperations": operations, "partialFailure": False, "validateOnly": validate_only},
    )


def create_search_campaign(token, manager, customer, final_url):
    name = f"Junior Bay Sandbox Promo {uuid.uuid4().hex[:12]}"
    operations = search_campaign_operations(customer, name, final_url)
    print(f"Validating paused campaign {name} in {customer}.", flush=True)
    _, request_id = mutate(token, manager, customer, operations, validate_only=True)
    print(f"Search fixture validated (request ID {request_id}).")
    print(f"Creating {name}. If the result is unclear, look up this name before retrying.", flush=True)
    result, request_id = mutate(token, manager, customer, operations)
    resources = {}
    responses = result.get("mutateOperationResponses", [])
    if len(responses) != len(operations):
        raise RuntimeError(f"Incomplete create response for {name} (request ID {request_id})")
    for operation, item in zip(operations, responses):
        result_key = next(iter(operation)).removesuffix("Operation") + "Result"
        resource = item.get(result_key, {}).get("resourceName")
        if not resource or not resource.startswith(f"customers/{customer}/"):
            raise RuntimeError(f"Missing {result_key} for {name} (request ID {request_id})")
        resources.setdefault(result_key, []).append(resource)
    print(f"Created paused Search campaign, budget, ad group, two keywords, and RSA (request ID {request_id}).")
    return resources["campaignResult"][0], resources["campaignBudgetResult"][0]


def verify_campaign_state(token, manager, customer, campaign, budget, status):
    query = (
        "SELECT campaign.resource_name, campaign.status, campaign_budget.resource_name, "
        f"campaign_budget.amount_micros FROM campaign WHERE campaign.resource_name = '{campaign}'"
    )
    for attempt in range(4):
        if attempt:
            time.sleep(1)
        result, request_id = ads_request(token, f"customers/{customer}/googleAds:search", manager=manager, query=query)
        rows = result.get("results", [])
        if rows and rows[0].get("campaign", {}).get("status") == status:
            linked_budget = rows[0].get("campaignBudget", {})
            if (
                linked_budget.get("resourceName") != budget
                or str(linked_budget.get("amountMicros")) != str(PROMO_BUDGET_MICROS)
            ):
                raise RuntimeError(f"Expected a $5.00 average daily budget (request ID {request_id})")
            print(f"Verified {status} with $5.00 average daily budget (request ID {request_id}).")
            return
    raise RuntimeError(f"Expected campaign status {status} for {campaign} (request ID {request_id})")


def set_tenant_campaign_status(token, manager, tenant_customer, campaign, status):
    # The Sandbox fixture supplies the actor's account independently of the target.
    if not re.fullmatch(rf"customers/{tenant_customer}/campaigns/[0-9]+", campaign):
        raise TenantAccessDenied("The requested campaign does not belong to this tenant fixture")
    _, request_id = mutate(token, manager, tenant_customer, [
        {"campaignOperation": {"update": {"resourceName": campaign, "status": status}, "updateMask": "status"}},
    ])
    print(f"Campaign status set to {status} (request ID {request_id}).")


def run_sandbox_suite(token, manager, tenant_a, tenant_b, final_url):
    verify_advertisers(token, manager, (tenant_a, tenant_b))
    campaign, budget = create_search_campaign(token, manager, tenant_a, final_url)
    print(f"Tenant A campaign: {campaign}", flush=True)
    verify_campaign_state(token, manager, tenant_a, campaign, budget, "PAUSED")

    try:
        set_tenant_campaign_status(token, manager, tenant_b, campaign, "PAUSED")
    except TenantAccessDenied:
        print("Cross-tenant fixture: Tenant B was blocked before contacting Google Ads.")
    else:
        raise RuntimeError("Cross-tenant fixture did not block Tenant B")

    try:
        set_tenant_campaign_status(token, manager, tenant_a, campaign, "ENABLED")
        verify_campaign_state(token, manager, tenant_a, campaign, budget, "ENABLED")
    finally:
        try:
            set_tenant_campaign_status(token, manager, tenant_a, campaign, "PAUSED")
        except (RuntimeError, OSError, http.client.HTTPException, ValueError):
            set_tenant_campaign_status(token, manager, tenant_a, campaign, "PAUSED")
        verify_campaign_state(token, manager, tenant_a, campaign, budget, "PAUSED")
    print("Sandbox suite passed. The Tenant A campaign and its ad are paused.")
    print("Deployed Junior Bay tenant authorization requires a separate check when the Ads routes exist.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--customer", type=customer_id, help="Test client customer ID")
    target.add_argument("--verify-manager", type=customer_id, help="Verify a directly accessible test manager")
    target.add_argument("--sandbox-suite", action="store_true", help="Verify two advertisers and run Search mutations")
    parser.add_argument("--manager", type=customer_id, help="Test manager ID for manager-routed access")
    parser.add_argument("--tenant-a", type=customer_id, help="Tenant A test advertiser for the Sandbox suite")
    parser.add_argument("--tenant-b", type=customer_id, help="Tenant B test advertiser for the Sandbox suite")
    parser.add_argument("--final-url", help="Public HTTPS final URL for the Sandbox responsive search ad")
    args = parser.parse_args()
    if args.verify_manager and args.manager:
        parser.error("--verify-manager checks the specified account directly")
    if args.sandbox_suite:
        if not all((args.manager, args.tenant_a, args.tenant_b, args.final_url)):
            parser.error("--sandbox-suite requires --manager, --tenant-a, --tenant-b, and --final-url")
        if len({args.manager, args.tenant_a, args.tenant_b}) != 3:
            parser.error("Manager and both advertiser customer IDs must be distinct")
        destination = urlsplit(args.final_url)
        if destination.scheme != "https" or not destination.hostname or destination.username is not None:
            parser.error("--final-url must be a public HTTPS URL without credentials")
    elif args.tenant_a or args.tenant_b or args.final_url:
        parser.error("--tenant-a, --tenant-b, and --final-url are only used with --sandbox-suite")
    if not sys.stdin.isatty():
        parser.error("Run in a terminal to enter a short-lived OAuth access token")
    token = getpass.getpass("Google Ads OAuth access token: ").strip()
    if not token:
        parser.error("An OAuth access token is required")
    try:
        if args.sandbox_suite:
            run_sandbox_suite(token, args.manager, args.tenant_a, args.tenant_b, args.final_url)
        else:
            verify_account(
                token, args.verify_manager or args.customer, args.manager, expect_manager=bool(args.verify_manager)
            )
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except (OSError, http.client.HTTPException, ValueError) as error:
        print(f"Google Ads probe failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

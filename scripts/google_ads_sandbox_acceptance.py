"""Check deployed Junior Bay dev isolation with two real Cognito sessions.

Use two approved Sandbox campaigns, one per tenant. Cross-tenant pause requests
check the actual authorization path on campaigns already confirmed paused.
"""

import argparse
import base64
import getpass
from hashlib import sha256
import json
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from google_ads_phase0 import PROMO_BUDGET_MICROS, ads_request, verify_account


DEV_ATTENTION = "https://bjhabjf4q1.execute-api.us-west-2.amazonaws.com/dev"
DEV_LOGIN = "https://dev.juniorbay.com/auth/login"
ADVERTISERS = ("6271196703", "5993800994")
MANAGER = "3009951352"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def tenant_claim(token):
    try:
        segment = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        if claims.get("token_use") != "id":
            raise ValueError
        tenant = next((str(claims[field]).strip() for field in ("custom:client_id", "custom:tenant_id", "sub")
                       if claims.get(field) and str(claims[field]).strip()), "")
        if not tenant:
            raise ValueError
        return tenant
    except (KeyError, ValueError, IndexError) as exc:
        raise RuntimeError("Expected a Junior Bay Cognito ID token") from exc


def sign_in(alias):
    email = input(f"Tenant {alias} Junior Bay dev email: ").strip()
    password = getpass.getpass(f"Tenant {alias} Junior Bay dev password: ")
    login = Request(
        DEV_LOGIN,
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(login, timeout=30) as reply:
            token = json.load(reply).get("session", {}).get("id_token")
    except HTTPError as error:
        raise RuntimeError(f"Tenant {alias} dev sign-in failed (HTTP {error.code})") from None
    require(isinstance(token, str) and bool(token), f"Tenant {alias} dev sign-in did not return an ID token")
    tenant_claim(token)
    print(f"Tenant {alias} signed in.")
    return token


def request(token, path, *, body=None, params=None, expected=200):
    url = DEV_ATTENTION + path + "?" + urlencode({"mode": "test", **(params or {})})
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    request_body = json.dumps(body).encode() if body is not None else None
    try:
        reply = build_opener(NoRedirect()).open(Request(url, data=request_body, headers=headers), timeout=30)
    except HTTPError as error:
        reply = error
    with reply:
        status = reply.code
        data = json.load(reply)
    require(status == expected, f"Expected {expected} from {path}, received {status} ({data.get('error', 'unknown')})")
    return data


def own_campaign(token, own_account, other_account, campaign_id):
    accounts = request(token, "/me/ads/accounts")["accounts"]
    require(any(account["account_id"] == own_account and account["test_account"] is True and account["connected"]
                for account in accounts), f"Expected connected Sandbox advertiser {own_account}")
    require(all(account["account_id"] != other_account for account in accounts),
            "Another tenant's advertiser appeared in the account list")
    listing = request(token, "/me/ads/campaigns")
    require(listing["promo"]["available"], "Expected an active dev Sandbox pilot grant")
    campaigns = listing["campaigns"]
    require(all(campaign["account_id"] != other_account for campaign in campaigns),
            "Another tenant's campaign appeared in the list")
    if not campaign_id:
        campaign_id = next((candidate["campaign_id"] for candidate in campaigns
                            if candidate["account_id"] == own_account and candidate["state"] == "paused"
                            and candidate.get("activation_confirmed_at") and candidate.get("pause_confirmed_at")
                            and candidate["draft"]["budget"]["amount_micros"] == PROMO_BUDGET_MICROS), None)
    require(campaign_id and any(campaign["campaign_id"] == campaign_id for campaign in campaigns),
            "Approve, launch, and pause a $5 Sandbox campaign for this tenant first")
    item = request(token, f"/me/ads/campaigns/{campaign_id}")["campaign"]
    require(item["account_id"] == own_account and item["state"] == "paused" and not item["pause_pending"],
            "Expected an owned campaign with a confirmed paused state")
    require(0 < (item.get("activation_confirmed_at") or 0) <= (item.get("pause_confirmed_at") or 0),
            "Expected provider-confirmed activation followed by a confirmed pause")
    require(item["has_provider_campaign"] and re.fullmatch(r"[0-9]+", item.get("provider_campaign_id", "")),
            "Campaign has no confirmed Google resource")
    budget = item["draft"]["budget"]
    require(budget == {"amount_micros": PROMO_BUDGET_MICROS, "currency": "USD", "kind": "average_daily"},
            "Junior Bay did not return the approved $5 average daily budget")
    return item


def check_isolation(owner_token, owner_claim, other_token, owner_campaign, other_claim):
    campaign_id = owner_campaign["campaign_id"]
    path = f"/me/ads/campaigns/{campaign_id}"
    # The query parameter intentionally identifies the owner while the credential belongs to the
    # other tenant. The deployed authorizer and handler must use the verified identity.
    require(request(other_token, path, params={"tenant_id": owner_claim}, expected=404)["error"]
            == "ads_campaign_not_found", "Cross-tenant detail must return campaign not found")
    nonce = uuid4().hex
    result = request(other_token, f"{path}/pause", body={
        "revision": owner_campaign["revision"], "request_id": nonce, "tenant_id": owner_claim,
    }, params={"tenant_id": owner_claim}, expected=404)
    require(result["error"] == "ads_campaign_not_found", "Cross-tenant pause must return campaign not found")
    # Verify that no provider workflow record was enqueued in either tenant partition.
    for claim in (owner_claim, other_claim):
        partition = "tenant#" + json.dumps([claim, "test"], separators=(",", ":"))
        fields = (partition, campaign_id, "pause", str(owner_campaign["revision"]), nonce)
        job_id = sha256(json.dumps(fields).encode()).hexdigest()[:32]
        key = {"partition_key": {"S": partition}, "record_key": {"S": f"workflow#{job_id}"}}
        result = subprocess.check_output([
            "aws", "dynamodb", "get-item", "--region", "us-west-2", "--table-name", "jb-attention-ads-dev",
            "--key", json.dumps(key), "--consistent-read", "--projection-expression", "record_key",
            "--no-cli-pager", "--output", "json",
        ])
        require(not json.loads(result or "{}").get("Item"), "Cross-tenant pause created a provider workflow job")
    current = request(owner_token, path)["campaign"]
    require(current["state"] == "paused" and not current["pause_pending"]
            and current.get("last_job") == owner_campaign.get("last_job"), "Owned state changed during the isolation check")
    print(f"Campaign {campaign_id}: owned access and cross-tenant read and pause rejection verified.")


def google_readback(token, account, campaign):
    verify_account(token, account, MANAGER, check_discovery=False)
    native = campaign["provider_campaign_id"]
    query = (
        "SELECT campaign.id, campaign.status, campaign_budget.amount_micros, "
        "campaign_budget.explicitly_shared "
        f"FROM campaign WHERE campaign.id = {native}"
    )
    response, request_id = ads_request(token, f"customers/{account}/googleAds:search", manager=MANAGER, query=query)
    rows = response.get("results", [])
    require(len(rows) == 1, "Google did not return the expected campaign")
    budget = rows[0]["campaignBudget"]
    require(str(rows[0]["campaign"]["id"]) == native and rows[0]["campaign"]["status"] == "PAUSED"
            and int(budget["amountMicros"]) == PROMO_BUDGET_MICROS and not budget.get("explicitlyShared", False),
            "Google did not confirm a paused campaign with a dedicated $5 average daily budget")
    print(f"Google confirmed the $5.00 average daily budget and paused state (request ID {request_id}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-a", help="Default is Tenant A's latest launched and paused $5 campaign")
    parser.add_argument("--campaign-b", help="Default is Tenant B's latest launched and paused $5 campaign")
    parser.add_argument("--sign-in", action="store_true", help="Sign in to Junior Bay dev with hidden password prompts")
    parser.add_argument("--isolation-only", action="store_true", help="Run the tenant checks without separate Google readback")
    args = parser.parse_args()
    if args.sign_in and not sys.stdin.isatty():
        parser.error("--sign-in requires an interactive terminal to keep passwords hidden")
    ids = (args.campaign_a, args.campaign_b)
    if (ids[0] and ids[0] == ids[1]) or not all(
        value is None or re.fullmatch(r"ads_[0-9a-f]{32}", value) for value in ids
    ):
        parser.error("Supply two distinct Junior Bay campaign IDs")
    tokens = tuple(
        sign_in(alias) if args.sign_in else getpass.getpass(f"Tenant {alias} Cognito ID token: ")
        for alias in ("A", "B")
    )
    claims = tuple(tenant_claim(token) for token in tokens)
    require(claims[0] != claims[1], "The checks require two distinct Junior Bay tenants")
    campaigns = tuple(own_campaign(tokens[i], ADVERTISERS[i], ADVERTISERS[1-i], ids[i]) for i in range(2))
    for i in range(2):
        check_isolation(tokens[i], claims[i], tokens[1-i], campaigns[i], claims[1-i])
    if args.isolation_only:
        print("Deployed API isolation passed. Independent Google budget readback is still pending.")
        return
    google_token = getpass.getpass("Google Ads Sandbox OAuth access token: ")
    for i in range(2):
        google_readback(google_token, ADVERTISERS[i], campaigns[i])
    print("Deployed API isolation and Google budget readback passed. Record the corresponding dashboard copy separately.")


if __name__ == "__main__":
    main()

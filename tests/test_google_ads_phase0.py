import pytest

from scripts import google_ads_phase0 as probe


MANAGER = "1000000000"
TENANT_A = "1000000001"
TENANT_B = "1000000002"
CAMPAIGN = f"customers/{TENANT_A}/campaigns/10"
BUDGET = f"customers/{TENANT_A}/campaignBudgets/20"
FINAL_URL = "https://juniorbay.com/"


def test_sandbox_suite_verifies_advertisers_and_pauses_created_campaign(monkeypatch):
    status = "PAUSED"
    steps = []

    def request(token, path, *, manager=None, query=None, payload=None):
        nonlocal status
        if path == "customers:listAccessibleCustomers":
            return {"resourceNames": [f"customers/{MANAGER}"]}, "discovery"
        customer = path.split("/")[1]
        if "FROM customer_client" in (query or ""):
            assert customer == MANAGER
            assert "customer_client.level = 1" in query
            assert f"IN ({TENANT_A}, {TENANT_B})" in query
            return {"results": [{"customerClient": {"id": cid}} for cid in (TENANT_A, TENANT_B)]}, "hierarchy"
        if query == probe.CUSTOMER_QUERY:
            assert manager == (None if customer == MANAGER else MANAGER)
            steps.append(customer)
            return {"results": [{"customer": {
                "id": customer,
                "manager": customer == MANAGER,
                "testAccount": True,
                "currencyCode": "USD",
                "timeZone": "America/Denver",
            }}]}, "account"

        assert customer == TENANT_A
        assert manager == MANAGER
        if query:
            assert CAMPAIGN in query
            steps.append(f"read {status}")
            return {"results": [{
                "campaign": {"resourceName": CAMPAIGN, "status": status},
                "campaignBudget": {"resourceName": BUDGET, "amountMicros": "5000000"},
            }]}, "state"

        assert payload["partialFailure"] is False
        operations = payload["mutateOperations"]
        if len(operations) == 1:
            operation = operations[0]["campaignOperation"]
            assert operation["updateMask"] == "status"
            assert operation["update"]["resourceName"] == CAMPAIGN
            status = operation["update"]["status"]
            steps.append(status)
            return {}, "update"

        budget, campaign, group, first_keyword, second_keyword, ad = operations
        budget = budget["campaignBudgetOperation"]["create"]
        campaign = campaign["campaignOperation"]["create"]
        group = group["adGroupOperation"]["create"]
        assert budget["amountMicros"] == "5000000"
        assert campaign["campaignBudget"] == budget["resourceName"]
        assert campaign["status"] == "PAUSED"
        assert group["campaign"] == campaign["resourceName"]
        for operation in (first_keyword, second_keyword):
            assert operation["adGroupCriterionOperation"]["create"]["adGroup"] == group["resourceName"]
        ad = ad["adGroupAdOperation"]["create"]
        assert ad["adGroup"] == group["resourceName"]
        assert ad["status"] == "PAUSED"
        assert ad["ad"]["finalUrls"] == [FINAL_URL]
        assert len(ad["ad"]["responsiveSearchAd"]["headlines"]) == 3
        if payload["validateOnly"]:
            steps.append("validate")
            return {}, "validation"
        steps.append("create")
        return {"mutateOperationResponses": [
            {"campaignBudgetResult": {"resourceName": BUDGET}},
            {"campaignResult": {"resourceName": CAMPAIGN}},
            {"adGroupResult": {"resourceName": f"customers/{TENANT_A}/adGroups/30"}},
            {"adGroupCriterionResult": {"resourceName": f"customers/{TENANT_A}/adGroupCriteria/30~40"}},
            {"adGroupCriterionResult": {"resourceName": f"customers/{TENANT_A}/adGroupCriteria/30~41"}},
            {"adGroupAdResult": {"resourceName": f"customers/{TENANT_A}/adGroupAds/30~50"}},
        ]}, "creation"

    monkeypatch.setattr(probe, "ads_request", request)
    probe.run_sandbox_suite("token", MANAGER, TENANT_A, TENANT_B, FINAL_URL)
    assert steps == [
        MANAGER, TENANT_A, TENANT_B, "validate", "create", "read PAUSED",
        "ENABLED", "read ENABLED", "PAUSED", "read PAUSED",
    ]


def test_sandbox_suite_pauses_after_uncertain_enable(monkeypatch):
    monkeypatch.setattr(probe, "verify_advertisers", lambda *args: None)
    monkeypatch.setattr(probe, "create_search_campaign", lambda *args: (CAMPAIGN, BUDGET))
    reads = []
    monkeypatch.setattr(probe, "verify_campaign_state", lambda *args: reads.append(args[-1]))
    writes = []

    def mutate(token, manager, customer, operations):
        assert customer == TENANT_A
        status = operations[0]["campaignOperation"]["update"]["status"]
        writes.append(status)
        if status == "ENABLED":
            raise TimeoutError("Enable result unknown")
        return {}, "pause"

    monkeypatch.setattr(probe, "mutate", mutate)
    with pytest.raises(TimeoutError):
        probe.run_sandbox_suite("token", MANAGER, TENANT_A, TENANT_B, FINAL_URL)
    assert writes == ["ENABLED", "PAUSED"]
    assert reads == ["PAUSED", "PAUSED"]


@pytest.mark.parametrize("account_override", [
    {"testAccount": False}, {"manager": True}, {"currencyCode": "CAD"}, {"timeZone": "America/New_York"},
])
def test_sandbox_suite_stops_before_mutation_when_advertiser_check_fails(monkeypatch, account_override):
    def request(token, path, *, manager=None, query=None, payload=None):
        assert payload is None
        if path == "customers:listAccessibleCustomers":
            return {"resourceNames": [f"customers/{MANAGER}"]}, "discovery"
        if "FROM customer_client" in query:
            return {"results": [{"customerClient": {"id": cid}} for cid in (TENANT_A, TENANT_B)]}, "hierarchy"
        customer = path.split("/")[1]
        account = {
            "id": customer, "manager": customer == MANAGER, "testAccount": True,
            "currencyCode": "USD", "timeZone": "America/Denver",
        }
        if customer == TENANT_B:
            account.update(account_override)
        return {"results": [{"customer": account}]}, "account"

    monkeypatch.setattr(probe, "ads_request", request)
    with pytest.raises(RuntimeError):
        probe.run_sandbox_suite("token", MANAGER, TENANT_A, TENANT_B, FINAL_URL)

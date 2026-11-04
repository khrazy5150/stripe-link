"""Whose business signs a review invite (plans/SITE_AS_BUSINESS_IDENTITY.md §1).

The reported bug: a customer who bought a Quill product got an invite signed **"Poliaxis Nutrition"** —
the other business the same tenant runs. Two separate causes, and either alone reproduces it:

1. the sweep resolved the business as "the FIRST Site that has an organization", a coin flip once a tenant
   has more than one;
2. `TenantProfile.business_name` then WON over whatever the Site said, and a tenant has exactly one of
   those no matter how many businesses they sell.

So the fix is per-invite resolution (order → page → Site) *and* an inverted precedence. These tests hold
both, plus the fallbacks that keep legacy invites sending.
"""
import unittest

from handlers.review_invites import handler as sweep_handler
from handlers.stripe_webhook import plan_order_review_invite
from stripe_link.domain.review_invites import plan_invite

QUILL = {"name": "Quill", "entity_type": "LocalBusiness"}
POLIAXIS = {"name": "Poliaxis Nutrition", "entity_type": "Organization"}


def invite(page_id="", invite_id="invite_o1", now=0):
    return plan_invite(tenant_id="t1", invite_id=invite_id, order_id=invite_id[7:],
                       product={"product_id": "prod_a", "name": "Widget", "product_type": "digital"},
                       customer={"email": "buyer@example.com", "name": "Jane"},
                       page_id=page_id, now=now)


class FakeInvites:
    def __init__(self, invites=()):
        self.docs = {(i["tenant_id"], i["invite_id"]): dict(i) for i in invites}

    def scan_type(self):
        return [dict(v) for v in self.docs.values()]

    def get(self, tenant_id, invite_id):
        doc = self.docs.get((tenant_id, invite_id))
        return dict(doc) if doc else None

    def put(self, doc):
        self.docs[(doc["tenant_id"], doc["invite_id"])] = dict(doc)
        return dict(doc)


class FakeSites:
    """Two businesses under one tenant — the shape the bug needs. `list_for_tenant` returns Poliaxis
    FIRST, so any test that passes by accident would be signing Poliaxis."""

    def __init__(self, sites=None):
        self.sites = sites if sites is not None else [
            {"site_id": "site_pol", "tenant_id": "t1", "organization": dict(POLIAXIS),
             "pages": {"/p": {"page_id": "page_pol"}}},
            {"site_id": "site_qui", "tenant_id": "t1", "organization": dict(QUILL),
             "pages": {"/q": {"page_id": "page_qui"}}},
        ]
        self.scans = 0

    def get(self, _tenant_id, site_id):
        return next((dict(s) for s in self.sites if s["site_id"] == site_id), None)

    def list_for_tenant(self, _tenant_id, **_kw):
        self.scans += 1
        return [dict(s) for s in self.sites]


class FakePages:
    def __init__(self, fail=False):
        self.fail = fail
        self.reads = []

    def get(self, tenant_id, page_id):
        self.reads.append((tenant_id, page_id))
        if self.fail:
            raise RuntimeError("throttled")
        return {"tenant_id": tenant_id, "page_id": page_id, "site_id": f"site_{page_id.split('_')[1][:3]}"}


PROFILE = {"user_id": "t1", "business": {"name": "Poliaxis Nutrition", "email": "hi@poliaxis.test",
                                         "email_verified": True}}


class FakeProfiles:
    def __init__(self, profile=PROFILE):
        self.profile = profile

    def get(self, _tenant, _user):
        return dict(self.profile) if self.profile else None


_DEFAULT = object()  # so a test can pass `sites=None` and MEAN none, not "give me the default"


def sweep(invites, *, sites=_DEFAULT, pages=None, profiles=None, day=4):
    sent = []
    result = sweep_handler({}, None, invites_repo=invites,
                           sites_repo=FakeSites() if sites is _DEFAULT else sites,
                           pages_repo=pages if pages is not None else FakePages(),
                           profiles_repo=profiles or FakeProfiles(),
                           mailer_send=lambda **kw: sent.append(kw) or {"MessageId": "m"},
                           now_fn=lambda: day * 86_400)
    return result, sent


class TheOrderCarriesThePageTests(unittest.TestCase):
    """Resolution has to start somewhere, and the sweep runs days later with only the invite in hand."""

    def _order(self, **over):
        order = {"order_id": "order_x", "status": "paid",
                 "customer": {"email": "buyer@example.com"},
                 "product": {"product_id": "prod_a", "name": "Widget"},
                 "attribution": {"page_id": "page_qui", "offer_id": "offer_1"}}
        order.update(over)
        return order

    def test_the_invite_records_the_page_the_buyer_converted_on(self):
        invites = FakeInvites()
        plan_order_review_invite(self._order(), "t1", None, invites, now=0)
        self.assertEqual(invites.get("t1", "invite_order_x")["page_id"], "page_qui")

    def test_page_id_comes_from_ATTRIBUTION_not_the_top_level(self):
        """There is no top-level `page_id` on an order; `attribution_from_metadata` is the one place every
        order builder puts it. Reading the wrong key fails open — an empty string and a silent fallback."""
        invites = FakeInvites()
        plan_order_review_invite(self._order(page_id="page_WRONG"), "t1", None, invites, now=0)
        self.assertEqual(invites.get("t1", "invite_order_x")["page_id"], "page_qui")

    def test_an_order_with_no_attribution_still_plans_an_invite(self):
        invites = FakeInvites()
        self.assertTrue(plan_order_review_invite(self._order(attribution=None), "t1", None, invites, now=0))
        self.assertEqual(invites.get("t1", "invite_order_x")["page_id"], "")


class TheSiteSignsTheInviteTests(unittest.TestCase):
    def test_a_QUILL_purchase_is_signed_QUILL(self):
        """The reported bug, end to end."""
        _result, sent = sweep(FakeInvites([invite(page_id="page_qui")]))
        self.assertTrue(sent)
        for message in sent:
            self.assertEqual(message["from_name"], "Quill")

    def test_the_SITE_beats_the_tenant_profile(self):
        """The precedence inversion, stated alone: the profile says Poliaxis on every one of this tenant's
        messages, and it must not be allowed to override the Site that actually made the sale."""
        _result, sent = sweep(FakeInvites([invite(page_id="page_qui")]),
                              profiles=FakeProfiles({"business": {"name": "Poliaxis Nutrition"}}))
        self.assertEqual(sent[0]["from_name"], "Quill")

    def test_the_reverse_edge_avoids_scanning_every_site(self):
        sites = FakeSites()
        sweep(FakeInvites([invite(page_id="page_qui")]), sites=sites)
        self.assertEqual(sites.scans, 0)

    def test_two_invites_on_DIFFERENT_pages_are_signed_DIFFERENTLY(self):
        """The per-tenant cache that used to hold the answer would sign both with whichever came first —
        which is the bug wearing a different hat. The cache is now keyed by (tenant, page)."""
        invites = FakeInvites([invite(page_id="page_qui", invite_id="invite_o1"),
                               invite(page_id="page_pol", invite_id="invite_o2")])
        _result, sent = sweep(invites)
        self.assertEqual({m["from_name"] for m in sent}, {"Quill", "Poliaxis Nutrition"})

    def test_the_review_destination_follows_the_SAME_site(self):
        """`organization` carries entity_type/place_id/review_destination too: resolving the wrong Site
        points the buyer at the wrong business's review page, not just the wrong signature."""
        sites = FakeSites([{"site_id": "site_qui", "tenant_id": "t1", "pages": {},
                            "organization": {**QUILL, "place_id": "ChIJ_quill"}}])
        _result, sent = sweep(FakeInvites([invite(page_id="page_qui")]), sites=sites)
        self.assertIn("ChIJ_quill", sent[0]["html"])


class TheFallbacksKeepSendingTests(unittest.TestCase):
    """Branding is worth less than delivery: every failure here degrades the name, never the message."""

    def test_a_LEGACY_invite_with_no_page_does_NOT_guess_between_two_sites(self):
        """Invites planned before `page_id` was stored have nothing to resolve from. With two businesses to
        choose between there is no answer, so the resolver declines to pick one and the tenant profile
        answers instead — ONE wrong-but-consistent name beats a coin flip between two."""
        sites = FakeSites()
        _result, sent = sweep(FakeInvites([invite(page_id="")]), sites=sites)
        self.assertEqual(sent[0]["from_name"], "Poliaxis Nutrition")  # from the profile, not from a Site

    def test_a_SINGLE_site_tenant_still_gets_their_site(self):
        """With one business there is nothing to guess, and the Site is the better source: the profile's
        business name is empty on every tenant that has ever existed."""
        sites = FakeSites([{"site_id": "site_qui", "tenant_id": "t1", "organization": dict(QUILL),
                            "pages": {}}])
        _result, sent = sweep(FakeInvites([invite(page_id="")]), sites=sites,
                              profiles=FakeProfiles({"email": "owner@quill.test"}))
        self.assertEqual(sent[0]["from_name"], "Quill")

    def test_a_site_with_NO_organization_falls_back_to_the_profile(self):
        sites = FakeSites([{"site_id": "site_qui", "tenant_id": "t1", "organization": {}, "pages": {}}])
        _result, sent = sweep(FakeInvites([invite(page_id="page_qui")]), sites=sites)
        self.assertEqual(sent[0]["from_name"], "Poliaxis Nutrition")

    def test_an_unreadable_pages_table_STILL_FINDS_THE_RIGHT_SITE(self):
        """The page read only supplies the `site_id` edge, which makes the lookup keyed instead of a scan.
        Without it the resolver looks for the page_id in each Site's route map and gets the same answer —
        so a throttled Pages table costs latency, not the business name."""
        sites = FakeSites()
        result, sent = sweep(FakeInvites([invite(page_id="page_qui")]), pages=FakePages(fail=True),
                             sites=sites)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["from_name"], "Quill")
        self.assertEqual(sites.scans, 1)

    def test_no_sites_repo_at_all_still_sends(self):
        """Unit tests and any environment without SITES_TABLE. The name falls back to the profile."""
        result, sent = sweep(FakeInvites([invite(page_id="page_qui")]), sites=None)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(sent[0]["from_name"], "Poliaxis Nutrition")

    def test_REPLY_TO_still_comes_from_the_verified_tenant_identity(self):
        """Per-Site Reply-To waits on per-Site email verification (§P3). Until then the display name is
        the Site's and the reply address is the tenant's — the only address SES has been shown."""
        _result, sent = sweep(FakeInvites([invite(page_id="page_qui")]))
        self.assertEqual(sent[0]["reply_to"], "hi@poliaxis.test")


if __name__ == "__main__":
    unittest.main()

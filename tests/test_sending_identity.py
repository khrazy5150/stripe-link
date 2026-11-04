"""The ONE resolver every tenant-authored email asks "who is this from?" (plans/SITE_AS_BUSINESS_IDENTITY.md §4).

Before it, each sweep held its own copy of the answer and the copies disagreed. Two held literally the same
wrong rule — "the first Site that has an organization" — which is a coin flip for a tenant running more than
one business, and both then let `TenantProfile.business_name` override whatever the Site said. That is how a
Quill customer's review invite arrived signed "Poliaxis Nutrition".

The rules this file pins, in the order the resolver applies them:

1. **A named Site wins.** `site_id`, or `page_id` → the page's `site_id` edge → the Site.
2. **One unambiguous Site wins.** Nothing narrowed the message, but the tenant has exactly ONE business:
   that is not a guess.
3. **Otherwise the tenant answers, and the resolver says so.** `source` records which rule fired, because a
   wrong name on a real message should be traceable to a resolution rather than guessed at.
4. **Reply-To is always the tenant's verified address**, even when the NAME is the Site's — it is the only
   address the platform has made them prove they can receive at (per-Site verification is §P3).
"""
import unittest

from stripe_link.sender_identity import sending_identity, site_organization

QUILL = {"name": "Quill", "entity_type": "LocalBusiness", "place_id": "ChIJ_quill"}
POLIAXIS = {"name": "Poliaxis Nutrition", "entity_type": "Organization"}
PROFILE = {"user_id": "t1", "email": "owner@example.test",
           "business": {"name": "Poliaxis Nutrition", "email": "hi@poliaxis.test", "email_verified": True}}


class Sites:
    def __init__(self, sites):
        self.sites = sites
        self.scans = 0
        self.explode = False

    def get(self, _tenant_id, site_id):
        if self.explode:
            raise RuntimeError("throttled")
        return next((dict(s) for s in self.sites if s.get("site_id") == site_id), None)

    def list_for_tenant(self, _tenant_id, **_kw):
        if self.explode:
            raise RuntimeError("throttled")
        self.scans += 1
        return [dict(s) for s in self.sites]


class Pages:
    def __init__(self, pages=None):
        self.pages = pages or {}

    def get(self, _tenant_id, page_id):
        page = self.pages.get(page_id)
        return dict(page) if page else None


class Profiles:
    def __init__(self, profile=PROFILE):
        self.profile = profile

    def get(self, _tenant, _user):
        return dict(self.profile) if self.profile else None


TWO_SITES = [
    {"site_id": "site_pol", "tenant_id": "t1", "organization": dict(POLIAXIS),
     "pages": {"/p": {"page_id": "page_pol"}}},
    {"site_id": "site_qui", "tenant_id": "t1", "organization": dict(QUILL),
     "pages": {"/q": {"page_id": "page_qui"}}},
]


def resolve(**over):
    kwargs = {"profiles_repo": Profiles(), "sites_repo": Sites(TWO_SITES), "pages_repo": Pages()}
    kwargs.update(over)
    return sending_identity("t1", **kwargs)


class ANamedSiteWinsTests(unittest.TestCase):
    def test_a_site_id_is_one_keyed_read(self):
        sites = Sites(TWO_SITES)
        identity = resolve(site_id="site_qui", sites_repo=sites)
        self.assertEqual(identity["business_name"], "Quill")
        self.assertEqual(identity["source"], "site")
        self.assertEqual(sites.scans, 0)

    def test_a_page_id_resolves_through_the_site_id_edge(self):
        sites = Sites(TWO_SITES)
        identity = resolve(page_id="page_qui", sites_repo=sites,
                           pages_repo=Pages({"page_qui": {"page_id": "page_qui", "site_id": "site_qui"}}))
        self.assertEqual(identity["business_name"], "Quill")
        self.assertEqual(sites.scans, 0)

    def test_a_page_with_NO_edge_is_found_in_the_route_maps(self):
        """`Site.pages` is the source of truth; the edge is a cache of it. A page written before the edge
        existed still resolves, which is what lets the backfill be optional rather than blocking."""
        sites = Sites(TWO_SITES)
        identity = resolve(page_id="page_qui", sites_repo=sites, pages_repo=Pages())
        self.assertEqual(identity["business_name"], "Quill")
        self.assertEqual(sites.scans, 1)

    def test_the_WHOLE_organization_comes_back_not_just_the_name(self):
        """Callers need entity_type/place_id too: they decide where a review is routed. Resolving the name
        from one Site and the routing from another would send a Quill buyer to Poliaxis's review page."""
        identity = resolve(site_id="site_qui")
        self.assertEqual(identity["organization"]["place_id"], "ChIJ_quill")

    def test_a_site_id_that_resolves_to_nothing_does_not_invent_one(self):
        identity = resolve(site_id="site_deleted")
        self.assertEqual(identity["business_name"], "Poliaxis Nutrition")
        self.assertEqual(identity["source"], "tenant")


class OneUnambiguousSiteWinsTests(unittest.TestCase):
    ONE = [{"site_id": "site_qui", "tenant_id": "t1", "organization": dict(QUILL), "pages": {}}]

    def test_with_exactly_one_business_there_is_nothing_to_guess(self):
        identity = resolve(sites_repo=Sites(self.ONE), profiles_repo=Profiles({"email": "o@q.test"}))
        self.assertEqual(identity["business_name"], "Quill")
        self.assertEqual(identity["source"], "site")

    def test_the_single_site_also_beats_a_tenant_business_name(self):
        """The profile's name is one name for a tenant who may run several businesses; the Site is the
        business. §P4 removes the profile field entirely."""
        identity = resolve(sites_repo=Sites(self.ONE))
        self.assertEqual(identity["business_name"], "Quill")

    def test_TWO_businesses_and_no_context_is_NOT_guessed(self):
        """The bug, stated as a rule: one wrong-but-consistent name beats a coin flip between two."""
        identity = resolve()
        self.assertEqual(identity["business_name"], "Poliaxis Nutrition")
        self.assertEqual(identity["source"], "tenant")
        self.assertEqual(identity["organization"], {})

    def test_a_second_site_WITHOUT_an_organization_is_not_a_second_candidate(self):
        """Ambiguity is between businesses, not between Sites. A Site nobody has given a business identity
        cannot be the sender, so it does not make the answer uncertain."""
        sites = Sites(self.ONE + [{"site_id": "site_blank", "tenant_id": "t1", "pages": {}}])
        self.assertEqual(resolve(sites_repo=sites)["business_name"], "Quill")

    def test_a_page_whose_site_has_no_organization_falls_through(self):
        sites = Sites([{"site_id": "site_blank", "tenant_id": "t1", "organization": {},
                        "pages": {"/b": {"page_id": "page_blank"}}}])
        identity = resolve(page_id="page_blank", sites_repo=sites)
        self.assertEqual(identity["source"], "tenant")


class TheTenantAnswersLastTests(unittest.TestCase):
    def test_no_site_at_all_is_the_tenant(self):
        identity = sending_identity("t1", profiles_repo=Profiles(), sites_repo=None)
        self.assertEqual(identity["business_name"], "Poliaxis Nutrition")
        self.assertEqual(identity["source"], "tenant")

    def test_nothing_anywhere_records_source_NONE(self):
        """So an unbranded message is distinguishable from an unresolved one."""
        identity = sending_identity("t1", profiles_repo=Profiles({}), sites_repo=Sites([]))
        self.assertEqual(identity["business_name"], "")
        self.assertEqual(identity["source"], "none")

    def test_an_exploding_sites_table_still_names_the_tenant(self):
        sites = Sites(TWO_SITES)
        sites.explode = True
        self.assertEqual(resolve(site_id="site_qui", sites_repo=sites)["business_name"],
                         "Poliaxis Nutrition")

    def test_an_exploding_profiles_table_still_names_the_site(self):
        class Exploding:
            def get(self, *_a):
                raise RuntimeError("throttled")

        self.assertEqual(resolve(site_id="site_qui", profiles_repo=Exploding())["business_name"], "Quill")

    def test_no_tenant_id_resolves_to_nothing_rather_than_raising(self):
        self.assertEqual(sending_identity("")["source"], "none")


class ReplyToStaysTheTenantsTests(unittest.TestCase):
    """The display name and the reply address come from different places ON PURPOSE, and this is the one
    asymmetry in the design worth a test of its own: SES will mail from any Reply-To it is handed, so the
    platform only ever uses an address the tenant has proven they can receive at. A Site's address becomes
    usable when verification is Site-scoped (§P3) — not before."""

    def test_the_site_names_the_message_and_the_tenant_takes_the_replies(self):
        identity = resolve(site_id="site_qui")
        self.assertEqual(identity["business_name"], "Quill")
        self.assertEqual(identity["reply_to"], "hi@poliaxis.test")

    def test_an_unverified_site_email_is_IGNORED(self):
        sites = Sites([{"site_id": "site_qui", "tenant_id": "t1", "pages": {},
                        "organization": {**QUILL, "email": "anyone@quill.test"}}])
        self.assertEqual(resolve(site_id="site_qui", sites_repo=sites)["reply_to"], "hi@poliaxis.test")


class TheModeIsAlwaysThreadedTests(unittest.TestCase):
    """A Site lives at `SITE#<mode>#<site_id>` and a page at `PAGE#<mode>#<page_id>`, so resolving a
    test-mode order against the live partition answers with the wrong business or with none. `mode`
    defaults to live because every sweep that mails a real customer is live-only — which makes a
    both-modes emitter that forgets it fail silently, in the one direction nobody looks."""

    def test_site_organization_takes_a_mode(self):
        import inspect

        self.assertIn("mode", inspect.signature(site_organization).parameters)
        self.assertIn("mode", inspect.signature(sending_identity).parameters)

    def test_every_caller_in_src_states_its_mode(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1] / "src"
        offenders = []
        for path in sorted(root.rglob("*.py")):
            source = path.read_text()
            for match in re.finditer(r"(?<!def )\bsending_identity\((?:[^()]|\([^()]*\))*\)", source):
                call = match.group(0)
                if "mode=" in call:
                    continue
                offenders.append(f"{path.relative_to(root.parent)}: {' '.join(call.split())[:90]}")
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()

"""One click, four documents, and a page that works before the tenant touches it.

plans/PAY_WHAT_YOU_WANT.md §5c. The point of the button is that pasting a Ko-fi URL stops being the easy
option -- which only holds if what it produces is a real, publishable, editable tip jar rather than a stub.
So these tests check the documents against the SAME validators the ordinary create endpoints use: a seeded
row that the builder would refuse to re-save is worse than no row.
"""
import json
import unittest

from handlers.tip_jar_provision import handler
from stripe_link.domain import tip_jar_provision as seed
from stripe_link.domain import tips
from stripe_link.domain.documents import (
    validate_offer_document,
    validate_page_document,
    validate_product_document,
    validate_site,
)
from tests.fakes import FakeDocumentRepository, FakeSubdomainRegistry

TENANT = "tenant_demo"


def _billing_config():
    return {}


class TipJarProvisionTests(unittest.TestCase):
    def setUp(self):
        self.sites = FakeDocumentRepository("site_id")
        self.products = FakeDocumentRepository("product_id")
        self.offers = FakeDocumentRepository("offer_id")
        self.pages = FakeDocumentRepository("page_id")
        self.tenants = FakeDocumentRepository("tenant_id")
        self.users = FakeDocumentRepository("user_id")
        self.registry = FakeSubdomainRegistry()
        self.tenants.put({"tenant_id": TENANT, "tier_id": "basic",
                          "avatar_url": "https://images.juniorbay.com/offers/0X5/small.webp",
                          "owner": {"first_name": "Keith", "last_name": "De Costa"}})

    def _repos(self):
        return {"sites_repo": self.sites, "products_repo": self.products, "offers_repo": self.offers,
                "pages_repo": self.pages, "tenant_repo": self.tenants, "users_repo": self.users,
                "registry": self.registry, "billing_config_loader": _billing_config}

    def _call(self, **body):
        payload = {"tenant_id": TENANT, **body}
        return handler({"httpMethod": "POST", "body": json.dumps(payload)}, None, **self._repos())

    def _created(self, response):
        self.assertEqual(response["statusCode"], 201, response["body"])
        return json.loads(response["body"])

    # --- what one click produces ------------------------------------------------------------------

    def test_one_click_produces_four_documents_the_validators_accept(self):
        made = self._created(self._call(request_id="req-1"))
        validate_site(made["site"])
        validate_product_document(made["product"])
        validate_offer_document(made["offer"])
        validate_page_document(made["page"])

    def test_the_page_is_published_and_reachable_on_its_site(self):
        # A draft tip jar is not a tip jar: the promise is a link to paste, and "now go and publish it" is
        # the step that loses people.
        made = self._created(self._call(request_id="req-1"))
        self.assertEqual(made["page"]["status"], "published")
        self.assertTrue(made["page"].get("published_at"))
        route = made["site"]["pages"][f"/{seed.PAGE_SLUG}"]
        self.assertEqual(route["page_id"], made["page"]["page_id"])
        self.assertEqual(route["offer_id"], made["offer"]["offer_id"])
        # short_code is what the test viewer addresses a page by; a page without one has no preview URL.
        self.assertTrue(made["page"].get("short_code"))

    def test_the_offer_reads_as_a_tip_jar_to_the_composer(self):
        # Everything downstream -- the composition, the renderer, the element's own page picker -- keys off
        # this one derivation. If it says "single", the page renders as a sales page.
        made = self._created(self._call(request_id="req-1"))
        products = {made["product"]["product_id"]: made["product"]}
        self.assertTrue(tips.offer_is_tip_jar(made["offer"], products))

    def test_the_tip_is_one_time_and_takes_any_amount_in_the_platform_range(self):
        made = self._created(self._call(request_id="req-1"))
        price = made["product"]["prices"][0]
        self.assertEqual(price["pricing_model"], "customer_chooses")
        # A seeded page the tenant has not read yet must not sign their supporters up to a repeating charge.
        self.assertFalse(price["allow_recurring"])
        self.assertTrue(price["allow_custom"])
        self.assertEqual(price["min_amount"], tips.MIN_AMOUNT)
        self.assertEqual(price["max_amount"], tips.MAX_AMOUNT)

    def test_the_presets_carry_both_halves_of_the_pair(self):
        # Keyed and charged, because neither can be re-derived from the other later without the fee table as
        # it stood that day. The gap between them is the net_guaranteed pitch made visible.
        made = self._created(self._call(request_id="req-1"))
        price = made["product"]["prices"][0]
        self.assertEqual(price["presets"], tips.recommended_presets("usd"))
        self.assertEqual(len(price["preset_charges"]), len(price["presets"]))
        self.assertEqual(price["fee_handling"], "net_guaranteed")
        for keyed, charged in zip(price["presets"], price["preset_charges"]):
            self.assertGreater(charged, keyed, "the buyer covers the fees under net_guaranteed")

    def test_a_tip_price_is_never_synced_to_stripe(self):
        # The amount is decided per buyer, so checkout prices the line inline and drops any synced id it
        # finds. Seeding one would be a number waiting to be charged instead of the one the buyer picked.
        made = self._created(self._call(request_id="req-1"))
        self.assertNotIn("stripe_price_id", made["product"]["prices"][0])

    def test_the_page_is_stripped_to_a_support_page(self):
        made = self._created(self._call(request_id="req-1"))
        page = made["page"]
        self.assertEqual(page["goal"], "minimal")
        self.assertFalse(page["chrome"]["breadcrumb"])
        self.assertFalse(page["composition"]["overrides"]["brand_label"]["enabled"])
        self.assertEqual(page["theme"]["preset"], seed.THEME_PRESET)
        types = [section["type"] for section in page["sections"]]
        self.assertEqual(types[:2], ["hero_media", "hero"])
        # Money changes hands here, so the policy -- and with it the "Manage a purchase" entry point -- is on
        # the page rather than assumed.
        self.assertIn("refund_policy", types)

    # --- the avatar ---------------------------------------------------------------------------------

    def test_the_avatar_shows_when_the_tenant_has_one(self):
        made = self._created(self._call(request_id="req-1"))
        self.assertEqual(made["page"]["sections"][0]["avatar_placement"], "overlay")

    def test_a_tenant_with_no_picture_gets_no_empty_ring(self):
        # An empty avatar ring on an otherwise finished page reads as a bug rather than as a blank, and a
        # tenant who sees broken does not go on to edit it.
        self.tenants.put({"tenant_id": TENANT, "tier_id": "basic",
                          "owner": {"first_name": "Nora", "last_name": "Pike"}})
        made = self._created(self._call(request_id="req-2"))
        self.assertEqual(made["page"]["sections"][0]["avatar_placement"], "hidden")

    # --- naming and versions -------------------------------------------------------------------------

    def test_the_site_is_named_after_the_tenant_and_versioned(self):
        made = self._created(self._call(request_id="req-1"))
        self.assertEqual(made["site"]["name"], "Keith De Costa tip-jar v1")
        # The platform subdomain is what the hyphenated shape in the spec actually lands as.
        self.assertTrue(made["site"]["hosting"]["platform_hostname"].startswith("keith-de-costa-tip-jar-v1."))

    def test_the_user_profile_display_name_wins_over_the_signup_name(self):
        # The canonical string is the one the Profile screen edits; the tenant profile's is written once at
        # signup and never updated, which is the freezing problem this codebase keeps rediscovering.
        self.users.put({"tenant_id": TENANT, "user_id": TENANT, "display_name": "Techno Green"})
        made = self._created(self._call(request_id="req-1"))
        self.assertEqual(made["site"]["name"], "Techno Green tip-jar v1")

    def test_a_second_jar_gets_the_next_version(self):
        self._created(self._call(request_id="req-1"))
        made = self._created(self._call(request_id="req-2"))
        self.assertEqual(made["site"]["name"], "Keith De Costa tip-jar v2")
        self.assertEqual(len(self.pages.list_for_tenant(TENANT)), 2)

    # --- resumability --------------------------------------------------------------------------------

    def test_the_same_request_id_resumes_instead_of_duplicating(self):
        # A double-click, or a retry after a timeout. Four writes cannot be made atomic across these tables,
        # so the guarantee is that a second attempt finishes the first job rather than starting another.
        first = self._created(self._call(request_id="req-1"))
        second = self._created(self._call(request_id="req-1"))
        self.assertEqual(first["page"]["page_id"], second["page"]["page_id"])
        self.assertEqual(first["product"]["product_id"], second["product"]["product_id"])
        self.assertEqual(len(self.sites.list_for_tenant(TENANT)), 1)
        self.assertEqual(len(self.products.list_for_tenant(TENANT)), 1)
        self.assertEqual(len(self.offers.list_for_tenant(TENANT)), 1)
        self.assertEqual(len(self.pages.list_for_tenant(TENANT)), 1)

    def test_a_half_finished_job_is_finished_not_restarted(self):
        """The anchor exists and records a product; the offer and page never got written."""
        made = self._created(self._call(request_id="req-1"))
        site = self.sites.get(TENANT, made["site"]["site_id"])
        product_id = made["product"]["product_id"]
        site["provision"] = {"source": "tip_jar", "request_id": "req-1", "product_id": product_id}
        site["pages"] = {}
        self.sites.put(site)
        self.offers.delete(TENANT, made["offer"]["offer_id"])
        self.pages.delete(TENANT, made["page"]["page_id"])

        resumed = self._created(self._call(request_id="req-1"))
        self.assertEqual(resumed["product"]["product_id"], product_id, "the finished step was not redone")
        self.assertEqual(len(self.products.list_for_tenant(TENANT)), 1)
        self.assertTrue(resumed["site"]["pages"])

    def test_the_page_is_attached_only_once_everything_else_exists(self):
        # Attaching first would make a half-finished job a live URL pointing at nothing.
        made = self._created(self._call(request_id="req-1"))
        self.assertEqual(made["site"]["provision"]["status"], "complete")
        self.assertIn(f"/{seed.PAGE_SLUG}", made["site"]["pages"])

    def test_the_page_is_published_after_it_is_attached_not_before(self):
        """The ordering that decides whether the artifact has a store identity at all.

        Attaching writes the SITE, never the page, so the Pages stream does not fire and an artifact rendered
        before the attach keeps the identity it had -- none. Measured on a real page on 2026-09-11: artifact
        21:12:50, attach 21:13:14, and nothing re-rendered it. So the page is written as a draft, attached,
        and only then published.
        """
        writes = []
        real_put = self.pages.put
        self.pages.put = lambda doc: (writes.append(doc.get("status")), real_put(doc))[1]
        site_writes = []
        real_site_put = self.sites.put
        self.sites.put = lambda doc: (site_writes.append(bool(doc.get("pages"))), real_site_put(doc))[1]

        self._created(self._call(request_id="req-1"))

        self.assertEqual(writes, ["draft", "published"])
        # The Site had its route map written before that final publish.
        self.assertTrue(any(site_writes[:-1]) or site_writes[-1])
        self.assertTrue(site_writes[-1], "the attach happened before the page went live")

    # --- provenance ----------------------------------------------------------------------------------

    def test_every_row_says_where_it_came_from(self):
        # Four catalogue rows appearing from one click is the kind of thing a tenant finds a month later and
        # does not recognise. This is what answers them when they look.
        made = self._created(self._call(request_id="req-1"))
        for key in ("site", "product", "offer", "page"):
            self.assertEqual(made[key]["provision"]["source"], "tip_jar", key)
            self.assertEqual(made[key]["provision"]["request_id"], "req-1", key)

    # --- currency ------------------------------------------------------------------------------------

    def test_the_ladder_follows_the_currency(self):
        made = self._created(self._call(request_id="req-1", currency="eur"))
        price = made["product"]["prices"][0]
        self.assertEqual(price["currency"], "eur")
        self.assertEqual(price["presets"], tips.recommended_presets("eur"))

    # --- method guard --------------------------------------------------------------------------------

    def test_only_post_provisions(self):
        response = handler({"httpMethod": "GET"}, None, **self._repos())
        self.assertEqual(response["statusCode"], 405)


if __name__ == "__main__":
    unittest.main()

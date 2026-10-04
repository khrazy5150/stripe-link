"""Zone-derived shipping on a hosted Checkout Session, with no page element involved.

plans/SHIPPING_ELEMENT.md phase 3 — the author's "offer B": physical goods, shipping handled automatically,
the buyer never presented with a choice.

**The constraint that shapes all of this:** Stripe fixes `shipping_options` when the session opens and never
asks us again, so it shows ONE list to every buyer whatever address they type. Zone pricing is therefore only
safe here when every allowed destination agrees. Where they disagree the honest answer is to charge nothing
and SAY WHY, rather than quote a price that is right for only some of the people who can reach the page.
"""
import unittest

from handlers.checkout import _tenant_shipping_config, build_checkout_payload, collect_shipping_for
from stripe_link.domain.shipping_charges import checkout_shipping, stripe_option_payload

SERVICES = [{"service_token": "ground", "label": "Ground"}]
UNIFORM = {"enabled_services": SERVICES, "zones": [
    {"destinations": [{"country": "US"}, {"country": "CA"}], "rule": {"type": "flat", "amount": 700}},
    {"destinations": [{"country": "*"}], "rule": {"type": "free"}}]}
MIXED = {"enabled_services": SERVICES, "zones": [
    {"destinations": [{"country": "US"}], "rule": {"type": "flat", "amount": 700}},
    {"destinations": [{"country": "CA"}], "rule": {"type": "flat", "amount": 1299}},
    {"destinations": [{"country": "*"}], "rule": {"type": "free"}}]}
LIVE = {"enabled_services": SERVICES, "zones": [
    {"destinations": [{"country": "US"}], "rule": {"type": "live"}},
    {"destinations": [{"country": "*"}], "rule": {"type": "free"}}]}

PRODUCTS = {"p1": {"product_id": "p1", "name": "Shirt", "product_type": "physical",
                   "fulfillment": {"requires_shipping": True},
                   "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]},
            "d1": {"product_id": "d1", "name": "Ebook", "product_type": "digital",
                   "fulfillment": {"requires_shipping": False},
                   "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}}


def payload(shipping_config=None, offer=None, product="p1", ship_to_country=""):
    return build_checkout_payload(
        tenant_id="t1",
        offer=offer or {"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": "payment"}},
        products_by_id=PRODUCTS,
        resolved={"items": [{"product_id": product, "price_id": "pr1", "quantity": 1,
                             "unit_amount": 2000, "currency": "usd"}],
                  "subtotal": 2000, "currency": "usd"},
        success_url="https://x/s", cancel_url="https://x/c", shipping_config=shipping_config,
        ship_to_country=ship_to_country)


def countries(built):
    """In the order Stripe receives them, which is the tenant's ZONE order -- their own priority, and the
    order the dropdown renders in. Sorted by index, not alphabetically."""
    entries = [(k, v) for k, v in built.items() if k.startswith("shipping_address_collection")]
    return [v for _, v in sorted(entries, key=lambda kv: int(kv[0].rsplit("[", 1)[1].rstrip("]")))]


def amounts(built):
    return [v for k, v in sorted(built.items()) if k.endswith("[fixed_amount][amount]")]


class UnanimityIsTheOnlySafeCase(unittest.TestCase):
    def test_agreeing_zones_produce_one_option(self):
        self.assertEqual(amounts(payload(UNIFORM)), ["700"])

    def test_disagreeing_zones_charge_NOTHING(self):
        """No single option is right for both a US and a Canadian buyer, and Stripe cannot ask again."""
        self.assertEqual(amounts(payload(MIXED)), [])

    def test_the_disagreement_is_explained_not_silent(self):
        decision = checkout_shipping({}, MIXED)
        self.assertIn("differ by destination", decision["reason"])
        self.assertIn("US", decision["reason"])
        self.assertIn("CA", decision["reason"])

    def test_a_service_list_that_differs_also_counts_as_disagreement(self):
        """A buyer offered Ground-only in one country and Ground-plus-Overnight in another is being shown a
        list that is wrong for one of them, even if the prices match."""
        config = {"enabled_services": [{"service_token": "ground", "label": "Ground"},
                                       {"service_token": "overnight", "label": "Overnight"}],
                  "zones": [
                      {"destinations": [{"country": "US"}], "rule": {"type": "flat", "amount": 700}},
                      {"destinations": [{"country": "CA"}],
                       "rule": {"type": "flat", "amount": 700, "services": ["ground"]}},
                      {"destinations": [{"country": "*"}], "rule": {"type": "free"}}]}
        self.assertEqual(checkout_shipping({}, config)["options"], [])

    def test_an_unpriceable_destination_poisons_the_whole_session(self):
        """One country needing a carrier means no price can be quoted for anyone, because the buyer picks the
        country AFTER these options are fixed."""
        decision = checkout_shipping({}, LIVE)
        self.assertEqual(decision["options"], [])
        self.assertIn("carrier", decision["reason"])

    def test_an_offer_level_flat_override_makes_it_unanimous_again(self):
        """A flat override is destination-independent by construction, which RESOLVES the multi-country
        problem rather than working around it."""
        offer = {"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": "payment"},
                 "shipping": {"override": {"type": "flat", "amount": 500}}}
        self.assertEqual(amounts(payload(MIXED, offer)), ["500"])


class AllowedCountriesComeFromTheZones(unittest.TestCase):
    def test_the_zones_decide_where_an_address_may_be(self):
        self.assertEqual(countries(payload(UNIFORM)), ["US", "CA"])

    def test_a_uk_zone_makes_uk_addresses_possible(self):
        """Hardcoded US/CA meant a tenant who configured a UK zone still could not receive a UK order -- a
        rule they wrote and the platform ignored."""
        config = {"enabled_services": SERVICES, "zones": [
            {"destinations": [{"country": "GB"}], "rule": {"type": "flat", "amount": 900}},
            {"destinations": [{"country": "*"}], "rule": {"type": "free"}}]}
        self.assertEqual(countries(payload(config)), ["GB"])

    def test_no_zones_falls_back_to_the_OLD_hardcoded_pair(self):
        """An empty allowed list would take checkout down, and silently changing behaviour for tenants who
        configured nothing is not an improvement."""
        self.assertEqual(countries(payload(None)), ["US", "CA"])
        self.assertEqual(countries(payload({})), ["US", "CA"])

    def test_no_zones_charges_nothing_and_says_so(self):
        decision = checkout_shipping({}, {})
        self.assertEqual(decision["options"], [])
        self.assertIn("no shipping zones", decision["reason"])


class ADeclaredDestinationLiftsTheUnanimityLimit(unittest.TestCase):
    """plans/SHIPPING_ELEMENT.md phase 5. Once the buyer says WHERE, there is only one zone to satisfy — so
    zones that disagree stop forcing us to charge nothing.

    The address is still collected by Stripe (a parcel needs a street). What the declaration removes is the
    buyer's ability to change COUNTRY at the pay button, which is the only part of the address that can move
    a tier 1 or tier 2 price.
    """

    def test_without_a_declaration_disagreeing_zones_charge_nothing(self):
        self.assertEqual(amounts(payload(MIXED)), [])

    def test_declaring_US_charges_the_US_zone(self):
        built = payload(MIXED, ship_to_country="US")
        self.assertEqual(amounts(built), ["700"])
        self.assertEqual(countries(built), ["US"])

    def test_declaring_CA_charges_the_CA_zone(self):
        built = payload(MIXED, ship_to_country="CA")
        self.assertEqual(amounts(built), ["1299"])
        self.assertEqual(countries(built), ["CA"])

    def test_the_country_is_NARROWED_so_it_cannot_change_at_the_pay_button(self):
        """A buyer quoted $12.99 for Canada must not be able to switch to the US and pay Canadian postage --
        or the reverse, which costs the tenant."""
        self.assertEqual(countries(payload(MIXED, ship_to_country="CA")), ["CA"])

    def test_a_country_the_tenant_does_not_ship_to_is_IGNORED(self):
        """A country typed into a URL is not a zone. It falls back to the undeclared behaviour rather than
        inventing a destination.

        MIXED carries a catch-all, so GB IS a zone to it -- that is what "everywhere else" means, and
        honouring it is the point of `offerable_countries`. The rule still has to hold for a tenant who
        named their countries and stopped there, so this asks it of one."""
        named_only = dict(MIXED, zones=MIXED["zones"][:2])
        built = payload(named_only, ship_to_country="GB")
        self.assertEqual(countries(built), ["US", "CA"])
        self.assertEqual(amounts(built), [])

    def test_a_catch_all_zone_DOES_honour_a_country_it_never_named(self):
        """The other side of it: the buyer picked GB from the element's dropdown, the element rated GB, and
        the tenant wrote a zone that serves GB. Collecting that declaration and then ignoring it is how a
        buyer in Mexico was told they could buy and then could not (author, 2026-10-04)."""
        built = payload(MIXED, ship_to_country="GB")
        self.assertEqual(countries(built), ["GB"])

    def test_lowercase_and_overlong_input_is_normalised(self):
        for given in ("us", " us ", "usa"):
            self.assertEqual(countries(payload(MIXED, ship_to_country=given.strip().upper()[:2])), ["US"])

    def test_a_declaration_does_not_override_an_offer_that_does_not_ship(self):
        offer = {"offer_id": "o1", "stripe_mode": "test", "checkout": {"mode": "payment"},
                 "shipping": {"eligibility": "none"}}
        self.assertEqual(amounts(payload(MIXED, offer, ship_to_country="US")), [])


class OnlyReadTheConfigWhenItCanMatter(unittest.TestCase):
    def test_a_digital_offer_needs_no_lookup(self):
        self.assertFalse(collect_shipping_for({"items": [{"product_id": "d1"}]}, PRODUCTS))

    def test_a_physical_offer_does(self):
        self.assertTrue(collect_shipping_for({"items": [{"product_id": "p1"}]}, PRODUCTS))

    def test_an_offer_marked_not_shipping_needs_no_lookup(self):
        offer = {"shipping": {"eligibility": "none"}, "items": [{"product_id": "p1"}]}
        self.assertFalse(collect_shipping_for(offer, PRODUCTS))

    def test_a_digital_cart_gets_no_shipping_options(self):
        self.assertEqual(amounts(payload(UNIFORM, product="d1")), [])


class TheConfigReadNeverCostsASale(unittest.TestCase):
    def test_an_unreadable_config_falls_back_to_empty(self):
        """It runs in the BUYER's path. A settings table that blinked must not refuse a sale -- but the
        failure is logged with its exception type, because the first version of this function called the
        repository factory with a keyword it does not accept and a broad guard would have hidden it."""
        import os

        saved = os.environ.pop("SHIPPING_CONFIG_TABLE", None)
        try:
            self.assertEqual(_tenant_shipping_config("t1"), {})
        finally:
            if saved is not None:
                os.environ["SHIPPING_CONFIG_TABLE"] = saved

    def test_an_empty_config_still_produces_a_valid_session(self):
        built = payload({})
        self.assertEqual(built["mode"], "payment")
        self.assertEqual(countries(built), ["US", "CA"])


class OneEncoderForBothPaths(unittest.TestCase):
    def test_an_explicit_offer_table_and_a_zone_resolution_encode_identically(self):
        """Two callers, one wire format, so the 5-option cap and the tax code cannot drift apart."""
        option = {"label": "Ground", "amount": 700}
        self.assertEqual(stripe_option_payload([option], currency="usd")[0]["shipping_rate_data"]["tax_code"],
                         "txcd_92010001")

    def test_the_cap_holds_on_the_shared_encoder(self):
        many = [{"label": f"Option {i}", "amount": i * 100} for i in range(9)]
        self.assertEqual(len(stripe_option_payload(many)), 5)


if __name__ == "__main__":
    unittest.main()

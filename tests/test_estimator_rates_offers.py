"""The rate estimator rates an OFFER -- the cart a buyer actually gets.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0e. `preview_rates` took `product_ids[]` the tenant assembled by
hand, so it rated a cart no buyer would ever have: one product showed $6.57 while the three-item bundle
shipped for $19. The offer IS the cart. Changing the input makes the preview AUTHORITATIVE rather than
indicative -- same offer, same packer, same rater, same path a buyer's `/shipping-quote` runs.
"""
import json
import unittest

from handlers.shipping import preview_rates

MEASURED = {"length_in": 4, "width_in": 3, "height_in": 2, "weight_lb": 1.0}


def product(pid, name, dims=MEASURED):
    fulfillment = {"requires_shipping": True, "weight_lb": 1.0}
    if dims:
        fulfillment["item_dimensions"] = dims
    return {"product_id": pid, "name": name, "product_type": "physical", "fulfillment": fulfillment}


CONFIG = {
    "ship_from_address": {"name": "Shop", "street1": "1 Main", "city": "Denver", "state": "CO",
                          "postal_code": "80301", "country": "US"},
    "provider": {"name": "mock", "api_key_ref": "ref_1"},
    "boxes": [{"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15},
              {"name": "Medium", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35}],
}
OFFER = {"offer_id": "o1", "tenant_id": "t1",
         "items": [{"product_id": "a", "quantity": 1}, {"product_id": "b", "quantity": 1}],
         "purchase_opportunities": [{"stage": "checkout", "product_id": "c", "price_id": "pr"}]}
PRODUCTS = {"a": product("a", "Gummies"), "b": product("b", "Protein"), "c": product("c", "Shaker")}


class Repo:
    def __init__(self, docs):
        self.docs = docs

    def get(self, tenant_id, doc_id=None):
        return self.docs.get(doc_id or tenant_id)


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "mock_key"


def call(body, products=None, offer=OFFER, config=None):
    event = {"requestContext": {"authorizer": {"claims": {"sub": "t1"}}}, "httpMethod": "POST",
             "body": json.dumps(body)}
    response = preview_rates(event, Repo({"t1": config or CONFIG}), Cipher(),
                             products_repo=Repo(products or PRODUCTS), offers_repo=Repo({"o1": offer}))
    return response, json.loads(response["body"])


class AnOfferIsTheSubjectTests(unittest.TestCase):
    def test_an_offer_rates_its_own_items(self):
        _, body = call({"offer_id": "o1"})
        self.assertTrue(body["rates"])
        self.assertGreaterEqual(body["parcel_count"], 1)

    def test_an_unknown_offer_is_a_404(self):
        response, body = call({"offer_id": "o1"}, offer=None)
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(body["error"], "offer_not_found")

    def test_hand_picked_products_still_work_as_the_SECONDARY_path(self):
        # Measuring a new product before it belongs to any offer is a real case; making it the only case
        # was the mistake.
        _, body = call({"product_ids": ["a"]})
        self.assertTrue(body["rates"])

    def test_one_of_the_two_is_required(self):
        response, body = call({})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body["error"], "missing_subject")


class EveryParcelIsRatedTests(unittest.TestCase):
    def test_the_whole_order_is_priced_not_just_the_first_parcel(self):
        # Rating `parcels[0]` is right when comparing boxes and wrong the moment the subject is an ORDER.
        big = {"length_in": 20, "width_in": 20, "height_in": 20, "weight_lb": 5}
        products = {"a": product("a", "Big A", big), "b": product("b", "Big B", big),
                    "c": PRODUCTS["c"]}
        _, body = call({"offer_id": "o1"}, products=products)
        self.assertGreater(body["parcel_count"], 1)
        two = body["rates"][0]["amount"]
        _, single = call({"product_ids": ["a"]}, products=products)
        self.assertGreater(two, single["rates"][0]["amount"])

    def test_the_breakdown_is_returned_not_just_a_price(self):
        # "3 parcels: Small x2" shows a tenant the consequence of unmeasured goods far more plainly than
        # a readiness list does.
        _, body = call({"offer_id": "o1"})
        self.assertEqual(len(body["parcels"]), body["parcel_count"])
        self.assertIn("box_name", body["parcels"][0])


class UnmeasuredGoodsShipFreeTests(unittest.TestCase):
    def test_an_offer_of_unmeasured_products_reports_free_rather_than_erroring(self):
        products = {k: product(k, PRODUCTS[k]["name"], dims=None) for k in PRODUCTS}
        response, body = call({"offer_id": "o1"}, products=products)
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(body["ships_free"])
        self.assertEqual(body["rates"], [])

    def test_it_names_which_products_caused_it(self):
        # "2 of 3" is not actionable; a name is.
        products = {"a": product("a", "Gummies", dims=None), "b": PRODUCTS["b"], "c": PRODUCTS["c"]}
        _, body = call({"offer_id": "o1"}, products=products)
        self.assertIn("Gummies", body["unmeasured"])
        self.assertNotIn("Protein", body["unmeasured"])


class TheBumpExposureIsShownTests(unittest.TestCase):
    def test_a_bump_that_adds_a_parcel_is_reported(self):
        # A bump taken on Stripe's hosted page can never be priced at checkout -- `optional_items` are
        # chosen after `shipping_options` is fixed. Disclosure is the whole remedy available.
        big = {"length_in": 20, "width_in": 20, "height_in": 20, "weight_lb": 5}
        products = {"a": PRODUCTS["a"], "b": PRODUCTS["b"], "c": product("c", "Shaker", big)}
        _, body = call({"offer_id": "o1"}, products=products)
        self.assertGreaterEqual(body["bump_parcel_delta"], 1)
        self.assertIn("Shaker", body["bump_products"])

    def test_a_bump_that_fits_the_same_box_is_genuinely_free(self):
        tiny = {"length_in": 1, "width_in": 1, "height_in": 1, "weight_lb": 0.1}
        products = {"a": PRODUCTS["a"], "b": PRODUCTS["b"], "c": product("c", "Shaker", tiny)}
        _, body = call({"offer_id": "o1"}, products=products)
        self.assertEqual(body["bump_parcel_delta"], 0)

    def test_an_offer_with_no_bump_says_nothing_about_bumps(self):
        plain = {k: v for k, v in OFFER.items() if k != "purchase_opportunities"}
        _, body = call({"offer_id": "o1"}, offer=plain)
        self.assertNotIn("bump_parcel_delta", body)

    def test_hand_picked_products_have_no_bump_either(self):
        _, body = call({"product_ids": ["a"]})
        self.assertNotIn("bump_parcel_delta", body)


class GrantsTests(unittest.TestCase):
    def test_the_function_may_read_the_offers_it_now_rates(self):
        import pathlib

        template = (pathlib.Path(__file__).resolve().parents[1]
                    / "template.yaml").read_text(encoding="utf-8")
        block = template.split("  ShippingFunction:", 1)[1].split("      Events:", 1)[0]
        self.assertIn("!Ref OffersTable", block)


class TheScreenAsksForAnOfferTests(unittest.TestCase):
    import pathlib as _pathlib

    SCREEN = (_pathlib.Path(__file__).resolve().parents[1]
              / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    def test_the_offer_picker_is_the_primary_control(self):
        self.assertIn('v-model="preview.offer_id"', self.SCREEN)
        self.assertIn("Choose an offer…", self.SCREEN)

    def test_individual_products_are_demoted_not_removed(self):
        # Measuring a new product before it belongs to any offer is a real case.
        self.assertIn("Or rate individual products", self.SCREEN)
        self.assertIn("<details class=\"preview-adhoc\"", self.SCREEN)

    def test_choosing_one_clears_the_other(self):
        # Sending both would leave the server to guess which the tenant meant.
        self.assertIn('@change="preview.product_ids = []"', self.SCREEN)
        self.assertIn("preview.offer_id = ''; togglePreviewProduct", self.SCREEN)

    def test_the_offer_wins_on_the_wire(self):
        block = self.SCREEN.split("async function runRatePreview", 1)[1][:1400]
        self.assertIn("offer_id: preview.offer_id || undefined", block)
        self.assertIn("product_ids: preview.offer_id ? undefined : preview.product_ids", block)

    def test_the_parcel_breakdown_is_summarised(self):
        self.assertIn("previewParcelSummary", self.SCREEN)
        self.assertIn('parcels"}: ${parts.join(", ")}', self.SCREEN.replace("'", '"'))

    def test_ships_free_is_an_answer_not_an_error(self):
        block = self.SCREEN.split("async function runRatePreview", 1)[1][:2200]
        self.assertIn("!previewShipsFree.value", block)
        self.assertIn("This ships free.", self.SCREEN)

    def test_the_bump_exposure_is_stated_with_what_to_do_about_it(self):
        self.assertIn("previewBumpDelta", self.SCREEN)
        self.assertIn("cannot reprice it after", self.SCREEN)
        self.assertIn("make the bump digital", self.SCREEN)

    def test_a_failed_offer_load_leaves_the_product_path_working(self):
        block = self.SCREEN.split("async function loadOffers", 1)[1][:300]
        self.assertIn("offers.value = []", block)

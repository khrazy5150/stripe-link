import copy
import unittest

from stripe_link.domain.funnels import (
    FunnelError,
    funnel_context_items,
    funnel_reserved_slugs,
    funnel_slug_entries,
    funnel_step_slug,
    post_purchase_plan,
    resolve_funnel_transition,
)


def post_checkout(**overrides):
    base = {
        "thank_you_page": {"page_id": "page_thank_you"},
        "funnel_steps": [
            {"step_id": "upsell_1", "page_id": "page_upsell_1", "on_accept": "thank_you", "on_decline": "downsell_1"},
            {"step_id": "downsell_1", "page_id": "page_downsell_1", "on_accept": "thank_you", "on_decline": "thank_you"},
        ],
    }
    base.update(overrides)
    return base


class ResolveFunnelTransitionTests(unittest.TestCase):
    def test_first_hop_resolves_to_first_step(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id=None, outcome="accept")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_upsell_1", "step_id": "upsell_1"})

    def test_first_hop_with_no_steps_resolves_to_thank_you_page(self):
        destination = resolve_funnel_transition(post_checkout(funnel_steps=[]), current_step_id=None, outcome="accept")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_thank_you", "step_id": "thank_you"})

    def test_first_hop_with_no_steps_resolves_to_external_thank_you_url(self):
        destination = resolve_funnel_transition(
            post_checkout(funnel_steps=[], thank_you_page={"url": "https://example.com/thanks"}),
            current_step_id=None,
            outcome="accept",
        )
        self.assertEqual(destination, {"kind": "url", "url": "https://example.com/thanks"})

    def test_declining_upsell_routes_to_downsell(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id="upsell_1", outcome="decline")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_downsell_1", "step_id": "downsell_1"})

    def test_accepting_upsell_routes_to_thank_you(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id="upsell_1", outcome="accept")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_thank_you", "step_id": "thank_you"})

    def test_declining_downsell_terminates_at_thank_you(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id="downsell_1", outcome="decline")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_thank_you", "step_id": "thank_you"})

    def test_unknown_current_step_raises(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition(post_checkout(), current_step_id="not_a_step", outcome="accept")

    def test_unknown_target_step_raises(self):
        broken = post_checkout(funnel_steps=[
            {"step_id": "upsell_1", "page_id": "page_upsell_1", "on_accept": "missing_step", "on_decline": "thank_you"},
        ])
        with self.assertRaises(FunnelError):
            resolve_funnel_transition(broken, current_step_id="upsell_1", outcome="accept")

    def test_detached_funnel_id_is_rejected_as_unsupported(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition({"funnel_id": "funnel_123"}, current_step_id=None, outcome="accept")

    def test_invalid_outcome_raises(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition(post_checkout(), current_step_id="upsell_1", outcome="maybe")

    def test_missing_thank_you_configuration_raises(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition({}, current_step_id=None, outcome="accept")


class FunnelSlugEntriesTests(unittest.TestCase):
    def test_step_slug_folds_to_hyphenated_slug(self):
        self.assertEqual(funnel_step_slug("upsell_1"), "/upsell-1")
        self.assertEqual(funnel_step_slug("Down Sell #2"), "/down-sell-2")
        self.assertEqual(funnel_step_slug("---"), "")

    def test_entries_map_thank_you_and_steps_to_noindex_types(self):
        entries = funnel_slug_entries(post_checkout())
        self.assertEqual(entries[0], {"slug": "/thank-you", "page_id": "page_thank_you", "page_type": "thank_you"})
        self.assertEqual(entries[1], {"slug": "/upsell-1", "page_id": "page_upsell_1", "page_type": "funnel_step"})
        self.assertEqual(entries[2], {"slug": "/downsell-1", "page_id": "page_downsell_1", "page_type": "funnel_step"})

    def test_external_thank_you_url_and_detached_funnel_yield_no_entries(self):
        self.assertEqual(funnel_slug_entries({"thank_you_page": {"url": "https://x.example/ty"}}), [])
        self.assertEqual(funnel_slug_entries({"funnel_id": "fnl_1"}), [])
        self.assertEqual(funnel_slug_entries({}), [])


def _product(product_id, prices):
    return {"product_id": product_id, "name": product_id, "prices": prices}


class FunnelDerivationTests(unittest.TestCase):
    def setUp(self):
        self.products = {
            "prod_up": _product("prod_up", [
                {"price_id": "price_up", "context": "upsell", "unit_amount": 2000, "currency": "usd"},
                {"price_id": "price_std", "context": "standard", "unit_amount": 3000, "currency": "usd"},
            ]),
            "prod_down": _product("prod_down", [
                {"price_id": "price_down", "context": "downsell", "unit_amount": 1000, "currency": "usd"},
            ]),
        }
        self.offer = {"funnel": {
            "upsells": [{"product_id": "prod_up", "price_id": "price_up"}],
            "downsells": [{"product_id": "prod_down", "price_id": "price_down"}],
        }}

    def test_resolves_upsell_and_downsell_items(self):
        ups = funnel_context_items(self.offer, self.products, "upsell")
        self.assertEqual([(i["product_id"], i["price_id"]) for i in ups], [("prod_up", "price_up")])
        downs = funnel_context_items(self.offer, self.products, "downsell")
        self.assertEqual([(i["product_id"], i["price_id"]) for i in downs], [("prod_down", "price_down")])

    def test_skips_entry_with_wrong_context_or_missing_product(self):
        offer = {"funnel": {"upsells": [
            {"product_id": "prod_up", "price_id": "price_std"},   # exists but NOT an upsell price
            {"product_id": "prod_missing", "price_id": "price_x"},  # product not loaded
            {"product_id": "prod_up", "price_id": "price_up"},    # valid
        ]}}
        self.assertEqual([i["price_id"] for i in funnel_context_items(offer, self.products, "upsell")], ["price_up"])

    def test_adding_a_price_takes_effect_WITHOUT_re_saving_the_offer(self):
        # The bug this closes. Roles used to be read from the offer's stored placement.surface, so adding a
        # downsell price to a product changed nothing until every offer containing it was re-saved -- while
        # DELETING a price took effect immediately. Derivation makes both directions behave the same.
        offer = {"funnel": {"upsells": [{"product_id": "prod_up", "price_id": "price_up"}]}}
        self.assertEqual(funnel_context_items(offer, self.products, "downsell"), [])

        products = copy.deepcopy(self.products)
        products["prod_up"]["prices"].append(
            {"price_id": "price_dn", "context": "downsell", "unit_amount": 900, "currency": "usd"})
        # Offer document untouched — only the product changed.
        downs = funnel_context_items(offer, products, "downsell")
        self.assertEqual([(i["product_id"], i["price_id"]) for i in downs], [("prod_up", "price_dn")])

    def test_removing_a_price_still_takes_effect_immediately(self):
        # The direction that already worked must keep working.
        products = copy.deepcopy(self.products)
        products["prod_up"]["prices"] = [p for p in products["prod_up"]["prices"] if p["context"] != "upsell"]
        self.assertEqual(funnel_context_items(self.offer, products, "upsell"), [])

    def test_a_role_is_not_configurable_per_offer(self):
        # Deriving means the offer's own stored funnel list carries no authority. Documented consequence:
        # a product's upsell price makes it an upsell in EVERY offer that includes it.
        offer_claiming_none = {"items": [{"product_id": "prod_up"}], "funnel": {"upsells": []}}
        ups = funnel_context_items(offer_claiming_none, self.products, "upsell")
        self.assertEqual([i["product_id"] for i in ups], ["prod_up"])

    def test_reserved_slugs_in_flow_order(self):
        self.assertEqual(funnel_reserved_slugs(self.offer, self.products), ["/upsell", "/downsell", "/thank-you"])

    def test_reserved_slugs_thank_you_only_without_funnel(self):
        self.assertEqual(funnel_reserved_slugs({}, self.products), ["/thank-you"])

    def test_reserved_slugs_omit_downsell_when_none_resolvable(self):
        offer = {"funnel": {"upsells": [{"product_id": "prod_up", "price_id": "price_up"}]}}
        self.assertEqual(funnel_reserved_slugs(offer, self.products), ["/upsell", "/thank-you"])


class PostPurchasePlanTests(unittest.TestCase):
    def _price(self, price_id, context, amount):
        return {"price_id": price_id, "context": context, "unit_amount": amount, "currency": "usd"}

    def test_upsell_pairs_same_products_downsell_in_place(self):
        # §6: the downsell is the SAME product's downsell-context price, paired by product_id.
        products = {"prod_a": _product("prod_a", [
            self._price("price_a_up", "upsell", 2217),
            self._price("price_a_down", "downsell", 1200),
            self._price("price_a_std", "standard", 3709),
        ])}
        offer = {"funnel": {
            "upsells": [{"product_id": "prod_a", "price_id": "price_a_up"}],
            "downsells": [{"product_id": "prod_a", "price_id": "price_a_down"}],
        }}
        plan = post_purchase_plan(offer, products)
        self.assertEqual(plan["strategy"], "sequence")
        self.assertEqual(len(plan["upsells"]), 1)
        entry = plan["upsells"][0]
        self.assertEqual(entry["sequence"], 1)
        self.assertEqual(entry["price_id"], "price_a_up")
        self.assertEqual(entry["downsell"]["price_id"], "price_a_down")

    def test_upsell_without_downsell_has_none(self):
        products = {"prod_a": _product("prod_a", [self._price("price_a_up", "upsell", 2000)])}
        offer = {"funnel": {"upsells": [{"product_id": "prod_a", "price_id": "price_a_up"}]}}
        plan = post_purchase_plan(offer, products)
        self.assertIsNone(plan["upsells"][0]["downsell"])

    def test_downsell_only_product_is_never_surfaced(self):
        # A product with a downsell price but no upsell never appears (documented gap): no upsell to attach to.
        products = {"prod_d": _product("prod_d", [self._price("price_d_down", "downsell", 900)])}
        offer = {"funnel": {"downsells": [{"product_id": "prod_d", "price_id": "price_d_down"}]}}
        plan = post_purchase_plan(offer, products)
        self.assertEqual(plan["upsells"], [])

    def test_four_or_more_upsells_force_carousel_strategy(self):
        products, upsells = {}, []
        for i in range(4):
            pid = f"prod_{i}"
            products[pid] = _product(pid, [self._price(f"price_{i}_up", "upsell", 1000 + i)])
            upsells.append({"product_id": pid, "price_id": f"price_{i}_up"})
        plan = post_purchase_plan({"funnel": {"upsells": upsells}}, products)
        self.assertEqual(plan["strategy"], "carousel")
        self.assertEqual([u["sequence"] for u in plan["upsells"]], [1, 2, 3, 4])

    def test_three_upsells_stay_sequence(self):
        products, upsells = {}, []
        for i in range(3):
            pid = f"prod_{i}"
            products[pid] = _product(pid, [self._price(f"price_{i}_up", "upsell", 1000 + i)])
            upsells.append({"product_id": pid, "price_id": f"price_{i}_up"})
        self.assertEqual(post_purchase_plan({"funnel": {"upsells": upsells}}, products)["strategy"], "sequence")

    def test_no_upsells_yields_empty_sequence_plan(self):
        self.assertEqual(post_purchase_plan({}, {}), {"strategy": "sequence", "upsells": []})


if __name__ == "__main__":
    unittest.main()

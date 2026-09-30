"""Where a refund policy comes from, and that no live page's promise changes by accident.

plans/REFUND_POLICY.md. The bug: `dashboard/src/stores/products.js` returned a hardcoded literal, stamped
`source: "user_preference_default"` on it, and the renderer published it. 29 of 32 dev products carry it.

The regression tests that matter here are the ones asserting what does NOT change. A refund window on a
storefront is an offer to a buyer, so resolution must reproduce today's promise exactly until a tenant
deliberately sets their own -- with one exception, proven below, where today's page prints the same
paragraph twice.
"""
import unittest

from stripe_link.domain.refund_policy import (
    CLASS_DEFAULTS,
    CONDITION_OPTIONS,
    DIGITAL,
    NON_REFUNDABLE,
    PHYSICAL,
    RETURN_METHOD_OPTIONS,
    SOURCE_PLATFORM_DEFAULT,
    SOURCE_PRODUCT_OVERRIDE,
    SOURCE_TENANT_DEFAULT,
    SOURCE_TIP_JAR,
    SUBSCRIPTION,
    WINDOW_OPTIONS,
    RefundPolicyError,
    build,
    generate_copy,
    normalize,
    platform_default,
    product_class,
    purchase_class,
    resolve,
    tenant_policies,
    window_days,
)

# The two shapes the JavaScript literal actually wrote, verbatim from jb-products-dev.
LITERAL_PHYSICAL = {
    "source": "user_preference_default", "refund_window": "30_days", "condition": "unused",
    "return_method": "no_return_customer_keeps", "short_label": "30-day money-back",
    "full_policy": ("Refunds are available within 30 days of delivery in unused condition.\n\nThis item does "
                    "not need to be returned. The customer may keep the item and dispose of it in a "
                    "responsible way. The seller may still grant a refund."),
}
LITERAL_DIGITAL = {
    "source": "user_preference_default", "refund_window": NON_REFUNDABLE, "condition": "any",
    "return_method": "digital_revoke_access", "short_label": "Non-refundable",
    "full_policy": ("All sales are final and as such, no item can be returned, replaced, or refunded in "
                    "full or in part."),
}


class ProductClass(unittest.TestCase):
    def test_type_drives_the_class(self):
        self.assertEqual(product_class({"product_type": "physical"}), PHYSICAL)
        self.assertEqual(product_class({"product_type": "digital"}), DIGITAL)
        self.assertEqual(product_class({"product_type": "subscription"}), SUBSCRIPTION)

    def test_services_and_unknowns_are_digital(self):
        """A service and a download have the same refund shape: nothing ships, nothing comes back.

        Deliberately not following fees.py, which gives services their own FEE class.
        """
        for product_type in ("service", "tip-jar", "course", "", None):
            self.assertEqual(product_class({"product_type": product_type}), DIGITAL)

    def test_only_recurring_makes_a_subscription(self):
        product = {"product_type": "physical",
                   "prices": [{"pricing_model": "recurring", "recurring": {"interval": "month"}}]}
        self.assertEqual(product_class(product), SUBSCRIPTION)

    def test_mixed_pricing_keeps_the_goods_class(self):
        """Live dev data: a physical product sold BOTH one-time and daily-recurring.

        The blunt rule (any recurring price wins) narrowed its published promise from 30 days of delivery
        to 72 hours of renewal -- for one-time buyers too, who are not renewing anything.
        """
        product = {"product_type": "physical", "prices": [
            {"pricing_model": "one_time"},
            {"pricing_model": "recurring", "recurring": {"interval": "day", "interval_count": 1}},
        ]}
        self.assertEqual(product_class(product), PHYSICAL)

    def test_purchase_class_answers_per_price(self):
        product = {"product_type": "physical", "prices": [{"pricing_model": "one_time"}]}
        self.assertEqual(purchase_class(product, {"pricing_model": "one_time"}), PHYSICAL)
        self.assertEqual(
            purchase_class(product, {"pricing_model": "recurring", "recurring": {"interval": "week"}}),
            SUBSCRIPTION)

    def test_recurring_label_without_an_interval_is_not_trusted(self):
        """validate_recurring_price's rule: such a price is SOLD as a one-time charge, and has been."""
        self.assertEqual(purchase_class({"product_type": "physical"}, {"recurring": {}}), PHYSICAL)


class GeneratedCopy(unittest.TestCase):
    def test_the_basis_follows_the_class(self):
        """The legacy generator rendered a 72-hour subscription window as "within 3 days of delivery" --
        wrong unit and wrong event, on a page making a commercial promise."""
        self.assertEqual(generate_copy(SUBSCRIPTION, "72_hours", "any")[1],
                         "Refunds are available within 72 hours of renewal.")
        self.assertEqual(generate_copy(PHYSICAL, "30_days", "unused")[1],
                         "Refunds are available within 30 days of delivery in unused condition.")
        self.assertEqual(generate_copy(DIGITAL, "14_days", "not_downloaded")[1],
                         "Refunds are available within 14 days of purchase provided the file has not "
                         "been downloaded.")

    def test_any_condition_adds_no_clause(self):
        self.assertEqual(generate_copy(PHYSICAL, "7_days", "any")[1],
                         "Refunds are available within 7 days of delivery.")

    def test_non_refundable_wording_is_the_published_sentence(self):
        self.assertEqual(generate_copy(DIGITAL, NON_REFUNDABLE, "any")[1],
                         LITERAL_DIGITAL["full_policy"])

    def test_the_return_note_is_not_baked_in(self):
        """The renderer emits it separately (html.py refund_policy_return_note), so including it here is
        why every published physical page prints that paragraph twice -- verified on
        jb-pages-dev/test/page_3VmYubKR3AM, once as "does not" and once as "doesn't"."""
        self.assertNotIn("may keep the item", generate_copy(PHYSICAL, "30_days", "unused")[1])

    def test_custom_generates_no_sentence(self):
        self.assertEqual(generate_copy(PHYSICAL, "custom", "any")[1], "")

    def test_every_window_and_condition_generates_something(self):
        for window in WINDOW_OPTIONS:
            for condition in CONDITION_OPTIONS:
                for policy_class in (PHYSICAL, DIGITAL, SUBSCRIPTION):
                    label, full = generate_copy(policy_class, window, condition)
                    self.assertTrue(label, (policy_class, window, condition))
                    if window != "custom":
                        self.assertTrue(full.endswith("."), (policy_class, window, condition))


class Windows(unittest.TestCase):
    def test_hours_round_down(self):
        """A window quoted in hours must never be stretched by day-rounding into a longer promise."""
        self.assertEqual(window_days("72_hours"), 3)

    def test_no_window_is_none_not_zero(self):
        self.assertIsNone(window_days(NON_REFUNDABLE))
        self.assertIsNone(window_days("custom"))
        self.assertIsNone(window_days("nonsense"))


class Build(unittest.TestCase):
    def test_refuses_unknown_vocabulary(self):
        for kwargs in ({"refund_window": "45_days"}, {"condition": "pristine"},
                       {"return_method": "print_label"}):
            base = {"refund_window": "30_days", "condition": "unused",
                    "return_method": "no_return_customer_keeps"} | kwargs
            with self.assertRaises(RefundPolicyError):
                build(PHYSICAL, **base)

    def test_refuses_stripe_cart_vocabulary(self):
        """The plan originally said port stripe-cart's tables; stripe-link's own enums hold live data."""
        with self.assertRaises(RefundPolicyError):
            build(PHYSICAL, refund_window="30_day_returns", condition="unused",
                  return_method="no_return_customer_keeps")

    def test_custom_window_requires_prose(self):
        """A custom policy IS its prose. Without it the page opens a summary onto nothing."""
        with self.assertRaises(RefundPolicyError):
            build(PHYSICAL, refund_window="custom", condition="any",
                  return_method="no_return_customer_keeps")
        ok = build(PHYSICAL, refund_window="custom", condition="any",
                   return_method="no_return_customer_keeps", full_policy="Ask us within a fortnight.")
        self.assertEqual(ok["full_policy"], "Ask us within a fortnight.")

    def test_tenant_wording_survives(self):
        policy = build(PHYSICAL, refund_window="30_days", condition="unused",
                       return_method="no_return_customer_keeps",
                       short_label="Our promise", full_policy="Legally reviewed sentence.")
        self.assertEqual(policy["short_label"], "Our promise")
        self.assertEqual(policy["full_policy"], "Legally reviewed sentence.")

    def test_keep_it_below_only_when_positive(self):
        self.assertNotIn("keep_it_below", build(
            PHYSICAL, refund_window="30_days", condition="unused",
            return_method="no_return_customer_keeps", keep_it_below=0))
        self.assertEqual(build(
            PHYSICAL, refund_window="30_days", condition="unused",
            return_method="no_return_customer_keeps", keep_it_below=2000)["keep_it_below"], 2000)


class Normalize(unittest.TestCase):
    def test_never_raises_on_rubbish(self):
        for junk in (None, "", 5, [], {"refund_window": "🙂"}, {"condition": None}):
            policy = normalize(junk, policy_class=PHYSICAL)
            self.assertEqual(policy["refund_window"], CLASS_DEFAULTS[PHYSICAL]["refund_window"])

    def test_unknown_values_fall_back_per_class(self):
        policy = normalize({"refund_window": "90_day_returns"}, policy_class=DIGITAL)
        self.assertEqual(policy["refund_window"], NON_REFUNDABLE)

    def test_decimal_keep_it_below(self):
        """Cents read back from DynamoDB arrive as Decimal; isinstance(x, int) is False for it."""
        from decimal import Decimal
        self.assertEqual(normalize({"keep_it_below": Decimal("2000")},
                                   policy_class=PHYSICAL)["keep_it_below"], 2000)

    def test_stored_wording_is_preserved(self):
        policy = normalize(LITERAL_DIGITAL, policy_class=DIGITAL)
        self.assertEqual(policy["full_policy"], LITERAL_DIGITAL["full_policy"])


class Resolution(unittest.TestCase):
    def test_no_tenant_default_says_platform_default(self):
        """The honesty fix: the old record claimed `user_preference_default` for a value no preference
        produced, and nothing anywhere read that preference."""
        policy = resolve(product={"product_type": "physical"})
        self.assertEqual(policy["source"], SOURCE_PLATFORM_DEFAULT)
        self.assertEqual(policy["mode"], "default")

    def test_the_literal_is_not_treated_as_an_override(self):
        """29 live products carry a policy stamped by a JavaScript literal. Treating those as overrides
        would freeze it forever -- every one would keep promising 30 days whatever the tenant later set."""
        product = {"product_type": "physical", "refund_policy": LITERAL_PHYSICAL}
        tenant = {"refund_policies": {PHYSICAL: {"refund_window": "60_days", "condition": "any",
                                                "return_method": "no_return_customer_keeps"}}}
        policy = resolve(tenant_config=tenant, product=product)
        self.assertEqual(policy["refund_window"], "60_days")
        self.assertEqual(policy["source"], SOURCE_TENANT_DEFAULT)

    def test_a_deliberate_override_wins(self):
        product = {"product_type": "physical", "refund_policy": dict(
            LITERAL_PHYSICAL, source=SOURCE_PRODUCT_OVERRIDE, refund_window="7_days")}
        tenant = {"refund_policies": {PHYSICAL: {"refund_window": "60_days", "condition": "any",
                                                "return_method": "no_return_customer_keeps"}}}
        policy = resolve(tenant_config=tenant, product=product)
        self.assertEqual(policy["refund_window"], "7_days")
        self.assertEqual(policy["mode"], "override")

    def test_tips_stay_non_refundable_whatever_the_tenant_sets(self):
        """tip_jar_provision writes non-refundable because a tip is not a purchase. A tenant's 30-day
        physical default must never make tips refundable."""
        product = {"product_type": "tip-jar", "refund_policy": {
            "source": SOURCE_TIP_JAR, "refund_window": NON_REFUNDABLE, "condition": "any",
            "return_method": "digital_revoke_access", "short_label": "Non-refundable",
            "full_policy": "Tips are gifts and are non-refundable."}}
        tenant = {"refund_policies": {DIGITAL: {"refund_window": "30_days", "condition": "any",
                                               "return_method": "no_return_customer_keeps"}}}
        policy = resolve(tenant_config=tenant, product=product)
        self.assertEqual(policy["refund_window"], NON_REFUNDABLE)
        self.assertEqual(policy["full_policy"], "Tips are gifts and are non-refundable.")

    def test_per_product_keep_it_below_survives_the_fall_through(self):
        """It is a fact about THIS item's postage economics, not a policy choice. returns.py reads it to
        waive a return that costs more to collect than the goods are worth."""
        product = {"product_type": "physical",
                   "refund_policy": dict(LITERAL_PHYSICAL, keep_it_below=1500)}
        self.assertEqual(resolve(product=product)["keep_it_below"], 1500)

    def test_price_decides_for_mixed_pricing(self):
        product = {"product_type": "physical", "prices": [
            {"price_id": "one", "pricing_model": "one_time"},
            {"price_id": "sub", "pricing_model": "recurring", "recurring": {"interval": "month"}}]}
        self.assertEqual(resolve(product=product, price=product["prices"][0])["policy_class"], PHYSICAL)
        self.assertEqual(resolve(product=product, price=product["prices"][1])["policy_class"], SUBSCRIPTION)

    def test_resolved_shape_is_what_the_consumers_already_read(self):
        """runtime/html.py reads short_label/full_policy; returns.py reads return_method/keep_it_below."""
        policy = resolve(product={"product_type": "physical"})
        for field in ("source", "refund_window", "condition", "return_method", "short_label",
                      "full_policy"):
            self.assertIn(field, policy)


class LivePromisesDoNotMove(unittest.TestCase):
    """The regression that matters: what 32 live dev products currently promise."""

    def test_the_digital_literal_resolves_to_identical_text(self):
        policy = resolve(product={"product_type": "digital", "refund_policy": LITERAL_DIGITAL})
        self.assertEqual(policy["short_label"], LITERAL_DIGITAL["short_label"])
        self.assertEqual(policy["full_policy"], LITERAL_DIGITAL["full_policy"])

    def test_the_physical_literal_loses_only_the_duplicated_paragraph(self):
        policy = resolve(product={"product_type": "physical", "refund_policy": LITERAL_PHYSICAL})
        self.assertEqual(policy["short_label"], LITERAL_PHYSICAL["short_label"])
        self.assertEqual(policy["full_policy"],
                         "Refunds are available within 30 days of delivery in unused condition.")
        self.assertTrue(LITERAL_PHYSICAL["full_policy"].startswith(policy["full_policy"]))

    def test_a_product_with_no_policy_still_renders_nothing_new(self):
        """3 live products carry no policy. The renderer returns "" for an empty one, and resolution must
        not invent a promise for a product that never made one."""
        self.assertEqual(resolve(product={"product_type": "physical"})["source"],
                         SOURCE_PLATFORM_DEFAULT)


class TenantDefaults(unittest.TestCase):
    def test_absent_classes_fall_back_and_say_so(self):
        policies = tenant_policies(None)
        self.assertEqual(sorted(policies), [DIGITAL, PHYSICAL, SUBSCRIPTION])
        for policy in policies.values():
            self.assertEqual(policy["source"], SOURCE_PLATFORM_DEFAULT)

    def test_a_set_class_is_labelled_as_the_tenants(self):
        policies = tenant_policies({"refund_policies": {PHYSICAL: {
            "refund_window": "60_days", "condition": "unopened",
            "return_method": "return_required"}}})
        self.assertEqual(policies[PHYSICAL]["source"], SOURCE_TENANT_DEFAULT)
        self.assertEqual(policies[DIGITAL]["source"], SOURCE_PLATFORM_DEFAULT)

    def test_platform_defaults_reproduce_the_literal(self):
        """The fault was provenance and editability, not the numbers. Changing them here would silently
        rewrite the promise on every live page that shows one."""
        self.assertEqual(platform_default(PHYSICAL)["refund_window"], "30_days")
        self.assertEqual(platform_default(PHYSICAL)["condition"], "unused")
        self.assertEqual(platform_default(DIGITAL)["refund_window"], NON_REFUNDABLE)
        self.assertEqual(platform_default(DIGITAL)["return_method"], "digital_revoke_access")

    def test_every_class_default_is_buildable(self):
        for policy_class, rule in CLASS_DEFAULTS.items():
            self.assertIn(rule["refund_window"], WINDOW_OPTIONS)
            self.assertIn(rule["condition"], CONDITION_OPTIONS)
            self.assertIn(rule["return_method"], RETURN_METHOD_OPTIONS)
            self.assertTrue(platform_default(policy_class)["full_policy"])


class VocabularyAgreesWithTheSchema(unittest.TestCase):
    """The enums live in Product.schema.json. A module that drifts from it writes invalid documents."""

    def _schema(self):
        import json
        with open("schemas/Product.schema.json") as handle:
            return json.load(handle)["properties"]["refund_policy"]["properties"]

    def test_windows_match(self):
        self.assertEqual(sorted(WINDOW_OPTIONS), sorted(self._schema()["refund_window"]["enum"]))

    def test_conditions_match(self):
        self.assertEqual(sorted(CONDITION_OPTIONS), sorted(self._schema()["condition"]["enum"]))

    def test_return_methods_match(self):
        self.assertEqual(sorted(RETURN_METHOD_OPTIONS), sorted(self._schema()["return_method"]["enum"]))

    def test_sources_are_valid(self):
        allowed = set(self._schema()["source"]["enum"])
        for source in (SOURCE_PRODUCT_OVERRIDE, SOURCE_TENANT_DEFAULT, SOURCE_PLATFORM_DEFAULT,
                       SOURCE_TIP_JAR):
            self.assertIn(source, allowed, f"{source} must be added to Product.schema.json")


if __name__ == "__main__":
    unittest.main()

"""Where a refund policy comes from, and that no live page's promise changes by accident.

plans/REFUND_POLICY.md. The bug: `dashboard/src/stores/products.js` returned a hardcoded literal, stamped
`source: "user_preference_default"` on it, and the renderer published it. 29 of 32 dev products carry it.

The regression tests that matter here are the ones asserting what does NOT change. A refund window on a
storefront is an offer to a buyer, so resolution must reproduce today's promise exactly until a tenant
deliberately sets their own -- with one exception, proven below, where today's page prints the same
paragraph twice.
"""
import pathlib
import unittest

from stripe_link.domain.refund_policy import (
    CLASS_FORM_SEEDS,
    CONDITION_LABELS,
    CONDITION_OPTIONS,
    CUSTOM,
    DIGITAL,
    KEEPS,
    RETURN_REQUIRED,
    REVOKE,
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
    product_class,
    purchase_class,
    resolve,
    default_return_shipping,
    tenant_policies,
    vocabulary,
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
            self.assertEqual(policy["refund_window"], CLASS_FORM_SEEDS[PHYSICAL]["refund_window"])

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
    def test_no_tenant_default_resolves_to_nothing(self):
        """The fallback is GONE (plans/REFUND_POLICY_AND_GUARANTEES.md P2). A tenant who has set nothing
        promises nothing: no sentence, no badge, no source. Silence is recoverable; a promise nobody
        chose is a dispute -- and for physical goods the old fallback said the buyer keeps the item AND
        may have their money back."""
        policy = resolve(product={"product_type": "physical"})
        self.assertEqual(policy["mode"], "unset")
        self.assertNotIn("source", policy)
        self.assertNotIn("full_policy", policy)
        self.assertNotIn("return_method", policy)

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
        waive a return that costs more to collect than the goods are worth. Needs a tenant default to
        fall THROUGH to, now that there is no platform one."""
        tenant = {"refund_policies": {PHYSICAL: {"refund_window": "30_days", "condition": "any",
                                                 "return_method": "return_required"}}}
        product = {"product_type": "physical",
                   "refund_policy": dict(LITERAL_PHYSICAL, keep_it_below=1500)}
        self.assertEqual(resolve(tenant_config=tenant, product=product)["keep_it_below"], 1500)

    def test_price_decides_for_mixed_pricing(self):
        product = {"product_type": "physical", "prices": [
            {"price_id": "one", "pricing_model": "one_time"},
            {"price_id": "sub", "pricing_model": "recurring", "recurring": {"interval": "month"}}]}
        self.assertEqual(resolve(product=product, price=product["prices"][0])["policy_class"], PHYSICAL)
        self.assertEqual(resolve(product=product, price=product["prices"][1])["policy_class"], SUBSCRIPTION)

    def test_resolved_shape_is_what_the_consumers_already_read(self):
        """runtime/html.py reads short_label/full_policy; returns.py reads return_method/keep_it_below.
        The shape holds when there IS a policy -- which now means a tenant set one."""
        tenant = {"refund_policies": {PHYSICAL: {"refund_window": "30_days", "condition": "unused",
                                                 "return_method": "return_required"}}}
        policy = resolve(tenant_config=tenant, product={"product_type": "physical"})
        for field in ("source", "refund_window", "condition", "return_method", "short_label",
                      "full_policy", "return_shipping"):
            self.assertIn(field, policy)


class LivePromisesDoNotMove(unittest.TestCase):
    """Superseded by P2, and kept as the record of what changed rather than deleted.

    These used to assert that the platform fallback reproduced the JavaScript literal word for word, so
    that removing the literal moved no live promise. That guarantee is now deliberately gone: the
    fallback promised, for physical goods, that the buyer keeps the item AND may have their money back,
    and nobody chose it. A product carrying the old literal resolves to NOTHING until its tenant sets a
    default -- which is the tenant-visible consequence P2 requires Configuration to announce.
    """

    def test_the_literal_no_longer_resolves_to_anything(self):
        for literal in (LITERAL_PHYSICAL, LITERAL_DIGITAL):
            with self.subTest(literal=literal["short_label"]):
                policy = resolve(product={"product_type": "physical", "refund_policy": literal})
                self.assertEqual(policy["mode"], "unset")

    def test_a_tenant_default_is_what_brings_the_promise_back(self):
        """And it is the tenant's wording, not the literal's -- which is the point of the whole family
        of plans: the promise on the page is one a human chose."""
        tenant = {"refund_policies": {PHYSICAL: {"refund_window": "90_days",
                                                 "condition": "working_condition",
                                                 "return_method": "return_required"}}}
        policy = resolve(tenant_config=tenant,
                         product={"product_type": "physical", "refund_policy": LITERAL_PHYSICAL})
        self.assertEqual(policy["mode"], "default")
        self.assertEqual(policy["short_label"], "90-day money-back")
        self.assertIn("in working condition", policy["full_policy"])


class TenantDefaults(unittest.TestCase):
    def test_absent_classes_are_simply_absent(self):
        """They used to be filled with the platform's fallback, which is how a promise nobody chose
        reached every live page. A caller must handle the gap rather than be handed a policy."""
        self.assertEqual(tenant_policies(None), {})

    def test_a_set_class_is_labelled_as_the_tenants(self):
        policies = tenant_policies({"refund_policies": {PHYSICAL: {
            "refund_window": "60_days", "condition": "unopened",
            "return_method": "return_required"}}})
        self.assertEqual(policies[PHYSICAL]["source"], SOURCE_TENANT_DEFAULT)
        self.assertNotIn(DIGITAL, policies)

    def test_nothing_manufactures_a_policy_any_more(self):
        """`platform_default` is gone. If it comes back, a tenant who set nothing starts promising
        again -- which is the entire fault this phase removed."""
        import stripe_link.domain.refund_policy as module
        self.assertFalse(hasattr(module, "platform_default"))

    def test_the_seeds_are_a_form_starting_point_not_a_promise(self):
        """They survive to fill the three selects when a tenant first enables a class, and to coerce a
        single bad field inside a policy that DOES exist. Neither can make a page say anything: the
        tenant still has to enable and save."""
        for policy_class, rule in CLASS_FORM_SEEDS.items():
            with self.subTest(policy_class=policy_class):
                self.assertIn(rule["refund_window"], WINDOW_OPTIONS)
                self.assertIn(rule["condition"], CONDITION_OPTIONS)
                self.assertIn(rule["return_method"], RETURN_METHOD_OPTIONS)
        self.assertEqual(tenant_policies({}), {})


class VocabularyAgreesWithTheSchema(unittest.TestCase):
    """The enums are duplicated across FOUR schema files, and this used to pin one of them.

    `Product`, `Page`, `Offer` and `TenantConfig` (three times, one per class) each carry their own copy
    of the refund window, condition and return-method enums -- six blocks in all. Pinning only Product
    let the other five drift silently, so widening the vocabulary would ship a document some other
    validator refuses. Widened BEFORE the vocabulary grew, so it proved the six were already in step
    rather than discovering it afterwards (plans/REFUND_POLICY_AND_GUARANTEES.md P1).
    """

    @staticmethod
    def _load(name):
        import json
        with open(f"schemas/{name}.schema.json") as handle:
            return json.load(handle)

    def _schema(self):
        return self._load("Product")["properties"]["refund_policy"]["properties"]

    def _every_policy_block(self):
        """Every refund-policy property block in every schema, as (where, properties) pairs.

        Found by SHAPE -- any object whose properties carry all three enums -- rather than by a list of
        paths. A path list is a second place to keep in step with the schemas, and would miss a block
        added somewhere new, which is precisely the drift this test exists to catch.
        """
        def walk(node, where, out):
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict) and all(
                        isinstance(props.get(k), dict) and "enum" in props[k]
                        for k in ("refund_window", "condition", "return_method")):
                    out.append((where, props))
                for key, value in node.items():
                    walk(value, f"{where}.{key}", out)
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{where}[{i}]", out)
            return out

        blocks = []
        for name in ("Product", "Page", "Offer", "TenantConfig"):
            walk(self._load(name), name, blocks)
        return blocks

    def test_every_schema_carries_the_same_vocabulary(self):
        seen = 0
        for where, props in self._every_policy_block():
            with self.subTest(schema=where):
                self.assertEqual(sorted(WINDOW_OPTIONS), sorted(props["refund_window"]["enum"]))
                self.assertEqual(sorted(CONDITION_OPTIONS), sorted(props["condition"]["enum"]))
                self.assertEqual(sorted(RETURN_METHOD_OPTIONS), sorted(props["return_method"]["enum"]))
                seen += 1
        # Six blocks, not one. A schema that stops being reachable by the walk above must fail here
        # rather than quietly reduce the coverage this test claims.
        self.assertEqual(seen, 6)

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


class TheVocabularyNamesRulesSellersActuallyUse(unittest.TestCase):
    """P1 of plans/REFUND_POLICY_AND_GUARANTEES.md.

    The condition list could not express the ordinary physical-goods rule. `unused` is stricter than most
    sellers mean and `any` gives away the only protection they have, so a tenant selling anything
    mechanical had no honest option and picked one of the two wrong ones.
    """

    def test_working_condition_exists_and_reads_as_a_clause(self):
        self.assertEqual(CONDITION_OPTIONS["working_condition"], "in working condition")

    def test_the_two_other_additions(self):
        self.assertIn("original packaging", CONDITION_OPTIONS["complete_in_packaging"])
        self.assertIn("loss of value", CONDITION_OPTIONS["any_value_adjusted"])

    def test_a_ninety_day_window_can_be_expressed(self):
        self.assertEqual(window_days("90_days"), 90)
        self.assertEqual(WINDOW_OPTIONS["90_days"]["short_label"], "90-day money-back")

    def test_every_condition_is_labelled(self):
        """A screen must never have to invent wording for a commercial term."""
        self.assertEqual(sorted(CONDITION_OPTIONS), sorted(CONDITION_LABELS))

    def test_value_adjusted_promises_no_arithmetic(self):
        """It changes the SENTENCE only. Refunds already support a partial amount and the merchant
        decides it; promising a deduction nothing computes would be a new implicit promise."""
        import stripe_link.domain.refund_policy as module
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        block = source.split("any_value_adjusted", 1)[1].split("}", 1)[0]
        self.assertNotIn("*", block)
        self.assertNotIn("round", block)


class WhoPaysTheReturnPostage(unittest.TestCase):
    """The missing half of "Free returns", and the single most commercially significant fact a returns
    policy states. `ledger.return_shipping_cost_entry` has recorded who BORE this cost since the shipping
    work; nothing has ever recorded who was PROMISED to."""

    def test_a_real_return_defaults_to_the_buyer(self):
        """The status quo on every page today: silence has always meant the customer arranges it. A
        seller-pays default would invent a promise no tenant made."""
        self.assertEqual(default_return_shipping(RETURN_REQUIRED), "buyer_pays")

    def test_nothing_travelling_back_makes_the_question_moot(self):
        for method in (KEEPS, REVOKE, CUSTOM):
            with self.subTest(method=method):
                self.assertEqual(default_return_shipping(method), "not_applicable")

    def test_build_rejects_an_unknown_value(self):
        with self.assertRaises(RefundPolicyError):
            build(PHYSICAL, refund_window="30_days", condition="any",
                  return_method=RETURN_REQUIRED, return_shipping="someone_else")

    def test_a_policy_stored_before_the_field_existed_still_normalises(self):
        """Nearly every stored policy predates it, so the fallback has to be the status quo."""
        policy = normalize({"refund_window": "30_days", "condition": "unused",
                            "return_method": RETURN_REQUIRED}, policy_class=PHYSICAL)
        self.assertEqual(policy["return_shipping"], "buyer_pays")

    def test_the_screen_is_given_the_options_and_the_defaults(self):
        vocab = vocabulary()
        self.assertEqual([o["value"] for o in vocab["return_shipping"]],
                         ["seller_pays", "buyer_pays", "not_applicable"])
        self.assertEqual(vocab["return_shipping_defaults"][RETURN_REQUIRED], "buyer_pays")

    def test_the_clause_is_the_servers_sentence(self):
        """Previewed from the server like every other promise on this screen -- a browser is not allowed
        to author one."""
        clauses = {o["value"]: o["clause"] for o in vocabulary()["return_shipping"]}
        self.assertEqual(clauses["seller_pays"], "Return postage is on us.")
        self.assertEqual(clauses["not_applicable"], "")


class ThePostageClauseRendersWithTheReturnNote(unittest.TestCase):
    """Appended to the NOTE, not to `full_policy`. The policy sentence belongs to `generate_copy` and the
    note belongs to the renderer -- the one-source rule that exists because the two were once both
    printing the return note, so every physical page said it twice."""

    @staticmethod
    def _note(**policy):
        from stripe_link.runtime.html import refund_policy_return_note
        return refund_policy_return_note({"return_method": RETURN_REQUIRED, **policy})

    def test_seller_pays_is_said_out_loud(self):
        self.assertTrue(self._note(return_shipping="seller_pays").endswith("Return postage is on us."))

    def test_buyer_pays_is_said_out_loud(self):
        self.assertIn("paid by the customer", self._note(return_shipping="buyer_pays"))

    def test_an_absent_field_adds_nothing(self):
        """Silence rather than a guess: a policy stored before the field existed must not gain a
        sentence about postage nobody wrote."""
        self.assertTrue(self._note().endswith("before the refund is completed."))

    def test_not_applicable_adds_nothing(self):
        self.assertTrue(self._note(return_shipping="not_applicable").endswith("completed."))

    def test_the_tenants_own_note_still_wins_outright(self):
        """Someone who wrote their own return instructions has said what they mean about postage too."""
        self.assertEqual(self._note(return_note="Post it back to us.", return_shipping="seller_pays"),
                         "Post it back to us.")

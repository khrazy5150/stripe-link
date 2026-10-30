"""P2 and P3 of plans/REFUND_POLICY_AND_GUARANTEES.md, and the hazard they share.

P3 says the two must land together, and the reason is the whole risk of the plan: remove the stamp
without moving `return_requirement` to `resolve()` in the SAME change and a product with no override
reads an empty policy, finds no `return_required`, and **every physical refund is released without the
goods coming back**.

These tests exist to make that impossible to reintroduce quietly.
"""

import unittest

from stripe_link.domain.refund_policy import apply_to_product, resolve, tenant_policies
from stripe_link.domain.returns import policy_snapshot, return_requirement

RETURNS = {"legal_defaults": {"refund_policies": {
    "physical": {"refund_window": "30_days", "condition": "working_condition",
                 "return_method": "return_required"}}}}
KEEPS = {"legal_defaults": {"refund_policies": {
    "physical": {"refund_window": "30_days", "condition": "any",
                 "return_method": "no_return_customer_keeps"}}}}

SHIPS = {"product_id": "p1", "name": "Mini Cam", "product_type": "physical",
         "fulfillment": {"requires_shipping": True}}
DOWNLOAD = {"product_id": "p2", "name": "Ebook", "product_type": "digital",
            "fulfillment": {"requires_shipping": False}}
LINES = [{"product_id": "p1"}]


class APhysicalRefundStillWaitsForTheGoods(unittest.TestCase):
    """The Definition of Done's own wording: proven by a test that resolves from a tenant default with
    NO product-level policy present."""

    def test_the_tenant_default_reaches_the_decision(self):
        self.assertIsNone(SHIPS.get("refund_policy"))
        requirement = return_requirement(LINES, {"p1": SHIPS}, tenant_config=RETURNS)
        self.assertTrue(requirement["required"])
        self.assertEqual([p["product_id"] for p in requirement["products"]], ["p1"])

    def test_a_keep_it_default_releases_the_money(self):
        """The same path in the other direction -- the tenant's choice is honoured either way."""
        self.assertFalse(return_requirement(LINES, {"p1": SHIPS}, tenant_config=KEEPS)["required"])

    def test_the_snapshot_carries_it_into_the_approval(self):
        snapshot = policy_snapshot(LINES, {"p1": SHIPS}, tenant_config=RETURNS)
        self.assertTrue(snapshot["return_required"])

    def test_no_policy_anywhere_still_asks_for_the_goods(self):
        """A tenant who set nothing has not said the buyer may keep a shipped item -- they have said
        nothing, and the two are opposite instructions. The OLD platform fallback answered "customer
        keeps" here, which is how a shipped item could be refunded with nothing coming back on a policy
        nobody chose. Requiring it is the recoverable direction: one click waives it, while a return
        wrongly skipped is goods AND money gone with nothing to click."""
        self.assertEqual(resolve(tenant_config={}, product=SHIPS)["mode"], "unset")
        self.assertTrue(return_requirement(LINES, {"p1": SHIPS}, tenant_config={})["required"])

    def test_a_download_is_never_asked_for(self):
        """It cannot be posted back, whatever any policy says."""
        self.assertFalse(return_requirement([{"product_id": "p2"}], {"p2": DOWNLOAD},
                                            tenant_config={})["required"])


class TheProductCarriesNoSnapshot(unittest.TestCase):
    def test_a_write_stores_no_policy(self):
        document = dict(SHIPS)
        apply_to_product(document, RETURNS)
        self.assertIsNone(document.get("refund_policy"))

    def test_an_override_survives_because_it_is_a_decision(self):
        document = dict(SHIPS, refund_policy={"source": "product_override", "refund_window": "7_days",
                                              "condition": "any", "return_method": "return_required"})
        apply_to_product(document, RETURNS)
        self.assertEqual(document["refund_policy"]["refund_window"], "7_days")

    def test_changing_the_default_changes_what_resolves_with_no_product_edited(self):
        """The fault P3 removes: `apply_to_product` ran on product WRITE only, so a tenant could set a
        policy, press Save, and watch nothing change -- forever, until each product happened to be
        edited for some other reason."""
        before = resolve(tenant_config=RETURNS, product=SHIPS)
        after = resolve(tenant_config=KEEPS, product=SHIPS)
        self.assertEqual(before["return_method"], "return_required")
        self.assertEqual(after["return_method"], "no_return_customer_keeps")


class NothingInventsAPromise(unittest.TestCase):
    def test_an_unset_class_resolves_to_nothing(self):
        self.assertEqual(tenant_policies({}), {})
        self.assertEqual(resolve(tenant_config={}, product=SHIPS)["mode"], "unset")

    def test_the_renderer_shows_no_section_for_an_empty_policy(self):
        """`render_refund_policy` already returned "" for an empty policy -- correct by accident while a
        policy always existed. Pinned so it stays correct on purpose (P2)."""
        from stripe_link.runtime.html import render_refund_policy
        section = {"id": "refund-policy", "type": "refund_policy"}
        self.assertEqual(render_refund_policy(section, {}, {"p1": SHIPS}), "")

    def test_a_resolved_policy_does_render(self):
        from stripe_link.runtime.html import render_refund_policy
        product = dict(SHIPS, refund_policy=resolve(tenant_config=RETURNS, product=SHIPS))
        offer = {"offer_id": "o1", "items": [{"product_id": "p1"}]}
        html = render_refund_policy({"id": "refund-policy", "type": "refund_policy"},
                                    offer, {"p1": product})
        self.assertIn("30-day money-back", html)
        self.assertIn("in working condition", html)


class PublishIsWhereItIsComposed(unittest.TestCase):
    SOURCE = None

    @classmethod
    def setUpClass(cls):
        import pathlib
        cls.SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "src" / "stripe_link" / "runtime"
                      / "publishing.py").read_text(encoding="utf-8")

    def test_publish_resolves_against_the_live_default(self):
        self.assertIn("refund_policy_module.resolve(tenant_config=tenant_config, product=product)",
                      self.SOURCE)

    def test_an_unset_class_has_its_policy_removed_from_the_render(self):
        self.assertIn('if resolved.get("mode") == "unset":', self.SOURCE)
        self.assertIn('product.pop("refund_policy", None)', self.SOURCE)

    def test_an_unreadable_config_leaves_the_stored_policy_alone(self):
        """It must not be mistaken for "the tenant set nothing" -- those say opposite things, and the
        second silently deletes a live promise."""
        block = self.SOURCE.split("THE REFUND PROMISE, RESOLVED NOW", 1)[1].split("# CAN THIS OFFER", 1)[0]
        self.assertIn("except Exception", block)
        self.assertIn("leaving policies as stored", block)

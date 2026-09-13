"""Product creation becomes a wizard: intent first, then only what that intent needs.

plans/LEAD_GEN_PAGES.md §10. The single form asks every question a product could have and hides most of them,
which is how it reached 1,200 lines -- and it asks them in an order that makes no sense for two of the three
things a product can be. A lead magnet is never sold and has no price; a tip jar is not a catalogue item and
has no SKU, category, condition or shipping.

CREATE goes through the wizard; EDIT keeps the full form. A wizard is the wrong shape for changing something
that already exists -- you want every field at once, not a path through three of them -- and it keeps the
blast radius of this change off the working edit path.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")
PRICE_FORM = (ROOT / "dashboard" / "src" / "utils" / "priceForm.js").read_text(encoding="utf-8")
PRICING = (ROOT / "dashboard" / "src" / "stores" / "pricing.js").read_text(encoding="utf-8")
TEMPLATE = PRODUCTS.split("<script setup>", 1)[0]
SCRIPT = PRODUCTS.split("<script setup>", 1)[1]


def _tip_jar_write_block():
    """The branch that WRITES a customer_chooses price.

    Anchored on `price.presets`, not on the `pricingModel === "customer_chooses"` test: that string appears
    twice in the file and the first is the fee-class lookup, so a naive split silently asserts against the
    wrong function and passes or fails for no reason. Got this wrong once writing these tests.
    """
    start = PRICING.index("price.presets")
    return PRICING[PRICING.rindex("customer_chooses", 0, start):PRICING.index("\n  }", start)]


class ShapeTests(unittest.TestCase):
    def test_create_uses_the_wizard_and_edit_does_not(self):
        self.assertIn('<form v-if="wizardMode"', TEMPLATE)
        self.assertIn('<form v-else class="product-create-body"', TEMPLATE)
        # openCreateModal turns it on, openEditModal turns it off.
        create = SCRIPT.split("function openCreateModal", 1)[1].split("async function openEditModal", 1)[0]
        edit = SCRIPT.split("async function openEditModal", 1)[1].split("function closeCreateModal", 1)[0]
        self.assertIn("wizardMode.value = true", create)
        self.assertIn("wizardMode.value = false", edit)

    def test_closing_resets_it(self):
        # Otherwise the next Edit opens in wizard mode, showing three steps for a product that exists.
        close = SCRIPT.split("function closeCreateModal", 1)[1][:300]
        self.assertIn("wizardMode.value = false", close)

    def test_three_steps_in_the_order_the_plan_gives(self):
        self.assertIn('const WIZARD_STEPS = ["Purpose", "Details", "Image"]', SCRIPT)


class IntentTests(unittest.TestCase):
    def test_the_three_intents_are_offered(self):
        block = SCRIPT.split("const PRODUCT_INTENTS = [", 1)[1].split("];", 1)[0]
        for key in ('"transaction"', '"lead_gen"', '"tip_jar"'):
            self.assertIn(key, block, key)

    def test_tip_jar_is_not_a_third_product_intent(self):
        # It is a transaction product priced customer_chooses. Mapping it that way means Offers, the fee class
        # and the index projection need no new shape (plans/PAY_WHAT_YOU_WANT.md §4), and product_intent's
        # enum -- which composition_key and offer validation both read -- stays two values.
        apply_block = SCRIPT.split("function applyWizardIntent", 1)[1].split("\n}", 1)[0]
        self.assertIn('form.value.product_intent = "transaction"', apply_block)
        self.assertIn('price.pricing_model = "customer_chooses"', apply_block)
        self.assertNotIn('product_intent = "tip_jar"', SCRIPT)

    def test_a_tip_jar_defaults_to_the_customer_covering_fees(self):
        # It is the pitch -- "everywhere else the fees come out of your tip; here your customer can cover
        # them" -- and a default contradicting the sentence that sold it would be strange. Editable.
        apply_block = SCRIPT.split("function applyWizardIntent", 1)[1].split("\n}", 1)[0]
        self.assertIn('price.fee_handling = "net_guaranteed"', apply_block)

    def test_the_intent_is_applied_before_step_two_is_shown(self):
        # Step 2 edits the form directly, so it has to already match the chosen intent.
        nxt = SCRIPT.split("function wizardNext", 1)[1].split("\n}", 1)[0]
        self.assertIn("applyWizardIntent()", nxt)


class GatingTests(unittest.TestCase):
    def test_you_cannot_continue_without_the_answer_that_step_needs(self):
        block = SCRIPT.split("const wizardCanAdvance = computed(", 1)[1].split("});", 1)[0]
        self.assertIn("wizardIntent.value", block)
        self.assertIn("form.value.name.trim()", block)
        # A lead product with no action has nothing for the page to do.
        self.assertIn("form.value.lead_capture.action", block)
        # A tip jar with neither presets nor a custom amount gives the customer nothing to choose -- the
        # same rule the document validator enforces server-side.
        self.assertIn("allow_custom", block)

    def test_the_image_step_is_skippable(self):
        # Last on purpose: it is the one step someone may reasonably skip, and a page with no image is
        # plainer rather than broken.
        panel = TEMPLATE.split('v-if="wizardStep === 3"', 1)[1].split("</section>", 1)[0]
        self.assertIn("optional", panel.lower())


class TipJarFieldTests(unittest.TestCase):
    def test_the_price_form_carries_the_legacy_shape(self):
        for field in ("presets", "max_amount", "allow_custom", "allow_recurring", "recurring_interval"):
            self.assertIn(field, PRICE_FORM, field)

    def test_a_legacy_suggested_amount_is_read_as_the_first_preset(self):
        # It always meant "one amount offered to the buyer", which is what a preset is.
        self.assertIn("[price.suggested_amount].filter(Boolean)", PRICE_FORM)

    def test_a_tip_jar_document_carries_no_fixed_price(self):
        # The whole bug: writing a unit_amount made the runtime sell at it. Deleting it means nothing
        # downstream can mistake a tip jar for a fixed price (plans/PAY_WHAT_YOU_WANT.md §1).
        block = _tip_jar_write_block()
        self.assertIn("delete price.unit_amount", block)
        self.assertIn("delete price.compare_at_unit_amount", block)

    def test_presets_are_stored_sorted_and_deduplicated(self):
        # The document validator refuses duplicates; sorting is so the buttons read left to right.
        block = _tip_jar_write_block()
        self.assertIn("new Set(presets)", block)
        self.assertIn("sort(", block)

    def test_the_pitch_wording_is_the_narrow_one(self):
        # DECIDED: the broad claim ("other platforms deduct fees and we don't") is falsifiable against Ko-fi.
        self.assertIn("Everywhere else, the fees come out of your tip", TEMPLATE)
        self.assertNotIn("unlike other platforms", TEMPLATE.lower())


if __name__ == "__main__":
    unittest.main()

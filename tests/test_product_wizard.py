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
TIPS_CONFIG = (ROOT / "dashboard" / "src" / "config" / "tips.js").read_text(encoding="utf-8")
# The tip-amount field is SHARED: the wizard sets the amounts at creation, the price editor changes them
# afterwards. Two copies would have drifted the moment one grew a rule the other did not.
TIP_FIELD = (ROOT / "dashboard" / "src" / "components" / "shared" / "TipAmountsField.vue").read_text(encoding="utf-8")
PRICING_CARD = (ROOT / "dashboard" / "src" / "components" / "shared" / "PricingCard.vue").read_text(encoding="utf-8")
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

    def test_the_name_placeholder_does_not_advertise_a_competitor(self):
        # "e.g. Buy me a coffee" is Ko-fi's neighbour by name (author, 2026-09-13: "This is cute, but it's a
        # competitor"). The example is the tenant's first impression of what a tip jar is for.
        self.assertNotIn("Buy me a coffee", PRODUCTS)

    def test_the_pitch_wording_is_the_narrow_one(self):
        # DECIDED: the broad claim ("other platforms deduct fees and we don't") is falsifiable against Ko-fi.
        self.assertIn("Everywhere else, the fees come out of your tip", TEMPLATE)
        self.assertNotIn("unlike other platforms", TEMPLATE.lower())


class CategoryTests(unittest.TestCase):
    """The blocking bug: "Choose a product category." on a wizard that has no category field.

    validateProductForm demanded one for every product, but the wizard asks only what the chosen intent
    needs -- and none of its three paths shows a category. So "Create product" failed on the last step with
    an error pointing at a field that was not on the screen, for all three intents.
    """

    def test_the_wizard_is_not_asked_for_a_field_it_never_shows(self):
        self.assertIn('if (!wizardMode.value && !form.value.product_category)', SCRIPT)
        # The full form still asks, and still requires it.
        self.assertIn('Product Category <span class="required">*</span>', TEMPLATE)

    def test_a_tip_jar_files_itself(self):
        # Author, 2026-09-13: "Auto-set all tips as 'Digital Product' and 'Tip' as the product category."
        apply_block = SCRIPT.split("function applyWizardIntent", 1)[1].split("\n}", 1)[0]
        self.assertIn('form.value.product_type = "digital"', apply_block)
        self.assertIn("form.value.product_category = TIP_CATEGORY", apply_block)
        self.assertIn('const TIP_CATEGORY = "tip"', SCRIPT)

    def test_the_type_watcher_cannot_undo_it(self):
        # Changing product_type clears product_category and the SKU. The tip branch sets BOTH, so without
        # the hydrating guard the watcher wipes the category the line above just wrote -- which is how a
        # field the wizard never shows ended up empty and blocking.
        apply_block = SCRIPT.split("function applyWizardIntent", 1)[1].split("\n}", 1)[0]
        self.assertIn("hydratingForm.value = true", apply_block)
        self.assertIn("nextTick(() => { hydratingForm.value = false; })", apply_block)
        watcher = SCRIPT.split("watch(() => form.value.product_type", 1)[1].split("});", 1)[0]
        self.assertIn("if (hydratingForm.value) return;", watcher)


class TipRulesTests(unittest.TestCase):
    """The amount range and the preset cap are the PLATFORM's, and both readers take them from one file.

    Author, 2026-09-13: "System set range: $1 - $500. Don't allow tenants to change it", and "4 max IF
    checkbox is checked, 5 max if unchecked".
    """

    def test_both_sides_read_the_same_rules_file(self):
        # The recurring bug in this codebase is two things that must agree with nothing forcing them to. A
        # form capping at five while the server accepts eight is that bug with money in it.
        self.assertIn("src/stripe_link/tip_rules.json", TIPS_CONFIG)
        tips_py = (ROOT / "src" / "stripe_link" / "domain" / "tips.py").read_text(encoding="utf-8")
        self.assertIn('"tip_rules.json"', tips_py)

    def test_the_form_no_longer_offers_to_change_the_range(self):
        self.assertNotIn('v-model.number="price.min_amount"', TIP_FIELD)
        self.assertNotIn('v-model.number="price.max_amount"', TIP_FIELD)
        self.assertNotIn('v-model.number="price.min_amount"', PRICING_CARD)
        # It says the range instead, from the rules file rather than from a number typed into the sentence.
        self.assertIn("TIP_RULES.min_amount", TIP_FIELD)
        self.assertIn("TIP_RULES.max_amount", TIP_FIELD)

    def test_the_document_carries_the_platform_range_not_the_form(self):
        block = _tip_jar_write_block()
        self.assertIn("price.min_amount = TIP_RULES.min_amount", block)
        self.assertIn("price.max_amount = TIP_RULES.max_amount", block)
        self.assertNotIn("cents(priceForm.min_amount)", block)

    def test_the_preset_cap_follows_the_custom_amount_checkbox(self):
        self.assertIn("const presetCap = computed(() => maxTipPresets(", TIP_FIELD)
        self.assertIn("price.presets.length < presetCap", TIP_FIELD)
        # And turning the checkbox on with a full row gives one place back, rather than saving a row the
        # server then refuses.
        watcher = TIP_FIELD.split("watch(() => props.price.allow_custom", 1)[1].split("});", 1)[0]
        self.assertIn("slice(0, presetCap.value)", watcher)

    def test_a_bad_amount_says_why_rather_than_failing_on_save(self):
        block = SCRIPT.split("function validateTipAmounts", 1)[1].split("\n}", 1)[0]
        self.assertIn("TIP_MIN", block)
        self.assertIn("TIP_MAX", block)
        self.assertIn("maxTipPresets(", block)


class RecurringTipTests(unittest.TestCase):
    def test_the_wizard_offers_a_recurring_donation(self):
        # Author, 2026-09-13: "Missing option: Recurring donations (daily, weekly, monthly, yearly or
        # whatever Stripe supports)." The document model already carried allow_recurring; only the field
        # that sets it was missing.
        self.assertIn('v-model="price.allow_recurring"', TIP_FIELD)
        self.assertIn('v-model="price.recurring_interval"', TIP_FIELD)
        self.assertIn("<TipAmountsField", TEMPLATE)

    def test_the_intervals_come_from_the_rules_file(self):
        self.assertIn("TIP_INTERVALS", TIP_FIELD)
        for interval in ('"day"', '"week"', '"month"', '"year"'):
            self.assertIn(interval, TIPS_CONFIG, interval)

    def test_the_document_keeps_the_chosen_interval(self):
        # It used to coerce anything that was not "year" to "month", which silently turned a weekly
        # donation into a monthly one.
        block = _tip_jar_write_block()
        self.assertIn("TIP_RULES.intervals.includes(priceForm.recurring_interval)", block)


class WizardImageStepTests(unittest.TestCase):
    def test_the_uploaded_image_is_shown_not_counted(self):
        # It said "1 image(s) added." and nothing else -- the tenant could not see what they had uploaded.
        panel = TEMPLATE.split('v-if="wizardStep === 3"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="product-image-previews"', panel)
        self.assertIn("<img", panel)
        self.assertIn('@click.prevent="croppingUrl = url"', panel)
        self.assertNotIn("image(s) added", panel)

    def test_there_is_one_cropper_for_both_bodies(self):
        # It used to live inside the full form's <form>. A Crop button in the wizard's <form> would set
        # croppingUrl and open nothing, because the element holding it was not rendered.
        self.assertEqual(TEMPLATE.count("<ImageCropper"), 1)
        wizard_form = TEMPLATE.split('<form v-if="wizardMode"', 1)[1].split("</form>", 1)[0]
        full_form = TEMPLATE.split('<form v-else class="product-create-body"', 1)[1].split("</form>", 1)[0]
        self.assertNotIn("<ImageCropper", wizard_form)
        self.assertNotIn("<ImageCropper", full_form)



class KeyedVersusChargedTests(unittest.TestCase):
    """What a preset MEANS, settled by showing both numbers (author, 2026-09-13).

    The first cut stored presets as charged amounts, which quietly made "the customer covers the fees, you
    keep the full amount" false of every button. The fix is the split an ordinary price already has -- the
    tenant keys what they keep, the document also stores what the buyer pays -- plus the preview that makes
    the difference visible while the tenant is choosing the fee mode. Legacy stored the same pair per preset
    price (`unit_amount` + `_gross_amount`).
    """

    def test_each_amount_shows_what_the_buyer_pays_and_what_the_tenant_keeps(self):
        self.assertIn("Customer pays", TIP_FIELD)
        self.assertIn("you keep", TIP_FIELD)
        self.assertIn("amountPreviewFor", TIP_FIELD)
        # And it says which of the two numbers the tenant is typing.
        self.assertIn("You enter what you want to keep", TIP_FIELD)

    def test_the_preview_reuses_the_apps_own_fee_maths(self):
        # Not a third copy of the gross-up: the same helpers the single-price preview uses.
        preview = PRICE_FORM.split("export function amountPreviewFor", 1)[1].split("\n}", 1)[0]
        self.assertIn("grossedCustomerAmount(", preview)
        self.assertIn("feeBreakdown(", preview)

    def test_the_document_stores_a_charge_for_every_preset(self):
        block = _tip_jar_write_block()
        self.assertIn("price.preset_charges = await Promise.all(", block)
        # Priced by the SERVER's calculation, like every other amount -- the renderer has no billing config.
        self.assertIn("calculatePriceWithFallback(", block)

    def test_the_fee_mode_is_asked_before_the_amounts(self):
        # Every amount restates itself when the mode changes, so asking it afterwards made the tenant type
        # three numbers and only then discover what they meant.
        panel = TEMPLATE.split('wizardIntent === \'lead_gen\'', 1)[1]
        self.assertLess(panel.index("Who pays the fees"), panel.index("<TipAmountsField"))

    def test_the_price_editor_can_change_the_amounts_too(self):
        # They used to be settable only at creation: the editor showed "Minimum amount" and the deprecated
        # "Suggested amount", and no way to touch the buttons the page actually renders.
        self.assertIn("<TipAmountsField", PRICING_CARD)
        # Checked on the INPUT, not the words: the comment explaining what replaced them says their names.
        self.assertNotIn('v-model.number="price.suggested_amount"', PRICING_CARD)
        # A tip jar has no sales price -- that field is what used to decide what it sold for.
        self.assertIn("price.pricing_model !== 'customer_chooses'", PRICING_CARD)


if __name__ == "__main__":
    unittest.main()

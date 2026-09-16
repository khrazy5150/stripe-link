"""Product creation becomes a wizard: intent first, then only what that intent needs.

plans/LEAD_GEN_PAGES.md §10. The single form asks every question a product could have and hides most of them,
which is how it reached 1,200 lines -- and it asks them in an order that makes no sense for two of the three
things a product can be. A lead magnet is never sold and has no price; a tip jar is not a catalogue item and
has no SKU, category, condition or shipping.

CREATE goes through the wizard; EDIT keeps the full form. A wizard is the wrong shape for changing something
that already exists -- you want every field at once, not a path through three of them -- and it keeps the
blast radius of this change off the working edit path.
"""
import json
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

    def test_the_flow_depends_on_the_intent(self):
        """Author, 2026-09-15: "Sell something" is five steps; the other two are still three.

        The intent decides which questions are REAL, so it has to decide how many there are: selling
        something has a price list, identifiers and a package, and a tip jar has none of those. One shared
        five-step rail would show a creator two screens that never apply to them.
        """
        flows = SCRIPT.split("const WIZARD_FLOWS = {", 1)[1].split("};", 1)[0]
        self.assertIn('transaction: ["purpose", "details", "pricing", "identifiers", "image"]', flows)
        self.assertIn('lead_gen: ["purpose", "details", "image"]', flows)
        self.assertIn('tip_jar: ["purpose", "details", "image"]', flows)

    def test_panels_are_addressed_by_key_not_by_number(self):
        # A panel gated on `wizardStep === 3` lands on a different question the moment a flow gains or loses
        # a step -- which is exactly what happened to this wizard.
        self.assertIn("const wizardStepKey = computed(", SCRIPT)
        self.assertNotIn('v-if="wizardStep === 2"', TEMPLATE)
        self.assertNotIn('v-if="wizardStep === 3"', TEMPLATE)
        for key in ("purpose", "details", "pricing", "identifiers", "image"):
            self.assertIn(f"wizardStepKey === '{key}'", TEMPLATE, key)

    def test_the_last_step_saves_whatever_number_it_is(self):
        # The submit handler used to hardcode step 3. On the five-step flow that would have saved the product
        # from the Pricing screen and never shown the last two.
        self.assertIn("const onLastWizardStep = computed(() => wizardStep.value >= wizardFlow.value.length)", SCRIPT)
        submit = SCRIPT.split("function onWizardSubmit", 1)[1].split("\n}", 1)[0]
        self.assertIn("onLastWizardStep.value", submit)
        self.assertIn("saveProduct()", submit)


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
        panel = TEMPLATE.split("wizardStepKey === 'image'", 1)[1].split("</section>", 1)[0]
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

    def test_a_category_is_required_wherever_it_is_asked_for(self):
        """Required on the flows that show the field, and nowhere else.

        It used to be exempt for the whole wizard, because the wizard showed no category field at all.
        Now the "Sell something" Details step asks for one, so it is required there -- while a tip jar (which
        files itself under "tip") and a lead magnet (never sold) are still not asked and still not blocked.
        """
        self.assertIn('const categoryAsked = !wizardMode.value || wizardIntent.value === "transaction"', SCRIPT)
        self.assertIn('if (categoryAsked && !form.value.product_category)', SCRIPT)
        # And the step will not advance without it, so it is caught on the screen that asks rather than at save.
        advance = SCRIPT.split("const wizardCanAdvance = computed(", 1)[1].split("\n});", 1)[0]
        self.assertIn('wizardIntent.value === "transaction" && !form.value.product_category', advance)

    def test_the_category_field_is_the_same_one_in_both_bodies(self):
        # Two copies of an autocomplete over a SHARED taxonomy is how the two quietly stop agreeing about
        # what a category is.
        self.assertEqual(TEMPLATE.count("<ProductCategoryField"), 2)
        self.assertNotIn("categoryQuery", TEMPLATE)

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

    def test_the_tenant_chooses_whether_one_off_tips_are_taken_too(self):
        # Three states, not two: no recurring / both (repeating pre-selected) / repeating only. Turning
        # one-time OFF is how a tenant says "this is a membership" -- it is not inferred from enabling
        # recurring, because removing the one-off converts the supporter who will never commit to $0.
        self.assertIn('v-model="price.allow_one_time"', TIP_FIELD)
        self.assertIn("Also accept one-time tips", TIP_FIELD)
        # And it says what turning it off costs, where the tenant is deciding.
        self.assertIn("has no way to give", TIP_FIELD)

    def test_the_intervals_come_from_the_rules_file(self):
        self.assertIn("TIP_INTERVALS", TIP_FIELD)
        for interval in ('"day"', '"week"', '"month"', '"year"'):
            self.assertIn(interval, TIPS_CONFIG, interval)

    def test_the_document_keeps_the_chosen_interval(self):
        # It used to coerce anything that was not "year" to "month", which silently turned a weekly
        # donation into a monthly one.
        block = _tip_jar_write_block()
        self.assertIn("TIP_RULES.intervals.includes(priceForm.recurring_interval)", block)


class LeadMagnetTests(unittest.TestCase):
    """A lead magnet files itself, because the wizard never asks it to (author, 2026-09-15).

    `product_category` is required of EVERY product server-side, and the lead flow shows no category field —
    there is nothing to categorise and nothing is sold. So the wizard produced a document the API rejected
    with "Product product_category must be a non-empty string": an error naming a field that was never on the
    screen. Exactly the shape that blocked every tip jar in September.
    """

    def _apply(self):
        return SCRIPT.split("function applyWizardIntent", 1)[1].split("\n}", 1)[0]

    def test_a_lead_magnet_files_itself(self):
        lead = self._apply().split('if (wizardIntent.value === "lead_gen")', 1)[1].split("} else if", 1)[0]
        self.assertIn('form.value.product_type = "digital"', lead)
        self.assertIn("form.value.product_category = LEAD_CATEGORY", lead)

    def test_it_is_filed_under_a_curated_public_safe_category(self):
        """"other", not a "lead_gen" key of its own.

        product_category is PUBLIC — it becomes schema.org `category`, a breadcrumb label, and the key a
        Site's category rail groups by. "Other" is meaningless there but harmless; "Lead Gen" would put
        internal jargon on a buyer-facing label. It is also already curated, so unlike "tip" it needs no
        exclusion from the suggestion list.
        """
        self.assertIn('const LEAD_CATEGORY = "other"', SCRIPT)
        from stripe_link.domain.categories import CURATED_CATEGORIES, SYSTEM_CATEGORIES
        self.assertIn("other", CURATED_CATEGORIES)
        self.assertIn("digital", CURATED_CATEGORIES["other"]["types"])
        self.assertNotIn("other", SYSTEM_CATEGORIES)

    def test_the_type_watcher_cannot_undo_it(self):
        # Changing product_type clears product_category. The lead branch sets BOTH, so without the guard the
        # watcher wipes the category the line above just wrote — the same trap the tip branch hit.
        lead = self._apply().split('if (wizardIntent.value === "lead_gen")', 1)[1].split("} else if", 1)[0]
        self.assertIn("hydratingForm.value = true", lead)

    def test_switching_back_to_selling_does_not_inherit_a_filed_category(self):
        # Its field IS shown on that flow, so inheriting "Tip" from an abandoned pass would pre-fill a
        # category the picker no longer offers, on a product that is actually for sale.
        transaction = self._apply().rsplit("} else {", 1)[1]
        self.assertIn("[TIP_CATEGORY, LEAD_CATEGORY].includes(form.value.product_category)", transaction)
        self.assertIn('form.value.product_category = ""', transaction)

    def test_the_action_field_is_labelled_like_every_other_field(self):
        # The bare button read as an instruction ("Action: Capture email") rather than as the value of
        # something called Lead Capture Action.
        panel = TEMPLATE.split("wizardStepKey === 'details'", 1)[1].split("\n          </section>", 1)[0]
        self.assertIn("Lead Capture Action", panel)
        self.assertNotIn("`Action: ${form.lead_capture.label}`", TEMPLATE)


class PricingModelTests(unittest.TestCase):
    """"Customer chooses" is not a pricing model a tenant picks (author, 2026-09-15).

    It is what the "Receive tips" purpose produces. Offering the same outcome as a radio on a product being
    SOLD gave two routes to one thing — and the radio route skipped the question the tip wizard asks first
    (who pays the fees), which is the question that decides what every amount below it means.
    """

    CARD = (ROOT / "dashboard" / "src" / "components" / "shared" / "PricingCard.vue").read_text(encoding="utf-8")

    def test_the_radio_offers_only_the_two_a_seller_picks_between(self):
        offered = self.CARD.split("pricingModels: {", 1)[1].split("},", 1)[0]
        self.assertIn('["one_time", "One-time"]', offered)
        self.assertIn('["recurring", "Recurring"]', offered)
        self.assertNotIn("customer_chooses", offered)

    def test_an_existing_tip_jar_still_says_what_it_is(self):
        # Removing the radio must not leave a tip product with a blank pricing model, or with no way to see
        # why its amounts behave differently from every other price.
        self.assertIn('v-else-if="isTipPrice(price)"', self.CARD)
        self.assertIn("Supporters choose the amount", self.CARD)

    def test_a_tip_jars_amounts_are_still_editable(self):
        # The whole card already branches on the model; only the radio was removed. If this regressed, a
        # tenant could no longer change the presets on a jar they already have.
        self.assertIn("<TipAmountsField v-if=\"price.pricing_model === 'customer_chooses'\"", self.CARD)

    def test_the_value_itself_is_untouched(self):
        # The model is the STORAGE a tip jar runs on -- checkout, the composer, the fee class and the
        # renderer all key off it. This change is about the picker, not the data.
        tips = (ROOT / "src" / "stripe_link" / "domain" / "tips.py").read_text(encoding="utf-8")
        self.assertIn('"customer_chooses"', tips)
        apply_block = SCRIPT.split("function applyWizardIntent", 1)[1].split("\n}", 1)[0]
        self.assertIn('price.pricing_model = "customer_chooses"', apply_block)


class SellSomethingStepsTests(unittest.TestCase):
    """The five-step "Sell something" flow (author, 2026-09-15).

    The old Details step asked for a name, a description, a type and a price, and promised the rest could be
    added "after saving" -- which meant the wizard produced a product the tenant then had to go and finish in
    the very form the wizard existed to replace. Breaking it up is what lets each screen ask one thing.
    """

    def _panel(self, key):
        return TEMPLATE.split(f"wizardStepKey === '{key}'", 1)[1].split("\n          </section>", 1)[0]

    def test_details_asks_what_the_thing_is_and_nothing_about_money(self):
        panel = self._panel("details")
        self.assertIn("form.name", panel)
        self.assertIn("form.description", panel)
        self.assertIn("form.product_type", panel)
        self.assertIn("<ProductCategoryField", panel)
        # Pricing is its own screen now. A price typed beside the product name reads as a detail of the name;
        # it is a decision with a fee mode and a preview attached.
        self.assertNotIn("<PricingCard", panel)
        self.assertNotIn("sales_price", panel)

    def test_only_something_that_ships_is_asked_about_a_box(self):
        panel = self._panel("details")
        self.assertIn("<ProductVariantsField", panel)
        self.assertIn("form.product_type === 'physical'", panel)

    def test_package_dimensions_and_variants_are_the_same_field_in_both_bodies(self):
        self.assertEqual(TEMPLATE.count("<ProductVariantsField"), 2)
        field = (ROOT / "dashboard" / "src" / "components" / "products" / "ProductVariantsField.vue").read_text(encoding="utf-8")
        for label in ("Length (inches)", "Width (inches)", "Height (inches)", "Weight (pounds)"):
            self.assertIn(label, field, label)
        self.assertIn("Item Size", field)
        self.assertIn("Item Color", field)

    def test_pricing_is_the_price_card_the_edit_form_uses(self):
        panel = self._panel("pricing")
        self.assertIn("<PricingCard", panel)
        self.assertIn('v-model:default-index="form.default_price_index"', panel)

    def test_identifiers_carries_the_optional_fields_the_sku_and_the_tags(self):
        panel = self._panel("identifiers")
        self.assertIn("<ProductIdentifiersField", panel)
        self.assertIn("<ProductTagsField", panel)
        # Open here, because this step exists to ask for exactly these fields; collapsed in the edit form,
        # where it is one section among a dozen.
        self.assertIn("sku-open", panel)
        self.assertIn("optional", panel.lower())

    def test_the_sku_flag_stays_with_the_watcher_that_respects_it(self):
        # A SKU follows the product NAME only until the tenant types their own. The component owns the input;
        # the parent owns the auto-SKU watcher, so the "they typed it" flag has to live with the watcher.
        self.assertIn('@sku-edited="skuTouched = true"', TEMPLATE)
        watcher = SCRIPT.split("watch(() => form.value.name,", 1)[1].split("});", 1)[0]
        self.assertIn("skuTouched.value", watcher)


class SharedProductFieldsTests(unittest.TestCase):
    """Every block the wizard and the edit form both show is ONE component.

    The alternative was a second copy of each in the wizard body. Two copies of the field that talks to the
    shared category taxonomy, or that enforces Stripe's 8-image limit, is how the two quietly stop agreeing.
    """

    FIELDS = ("ProductCategoryField", "ProductIdentifiersField", "ProductImagesField",
              "ProductTagsField", "ProductVariantsField")

    def test_each_block_is_rendered_twice_and_defined_once(self):
        for name in self.FIELDS:
            path = ROOT / "dashboard" / "src" / "components" / "products" / f"{name}.vue"
            self.assertTrue(path.exists(), name)
            self.assertEqual(TEMPLATE.count(f"<{name}"), 2, name)
            self.assertIn(f'import {name} from "./products/{name}.vue"', SCRIPT, name)

    def test_uploading_stayed_out_of_the_image_component(self):
        # Presigning, counting the remaining slots and recording dimensions are business logic; the component
        # raises the files and renders the progress it is handed (CLAUDE.md: keep business logic out of Vue
        # components).
        field = (ROOT / "dashboard" / "src" / "components" / "products" / "ProductImagesField.vue").read_text(encoding="utf-8")
        self.assertNotIn("apiRequest", field)
        self.assertNotIn("uploadProductImage", field)
        self.assertIn('emit("files"', field)
        self.assertIn("handleImageFiles", SCRIPT)

    def test_the_variant_shape_has_one_definition(self):
        # Two places build these rows -- the field, and the hydration that widens a legacy string variant --
        # so the factory is shared rather than copied.
        util = (ROOT / "dashboard" / "src" / "utils" / "productVariants.js").read_text(encoding="utf-8")
        self.assertIn("export function defaultSizeVariant", util)
        self.assertIn("export function defaultColorVariant", util)
        self.assertNotIn("function defaultSizeVariant", SCRIPT)
        self.assertIn('from "../utils/productVariants"', SCRIPT)

    def test_normalize_tag_has_one_definition(self):
        # Products.vue carried a byte-identical private copy of the store's until 2026-09-15.
        store = (ROOT / "dashboard" / "src" / "stores" / "products.js").read_text(encoding="utf-8")
        self.assertIn("export function normalizeTag", store)
        self.assertNotIn("function normalizeTag", SCRIPT)


class WizardImageStepTests(unittest.TestCase):
    def test_the_uploaded_image_is_shown_not_counted(self):
        # It said "1 image(s) added." and nothing else -- the tenant could not see what they had uploaded.
        field = (ROOT / "dashboard" / "src" / "components" / "products" / "ProductImagesField.vue").read_text(encoding="utf-8")
        self.assertIn('class="product-image-previews"', field)
        self.assertIn("<img", field)
        self.assertIn("emit('crop', url)", field)
        self.assertNotIn("image(s) added", field)
        # And the wizard's image step renders that field rather than a second copy of it.
        panel = TEMPLATE.split("wizardStepKey === 'image'", 1)[1].split("</section>", 1)[0]
        self.assertIn("<ProductImagesField", panel)

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


class RecommendedAmountsTests(unittest.TestCase):
    """One click, sensible amounts, and the tenant never has to invent a ladder (author, 2026-09-14).

    Frequency-aware because the same number means two different things: $50 is an ordinary one-off tip and a
    steep monthly commitment. The bottoms are the platforms' own defaults -- Ko-fi opens at $3, Buy Me a
    Coffee at $5 -- and the repeating ladder tops out where membership tiers cluster.
    """

    def _rules(self):
        return json.loads((ROOT / "src" / "stripe_link" / "tip_rules.json").read_text(encoding="utf-8"))

    def test_the_button_is_there_and_writes_the_ladder(self):
        self.assertIn("Use recommended amounts", TIP_FIELD)
        self.assertIn("props.price.presets = [...recommended.value]", TIP_FIELD)
        # And the tenant can see what it would write before clicking it.
        self.assertIn("recommendedSummary", TIP_FIELD)

    def test_a_repeating_jar_gets_the_lower_ladder(self):
        usd = self._rules()["recommended"]["usd"]
        self.assertEqual(usd["one_time"], [500, 1000, 2500, 5000, 10000])
        self.assertEqual(usd["recurring"], [300, 500, 1000, 2500, 5000])
        self.assertLess(usd["recurring"][-1], usd["one_time"][-1])
        self.assertIn("allowRecurring ? ladders.recurring : ladders.one_time", TIPS_CONFIG)

    def test_the_ladder_is_keyed_by_currency(self):
        # EUR set by the author 2026-09-14: 2 / 5 / 10 / 25 / 50. A currency with no ladder of its own falls
        # back to USD, which reads oddly at a different magnitude -- the open question the range shares.
        recommended = self._rules()["recommended"]
        self.assertEqual(recommended["eur"]["one_time"], [200, 500, 1000, 2500, 5000])
        self.assertEqual(recommended["eur"]["recurring"], [200, 500, 1000, 2500, 5000])
        self.assertIn('rules.recommended[String(currency || "usd").toLowerCase()] || rules.recommended.usd',
                      TIPS_CONFIG)
        # The field asks for the ladder in the PRICE's currency, not a default.
        self.assertIn("props.price.currency", TIP_FIELD)

    def test_the_button_is_the_primary_one(self):
        # It is the shortcut past the decision most tenants stall on; white undersold it.
        block = TIP_FIELD.split("Use recommended amounts", 1)[0]
        self.assertIn('class="primary-action compact" type="button" @click="useRecommended()"', block)

    def test_enter_your_own_drops_the_top_amount(self):
        # Not a second rule: the ladder is trimmed to the SAME preset cap the row already enforces.
        self.assertIn("ladder.slice(0, maxTipPresets(allowCustom))", TIPS_CONFIG)

    def test_every_recommended_amount_is_inside_the_platform_range(self):
        # A recommended amount the server would refuse is a button that fails on save.
        rules = self._rules()
        for currency, ladders in rules["recommended"].items():
            for frequency, ladder in ladders.items():
                where = f"{currency}/{frequency}"
                for amount in ladder:
                    self.assertGreaterEqual(amount, rules["min_amount"], where)
                    self.assertLessEqual(amount, rules["max_amount"], where)
                self.assertEqual(ladder, sorted(set(ladder)), where)
                self.assertGreaterEqual(len(ladder), rules["max_presets"], where)

    def test_the_wizard_seeds_from_the_same_ladder(self):
        # A hardcoded [5, 10, 25] here would be a second answer to "what should a new tip jar offer?".
        apply_block = SCRIPT.split("function applyWizardIntent", 1)[1].split("\n}", 1)[0]
        self.assertIn("recommendedTipPresets(", apply_block)
        self.assertNotIn("[5, 10, 25]", apply_block)


if __name__ == "__main__":
    unittest.main()

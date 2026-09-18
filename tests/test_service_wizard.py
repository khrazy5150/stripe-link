"""Creating a service without meeting the operations console.

Author, 2026-09-18: the Products wizard offered "Service — opens booking flow" and then ran the
physical-product path, package dimensions and all, because WIZARD_FLOWS is keyed on intent and nothing in
that file branched on product_type. Meanwhile the only door to a Service was a modal asking ~22 questions for
a document whose validator requires three.

The framing that shaped the fix: *"we need to ASSUME that a service tenant has NO IDEA about the physical
products screen and vice-versa"*. So the wizard is the front door on Services itself, and the product wizard
hands off to it rather than pretending to build one.

Edits keep the whole console -- the big form is a good tool for someone who already has a service and knows
what a fulfiller is, and a bad first impression for someone who wants to say "I cut hair, 45 minutes, £40".
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES = (ROOT / "dashboard" / "src" / "components" / "Services.vue").read_text(encoding="utf-8")
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")
APP = (ROOT / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")
SETUP = SERVICES.rsplit("<script setup>", 1)[-1]
TEMPLATE = SERVICES.rsplit("</template>", 1)[0]


class OneFormOneSaveTests(unittest.TestCase):
    """The wizard shows and hides parts of ONE form. There is nothing to drift.

    savePage() in LandingPages.vue was the other approach -- a second form model with a second save -- and it
    quietly stopped being called, taking the Site-attach behaviour with it for weeks. Not repeating that.
    """

    def test_there_is_exactly_one_service_save(self):
        self.assertEqual(SETUP.count("async function saveService("), 1)
        self.assertNotIn("async function saveWizardService", SETUP)

    def test_the_wizard_writes_the_same_form(self):
        # No second model: the steps reveal fields on `form`, which defaultServiceForm() already seeds.
        self.assertEqual(SETUP.count("const form = ref(defaultServiceForm())"), 1)
        self.assertNotIn("wizardForm", SETUP)

    def test_enter_advances_rather_than_saving_a_half_filled_service(self):
        self.assertIn('@submit.prevent="onServiceFormSubmit"', TEMPLATE)
        body = SETUP.split("function onServiceFormSubmit()", 1)[1].split("\n}", 1)[0]
        self.assertIn("nextWizardStep()", body)
        self.assertIn("return;", body)


class StepTests(unittest.TestCase):
    def test_four_steps_in_the_order_a_tenant_thinks_in(self):
        self.assertIn('SERVICE_WIZARD_STEPS = ["details", "pricing", "scheduling", "photo"]', SETUP)

    def test_the_rail_is_the_one_every_other_wizard_uses(self):
        self.assertIn('import WizardSteps from "./shared/WizardSteps.vue"', SERVICES)
        self.assertIn('<WizardSteps v-if="wizardMode"', TEMPLATE)

    def test_each_step_gates_its_own_block(self):
        for key in ("details", "pricing", "scheduling", "photo"):
            self.assertIn(f"showsBlock('{key}')", TEMPLATE, key)

    def test_a_name_and_a_duration_are_still_required(self):
        # The two things validate_service cannot do without, asked at the step that owns them.
        body = SETUP.split("function nextWizardStep()", 1)[1].split("\n}", 1)[0]
        self.assertIn("Give the service a name.", body)
        self.assertIn("duration_minutes", body)


class NoOperationsConsoleWhileCreatingTests(unittest.TestCase):
    """A solo tenant creating their first service should never meet the word "fulfiller" -- they are one."""

    def test_the_advanced_console_is_edit_only(self):
        self.assertIn("const showsAdvanced = computed(() => !wizardMode.value)", SETUP)
        self.assertIn('<section v-if="showsAdvanced" class="offer-form-section">', TEMPLATE)

    def test_compensation_and_check_in_cannot_reach_a_new_service(self):
        self.assertIn('v-if="showsAdvanced && form.allowed_fulfillers.length"', TEMPLATE)

    def test_the_questions_with_working_defaults_are_not_asked(self):
        """location_mode and booking_flow both have defaults that suit a first service.

        Asked at creation they are two more decisions before a haircut exists; in the editor they are there
        for the tenant who knows they need them.
        """
        for field in ("form.location_mode", "form.booking_flow"):
            block = TEMPLATE.split(field, 1)[0]
            self.assertIn('v-if="!wizardMode"', block.rsplit("<label", 1)[-1] + "<label", field)

    def test_fulfillment_mode_is_asked_as_a_question_not_a_schema_field(self):
        self.assertIn("Customers book an appointment for this", TEMPLATE)
        # ...and it still writes the enum the validator expects.
        self.assertIn("form.fulfillment_mode = $event.target.checked ? 'scheduled' : 'no_booking'", TEMPLATE)


class EditingIsUnchangedTests(unittest.TestCase):
    """"Keep the big screen for edits" -- the console is a good tool, just a bad front door."""

    def test_opening_an_existing_service_leaves_the_wizard(self):
        body = SETUP.split("async function openEditModal(row)", 1)[1].split("\n}", 1)[0]
        self.assertIn("wizardMode.value = false", body)

    def test_creating_enters_it(self):
        body = SETUP.split("function openCreateModal()", 1)[1].split("\n}", 1)[0]
        self.assertIn("wizardMode.value = true", body)
        self.assertIn("wizardStep.value = 1", body)

    def test_closing_resets_it(self):
        # Otherwise the next Create opens on step 3 of the last one.
        body = SETUP.split("function closeServiceModal()", 1)[1].split("\n}", 1)[0]
        self.assertIn("wizardMode.value = false", body)
        self.assertIn("wizardStep.value = 1", body)


class ProductWizardHandsOffTests(unittest.TestCase):
    def test_it_no_longer_promises_a_flow_it_does_not_open(self):
        self.assertNotIn("Service — opens booking flow", PRODUCTS)

    def test_it_points_at_where_services_are_actually_made(self):
        self.assertIn('v-if="form.product_type === \'service\'"', PRODUCTS)
        self.assertIn("goCreateService", PRODUCTS)

    def test_the_shell_provides_that_navigation(self):
        self.assertIn('provide("navigateTo"', APP)
        self.assertIn('inject("navigateTo", null)', PRODUCTS)

    def test_it_survives_the_provider_being_absent(self):
        # A template reading an undefined name builds clean and renders nothing; this dashboard has no linter.
        body = PRODUCTS.split("function goCreateService()", 1)[1].split("\n}", 1)[0]
        self.assertIn("if (navigateTo)", body)


class DeclaredWhereReadTests(unittest.TestCase):
    """Every name the template reads must exist in the component that reads it.

    Twice in one day a `store` vs `sitesStore` slip built clean and rendered nothing.
    """

    def test_every_wizard_name_is_declared(self):
        for name in ("wizardMode", "wizardStep", "wizardStepKey", "wizardLabels", "onLastWizardStep",
                     "showsBlock", "showsAdvanced", "nextWizardStep", "previousWizardStep",
                     "onServiceFormSubmit"):
            self.assertIn(name, TEMPLATE, f"{name} unused in template")
            self.assertRegex(SETUP, r"\b(?:const|let|function|async function)\s+" + name + r"\b", name)


if __name__ == "__main__":
    unittest.main()

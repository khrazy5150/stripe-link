"""Creating a service without being handed a console.

Author, 2026-09-18/19. The Products wizard offered "Service — opens booking flow" and ran the
physical-product path, package dimensions and all, because `WIZARD_FLOWS` is keyed on intent and nothing in
that file branched on `product_type`. The only door to a Service was a modal asking ~22 questions for a
document whose validator requires three, beside five stacked panels.

Two instructions shaped the fix, and the first build got both wrong:

  * *"when people think of 'product' they think of product or service — the labor of one's hands is also a
    product"*. So the wizard lives in the PRODUCTS flow, with Services as a second door into the same
    component. A hand-off to another screen was the wrong answer.
  * *"if we simply say: here you go… create your service in this huge screen, our software loses value"*. So
    the wizard COVERS the console rather than hiding it — the panels are embedded, not omitted.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard" / "src"
WIZARD = (DASH / "components" / "services" / "ServiceWizard.vue").read_text(encoding="utf-8")
SERVICES = (DASH / "components" / "Services.vue").read_text(encoding="utf-8")
PRODUCTS = (DASH / "components" / "Products.vue").read_text(encoding="utf-8")
STORE = (DASH / "stores" / "products.js").read_text(encoding="utf-8")
APP = (DASH / "App.vue").read_text(encoding="utf-8")


def _template(src, *, with_comments=True):
    """The markup. `with_comments=False` strips HTML comments first.

    Asserting that a string is ABSENT from a template is otherwise defeated by a comment explaining why it
    is absent -- which is how this file first failed: the note recording that `@uploaded` is not a real
    event contained the words `@uploaded`.
    """
    markup = src.rsplit("</template>", 1)[0]
    return markup if with_comments else re.sub(r"<!--.*?-->", "", markup, flags=re.S)


def _setup(src):
    return src.rsplit("<script setup>", 1)[-1]


class OneWizardTwoDoorsTests(unittest.TestCase):
    def test_both_screens_mount_the_same_component(self):
        # Not two wizards that have to be kept in step -- this codebase's recurring bug.
        for name, src in (("Services.vue", SERVICES), ("Products.vue", PRODUCTS)):
            self.assertIn("ServiceWizard", src, name)
            self.assertIn("<ServiceWizard", _template(src), name)

    def test_the_products_wizard_branches_on_type(self):
        """The branch that never existed, and caused the original bug."""
        body = _setup(PRODUCTS).split("function wizardNext()", 1)[1].split("\n}", 1)[0]
        self.assertIn('wizardStepKey.value === "details"', body)
        self.assertIn('form.value.product_type === "service"', body)

    def test_it_carries_what_was_already_answered(self):
        # Asking for the name twice would be the discontinuity the move exists to remove.
        body = _setup(PRODUCTS).split("function wizardNext()", 1)[1].split("\n}", 1)[0]
        for field in ("name", "description", "product_category"):
            self.assertIn(field, body, field)
        self.assertIn('seed: { type: Object', WIZARD)

    def test_the_service_modal_stacks_ABOVE_the_product_one(self):
        """Reported as "when I click Continue nothing happens".

        The product wizard stays open behind the hand-off so Cancel returns the tenant to where they were --
        and two `position: fixed` backdrops at the same z-index stack in DOM ORDER. Declared before the
        product modal, the service wizard opened underneath it: present, mounted, invisible.
        """
        template = _template(PRODUCTS)
        backdrops = [i for i, line in enumerate(template.splitlines()) if "modal-backdrop" in line]
        service = next(i for i, line in enumerate(template.splitlines()) if 'v-if="serviceWizardOpen"' in line)
        create = next(i for i, line in enumerate(template.splitlines()) if 'v-if="showCreateModal"' in line)
        self.assertGreater(service, create,
                           "the service wizard must be declared after the product wizard or it opens behind it")
        self.assertEqual(max(backdrops), service, "it must be the last backdrop in the template")

    def test_the_hand_off_button_is_gone(self):
        self.assertNotIn("Create a service instead", PRODUCTS)
        self.assertNotIn("Service — opens booking flow", PRODUCTS)


class StepsFollowTheBusinessTests(unittest.TestCase):
    def test_one_list_decides_the_rail_the_labels_and_the_bounds(self):
        """LandingPages.vue is the scar: three calculations each deciding how long a conditional wizard is,
        and a rail that misreported how much was left."""
        for derived in ("stepLabels", "stepKey", "displayStep", "onLastStep"):
            line = [l for l in WIZARD.splitlines() if l.startswith(f"const {derived}")][0]
            self.assertIn("steps.value", line, derived)

    def test_the_booking_answer_collapses_the_wizard(self):
        block = WIZARD.split("const steps = computed(", 1)[1].split("});", 1)[0]
        for conditional in ("duration", "payment", "availability", "exceptions", "calendar"):
            self.assertIn(conditional, block, conditional)
        self.assertIn("booked.value", block)

    def test_tenant_scoped_setup_is_asked_once(self):
        """Availability, exceptions and the calendar belong to the BUSINESS, not to this service.

        A wizard that re-asks your opening hours for every haircut is worse than the console it replaced.
        """
        block = WIZARD.split("const steps = computed(", 1)[1].split("});", 1)[0]
        self.assertIn("availabilityAlreadySet", block)
        self.assertIn("const availabilityAlreadySet", WIZARD)

    def test_a_solo_tenant_never_meets_the_word_fulfiller(self):
        # Step 7 asks who does the work; only "my team" reveals the vocabulary.
        before_staff = _template(WIZARD).split('v-if="hasStaff"', 1)[0]
        self.assertNotIn("Fulfiller", before_staff)
        self.assertNotIn("fulfiller", before_staff.replace("tips_to_fulfiller", ""))


class EmbedsRatherThanRebuildsTests(unittest.TestCase):
    """The five panels already existed, self-contained, each owning its store."""

    PANELS = ("FulfillersPanel", "TenantAvailabilityPanel", "AvailabilityExceptionsPanel", "CalendarPanel")

    def test_the_wizard_mounts_the_real_panels(self):
        for panel in self.PANELS:
            self.assertIn(f"<{panel} embedded />", _template(WIZARD), panel)

    def test_each_panel_accepts_that_contract(self):
        # A prop, not the wizard reaching in with :deep() -- which would break silently when markup moves.
        for panel in self.PANELS:
            src = (DASH / "components" / "services" / f"{panel}.vue").read_text(encoding="utf-8")
            self.assertIn("embedded: { type: Boolean", src, panel)
            self.assertIn('v-if="!embedded"', src, panel)


class HeroUploadTests(unittest.TestCase):
    """The upload did nothing because I invented the component's API instead of reading it.

    ImageUploadField REQUIRES an `uploader` function, emits `update:crop` (never `uploaded`), and the ratio
    key is `asset.service_hero`. Three guesses, three wrong, and the build reported none of them.
    """

    def test_it_is_given_an_uploader(self):
        self.assertIn(':uploader="uploadServiceHero"', _template(WIZARD))
        self.assertIn("async function uploadServiceHero(file)", WIZARD)

    def test_it_listens_for_the_event_that_is_actually_emitted(self):
        emitted = (DASH / "components" / "shared" / "ImageUploadField.vue").read_text(encoding="utf-8")
        self.assertIn("update:crop", emitted)
        self.assertNotIn("@uploaded", _template(WIZARD, with_comments=False))

    def test_it_uses_a_ratio_key_that_exists(self):
        import json

        ratios = json.loads((ROOT / "src" / "stripe_link" / "image_ratios.json").read_text(encoding="utf-8"))
        self.assertIn("service_hero", ratios["asset"])
        self.assertIn("imageRatios.asset.service_hero", _template(WIZARD))

    def test_it_uploads_the_same_way_the_editor_does(self):
        # One behaviour, two surfaces -- not a second uploader that drifts from the first.
        body = WIZARD.split("async function uploadServiceHero(file)", 1)[1].split("\n}", 1)[0]
        editor = SERVICES.split("async function uploadServiceHero(file)", 1)[1].split("\n}", 1)[0]
        self.assertIn('basePrefix: "services"', body)
        self.assertIn('basePrefix: "services"', editor)


class RailTests(unittest.TestCase):
    def test_the_rail_is_inset_like_the_body_beneath_it(self):
        """It sits OUTSIDE .coupon-form, which carries the 2.4rem everything else is inset by, so without
        its own rule the steps ran flush to the modal edge."""
        css = (DASH / "styles.css").read_text(encoding="utf-8")
        rule = next(chunk for chunk in css.split("}")
                    if ".service-wizard .wizard-steps" in chunk.split("{")[0])
        self.assertRegex(rule.split("{", 1)[1], r"padding:[^;]*2\.4rem")


class ServicesInTheProductListTests(unittest.TestCase):
    def test_the_list_shows_them(self):
        getter = STORE.split("filteredProducts(state)", 1)[1].split("},", 1)[0]
        self.assertIn("state.services", getter)
        self.assertIn("serviceListRow", getter)

    def test_the_type_filter_finally_matches_something(self):
        """Products.vue has offered a "Service" option all along, filtering on product_type over an array
        that never contains one."""
        self.assertIn('<option value="service">Service</option>', PRODUCTS)
        self.assertIn('product_type: "service"', STORE)

    def test_a_service_row_is_visibly_a_service(self):
        self.assertIn("product.__service ? 'Service'", _template(PRODUCTS))

    def test_it_does_not_offer_actions_it_cannot_perform(self):
        """A row that looks like the others and silently ignores Archive is worse than one plainly different."""
        actions = _template(PRODUCTS).split("<template #actions>", 1)[1].split("</template>", 1)[0]
        self.assertIn('v-if="product.__service"', actions)
        self.assertIn("Edit in Services", actions)

    def test_both_documents_are_loaded(self):
        # The list shows both, so the screen must fetch both or silently omit services.
        body = _setup(PRODUCTS).split("function loadAll(", 1)[1].split("\n}", 1)[0]
        self.assertIn("store.", body)
        self.assertIn("servicesStore.load()", body)


class DeepLinkTests(unittest.TestCase):
    def test_edit_opens_the_service_in_its_own_console(self):
        self.assertIn('navigateTo("services", { edit: row.service_id })', PRODUCTS)

    def test_the_intent_is_read_once(self):
        """Otherwise returning to Services later reopens whatever was asked for the first time."""
        self.assertIn('provide("takeViewIntent"', APP)
        block = APP.split('provide("takeViewIntent"', 1)[1].split(");", 1)[0]
        self.assertIn("viewIntent.value = null", block)

    def test_services_acts_on_it_on_arrival(self):
        body = _setup(SERVICES).split("onMounted(", 1)[1].split("});", 1)[0]
        self.assertIn("takeViewIntent", body)
        self.assertIn("openEditModal(row)", body)


class NoSecondSaveTests(unittest.TestCase):
    def test_the_wizard_saves_through_the_store_like_everything_else(self):
        self.assertIn("store.saveService(form.value, null)", WIZARD)
        self.assertEqual(WIZARD.count("async function save("), 1)

    def test_enter_advances_rather_than_creating_a_half_built_service(self):
        body = WIZARD.split("function onSubmit()", 1)[1].split("\n}", 1)[0]
        self.assertIn("next()", body)
        self.assertIn("return;", body)

    def test_nothing_uncalled_was_left_behind(self):
        """savePage() in LandingPages.vue was dead code that still LOOKED like the feature, and the Site
        attach it owned silently stopped happening. Both screens were edited heavily here."""
        for name, src in (("Services.vue", SERVICES), ("Products.vue", PRODUCTS)):
            for fn in re.findall(r"\n(?:async )?function ([a-zA-Z_$][\w$]*)\(", src):
                uses = len(re.findall(r"\b" + re.escape(fn) + r"\b", src))
                self.assertGreater(uses, 1, f"{name}: {fn}() is defined and never called")


class DeclaredWhereReadTests(unittest.TestCase):
    """A Vue template reading an undefined name builds clean and renders nothing, and a missing NAMED EXPORT
    from a local module also builds clean -- both were hit while writing this. The build is not a safety net.
    """

    def test_every_named_import_resolves_to_a_real_export(self):
        missing = []
        for f in DASH.rglob("*.vue"):
            src = f.read_text(encoding="utf-8")
            for m in re.finditer(r'import \{([^}]+)\} from "([^"]+)"', src):
                mod = m.group(2)
                if not mod.startswith("."):
                    continue
                target = (f.parent / mod).resolve()
                target = next((c for c in (target, pathlib.Path(f"{target}.js"), pathlib.Path(f"{target}.vue"))
                               if c.is_file()), None)
                if not target:
                    continue
                mod_src = target.read_text(encoding="utf-8")
                for name in [n.split(" as ")[0].strip() for n in m.group(1).replace("\n", " ").split(",") if n.strip()]:
                    exported = re.search(r"export\s+(?:const|let|function|async function|class)\s+"
                                         + re.escape(name) + r"\b", mod_src)
                    listed = re.search(r"export\s*\{[^}]*\b" + re.escape(name) + r"\b", mod_src)
                    if not exported and not listed:
                        missing.append(f"{f.relative_to(DASH)} imports '{name}' from {mod}")
        self.assertEqual(missing, [])

    def test_every_store_and_component_used_is_actually_imported(self):
        """The gap that shipped a blank Products page.

        The previous test checked that imports RESOLVE. It could not catch a name that is used and never
        imported at all -- `useServicesStore()` was called in Products.vue with no import line, which builds
        clean and throws `ReferenceError` the moment the component mounts.

        Scoped to the two shapes that are always either imported or broken: pinia stores (`useXStore()`) and
        PascalCase components in the template. Both fail at runtime, never at build time.
        """
        problems = []
        for f in sorted(DASH.rglob("*.vue")):
            src = f.read_text(encoding="utf-8")
            template, setup = _template(src), _setup(src)
            used = set(re.findall(r"\b(use[A-Z][A-Za-z0-9_]*)\s*\(", setup))
            used |= {n for n in re.findall(r"<([A-Z][A-Za-z0-9_]*)[\s/>]", template)}
            for name in sorted(used):
                declared = re.search(r"\b(?:const|let|function|async function|class)\s+" + name + r"\b", setup)
                imported = re.search(r"import\s+(?:\{[^}]*\b" + name + r"\b[^}]*\}|" + name + r")\s+from", src)
                if not declared and not imported:
                    problems.append(f"{f.relative_to(DASH)}: '{name}' used but never imported")
        self.assertEqual(problems, [])

    def test_the_wizards_own_names_exist(self):
        template, setup = _template(WIZARD), _setup(WIZARD)
        for name in ("stepKey", "stepLabels", "displayStep", "onLastStep", "skippable", "goToStep",
                     "reviewRows", "hasStaff", "next", "back", "onSubmit", "form", "error"):
            self.assertIn(name, template, f"{name} unused in template")
            self.assertRegex(setup, r"\b(?:const|let|function|async function)\s+" + name + r"\b", name)
        # `booked` is deliberately script-only: it decides which STEPS exist, and is never read by the
        # markup. Asserting it appeared in the template was the test being wrong about the component.
        self.assertRegex(setup, r"\bconst booked\b")


if __name__ == "__main__":
    unittest.main()

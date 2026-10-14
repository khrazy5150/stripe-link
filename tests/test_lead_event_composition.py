"""The webinar page shape (plans/WEBINAR.md §5).

A registration page is a lead page of a particular shape, which is how this codebase already expresses
`lead_capture`, `lead_bridge`, `lead_social` and `lead_call`. `lead_event` is the fifth, selected by a new
lead-capture action rather than by a new page type.
"""
import json
import pathlib
import unittest

from stripe_link.domain.composition import LEAD_COMPOSITIONS, composition_key
from stripe_link.domain.documents import LEAD_CAPTURE_ACTIONS

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
SHAPE = RULES["offer_types"]["lead_event"]


class ItIsSelectedByTheAction(unittest.TestCase):
    def test_register_event_is_a_lead_capture_action(self):
        self.assertIn("register_event", LEAD_CAPTURE_ACTIONS)

    def test_it_maps_to_the_event_composition(self):
        self.assertEqual(LEAD_COMPOSITIONS["register_event"], "lead_event")

    def test_an_offer_with_that_action_composes_as_one(self):
        offer = {"product_intent": "lead_gen", "lead_capture_action": "register_event"}
        self.assertEqual(composition_key(offer), "lead_event")

    def test_the_other_lead_actions_are_unchanged(self):
        for action, expected in (("capture_email", "lead_capture"), ("call_number", "lead_call"),
                                 ("external_url", "lead_bridge"), ("social_redirect", "lead_social")):
            with self.subTest(action=action):
                self.assertEqual(composition_key(
                    {"product_intent": "lead_gen", "lead_capture_action": action}), expected)

    def test_every_action_still_has_a_glyph(self):
        """A picker falls back to a bare initial without one -- the bug the shared icon factory fixed."""
        icons = (ROOT / "dashboard" / "src" / "utils" / "leadActionIcon.js").read_text(encoding="utf-8")
        self.assertIn("register_event:", icons)


class TheShape(unittest.TestCase):
    def test_the_date_is_a_section_not_merely_allowed(self):
        """A page announcing a live session without saying when is not a draft, it is wrong."""
        self.assertIn("event_date", SHAPE["sections"])

    def test_it_keeps_the_form(self):
        """checkout_cta IS the registration form; removing it removes the thing the page exists for."""
        self.assertIn("checkout_cta", SHAPE["sections"])

    def test_it_sells_nothing(self):
        for excluded in ("offer_price_selector", "price_highlight", "product_details", "refund_policy"):
            with self.subTest(section=excluded):
                self.assertIn(excluded, SHAPE["excludes"])

    def test_trust_badges_survive_here_unlike_lead_capture(self):
        """A free session is still asking for an email address, and "no spam" is the objection."""
        self.assertIn("trust_badges", RULES["offer_types"]["lead_capture"]["excludes"])
        self.assertNotIn("trust_badges", SHAPE["excludes"])

    def test_the_ask_is_a_seat_not_a_call(self):
        self.assertEqual(SHAPE["allowed_ctas"], ["email_capture"])


class TheProductPickerOffersIt(unittest.TestCase):
    """The tile in "Choose a lead capture action" — without it the action exists and no tenant can reach it."""

    PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")

    def test_the_action_is_in_the_picker(self):
        self.assertIn('action: "register_event"', self.PRODUCTS)

    def test_it_asks_which_event(self):
        self.assertIn("form.lead_capture.event_id", self.PRODUCTS)

    def test_the_CREATE_WIZARD_asks_too_not_just_the_edit_form(self):
        """The bug this exists to prevent, reported 2026-10-14: the selector was added to the edit form
        only, so creating a product walked to the last step and failed with "lead_capture.event_id must be
        a non-empty string" -- a field the create flow never showed."""
        wizard = self.PRODUCTS[self.PRODUCTS.index("wizardStepKey === 'details'"):]
        wizard = wizard[:wizard.index("wizardStepKey === 'pricing'")]
        self.assertIn("form.lead_capture.event_id", wizard)

    def test_the_wizard_blocks_on_the_step_that_asks(self):
        """Required where it is asked, not discovered two steps later as a save error."""
        guard = self.PRODUCTS[self.PRODUCTS.index("const wizardCanAdvance"):][:1200]
        self.assertIn('action === "register_event"', guard)
        self.assertIn("Boolean(form.value.lead_capture.event_id)", guard)

    def test_it_says_what_to_do_when_there_are_none(self):
        """Otherwise the dropdown is empty and the tenant has no idea why."""
        self.assertIn("create one on the Events screen", self.PRODUCTS)

    def test_re_confirming_the_action_keeps_the_chosen_event(self):
        """Same rule as `target`: re-opening the picker and confirming must not silently clear it."""
        self.assertIn("sameAction ? form.value.lead_capture.event_id", self.PRODUCTS)

    def test_switching_action_drops_it(self):
        start = self.PRODUCTS.index("function applyLeadAction()")
        applied = self.PRODUCTS[start:self.PRODUCTS.index("\n}", start)]
        self.assertIn('event_id: eventId', applied)
        self.assertIn('const eventId = sameAction ?', applied)


class TheStoreBuildsTheWholeShape(unittest.TestCase):
    """`leadCaptureShape` rebuilds the payload from an allow-list PER ACTION, so an action matching no
    branch silently loses everything that branch would have added. `register_event` matched none: it lost
    the event AND the fields, and borrowed another action's form copy (reported 2026-10-14, after the
    selector was visibly filled in)."""

    STORE = (ROOT / "dashboard" / "src" / "stores" / "products.js").read_text(encoding="utf-8")

    def test_the_event_is_carried_through(self):
        self.assertIn("base.event_id = action.event_id", self.STORE)

    def test_a_registration_declares_its_fields(self):
        """`validate_product_lead_capture` requires non-empty fields for a capture action, and a
        registration is one -- this was the bug waiting behind the first."""
        branch = self.STORE[self.STORE.index('if (base.action === "register_event")'):][:700]
        self.assertIn('name: "email"', branch)
        self.assertIn("base.fields", branch)

    def test_it_has_its_own_form_copy(self):
        """Falling back to another action's wording would ask a webinar registrant where to send a guide."""
        self.assertIn("register_event: { title:", self.STORE)

    def test_every_lead_action_has_form_copy(self):
        """Derived, so the next action added cannot silently borrow capture_email's words."""
        import re
        from stripe_link.domain.documents import LEAD_CAPTURE_ACTIONS
        block = re.search(r"const LEAD_FORM_COPY = \{(.*?)\n\};", self.STORE, re.S).group(1)
        declared = set(re.findall(r"^  (\w+):", block, re.M))
        self.assertEqual(set(LEAD_CAPTURE_ACTIONS) - declared, set())


class TheProductMustNameTheEvent(unittest.TestCase):
    def _product(self, **lead_capture):
        base = {"schema_version": "1.0.0", "document_type": "product", "tenant_id": "t",
                "product_id": "p", "name": "Live training", "product_intent": "lead_gen",
                "lead_capture": {"action": "register_event", "title": "T", "description": "D",
                                 "fields": [{"name": "email", "type": "email", "required": True}],
                                 **lead_capture}}
        return base

    def test_it_validates_with_an_event(self):
        from stripe_link.domain.documents import validate_product_lead_capture
        validate_product_lead_capture(self._product(event_id="ev_1"))

    def test_without_one_it_is_refused(self):
        """The page would have nothing to announce and the registration nothing to point at."""
        from stripe_link.domain.documents import DocumentValidationError, validate_product_lead_capture
        with self.assertRaises(DocumentValidationError):
            validate_product_lead_capture(self._product())

    def test_it_still_needs_the_fields_a_capture_needs(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_product_lead_capture
        product = self._product(event_id="ev_1")
        product["lead_capture"]["fields"] = []
        with self.assertRaises(DocumentValidationError):
            validate_product_lead_capture(product)


if __name__ == "__main__":
    unittest.main()

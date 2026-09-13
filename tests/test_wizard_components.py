"""Wizards share their chrome, rather than each inventing it.

Author, 2026-09-13: "drifting components that should be similar". Three surfaces had three answers to the same
two questions.

**Progress.** The product wizard drew numbered pills, the landing-page wizard drew three anonymous dots AND a
"Step 2 of 3" line in its header. A tenant meeting two of them in one session is meeting two products.

**Selection.** The Offer item picker draws a filled circle with a white tick; the landing-page wizard drew a
bare grey ✓ that was visible on every card, selected or not, because only `display` was ever set on it and no
base rule gave it the circle. The one a tenant already recognises should win.

And the product wizard's tinted glyphs are gone: three icons made a list of three sentences read as a toolbar.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "dashboard" / "src" / "components" / "shared"
STEPS = (SHARED / "WizardSteps.vue").read_text(encoding="utf-8")
CARD = (SHARED / "WizardChoiceCard.vue").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")
PAGES = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
WIZARDS = {"Products.vue": PRODUCTS, "LandingPages.vue": PAGES}


def _base_check_rule():
    """The BASE `.wizard-choice-check` rule, not one of the `.selected` ones.

    Anchored on a newline, because three rules in the file contain the substring `.wizard-choice-check {` and
    splitting on it lands on whichever comes first. That is the third time in this codebase a test has sliced
    a file on a string that appears more than once and quietly asserted against the wrong block -- so it gets
    a named helper rather than another inline split.
    """
    return CSS.split("\n.wizard-choice-check {", 1)[1].split("}", 1)[0]


class AdoptionTests(unittest.TestCase):
    def test_both_wizards_use_the_shared_components(self):
        for name, src in WIZARDS.items():
            self.assertIn("WizardSteps", src, name)
            self.assertIn("WizardChoiceCard", src, name)
            self.assertIn('shared/WizardSteps.vue"', src, name)
            self.assertIn('shared/WizardChoiceCard.vue"', src, name)

    def test_no_wizard_still_draws_its_own_progress(self):
        # The landing-page wizard's dots and the product wizard's hand-rolled <ol> are both gone.
        for name, src in WIZARDS.items():
            self.assertNotIn('class="wizard-progress"', src, name)
            self.assertNotIn('<ol class="wizard-steps"', src, name)

    def test_no_wizard_still_draws_its_own_choice_card(self):
        for name, src in WIZARDS.items():
            self.assertNotIn('class="wizard-goal-card"', src, name)

    def test_there_is_one_selected_state_everywhere(self):
        # The offer picker keeps its own card SHAPE -- it carries an image -- but not its own idea of what
        # "chosen" looks like. wizard-card-check is gone entirely; there is one check class now.
        for name, src in WIZARDS.items():
            self.assertNotIn("wizard-card-check", src, name)
        self.assertNotIn("wizard-card-check", CSS)


class SelectionTests(unittest.TestCase):
    def test_the_check_matches_the_offer_pickers(self):
        # Same shape, same size, same accent fill as .selector-card-check -- that is the whole point.
        block = _base_check_rule()
        self.assertIn("border-radius: 50%", block)
        self.assertIn("background: var(--accent)", block)
        self.assertIn("color: #fff", block)

    def test_it_is_hidden_until_selected(self):
        # The landing-page wizard's tick was visible on every card, because nothing ever hid it: there was no
        # base rule at all, only `display: grid` when selected.
        block = _base_check_rule()
        self.assertIn("display: none", block)
        self.assertIn(".wizard-choice-card.selected .wizard-choice-check { display: block; }", CSS)

    def test_the_card_leaves_room_for_it(self):
        # Right padding, so the check never lands on the description of a long option.
        block = CSS.split("\n.wizard-choice-card {", 1)[1].split("}", 1)[0]
        self.assertRegex(block, r"padding:[^;]*4\.4rem")


class NoIconsTests(unittest.TestCase):
    def test_the_intent_cards_carry_no_glyphs(self):
        block = PRODUCTS.split("const PRODUCT_INTENTS = [", 1)[1].split("];", 1)[0]
        self.assertNotIn("tone:", block)
        self.assertNotIn("intentIcon", PRODUCTS)

    def test_the_card_component_takes_no_icon(self):
        # Not merely unused here -- there is no prop for one, so the next wizard cannot quietly reintroduce
        # the drift. Checked on the PROPS, not on the file text: the first version of this test searched the
        # template for the word "icon" and matched the comment explaining why there is no icon.
        props = CARD.split("defineProps({", 1)[1].split("});", 1)[0]
        self.assertNotIn("icon", props.lower())
        self.assertEqual(sorted(re.findall(r"^\s*(\w+):", props, re.M)),
                         ["description", "selected", "title"])


class StepRailTests(unittest.TestCase):
    def test_a_completed_step_shows_a_tick_rather_than_its_number(self):
        self.assertIn('current > index + 1 ? "✓" : index + 1', STEPS)

    def test_the_current_step_is_announced(self):
        # A visual-only rail tells a screen-reader user nothing about where they are.
        self.assertIn('aria-current', STEPS)

    def test_the_landing_wizard_labels_the_path_it_is_actually_taking(self):
        # Its step count varies -- a Social Page skips the goal step -- so constant labels would mislabel it.
        block = PAGES.split("const wizardStepLabels = computed(", 1)[1].split("});", 1)[0]
        self.assertIn("wizardSkipsGoal", block)
        self.assertIn("displayTotal", block)


if __name__ == "__main__":
    unittest.main()

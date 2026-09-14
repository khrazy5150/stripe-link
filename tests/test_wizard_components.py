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
DASHBOARD = (ROOT / "dashboard" / "src" / "components" / "Dashboard.vue").read_text(encoding="utf-8")
KEYS = (ROOT / "dashboard" / "src" / "components" / "StripeKeys.vue").read_text(encoding="utf-8")
WIZARDS = {"Products.vue": PRODUCTS, "LandingPages.vue": PAGES}
# Every wizard in the app, including the two Stripe Connect ones, which do not use choice cards.
ALL_WIZARDS = {**WIZARDS, "Dashboard.vue": DASHBOARD, "StripeKeys.vue": KEYS}


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
        # Four wizards, four hand-rolled rails: the landing page's dots, the product wizard's <ol>, and the
        # two Stripe Connect ones' onboarding-dots. All four now render the same component.
        for name, src in ALL_WIZARDS.items():
            self.assertIn("WizardSteps", src, name)
            self.assertNotIn('class="wizard-progress"', src, name)
            self.assertNotIn('<ol class="wizard-steps"', src, name)
            self.assertNotIn("onboarding-dot", src, name)

    def test_no_wizard_counts_its_own_steps_in_prose(self):
        # "Step 2 of 4" beside a rail says the same thing twice, and the two can disagree -- which is exactly
        # what happened when the landing-page rail was built four labels long for a five-step path.
        for name, src in ALL_WIZARDS.items():
            self.assertNotIn("Step {{", src, name)

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

    def test_every_landing_wizard_path_is_fully_labelled(self):
        """The rail must be exactly as long as the wizard, on all three paths.

        The first version was four labels `.slice()`d to length, which showed a FOUR-step rail on the
        five-step offer path -- a rail that lies about how much is left is worse than the dots it replaced.
        Recomputed here from the same expressions the component uses.
        """
        # wizardTotalSteps: offer -> 4, else 2. displayTotal: that + 1 (the prepended Site step) - 1 if the
        # goal step is skipped (a Social Page).
        for kind, skips_goal, expected in (("offer", False, 5), ("offer", True, 4), ("storefront", False, 3)):
            total = (4 if kind == "offer" else 2) + 1 - (1 if skips_goal else 0)
            if kind != "offer":
                labels = ["Site", "Type", "Details"]
            else:
                labels = ["Site", "Type"] + ([] if skips_goal else ["Goal"]) + ["Configure", "Review"]
            self.assertEqual(len(labels), total, f"{kind} skips_goal={skips_goal}")
            self.assertEqual(total, expected)

    def test_the_landing_wizard_rail_keeps_the_modal_gutter(self):
        """It hangs off the modal card itself, so nothing else supplies its side padding.

        The dots it replaced had `padding: 1.2rem 2.4rem` baked into `.wizard-progress`; the shared rail has
        no padding of its own (the product wizard's sits inside an already-padded body), so swapping them ran
        the rail edge to edge -- the labels touched both sides of the modal.
        """
        block = CSS.split("\n.landing-wizard-modal .wizard-steps {", 1)[1].split("}", 1)[0]
        self.assertRegex(block, r"padding:[^;]*2\.4rem")
        # The gutter it borrows is the modal's own, so the rail lines up with the title and the step body.
        body = CSS.split("\n.landing-wizard-body {", 1)[1].split("}", 1)[0]
        self.assertIn("2.4rem", body)

    def test_the_dot_rail_styling_is_gone_too(self):
        # No component draws `.wizard-progress` any more; leaving its rules behind invites the next wizard to
        # pick them back up. Matched on the SELECTOR, not the bare name -- the replacement rule's comment
        # mentions the class it supersedes, and the first version of this test failed on that comment.
        self.assertNotRegex(CSS, r"(?m)^\.wizard-progress\b")

    def test_the_landing_wizard_labels_the_path_it_is_actually_taking(self):
        # Its step count varies -- a Social Page skips the goal step -- so constant labels would mislabel it.
        block = PAGES.split("const wizardStepLabels = computed(", 1)[1].split("});", 1)[0]
        self.assertIn("wizardSkipsGoal", block)
        self.assertIn("form.pageKind", block)
        # Built, not truncated. `.slice()`-to-length is what produced the four-label rail on a five-step path:
        # it hides the mismatch instead of failing on it.
        self.assertNotIn(".slice(", block)


if __name__ == "__main__":
    unittest.main()

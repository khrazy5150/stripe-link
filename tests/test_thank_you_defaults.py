"""The thank-you defaults, and why a default is never a suggestion.

plans/THANK_YOU_PAGE.md P3. "Start Your Journey" was written as inspiration — a worked example for tenants
selling courses, to be edited or deleted. It was being left exactly as shipped, on stores that sell
supplements. Whatever a default says is what most stores will say.

Removing it works only because of a mechanism worth stating: `thankYouCopyOverrides` persists `next_steps`
ONLY when they have been edited away from the defaults. A tenant who left them alone has nothing stored
and inherits whatever the runtime default now is. A tenant who edited keeps theirs — their data, their
choice, no migration.

That mechanism also makes the two lists load-bearing: the Vue copy is COMPARED against the saved cards to
decide whether to persist them. If it drifts from the Python one by a single character, every page starts
storing its cards and no default change ever reaches anyone again.
"""
import json
import pathlib
import re
import unittest

from stripe_link.runtime.upsell_pages import DEFAULT_THANK_YOU

ROOT = pathlib.Path(__file__).resolve().parents[1]
LANDING_VUE = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text()


def _vue_default_cards():
    block = LANDING_VUE.split("const THANK_YOU_DEFAULT_CARDS = [", 1)[1].split("];", 1)[0]
    cards = []
    # One card per line. Not a brace-matching regex: `{{arrival}}` lives inside a value and would end the
    # match early, which is exactly how this parser failed first time round.
    for row in block.splitlines():
        if "icon:" not in row:
            continue
        cards.append({
            key: re.search(rf'{key}:\s*"((?:[^"\\]|\\.)*)"', row).group(1).replace('\\"', '"')
            for key in ("icon", "title", "desc")
        })
    return cards


class TheTwoCopiesMustAgreeTests(unittest.TestCase):
    def test_the_dashboard_mirrors_the_runtime_defaults(self):
        """A drift of one character and every page stores its cards forever after."""
        self.assertEqual(_vue_default_cards(), DEFAULT_THANK_YOU["next_steps"])

    def test_the_comparison_that_depends_on_it_still_exists(self):
        self.assertIn("JSON.stringify(cards) !== JSON.stringify(THANK_YOU_DEFAULT_CARDS)", LANDING_VUE)


class TheDefaultsAreTheSummaryNotTheInspirationTests(unittest.TestCase):
    CARDS = DEFAULT_THANK_YOU["next_steps"]

    def test_start_your_journey_is_gone(self):
        self.assertNotIn("Start Your Journey", json.dumps(self.CARDS))

    def test_so_is_the_claim_that_shipping_was_free(self):
        """It said "Free Shipping" over an order that had just paid $39.59, and "arrive within 5–7 business
        days" to a buyer whose destination nobody knew."""
        blob = json.dumps(self.CARDS)
        self.assertNotIn("Free Shipping", blob)
        self.assertNotIn("business days", blob)

    def test_it_is_three_steps(self):
        self.assertEqual(len(self.CARDS), 3)

    def test_the_middle_one_carries_the_date(self):
        """Repeating the arrival date here is deliberate: it is the line a buyer scans for, and one who
        scrolled past the element above should still meet it."""
        self.assertIn("{{arrival}}", self.CARDS[1]["desc"])

    def test_exactly_one_card_claims_a_date(self):
        # Two would be two chances to disagree with the element.
        self.assertEqual(sum("{{arrival}}" in c["desc"] for c in self.CARDS), 1)


class TheTokenReadsAsASentenceTests(unittest.TestCase):
    """`{{arrival}}` carries its own preposition, so a tenant writes around it and it still parses."""

    def test_the_default_sentence_completes_with_a_date(self):
        from stripe_link.domain.shipping_promise import arrival_phrase

        phrase = arrival_phrase({"has_date": True, "arrives_on": "2026-10-08", "arrives_through": None})
        sentence = DEFAULT_THANK_YOU["next_steps"][1]["desc"].replace("{{arrival}}", phrase)
        self.assertEqual(sentence, "Your order is expected to arrive on Thursday, October 8.")

    def test_and_completes_WITHOUT_one(self):
        from stripe_link.domain.shipping_promise import arrival_phrase

        sentence = DEFAULT_THANK_YOU["next_steps"][1]["desc"].replace("{{arrival}}", arrival_phrase({}))
        self.assertTrue(sentence.endswith("."))
        self.assertIn("soon", sentence)


class TheIconsCanActuallyBeChangedTests(unittest.TestCase):
    """A bare text input meant an icon could only be changed by pasting an emoji from somewhere else,
    which is a large part of why every thank-you page in the wild still wears the defaults."""

    def test_the_card_editor_uses_the_shared_picker(self):
        block = LANDING_VUE.split('<div v-for="(card, i) in builder.post_purchase.thank_you.next_steps"', 1)[1][:1400]
        self.assertIn("showIconPicker(card.icon", block)

    def test_the_raw_text_input_is_gone(self):
        block = LANDING_VUE.split('<div v-for="(card, i) in builder.post_purchase.thank_you.next_steps"', 1)[1][:1400]
        self.assertNotIn('v-model.trim="card.icon" type="text"', block)

    def test_the_tenant_is_told_the_token_exists(self):
        self.assertIn("becomes that buyer's own delivery", LANDING_VUE)

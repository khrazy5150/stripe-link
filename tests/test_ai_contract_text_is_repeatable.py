"""Building the AI's element instructions must not consume them.

`contract()` returns the LIVE cached rules — one parse of the JSON, shared by every caller for the life
of the process. The prompt builder popped `why` off each bad example, which edited that cache: the first
generation on a warm Lambda got "WRONG: {...}  <- here is why", and every generation after it in the same
container got "WRONG: {...}" with nothing attached.

That is the worst possible direction for the failure. A bad example without its reason is a shape the
model is shown and told nothing about — so the instructions silently taught LESS the longer a container
lived, and the AI's grasp of which element to use degraded with uptime rather than with anything
observable.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from stripe_link.domain import ai_elements  # noqa: E402


class TheInstructionsSurviveBeingReadTests(unittest.TestCase):
    def setUp(self):
        # Drop the module cache so each test starts from a fresh parse of the rules file. Without this
        # the tests poison each other exactly the way the bug poisons generations -- and the first
        # version of this file passed against the bug for precisely that reason.
        ai_elements._CACHE = None

    def _elements_with_bad_examples(self):
        return [e for e in ai_elements.contracted()
                if any(isinstance(b, dict) and b.get("why")
                       for b in (ai_elements.contract(e).get("bad") or []))]

    def test_there_are_bad_examples_with_reasons_to_protect(self):
        """Guards the guard: if the contracts lose their `why` fields this test must not quietly pass."""
        self.assertTrue(self._elements_with_bad_examples(),
                        "no contract carries a bad example with a reason")

    def test_building_twice_produces_the_same_text(self):
        first = ai_elements.for_prompt(ai_elements.contracted())
        second = ai_elements.for_prompt(ai_elements.contracted())
        self.assertEqual(first, second, "the second build lost content the first one consumed")

    def test_the_reasons_survive_a_build(self):
        before = {e: [dict(b) for b in ai_elements.contract(e).get("bad") or []]
                  for e in self._elements_with_bad_examples()}
        ai_elements.for_prompt(ai_elements.contracted())
        for element, examples in before.items():
            with self.subTest(element=element):
                after = ai_elements.contract(element).get("bad") or []
                self.assertEqual([b.get("why") for b in examples], [b.get("why") for b in after],
                                 f"{element} lost its bad-example reasons to the prompt builder")

    def test_a_reason_actually_reaches_the_text(self):
        element = self._elements_with_bad_examples()[0]
        why = next(b["why"] for b in ai_elements.contract(element)["bad"] if b.get("why"))
        self.assertIn(why, ai_elements.for_prompt(ai_elements.contracted()))


if __name__ == "__main__":
    unittest.main()

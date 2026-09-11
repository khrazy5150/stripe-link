"""One answer to "is this offer lead-gen?", used by everything that asks.

Four places asked it in the builder and three agreed. deriveOfferType -- the one driving SECTION
VISIBILITY through sectionVisible() -- read `offer.product_intent` alone with no product fallback, while
builderIntent (which drives the CTA) fell back to the product. An offer whose intent had to come from its
product therefore produced a lead-gen CTA and TRANSACTIONAL sections: a page wearing trust badges and a
refund policy while selling nothing.

Source-level pins, because the dashboard has no JS test runner (see the ESLint item in TODO.md).
"""
import pathlib
import re
import unittest

BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


class SingleDerivationTests(unittest.TestCase):
    def test_there_is_exactly_one_definition(self):
        self.assertEqual(len(re.findall(r"function offerIntent\(", BUILDER)), 1)

    def test_it_falls_back_to_the_product(self):
        body = re.search(r"function offerIntent\(offer\) \{(.*?)\n\}", BUILDER, re.S).group(1)
        self.assertIn("offer?.product_intent", body)
        self.assertIn("offerProducts(offer)[0]?.product_intent", body)
        self.assertIn('"transaction"', body)

    def test_nothing_derives_intent_on_its_own_any_more(self):
        """The specific failure: a second, subtly different derivation. Any reader of product_intent that
        is NOT inside offerIntent is a candidate to drift from it again."""
        readers = []
        for match in re.finditer(r"^.*product_intent.*$", BUILDER, re.M):
            line = match.group(0)
            if "function offerIntent" in line or "offerProducts(offer)[0]?.product_intent" in line:
                continue
            if "offer?.product_intent" in line and "offerIntent" not in line:
                readers.append(line.strip()[:90])
        self.assertEqual(readers, [], "these derive intent independently of offerIntent(): " + str(readers))

    def test_section_visibility_and_the_cta_ask_the_same_function(self):
        # The two that disagreed. If these ever read different things again, a lead-gen page can carry
        # transactional sections while its CTA says otherwise.
        self.assertIn("const builderIntent = computed(() => offerIntent(", BUILDER)
        self.assertIn("if (offerIntent(offer) === \"lead_gen\") return \"lead_gen\";", BUILDER)


if __name__ == "__main__":
    unittest.main()

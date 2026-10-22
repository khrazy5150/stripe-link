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
        #
        # Asserted on the BODY rather than as one literal line, because builderIntent now short-circuits
        # for an offer-less page -- a storefront neither transacts nor captures a lead, and inheriting
        # offerIntent(null)'s "transaction" default minted a post_checkout thank-you page for it
        # (plans/OFFERLESS_PAGES_IN_BUILDER.md P2). That branch answers a question about the PAGE and is
        # taken only when there is no offer at all; the moment there IS one, this still delegates to
        # offerIntent and to nothing else, which is the invariant the test exists for.
        body = re.search(r"const builderIntent = computed\((.*?)\);", BUILDER, re.S).group(1)
        self.assertIn("offerIntent(", body)
        self.assertNotIn("product_intent", body, "builderIntent derives intent itself again")
        self.assertIn('if (offerIntent(offer) === "lead_gen") {', BUILDER)

    def test_only_an_offerless_page_may_skip_offerIntent(self):
        """The short-circuit must key on the page having NO offer. Keyed on anything else it would start
        answering for pages that do have one, which is the drift this file exists to prevent."""
        body = re.search(r"const builderIntent = computed\((.*?)\);", BUILDER, re.S).group(1)
        self.assertIn("builder.offerless", body)
        populate = BUILDER.split("function populateBuilderFromPage(page) {", 1)[1][:4000]
        self.assertIn('page.offer_id ? "" : offerlessComposition(page)', populate)


if __name__ == "__main__":
    unittest.main()

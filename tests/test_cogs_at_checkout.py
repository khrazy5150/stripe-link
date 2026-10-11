"""Cost of goods, from the product form to the profit line.

`domain/ledger.py` declared `cogs` as one of six amount components the day it was written, and
`sale_entry(cogs=...)` has always negated and stored it. **Nothing ever passed a non-zero value.** So
`profit` was `net`, and `Reports.vue` showed it under the word "Profit" — the same shape as the
Dashboard's "Net Revenue" that was really gross (fixed 2026-10-09).

P2 of `plans/MONEY_ACROSS_SILOS.md` supplies it: the tenant records a unit cost, checkout stamps it into
Stripe metadata, the webhook freezes it on the order, and the ledger entry carries it.

**The invariant every test here defends: ABSENT IS NOT ZERO.** A tenant who has not recorded a cost is
not a tenant with no costs, and the difference is the difference between a margin report and a flattering
guess. Treating unknown as zero fails in the direction a seller wants to believe, which is the worst
direction for a number to fail in.
"""
import unittest

from stripe_link.domain import cogs
from stripe_link.domain.ledger import sale_entry_from_order, summarize


class AbsentIsNotZero(unittest.TestCase):
    def test_a_product_with_no_cost_recorded_reads_as_unknown(self):
        self.assertIsNone(cogs.unit_cost({"product_id": "p"}))

    def test_a_genuinely_free_product_reads_as_zero(self):
        """A digital download may really cost nothing. That is an answer, not a missing answer."""
        self.assertEqual(cogs.unit_cost({"unit_cost": 0}), 0)

    def test_a_decimal_from_dynamodb_is_read_as_an_integer(self):
        """A document read back from DynamoDB carries Decimal. An isinstance check against int passes on
        a fixture and fails on stored data, which 404'd published pages once already."""
        from decimal import Decimal
        self.assertEqual(cogs.unit_cost({"unit_cost": Decimal("650")}), 650)

    def test_rubbish_is_unknown_rather_than_zero(self):
        for bad in ("", "abc", None, -5, [1]):
            self.assertIsNone(cogs.unit_cost({"unit_cost": bad}), bad)


class WhatTheItemsCost(unittest.TestCase):
    PRODUCTS = {"p1": {"unit_cost": 650}, "p2": {"unit_cost": 100}, "p3": {"name": "uncosted"}}

    def test_quantity_is_multiplied(self):
        total, unknown = cogs.items_cogs([{"product_id": "p1", "quantity": 3}], self.PRODUCTS)
        self.assertEqual((total, unknown), (1950, 0))

    def test_a_missing_quantity_means_one(self):
        self.assertEqual(cogs.items_cogs([{"product_id": "p1"}], self.PRODUCTS), (650, 0))

    def test_an_uncosted_line_is_counted_not_ignored(self):
        """Summing only what we happen to know is how the total comes out plausible and wrong."""
        total, unknown = cogs.items_cogs(
            [{"product_id": "p1"}, {"product_id": "p3"}], self.PRODUCTS)
        self.assertEqual((total, unknown), (650, 1))

    def test_a_service_line_is_unknown_rather_than_free(self):
        """A service has a labour cost this codebase has nowhere to record. Calling it zero would report a
        service business's entire revenue as profit."""
        self.assertEqual(cogs.items_cogs([{"kind": "service"}], {}), (0, 1))
        self.assertEqual(cogs.items_cogs([{"service_id": "svc_1"}], {}), (0, 1))

    def test_a_product_we_could_not_load_is_unknown(self):
        self.assertEqual(cogs.items_cogs([{"product_id": "gone"}], self.PRODUCTS), (0, 1))


class TheStampStaysOffSessionsThatHaveNothingToSay(unittest.TestCase):
    """Stripe allows 50 metadata keys and a session already carries about fourteen."""

    def test_a_fully_uncosted_digital_offer_adds_no_keys(self):
        self.assertEqual(cogs.stamp(0, 0, ""), {})

    def test_zero_cost_with_no_unknowns_adds_no_keys_either(self):
        """A session where everything is genuinely free is indistinguishable from one never costed, and
        that is fine: both report `known: False` and withhold profit rather than claim 100% margin."""
        self.assertEqual(cogs.stamp(0, 0, ""), {})

    def test_the_unknown_count_is_stamped_on_its_own(self):
        self.assertEqual(cogs.stamp(0, 2, ""), {"cogs_unknown": "2"})

    def test_a_costed_sale_stamps_the_total(self):
        self.assertEqual(cogs.stamp(1400, 0, ""), {"cogs": "1400"})


class OrderBumpsAreCountedWhenTicked(unittest.TestCase):
    """A bump is ticked on Stripe's hosted page AFTER the session is created, so checkout stamps what each
    bump WOULD cost and the webhook adds up the ones the buyer took — the same shape as
    `order_bump_shipping`."""

    META = {"cogs": "1400", "bump_cogs": "price_bump:250"}

    def test_a_bump_not_taken_costs_nothing(self):
        self.assertEqual(cogs.from_metadata(self.META)["cogs"], 1400)

    def test_a_bump_taken_adds_its_cost(self):
        self.assertEqual(
            cogs.from_metadata(self.META, purchased_bumps=[("price_bump", 1)])["cogs"], 1650)

    def test_a_bump_taken_THREE_TIMES_costs_three_times(self):
        """`bump_postage_collected` multiplies by quantity for exactly this reason. Summing the unit cost
        once understates COGS and overstates margin."""
        self.assertEqual(
            cogs.from_metadata(self.META, purchased_bumps=[("price_bump", 3)])["cogs"], 2150)

    def test_a_bump_with_no_stamped_cost_makes_the_sale_unknowable(self):
        """The buyer bought something we cannot price, so the margin is not knowable even though the base
        lines were."""
        result = cogs.from_metadata(self.META, purchased_bumps=[("price_other", 1)])
        self.assertEqual(result["cogs"], 1400)
        self.assertEqual(result["unknown_lines"], 1)
        self.assertFalse(result["known"])

    def test_a_malformed_pair_costs_one_line_not_the_sale(self):
        self.assertEqual(cogs.decode_bump_costs("price_a:100,rubbish,price_b:x,:5"),
                         {"price_a": 100})

    def test_encode_skips_bumps_whose_cost_is_unknown(self):
        self.assertEqual(cogs.encode_bump_costs([("price_a", 100), ("price_b", None)]),
                         "price_a:100")


class ASessionFromBeforeThisShippedIsUnknown(unittest.TestCase):
    """Every session created before P2 carries none of these keys. Reading that as 'fully costed, and the
    cost was nothing' would reintroduce the inflated-margin bug as a migration default."""

    def test_no_keys_at_all_means_unknown(self):
        result = cogs.from_metadata({"product_id": "p1", "tenant_id": "t"})
        self.assertEqual(result, {"cogs": 0, "unknown_lines": 0, "known": False})

    def test_empty_metadata_means_unknown(self):
        self.assertFalse(cogs.from_metadata({})["known"])
        self.assertFalse(cogs.from_metadata(None)["known"])


class TheLedgerEntryCarriesIt(unittest.TestCase):
    ORDER = {"tenant_id": "t", "order_id": "order_x", "amount_total": 3291, "stripe_mode": "test",
             "currency": "usd", "fees": {"stripe_fee": 125, "platform_fee": 66}}

    def test_a_costed_order_produces_a_negative_cogs_amount(self):
        entry = sale_entry_from_order(
            dict(self.ORDER, costs={"cogs": 650, "unknown_lines": 0, "known": True}), now_epoch=1)
        self.assertEqual(entry["amounts"]["cogs"], -650, "a cost reduces the tenant's cash")
        self.assertTrue(entry["cogs_known"])

    def test_an_order_with_no_costs_block_is_not_claimed_as_costed(self):
        entry = sale_entry_from_order(self.ORDER, now_epoch=1)
        self.assertFalse(entry.get("cogs_known"))

    def test_an_incomplete_order_carries_the_amount_but_not_the_claim(self):
        """The partial total is still recorded — it is real money — but the sale cannot support a profit."""
        entry = sale_entry_from_order(
            dict(self.ORDER, costs={"cogs": 650, "unknown_lines": 1, "known": False}), now_epoch=1)
        self.assertEqual(entry["amounts"]["cogs"], -650)
        self.assertFalse(entry.get("cogs_known"))

    def test_the_flag_is_omitted_rather_than_stored_false(self):
        entry = sale_entry_from_order(self.ORDER, now_epoch=1)
        self.assertNotIn("cogs_known", entry,
                         "absent reads as unknown; a stored false says the same in more bytes")


class ProfitIsWithheldRatherThanGuessed(unittest.TestCase):
    COSTED = {"entry_type": "sale", "cogs_known": True,
              "amounts": {"gross": 3291, "stripe_fee": -125, "platform_fee": -66, "cogs": -650}}
    UNCOSTED = {"entry_type": "sale",
                "amounts": {"gross": 3291, "stripe_fee": -125, "platform_fee": -66}}
    REFUND = {"entry_type": "refund", "amounts": {"gross": -3291}}

    def test_every_sale_costed_means_profit_is_shown(self):
        summary = summarize([self.COSTED, self.COSTED])
        self.assertTrue(summary["profit_known"])
        self.assertEqual(summary["uncosted_sales"], 0)
        self.assertEqual(summary["profit"], 2 * (3291 - 125 - 66 - 650))

    def test_one_uncosted_sale_withholds_the_whole_period(self):
        """The figure would be short by an unknown amount and inflated in the flattering direction."""
        summary = summarize([self.COSTED, self.UNCOSTED])
        self.assertFalse(summary["profit_known"])
        self.assertEqual(summary["uncosted_sales"], 1)

    def test_a_refund_does_not_make_a_period_unknowable(self):
        """A refund has no cost of goods to know. Requiring a flag on one would make any refunded period
        permanently blank."""
        self.assertTrue(summarize([self.COSTED, self.REFUND])["profit_known"])

    def test_an_empty_period_is_unknown_not_zero_profit(self):
        """A tenant's first visit should not be told their profit is zero with authority."""
        summary = summarize([])
        self.assertFalse(summary["profit_known"])
        self.assertEqual(summary["uncosted_sales"], 0)

    def test_the_legacy_ledger_reports_no_profit(self):
        """Every entry written before P2 lacks the flag, which is the honest answer for all of them."""
        self.assertFalse(summarize([self.UNCOSTED] * 5)["profit_known"])


class TheProductDocumentAcceptsIt(unittest.TestCase):
    def test_a_valid_cost_passes_validation(self):
        from stripe_link.domain.documents import validate_product_document
        validate_product_document(_product(unit_cost=650))
        validate_product_document(_product(unit_cost=0))
        validate_product_document(_product())  # absent is legal

    def test_a_negative_cost_is_refused(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_product_document
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(unit_cost=-1))

    def test_a_string_cost_is_refused(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_product_document
        with self.assertRaises(DocumentValidationError):
            validate_product_document(_product(unit_cost="650"))

    def test_the_schema_declares_it(self):
        import json
        import pathlib
        schema = json.loads((pathlib.Path(__file__).resolve().parents[1]
                             / "schemas" / "Product.schema.json").read_text())
        field = schema["properties"]["unit_cost"]
        self.assertEqual(field["type"], "integer")
        self.assertEqual(field["minimum"], 0)
        self.assertIn("ABSENT MEANS UNKNOWN", field["description"],
                      "the one rule a future reader must not get wrong")


def _product(**extra):
    """The canonical example product, with the field under test applied.

    A hand-rolled fixture was tried first and failed validation three times on fields this test has no
    opinion about (`fulfillment.dimensions`, `sync`). Building from the shipped example means the fixture
    cannot drift from what the validator actually requires -- the same reason the orphan-sweep tests wrap
    the REAL repository instead of inventing one.
    """
    import json
    import pathlib as _pathlib
    examples = _pathlib.Path(__file__).resolve().parents[1] / "schemas" / "examples"
    document = json.loads(next(examples.glob("product-*.json")).read_text(encoding="utf-8"))
    document.update(extra)
    return document


if __name__ == "__main__":
    unittest.main()


class TheSessionIsStampedWithIt(unittest.TestCase):
    """End of the chain's first half: the payload Stripe is actually sent.

    Driven through the real `build_checkout_payload`, because the stamp's whole value is that it survives
    to the completed session — a helper that returns the right dict while the builder never calls it
    would pass a unit test and record no costs at all.
    """

    PRODUCT = {"product_id": "p1", "product_type": "physical", "unit_cost": 650, "name": "Gummies",
               "prices": [{"price_id": "pr1", "unit_amount": 3291, "currency": "usd",
                           "stripe_price_id": "price_main"}]}

    def _payload(self, items, products):
        from handlers.checkout import build_checkout_payload
        return build_checkout_payload(
            tenant_id="t1", offer={"offer_id": "o1", "checkout": {}}, products_by_id=products,
            resolved={"items": items, "currency": "usd"},
            success_url="https://x/s", cancel_url="https://x/c", mode="test")

    def test_a_costed_line_stamps_the_total(self):
        payload = self._payload([{"product_id": "p1", "price_id": "pr1", "quantity": 2}],
                                {"p1": self.PRODUCT})
        self.assertEqual(payload["metadata[cogs]"], "1300", "650 a unit, two units")
        self.assertNotIn("metadata[cogs_unknown]", payload)

    def test_an_uncosted_line_stamps_the_count_instead(self):
        bare = {key: value for key, value in self.PRODUCT.items() if key != "unit_cost"}
        payload = self._payload([{"product_id": "p1", "price_id": "pr1", "quantity": 1}], {"p1": bare})
        self.assertEqual(payload["metadata[cogs_unknown]"], "1")
        self.assertNotIn("metadata[cogs]", payload)

    def test_a_mixed_order_stamps_both(self):
        bare = dict(self.PRODUCT, product_id="p2")
        bare.pop("unit_cost")
        payload = self._payload(
            [{"product_id": "p1", "price_id": "pr1", "quantity": 1},
             {"product_id": "p2", "price_id": "pr1", "quantity": 1}],
            {"p1": self.PRODUCT, "p2": bare})
        self.assertEqual(payload["metadata[cogs]"], "650")
        self.assertEqual(payload["metadata[cogs_unknown]"], "1")

    def test_a_session_with_nothing_costed_carries_no_cogs_keys(self):
        """Stripe allows 50 metadata keys and a session already uses about fourteen."""
        payload = self._payload([], {})
        self.assertFalse([key for key in payload if "cogs" in key], "no keys at all")

    def test_the_round_trip_agrees_with_what_the_webhook_will_read(self):
        """The two halves share one module, so this proves the wire format end to end rather than
        asserting the same string twice."""
        payload = self._payload([{"product_id": "p1", "price_id": "pr1", "quantity": 3}],
                                {"p1": self.PRODUCT})
        metadata = {key[len("metadata["):-1]: value
                    for key, value in payload.items() if key.startswith("metadata[")}
        self.assertEqual(cogs.from_metadata(metadata),
                         {"cogs": 1950, "unknown_lines": 0, "known": True})

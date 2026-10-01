"""The shipping quote primitive: what the buyer agreed to, and what the carrier later charged.

plans/LIVE_SHIPPING_RATES.md phase 1. Nothing here rates anything -- these are the rules that let a stored
answer price a checkout safely, and the ones that decide when a variance is worth a tenant's attention.
"""
import pathlib
import unittest

from stripe_link.domain.shipping_quotes import (
    FALLBACK,
    cache_id,
    QUOTE_RETENTION_SECONDS,
    QUOTE_TTL_SECONDS,
    REQUOTE,
    USE,
    USE_CHEAPEST,
    build_actual,
    build_quote,
    cheapest_option,
    fingerprint,
    is_expired,
    normalize_destination,
    normalize_quote_option,
    option_for,
    validate,
    variance,
    variance_threshold,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

ITEMS = [{"product_id": "p1", "price_id": "pr1", "quantity": 2}]
PARCELS = [{"length": 10, "width": 8, "height": 6, "weight": "3.5", "box_name": "Medium"}]
TO = {"country": "US", "postal_code": "80202", "region": "CO"}
OPTIONS = [
    {"service_token": "ups_ground_saver", "carrier": "ups", "label": "UPS Ground Saver",
     "amount": 642, "estimated_days": 4},
    {"service_token": "usps_ground_advantage", "carrier": "usps", "label": "USPS Ground Advantage",
     "amount": 718, "estimated_days": 5},
    {"service_token": "ups_3_day_select", "carrier": "ups", "label": "UPS 3 Day Select",
     "amount": 1260, "estimated_days": 3},
]


def a_quote(**overrides):
    base = dict(quote_id="shq_1", tenant_id="t1", mode="test", offer_id="o1",
                destination=TO, parcels=PARCELS, items=ITEMS, options=OPTIONS,
                source="zone", now=1_000_000)
    base.update(overrides)
    return build_quote(**base)


class FingerprintTests(unittest.TestCase):
    def test_it_is_stable_across_key_order_and_number_formatting(self):
        a = fingerprint(offer_id="o1", items=ITEMS, parcels=PARCELS, destination=TO)
        b = fingerprint(destination=dict(reversed(list(TO.items()))),
                        parcels=[{"weight": 3.50, "height": 6.0, "width": 8, "length": "10.00"}],
                        items=[{"quantity": "2", "price_id": "pr1", "product_id": "p1"}], offer_id="o1")
        self.assertEqual(a, b)

    def test_a_different_quantity_is_a_different_cart(self):
        other = [{"product_id": "p1", "price_id": "pr1", "quantity": 3}]
        self.assertNotEqual(fingerprint(offer_id="o1", items=ITEMS, parcels=PARCELS, destination=TO),
                            fingerprint(offer_id="o1", items=other, parcels=PARCELS, destination=TO))

    def test_a_reweighed_product_invalidates_the_quote(self):
        # The parcel is what the CARRIER priced. A corrected weight, a box added, or a packer change must
        # all invalidate -- and only the parcel side of the fingerprint notices those.
        heavier = [dict(PARCELS[0], weight="9.0")]
        self.assertNotEqual(fingerprint(offer_id="o1", items=ITEMS, parcels=PARCELS, destination=TO),
                            fingerprint(offer_id="o1", items=ITEMS, parcels=heavier, destination=TO))

    def test_a_different_destination_is_a_different_quote(self):
        self.assertNotEqual(fingerprint(offer_id="o1", items=ITEMS, parcels=PARCELS, destination=TO),
                            fingerprint(offer_id="o1", items=ITEMS, parcels=PARCELS,
                                        destination=dict(TO, postal_code="90210")))

    def test_postal_codes_normalize_so_one_address_is_one_quote(self):
        # "k1a 0b1" and "K1A0B1" are the same Canadian address. Disagreeing would spend a carrier call to
        # discover that.
        self.assertEqual(normalize_destination({"country": "ca", "postal_code": "k1a 0b1"})["postal_code"],
                         "K1A0B1")
        self.assertEqual(fingerprint(offer_id="o", items=[], parcels=[],
                                     destination={"country": "CA", "postal_code": "k1a 0b1"}),
                         fingerprint(offer_id="o", items=[], parcels=[],
                                     destination={"country": "ca", "postal_code": "K1A0B1"}))


class BuildQuoteTests(unittest.TestCase):
    def test_it_carries_the_fingerprint_of_what_it_quoted(self):
        quote = a_quote()
        self.assertEqual(quote["fingerprint"],
                         fingerprint(offer_id="o1", items=ITEMS, parcels=PARCELS, destination=TO))

    def test_the_price_expires_long_before_the_record_does(self):
        # The row is the audit trail behind any variance the tenant is later shown. A TTL that deleted the
        # evidence with the price would lose it a week before the question gets asked.
        quote = a_quote()
        self.assertEqual(quote["expires_at"], 1_000_000 + QUOTE_TTL_SECONDS)
        self.assertEqual(quote["retention_expires_at"], 1_000_000 + QUOTE_RETENTION_SECONDS)
        self.assertGreater(quote["retention_expires_at"], quote["expires_at"])

    def test_an_option_without_a_service_token_is_dropped(self):
        quote = a_quote(options=[{"amount": 500, "label": "Mystery"}] + OPTIONS)
        self.assertEqual(len(quote["options"]), 3)
        self.assertIsNone(normalize_quote_option({"amount": 500}))

    def test_option_lookup_and_cheapest(self):
        quote = a_quote()
        self.assertEqual(option_for(quote, "usps_ground_advantage")["amount"], 718)
        self.assertIsNone(option_for(quote, "fedex_overnight"))
        self.assertEqual(cheapest_option(quote)["service_token"], "ups_ground_saver")

    def test_expiry_is_inclusive_at_the_boundary(self):
        quote = a_quote()
        self.assertFalse(is_expired(quote, quote["expires_at"] - 1))
        self.assertTrue(is_expired(quote, quote["expires_at"]))


class ValidateTests(unittest.TestCase):
    """Each kind of invalid wants a DIFFERENT answer, so the action is what gets asserted."""

    def _args(self, quote, **over):
        base = dict(tenant_id="t1", mode="test", offer_id="o1",
                    cart_fingerprint=quote["fingerprint"],
                    service_token="ups_ground_saver", now=1_000_100)
        base.update(over)
        return base

    def test_a_matching_quote_is_used(self):
        quote = a_quote()
        result = validate(quote, **self._args(quote))
        self.assertEqual(result["action"], USE)
        self.assertEqual(result["option"]["amount"], 642)

    def test_a_missing_quote_falls_back_to_the_zone_path(self):
        # Exactly what happens for a buyer who never touched the element -- not an error.
        self.assertEqual(validate(None, **self._args(a_quote()))["action"], FALLBACK)

    def test_another_tenants_quote_is_never_used(self):
        quote = a_quote()
        result = validate(quote, **self._args(quote, tenant_id="t2"))
        self.assertEqual((result["action"], result["reason"]), (FALLBACK, "tenant_mismatch"))

    def test_a_test_quote_cannot_price_a_live_checkout(self):
        quote = a_quote()
        result = validate(quote, **self._args(quote, mode="live"))
        self.assertEqual((result["action"], result["reason"]), (FALLBACK, "mode_mismatch"))

    def test_a_quote_for_another_offer_is_refused(self):
        quote = a_quote()
        self.assertEqual(validate(quote, **self._args(quote, offer_id="o2"))["reason"], "offer_mismatch")

    def test_a_changed_cart_triggers_a_requote_not_a_fallback(self):
        # The quote WAS ours; it just no longer describes this purchase. Asking the carrier again is a
        # better answer than charging nothing.
        quote = a_quote()
        result = validate(quote, **self._args(quote, cart_fingerprint="something-else"))
        self.assertEqual((result["action"], result["reason"]), (REQUOTE, "cart_changed"))

    def test_an_expired_quote_triggers_a_requote(self):
        quote = a_quote()
        result = validate(quote, **self._args(quote, now=quote["expires_at"] + 1))
        self.assertEqual((result["action"], result["reason"]), (REQUOTE, "expired"))

    def test_a_service_not_in_the_quote_falls_to_the_quotes_own_cheapest(self):
        # A stale page, or a tampered token. Either way the amount is one WE computed.
        quote = a_quote()
        result = validate(quote, **self._args(quote, service_token="fedex_priority_overnight"))
        self.assertEqual((result["action"], result["reason"]), (USE_CHEAPEST, "service_unavailable"))
        self.assertEqual(result["option"]["amount"], 642)

    def test_a_tampered_amount_cannot_enter_through_validation_at_all(self):
        # There is no amount in the inputs. The only amounts validation can return are the row's own.
        quote = a_quote()
        result = validate(quote, **self._args(quote))
        self.assertIn(result["option"]["amount"], {o["amount"] for o in quote["options"]})


class VarianceTests(unittest.TestCase):
    def test_the_threshold_table(self):
        """max($2.00, 25% of the quote) -- the author's table, 2026-10-01."""
        for quoted, expected in ((400, 200), (800, 200), (1200, 300), (2000, 500)):
            with self.subTest(quoted=quoted):
                self.assertEqual(variance_threshold(quoted), expected)

    def test_free_shipping_still_gets_the_floor(self):
        self.assertEqual(variance_threshold(0), 200)

    def test_the_worked_example(self):
        # $6.42 quoted, $9.10 label, +$2.68, over the $2.00 threshold.
        result = variance(quoted_amount=642, actual_amount=910)
        self.assertEqual(result["delta"], 268)
        self.assertEqual(result["threshold"], 200)
        self.assertTrue(result["flagged"])
        self.assertEqual(result["direction"], "over")

    def test_exactly_at_the_threshold_does_not_flag(self):
        # "exceeds the threshold", not "reaches it".
        self.assertFalse(variance(quoted_amount=400, actual_amount=600)["flagged"])
        self.assertTrue(variance(quoted_amount=400, actual_amount=601)["flagged"])

    def test_a_cheaper_label_is_recorded_but_never_flagged(self):
        # An alert that fires when the tenant MAKES money trains them to ignore alerts.
        result = variance(quoted_amount=1260, actual_amount=400)
        self.assertEqual(result["delta"], -860)
        self.assertFalse(result["flagged"])
        self.assertEqual(result["direction"], "under")


class ActualRecordTests(unittest.TestCase):
    def test_the_quote_is_never_mutated_by_recording_the_label(self):
        quote = a_quote()
        before = dict(quote)
        build_actual(quote_id=quote["quote_id"], order_id="ord_1", service_token="ups_ground_saver",
                     amount=910, quoted_amount=642, destination={"country": "US", "postal_code": "80205"},
                     quoted_destination=quote["destination"], carrier="ups", now=1_002_000)
        self.assertEqual(quote, before)

    def test_it_keeps_both_postal_codes_so_a_variance_explains_itself(self):
        # "You were charged more than you quoted" is an assertion. "Quoted 80202, shipped to 80205" is a
        # reason the tenant can check.
        record = build_actual(quote_id="shq_1", order_id="ord_1", service_token="ups_ground_saver",
                              amount=910, quoted_amount=642,
                              destination={"country": "US", "postal_code": "80205"},
                              quoted_destination=TO, carrier="ups", now=1_002_000)
        self.assertEqual(record["quoted_destination"]["postal_code"], "80202")
        self.assertEqual(record["destination"]["postal_code"], "80205")
        self.assertEqual(record["quoted_amount"], 642)
        self.assertEqual(record["actual_amount"], 910)
        self.assertTrue(record["flagged"])


class CacheIdTests(unittest.TestCase):
    """The quote row doubles as its own cache, which is only safe because it is not the audit record."""

    def test_the_same_cart_to_the_same_place_reuses_one_row(self):
        self.assertEqual(cache_id(tenant_id="t1", mode="test", cart_fingerprint="abc"),
                         cache_id(tenant_id="t1", mode="test", cart_fingerprint="abc"))

    def test_mode_and_tenant_both_separate_the_cache(self):
        base = cache_id(tenant_id="t1", mode="test", cart_fingerprint="abc")
        self.assertNotEqual(base, cache_id(tenant_id="t1", mode="live", cart_fingerprint="abc"))
        self.assertNotEqual(base, cache_id(tenant_id="t2", mode="test", cart_fingerprint="abc"))

    def test_a_different_cart_is_a_different_row(self):
        self.assertNotEqual(cache_id(tenant_id="t1", mode="test", cart_fingerprint="abc"),
                            cache_id(tenant_id="t1", mode="test", cart_fingerprint="xyz"))


class WiringTests(unittest.TestCase):
    def test_quotes_and_actuals_are_separate_document_types_in_the_carts_table(self):
        source = (ROOT / "src/stripe_link/repositories/documents.py").read_text(encoding="utf-8")
        self.assertIn('document_type="shipping_quote"', source)
        self.assertIn('document_type="shipping_actual"', source)

    def test_label_records_are_keyed_per_order_not_per_quote(self):
        # Two buyers with an identical cart and destination share one quote row -- it is the same answer --
        # but they buy two labels at two prices. Keying actuals by quote would let one overwrite the other.
        source = (ROOT / "src/stripe_link/repositories/documents.py").read_text(encoding="utf-8")
        actual_block = source.split('document_type="shipping_actual"', 1)[1][:200]
        self.assertIn('id_field="order_id"', actual_block)

    def test_checkout_may_write_the_quotes_it_mints(self):
        # Minting is a WRITE, and CheckoutFunction had no grant on CartsTable at all. Without this the
        # endpoint would 500 only once deployed -- the kind of gap local tests cannot see.
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        block = template.split("  CheckoutFunction:", 1)[1].split("      Events:", 1)[0]
        self.assertIn("DynamoDBCrudPolicy", block)
        self.assertIn("!Ref CartsTable", block)

"""Marking an order shipped without buying a label — and buying one without a sender email.

Two faults reported together on 2026-10-05, both of which left a tenant unable to tell a buyer their
parcel was on its way:

1. **"Mark shipped" was unreachable.** `MarkShippedModal.vue`, `submitShipped` and
   `POST /orders/{id}/ship` all existed and all worked. Nothing ever set `shipping` to an order, so the
   modal could not open — a complete feature with no door. A tenant who posts parcels themselves had
   nowhere to go, and neither did one whose label purchase failed.
2. **The label purchase failed** with Shippo's own words: `Attribute "address_from.email" must not be
   empty`. Shippo rejects a PURCHASE without a sender email and does not reject a RATE, so a tenant can
   price parcels all week and meet the gap only at the moment they try to post one.
"""
import pathlib
import unittest

from stripe_link.domain.shipping import sender_address

ROOT = pathlib.Path(__file__).resolve().parents[1]
ORDERS_VUE = (ROOT / "dashboard" / "src" / "components" / "Orders.vue").read_text()
MODAL_VUE = (ROOT / "dashboard" / "src" / "components" / "orders" / "MarkShippedModal.vue").read_text()
SHIPPING_PY = (ROOT / "src" / "handlers" / "shipping.py").read_text()


class TheManualPathHasADoorTests(unittest.TestCase):
    def test_something_opens_the_modal(self):
        """`shipping` was only ever assigned `null`. The modal, its handler and its endpoint were all
        reachable from each other and from nothing else."""
        self.assertIn('@click.stop="shipping = order"', ORDERS_VUE)

    def test_it_is_offered_only_while_there_is_nothing_shipped(self):
        self.assertIn('v-if="!order.fulfilment?.shipment"', ORDERS_VUE)

    def test_it_sits_beside_the_label_button(self):
        # The tenant whose label just failed is looking at exactly this cell.
        label_at = ORDERS_VUE.index(">Label</button>")
        self.assertLess(abs(ORDERS_VUE.index('shipping = order') - label_at), 900)


class TheTenantCanExplainTests(unittest.TestCase):
    """The note reaches the buyer in the tenant's own words. The backend accepted one and the email
    carried it; the form had no box, so it could only be sent by calling the API directly."""

    def test_the_modal_offers_a_note(self):
        self.assertIn('v-model.trim="form.note"', MODAL_VUE)

    def test_it_travels_with_the_submission(self):
        self.assertIn('note: ""', MODAL_VUE)

    def test_it_is_capped_where_it_is_typed_too(self):
        # The handler caps at 400; a form that lets someone type 4000 and silently truncates is a worse
        # experience than one that stops them.
        self.assertIn('maxlength="400"', MODAL_VUE)

    def test_it_is_offered_whether_or_not_the_parcel_is_late(self):
        """A parcel going out early is worth a line too, and a box that appears only on bad news is a box
        nobody finds when they want it."""
        self.assertNotIn('v-if="late"', MODAL_VUE)


class ALabelNeedsASenderEmailTests(unittest.TestCase):
    def test_the_addresss_own_email_wins(self):
        out = sender_address({"name": "X", "email": "a@b.com"}, {"email": "biz@c.com"}, "me@d.com")
        self.assertEqual(out["email"], "a@b.com")

    def test_then_the_business_email(self):
        self.assertEqual(sender_address({"name": "X"}, {"email": "biz@c.com"}, "me@d.com")["email"],
                         "biz@c.com")

    def test_then_the_account_they_sign_in_with(self):
        """All three are the seller, and a label's sender address is for the carrier to reach THEM."""
        self.assertEqual(sender_address({"name": "X"}, {}, "me@d.com")["email"], "me@d.com")

    def test_with_none_it_adds_nothing_rather_than_a_blank(self):
        self.assertNotIn("email", sender_address({"name": "X"}, {}, ""))

    def test_the_original_address_is_not_mutated(self):
        original = {"name": "X"}
        sender_address(original, {"email": "biz@c.com"})
        self.assertNotIn("email", original)

    def test_the_failure_is_named_where_it_can_be_FIXED(self):
        """Relaying "Attribute address_from.email must not be empty" tells a tenant what a carrier's API
        thinks, not what to do about it."""
        block = SHIPPING_PY.split("def buy_label", 1)[1][:4200]
        self.assertIn("ship_from_email_required", block)
        self.assertIn("Shipping screen", block)

    def test_a_missing_profile_never_raises(self):
        from handlers.shipping import _seller_contact

        class Exploding:
            def get(self, *a, **k):
                raise RuntimeError("dynamo down")

        self.assertEqual(_seller_contact("t1", Exploding()), ({}, ""))

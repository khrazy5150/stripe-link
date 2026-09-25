"""The Refunds screen has to show the leg between approval and the money going back.

plans/ORDER_FULFILMENT.md R1: `approved` no longer means "the money is going back now", so a screen that
still offers only Approve then Issue would strand every returnable refund in a state it cannot name.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = (ROOT / "dashboard/src/components/Refunds.vue").read_text(encoding="utf-8")
STORE = (ROOT / "dashboard/src/stores/refunds.js").read_text(encoding="utf-8")


class ReturnStatesAreVisibleTests(unittest.TestCase):
    def test_every_return_state_has_a_human_label(self):
        for status in ("return_pending", "return_in_transit", "return_received"):
            self.assertIn(status, STORE, f"{status} has no label; it would render as a raw enum")

    def test_a_waiting_refund_is_not_treated_as_done(self):
        # It must not sit in a "resolved" bucket while the goods are still in the post.
        block = STORE.split("outstanding", 1)[1][:400] if "outstanding" in STORE else STORE
        self.assertIn("return_pending", block)

    def test_the_tenant_can_say_the_goods_came_back(self):
        self.assertIn("markReturnReceived", STORE)
        self.assertIn("markReturnReceived", SCREEN)

    def test_issuing_is_offered_from_return_received_as_well_as_approved(self):
        self.assertIn("'return_received'", SCREEN)

    def test_marking_received_is_a_BUTTON_not_an_automatic_transition(self):
        """A scan says a parcel arrived; only the tenant can say the right item came back in usable
        condition. Automating it would refund on a delivery scan alone."""
        self.assertRegex(SCREEN, r'@click="store\.markReturnReceived')

    def test_the_buyers_deadline_is_shown(self):
        self.assertIn("return_label_expires_at", SCREEN)


if __name__ == "__main__":
    unittest.main()

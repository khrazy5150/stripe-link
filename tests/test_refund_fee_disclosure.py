"""The tenant is told, once, that a refund costs them the fees.

plans/TODO.md — "say on the refund dialog that the fees are not coming back" (author, 2026-09-14). A refunded
order debits the connected account for the FULL charge; Stripe's fee is unrecoverable and the platform's is
kept (`refund_application_fee` defaults to false, which is the decided policy: it prices refund risk to the
only party who can reduce it). On a $100 physical product that is ~$8.20 out of the tenant's pocket, and the
product said so nowhere.

It belongs on the confirm dialog and NOWHERE EARLIER. Beside a price it is a caveat the tenant cannot act on,
and the only action it suggests -- switching fee mode -- costs them more than it saves: `net_guaranteed`
earns +$8.20 per completed sale and costs +$0.71 per refunded one, break-even at a 92% refund rate.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REFUNDS = (ROOT / "dashboard" / "src" / "components" / "Refunds.vue").read_text(encoding="utf-8")
PRICING_CARD = (ROOT / "dashboard" / "src" / "components" / "shared" / "PricingCard.vue").read_text(encoding="utf-8")
TIP_FIELD = (ROOT / "dashboard" / "src" / "components" / "shared" / "TipAmountsField.vue").read_text(encoding="utf-8")


class DisclosureTests(unittest.TestCase):
    def test_the_issue_refund_dialog_says_the_fees_are_not_returned(self):
        dialog = REFUNDS.split('title="Issue refund?"', 1)[1].split("</ConfirmDialog>", 1)[0]
        self.assertIn("Stripe's fee and the Junior Bay fee are not returned", dialog)
        self.assertIn("out of your own pocket", dialog)

    def test_it_is_on_the_last_screen_before_the_money_moves(self):
        # Not on the card, not on the list: on the confirm dialog, where a replacement or a partial is still
        # a choice the tenant can make.
        self.assertIn("refund-fee-note", REFUNDS)
        before_dialog = REFUNDS.split('title="Issue refund?"', 1)[0]
        self.assertNotIn("refund-fee-note", before_dialog)

    def test_the_pricing_form_carries_no_refund_caveat(self):
        # DECIDED against (author): a refund warning beside a price is unactionable, and steering a tenant
        # away from net_guaranteed to dodge $0.71 per refund costs them $8.20 per sale.
        for name, source in (("PricingCard.vue", PRICING_CARD), ("TipAmountsField.vue", TIP_FIELD)):
            self.assertNotIn("refund", source.lower(), name)


if __name__ == "__main__":
    unittest.main()

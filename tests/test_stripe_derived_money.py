"""Stripe carries all six money components, and the ledger is checked against it.

`plans/MONEY_ACROSS_SILOS.md` P3 (the deferred metadata half) and P4 (the Stripe-derived view).

The author's requirement on 2026-10-07, after a live sale went missing: *"the ledger in our software must
match Stripe to the penny."* These tests pin the two halves of that — that Stripe holds enough to rebuild
the six components without reading our tables, and that a disagreement is reported rather than absorbed.
"""
import unittest

from stripe_link.domain import reconciliation as rec
from stripe_link.domain import shipping_cost_metadata as scm
from stripe_link.domain.fee_reconciliation import fees_from_balance_transaction


def txn(stripe_fee=362, platform_fee=770, net=11000):
    return {"net": net, "fee": stripe_fee + platform_fee,
            "fee_details": [{"type": "stripe_fee", "amount": stripe_fee},
                            {"type": "application_fee", "amount": platform_fee}]}


def charge(cid="ch_1", amount=12132, refunded=0, silo="production", livemode=True,
           balance_transaction=None, invoice=None, metadata=None):
    return {"id": cid, "livemode": livemode, "paid": True, "status": "succeeded",
            "amount_captured": amount, "amount_refunded": refunded,
            "payment_intent": f"pi_{cid}",
            "balance_transaction": txn() if balance_transaction is None else balance_transaction,
            "invoice": invoice,
            "metadata": {"silo": silo, **(metadata or {})}}


class TheFeeSplitHasOneImplementation(unittest.TestCase):
    """`txn.fee` is Stripe's fee PLUS the platform's application fee. Reading it as "the Stripe fee"
    charges the tenant for the platform's own cut, and only `fee_details` can tell them apart."""

    def test_it_separates_stripe_from_the_platform(self):
        self.assertEqual(fees_from_balance_transaction(txn()),
                         {"stripe_fee": 362, "platform_fee": 770, "net": 11000})

    def test_the_total_is_never_mistaken_for_stripes_share(self):
        self.assertNotEqual(fees_from_balance_transaction(txn())["stripe_fee"], 1132)

    def test_an_unsettled_transaction_is_absent_not_zero(self):
        """Returning zeros would let a usable estimate be overwritten with nothing."""
        self.assertEqual(fees_from_balance_transaction(None), {})
        self.assertEqual(fees_from_balance_transaction("txn_1"), {})

    def test_the_webhook_reader_still_answers_exactly_as_before(self):
        """It delegates now; its contract is {stripe_fee, net} and must not grow a platform fee, which
        `true_up_fees` deliberately leaves alone."""
        from handlers.stripe_webhook import fees_from_payment_intent
        got = fees_from_payment_intent({"latest_charge": {"balance_transaction": txn()}})
        self.assertEqual(got, {"stripe_fee": 362, "net": 11000})


class ShippingCostRidesInMetadata(unittest.TestCase):
    def test_one_key_per_label(self):
        keys = scm.stamp("shp_1a2b3c4d5e6f7a8b", 799)
        self.assertEqual(keys, {"sc_5e6f7a8b": "799"})

    def test_a_return_label_gets_its_own_prefix(self):
        """So a reconstruction can keep returns out of shipping margin exactly as `summarize` does --
        a return has no postage revenue beside it."""
        self.assertEqual(scm.stamp("shp_1a2b3c4d5e6f7a8b", 650, returning=True), {"sr_5e6f7a8b": "650"})

    def test_restamping_the_same_label_does_not_double_the_total(self):
        """The reason it is one key per label rather than a running total: a running total has to be read
        before it is written, and a retried purchase would add the same postage twice."""
        meta = {**scm.stamp("shp_aaaaaaaa1111", 799), **scm.stamp("shp_bbbbbbbb2222", 1250)}
        once = scm.from_metadata(meta)
        twice = scm.from_metadata({**meta, **scm.stamp("shp_aaaaaaaa1111", 799)})
        self.assertEqual(once["shipping_cost"], 2049)
        self.assertEqual(twice, once)

    def test_two_parcels_of_one_order_do_not_collide(self):
        """The reference is the TAIL of the id: carrier ids share a prefix, so taking the front would
        make every parcel of an order write the same key."""
        a, b = scm.stamp("shp_abcdef0000001111", 500), scm.stamp("shp_abcdef0000002222", 700)
        self.assertNotEqual(list(a), list(b))
        self.assertEqual(scm.from_metadata({**a, **b})["shipping_cost"], 1200)

    def test_a_zero_cost_label_writes_nothing(self):
        """A key saying "this parcel cost nothing" cannot be told apart from one we failed to write, and
        it spends a key against Stripe's 50-key ceiling to say it."""
        self.assertEqual(scm.stamp("shp_x1234567", 0), {})
        self.assertEqual(scm.stamp("", 799), {})

    def test_no_label_yet_is_unknown_not_free(self):
        """Every charge taken before this shipped looks exactly like this. Reporting them as costing
        nothing to post would overstate profit by precisely the postage."""
        self.assertEqual(scm.from_metadata({"silo": "production"}),
                         {"shipping_cost": 0, "outbound": 0, "returns": 0, "labels": 0, "known": False})

    def test_outbound_and_returns_are_summed_apart(self):
        meta = {**scm.stamp("shp_aaaaaaaa1111", 799), **scm.stamp("shp_aaaaaaaa1111", 650, returning=True)}
        got = scm.from_metadata(meta)
        self.assertEqual((got["outbound"], got["returns"], got["shipping_cost"]), (799, 650, 1449))


class AChargeRebuildsAllSixComponents(unittest.TestCase):
    def test_every_component_in_the_ledgers_sign_convention(self):
        """Costs negative, exactly as `ledger.sale_entry` stores them, so summing a component means the
        same thing on both sides and "up" is always good."""
        pi = {"id": "pi_ch_1", "metadata": {"cogs": "799", "sc_5e6f7a8b": "783"}}
        got = rec.components_from_charge(charge(metadata={"cogs": "799"}), payment_intent=pi)
        self.assertEqual(got["amounts"], {"gross": 12132, "stripe_fee": -362, "platform_fee": -770,
                                          "tax": 0, "cogs": -799, "shipping_cost": -783})

    def test_shipping_cost_is_read_from_the_payment_intent_not_the_charge(self):
        """A charge's metadata is a copy frozen when the charge was created; P3 writes the label's cost
        onto the PaymentIntent AFTER that, when the carrier is paid. The charge's copy can never carry
        it, so passing only the charge must say `unknown` rather than zero."""
        only_charge = rec.components_from_charge(charge(metadata={"cogs": "799"}))
        self.assertEqual(only_charge["amounts"]["shipping_cost"], 0)
        self.assertFalse(only_charge["known"]["shipping"])
        self.assertTrue(only_charge["known"]["cogs"], "COGS is stamped before the charge exists")

    def test_tax_is_unknown_without_the_session(self):
        """The plan said Stripe knows four of six; from a charge listing it knows three. `tax` lives on
        the Checkout Session, and zero is also the true answer while Stripe Tax is off -- so `known` is
        what tells a correct zero from an unasked question."""
        self.assertFalse(rec.components_from_charge(charge())["known"]["tax"])
        with_session = rec.components_from_charge(
            charge(), session={"total_details": {"amount_tax": 131}})
        self.assertTrue(with_session["known"]["tax"])
        self.assertEqual(with_session["amounts"]["tax"], 131)

    def test_a_refund_reduces_the_reconstructed_gross(self):
        got = rec.components_from_charge(charge(amount=8841, refunded=8841))
        self.assertEqual(got["amounts"]["gross"], 0)
        self.assertEqual(got["refunded"], 8841)

    def test_unsettled_fees_are_not_reported_as_zero_fees(self):
        got = rec.components_from_charge(charge(balance_transaction="txn_1"))
        self.assertFalse(got["known"]["fees"])


class TheReconstructionIsScopedToThisSilo(unittest.TestCase):
    """Both deployments hold credentials for the same connected account, so each lists the other's
    charges. Summing without the ownership filter is how production reported the sandbox silo's money
    as its own (P4, defect 2) -- a total of two silos' takings, stated confidently."""

    def test_another_silos_charge_is_not_counted(self):
        got = rec.summarize_charges(
            [charge("a", 145), charge("x", 19792, silo="sandbox")],
            mode="live", this_silo="production")
        self.assertEqual(got["charges"], 1)
        self.assertEqual(got["totals"]["gross"], 145)

    def test_profit_is_withheld_while_any_cost_is_unknown(self):
        """The same rule `ledger.summarize` applies: a profit figure that silently excludes the charges
        it could not cost is worse than no figure."""
        got = rec.summarize_charges([charge("a", 145)], mode="live", this_silo="production")
        self.assertIsNone(got["profit"])
        self.assertFalse(got["profit_known"])
        self.assertEqual(got["incomplete"]["cogs"], 1)

    def test_profit_appears_once_every_cost_is_accounted_for(self):
        pi = {"id": "pi_a", "metadata": {"cogs": "50", "sc_11112222": "20"}}
        got = rec.summarize_charges([charge("a", 1000, metadata={"cogs": "50"})],
                                    mode="live", this_silo="production",
                                    payment_intents={"pi_a": pi})
        self.assertTrue(got["profit_known"])
        # 1000 - 362 - 770 - 50 - 20 is negative, and a negative profit is a real answer.
        self.assertEqual(got["profit"], 1000 - 362 - 770 - 50 - 20)

    def test_an_uncaptured_charge_is_not_money(self):
        failed = dict(charge("a", 145), paid=False)
        self.assertEqual(rec.summarize_charges([failed], mode="live", this_silo="production")["charges"], 0)


class TheLedgerIsCheckedPerCharge(unittest.TestCase):
    """Bounded on purpose: deterministic entry ids mean a point read per charge, where a window
    comparison would read a tenant's entire financial history every five minutes and cost more the
    longer they had been successful."""

    def entry(self, gross=12132, stripe_fee=-362, platform_fee=-770):
        return {"entry_type": "sale",
                "amounts": {"gross": gross, "stripe_fee": stripe_fee, "platform_fee": platform_fee}}

    def test_an_agreeing_charge_produces_no_finding(self):
        got = rec.audit([charge()], mode="live", this_silo="production",
                        entry_for_id=lambda _id: self.entry())
        self.assertTrue(got["agrees"])
        self.assertEqual((got["examined"], got["matched"]), (1, 1))

    def test_a_wrong_gross_is_reported_with_its_direction(self):
        got = rec.audit([charge()], mode="live", this_silo="production",
                        entry_for_id=lambda _id: self.entry(gross=1213))
        self.assertFalse(got["agrees"])
        self.assertEqual(got["findings"][0]["component"], "gross")
        self.assertGreater(got["findings"][0]["drift"]["gross"], 0, "Stripe ahead = money not recorded")

    def test_a_fully_refunded_sale_that_we_did_record_is_not_drift(self):
        """The subtle half: the reconstruction nets refunds out of `gross`, the sale entry does not --
        it records what was taken, and the reversal is an entry of its own. Comparing the netted figure
        against the un-netted one made the first draft report every refunded sale as a disagreement."""
        got = rec.audit([charge(amount=8841, refunded=8841)], mode="live", this_silo="production",
                        entry_for_id=lambda _id: self.entry(gross=8841))
        self.assertTrue(got["agrees"], rec.describe(got))

    def test_a_charge_with_no_entry_is_not_reported_here(self):
        """That is the orphan pass's finding, in the same loop. Reporting it twice would double every
        alarm for one missing sale."""
        got = rec.audit([charge()], mode="live", this_silo="production", entry_for_id=lambda _id: None)
        self.assertTrue(got["agrees"])
        self.assertEqual(got["unmatched"], 1)
        self.assertEqual(got["findings"], [])

    def test_it_counts_the_charges_whose_fees_it_really_compared(self):
        """Without this counter a listing that forgot to expand `balance_transaction` looks exactly like
        a listing where everything agreed -- the fee half present in the code and absent in effect."""
        settled = rec.audit([charge()], mode="live", this_silo="production",
                            entry_for_id=lambda _id: self.entry())
        self.assertEqual(settled["fee_checked"], 1)
        unexpanded = rec.audit([charge(balance_transaction="txn_1")], mode="live",
                               this_silo="production", entry_for_id=lambda _id: self.entry())
        self.assertEqual(unexpanded["fee_checked"], 0, "the expand was missing and the tally says so")

    def test_fees_are_not_compared_until_stripe_has_settled_them(self):
        """Ours is an estimate by design and the sweep's own job is to true it up. Comparing an unsettled
        charge would report the sweep's pending work as a discrepancy, every five minutes, on every sale."""
        got = rec.audit([charge(balance_transaction="txn_1")], mode="live", this_silo="production",
                        entry_for_id=lambda _id: self.entry(stripe_fee=0, platform_fee=0))
        self.assertTrue(got["agrees"], "an estimate is a correct intermediate state")

    def test_a_settled_fee_that_disagrees_is_reported(self):
        got = rec.audit([charge()], mode="live", this_silo="production",
                        entry_for_id=lambda _id: self.entry(stripe_fee=-100))
        self.assertFalse(got["agrees"])
        self.assertEqual(got["findings"][0]["drift"]["stripe_fee"], 262)

    def test_an_unreadable_table_is_not_a_disagreement_about_money(self):
        def boom(_id):
            raise RuntimeError("DynamoDB is down")
        got = rec.audit([charge()], mode="live", this_silo="production", entry_for_id=boom)
        self.assertTrue(got["agrees"])
        self.assertEqual(got["failed"], 1)

    def test_another_silos_charge_is_never_audited(self):
        got = rec.audit([charge("x", silo="sandbox")], mode="live", this_silo="production",
                        entry_for_id=lambda _id: None)
        self.assertEqual(got["examined"], 0)


class TheEntryIdsMatchWhatTheWritersChose(unittest.TestCase):
    def test_a_checkout_charge_is_keyed_on_its_payment_intent(self):
        self.assertEqual(rec.sale_entry_ids(charge("c1")), ["le_sale_pi_c1"])

    def test_an_invoice_charge_is_asked_about_the_invoice_first(self):
        """A subscription order has no PaymentIntent field at all (P4, defect 1), so a renewal lands
        under `le_sale_order_<invoice>`; the manual invoicing path keys the same situation on the
        invoice's PaymentIntent. Both have to be asked, invoice first."""
        ids = rec.sale_entry_ids(charge("c1", invoice={"id": "in_9"}))
        self.assertEqual(ids, ["le_sale_order_in_9", "le_sale_pi_c1"])

    def test_an_invoice_given_as_a_bare_id_still_resolves(self):
        self.assertEqual(rec.sale_entry_ids(charge("c1", invoice="in_9"))[0], "le_sale_order_in_9")


class TheSummaryNamesTheWorstComponentNotTheNet(unittest.TestCase):
    """An earlier version keyed the message off `net`, which hid the case it most needed to show: a sale
    we never recorded that was later refunded nets to zero on both sides, so it printed "ahead by 0
    cents" while gross was out by the whole sale."""

    def test_it_names_the_component_that_decided_the_verdict(self):
        got = rec.audit([charge()], mode="live", this_silo="production",
                        entry_for_id=lambda _id: {"amounts": {"gross": 1213, "stripe_fee": -362,
                                                              "platform_fee": -770}})
        line = rec.describe(got)
        self.assertIn("gross", line)
        self.assertIn("Stripe is ahead", line)
        self.assertNotIn("by 0 cents", line)

    def test_agreement_reads_as_agreement(self):
        got = rec.audit([charge()], mode="live", this_silo="production",
                        entry_for_id=lambda _id: {"amounts": {"gross": 12132, "stripe_fee": -362,
                                                              "platform_fee": -770}})
        self.assertIn("agrees", rec.describe(got))

    def test_charges_we_do_not_hold_are_named_rather_than_hidden(self):
        got = rec.audit([charge()], mode="live", this_silo="production", entry_for_id=lambda _id: None)
        self.assertIn("not held here", rec.describe(got))


class TheLabelPathMirrorsItsCostToStripe(unittest.TestCase):
    """The one Stripe call `handlers/shipping.py` makes. Never raises: the label is bought and the parcel
    is going, so a bookkeeping mirror must not turn a successful purchase into an error a tenant thinks
    they should retry. The LEDGER is canonical -- a failure here costs cross-silo reconstruction only."""

    def setUp(self):
        from handlers import shipping
        self.shipping = shipping
        self.calls = []

    def mirror(self, order, shipment, **kwargs):
        return self.shipping.record_shipping_cost_metadata(
            order, shipment, "t1", mode="live",
            stripe_repo=_KeysRepo(), secret_cipher=_Cipher(),
            stripe_post=lambda *a, **k: self.calls.append((a, k)), **kwargs)

    def test_it_writes_one_flat_metadata_key_for_the_label(self):
        ok = self.mirror({"order_id": "o1", "payment_intent_id": "pi_1"},
                         {"shipment_id": "shp_1a2b3c4d5e6f7a8b", "cost": {"amount": 783}})
        self.assertTrue(ok)
        (method, path), kwargs = self.calls[0]
        self.assertEqual((method, path), ("POST", "/payment_intents/pi_1"))
        self.assertEqual(kwargs["data"], {"metadata[sc_5e6f7a8b]": "783"})

    def test_a_return_label_uses_the_return_prefix(self):
        self.mirror({"order_id": "o1", "payment_intent_id": "pi_1"},
                    {"shipment_id": "shp_1a2b3c4d5e6f7a8b", "cost": {"amount": 650}}, returning=True)
        self.assertEqual(self.calls[0][1]["data"], {"metadata[sr_5e6f7a8b]": "650"})

    def test_a_subscription_order_has_nothing_to_mirror_onto(self):
        """`order_record_from_invoice` keys on the invoice and stores no PaymentIntent field at all --
        exactly what made the orphan sweep read every renewal as lost money. A skip, not a failure."""
        self.assertFalse(self.mirror({"order_id": "order_in_9"},
                                     {"shipment_id": "shp_1a2b3c4d5e6f7a8b", "cost": {"amount": 783}}))
        self.assertEqual(self.calls, [])

    def test_a_free_label_writes_nothing(self):
        self.assertFalse(self.mirror({"order_id": "o1", "payment_intent_id": "pi_1"},
                                     {"shipment_id": "shp_1a2b3c4d5e6f7a8b", "cost": {"amount": 0}}))
        self.assertEqual(self.calls, [])

    def test_a_stripe_failure_never_reaches_the_caller(self):
        def boom(*_a, **_k):
            raise RuntimeError("stripe said no")
        got = self.shipping.record_shipping_cost_metadata(
            {"order_id": "o1", "payment_intent_id": "pi_1"},
            {"shipment_id": "shp_1a2b3c4d5e6f7a8b", "cost": {"amount": 783}},
            "t1", mode="live", stripe_repo=_KeysRepo(), secret_cipher=_Cipher(), stripe_post=boom)
        self.assertFalse(got)

    def test_an_unconfigured_tenant_is_a_skip(self):
        got = self.shipping.record_shipping_cost_metadata(
            {"order_id": "o1", "payment_intent_id": "pi_1"},
            {"shipment_id": "shp_1a2b3c4d5e6f7a8b", "cost": {"amount": 783}},
            "t1", mode="live", stripe_repo=_KeysRepo(row={}), secret_cipher=_Cipher(),
            stripe_post=lambda *a, **k: self.calls.append(a))
        self.assertFalse(got)
        self.assertEqual(self.calls, [])


class _KeysRepo:
    """A tenant on their OWN Stripe key, which is the branch of `checkout_credentials` that needs no
    platform secret -- so the test exercises real credential resolution rather than a stub of it."""

    def __init__(self, row=None):
        self.row = {"secret_key_ref": "kms:wrapped"} if row is None else row

    def get(self, _tenant_id, mode="test"):
        return self.row


class _Cipher:
    def decrypt(self, _ref, **_kwargs):
        return "sk_test_fake"


class BothLabelPathsActuallyCallIt(unittest.TestCase):
    """The defect shape this guards against is the one P4 found three times: a code path present and
    never reached. `record_return_shipping_cost_entry` existed for months while `buy_return_label`
    called nothing."""

    def source(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1]
                / "src" / "handlers" / "shipping.py").read_text()

    def test_the_outbound_path_mirrors(self):
        text = self.source()
        self.assertIn("record_shipping_cost_entry(order, saved, now=now)", text)
        self.assertIn("record_shipping_cost_metadata(order, saved, tenant_id, mode=mode, "
                      "secret_cipher=secret_cipher)", text)

    def test_the_return_path_mirrors_as_a_return(self):
        self.assertIn("record_shipping_cost_metadata(order, saved, tenant_id, mode=mode, returning=True",
                      self.source())


if __name__ == "__main__":
    unittest.main()

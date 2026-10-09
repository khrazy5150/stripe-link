"""The seller can refund from the Orders screen.

Until 2026-10-09 the only route to a refund was the CUSTOMER finding their purchase-management page and
asking, which the tenant then approved. That is the wrong default: most customers email or phone, and
the tenant had no way to act on it without talking someone through finding a link they had been sent
once, weeks earlier.

Three decisions worth keeping, each of which could reasonably have gone the other way:

- **It creates a request and executes it**, rather than calling Stripe directly. The request is the
  audit trail that the Refunds screen, the ledger entry, the reconciliation and the notification all
  hang off. A second path to the money that skipped it would leave refunds no report could see.
- **It is born approved.** Approval decides a CLAIM; a tenant clicking "Issue refund" on their own
  order has decided. Routing it through `new` would make them answer their own request elsewhere.
- **The return gate does not apply.** `can_release_refund` holds money until goods come back, and the
  person it protects is the tenant — who is the one asking.
"""
import copy
import json
import unittest

from handlers.orders import _is_refund_path, refund_order


class FakeOrders:
    def __init__(self, order=None):
        self.order = order
        self.written = []

    def get(self, _tenant, order_id):
        return self.order if self.order and self.order.get("order_id") == order_id else None

    def put(self, document):
        self.written.append(document)
        return document


class FakeRequests:
    """Stores a COPY per write, so the sequence of states is visible.

    Holding references hid the real behaviour: `_execute` writes the request a second time and mutates
    it in place, so both entries read the final status and the intermediate one was invisible.
    """

    def __init__(self):
        self.saved = []

    def put(self, document):
        self.saved.append(copy.deepcopy(document))
        return document


class FakeRefunds:
    def __init__(self):
        self.saved = []

    def put(self, document):
        self.saved.append(document)
        return document

    def find_by_stripe_refund(self, _id):
        return None


class FakeKeys:
    def get(self, *_a, **_k):
        return {"tenant_id": "t_1", "mode": "live"}


ORDER = {
    "tenant_id": "t_1", "order_id": "ord_1", "payment_intent_id": "pi_1", "mode": "live",
    "amount_total": 145, "amount_paid": 145, "amount_refunded": 0, "refund_count": 0,
    "currency": "usd", "customer": {"name": "A Buyer", "email": "buyer@example.test"},
}


def call(order=ORDER, body=None, stripe=None):
    event = {"httpMethod": "POST", "resource": "/orders/{order_id}/refund",
             "pathParameters": {"order_id": "ord_1"},
             "queryStringParameters": {"tenant_id": "t_1", "mode": "live"}}
    if body is not None:
        event["body"] = json.dumps(body)
    requests_repo, refunds_repo = FakeRequests(), FakeRefunds()
    response = refund_order(
        event, FakeOrders(order), "ord_1", "live", now_fn=lambda: 1781230000,
        requests_repo=requests_repo, refunds_repo=refunds_repo, stripe_repo=FakeKeys(),
        secret_cipher=None,
        caller=stripe or (lambda *a, **k: {"id": "re_1", "amount": 145, "status": "succeeded",
                                           "charge": "ch_1"}),
        credentials_fn=lambda *a, **k: ("sk_live_x", "acct_1"),
    )
    return response, requests_repo, refunds_repo


class TheRouteIsRecognised(unittest.TestCase):
    def test_it_matches_the_resource_template(self):
        """API Gateway sends `resource` as the TEMPLATE. The refunds handler was broken for three
        months by assuming otherwise, so this one checks the shape the gateway really sends."""
        self.assertTrue(_is_refund_path({"resource": "/orders/{order_id}/refund"}))

    def test_it_matches_a_concrete_path_too(self):
        self.assertTrue(_is_refund_path({"path": "/orders/ord_1/refund"}))

    def test_it_does_not_swallow_the_ship_route(self):
        self.assertFalse(_is_refund_path({"resource": "/orders/{order_id}/ship"}))


class ItRefundsThroughTheNormalPipeline(unittest.TestCase):
    def test_the_money_goes_back(self):
        response, _requests, refunds = call()
        self.assertEqual(response["statusCode"], 200, response.get("body"))
        self.assertTrue(refunds.saved, "the refund must be recorded, not just sent to Stripe")

    def test_a_request_is_written_as_the_audit_trail(self):
        _response, requests, _refunds = call()
        self.assertTrue(requests.saved)
        request = requests.saved[0]
        self.assertEqual(request["order_id"], "ord_1")
        self.assertEqual(request["document_type"], "refund_request")

    def test_it_ends_at_refunded(self):
        """`_execute` writes it again with the outcome, which is the state the Refunds screen shows."""
        _r, requests, _f = call()
        self.assertEqual(requests.saved[-1]["status"], "refunded")

    def test_it_is_marked_as_the_sellers_doing(self):
        """So a report can tell a refund the seller chose from one a customer asked for."""
        _r, requests, _f = call()
        self.assertEqual(requests.saved[0]["initiated_by"], "tenant")

    def test_it_never_sits_at_new_waiting_for_its_own_author(self):
        """Approval decides a CLAIM. A seller refunding their own order has decided, so the request
        must not land in the queue for them to answer on another screen."""
        _r, requests, _f = call()
        self.assertNotIn("new", [s["status"] for s in requests.saved[1:]],
                         "after approval it must never be back at `new`")

    def test_a_download_needs_no_return_so_the_money_goes_straight_back(self):
        _r, requests, refunds = call()
        self.assertFalse(requests.saved[-1]["policy_snapshot"]["return_required"])
        self.assertTrue(refunds.saved, "nothing to wait for, so it should have refunded")

    def test_the_sellers_reason_is_recorded_when_given(self):
        _r, requests, _f = call(body={"reason": "Customer phoned"})
        self.assertEqual(requests.saved[0].get("reason"), "Customer phoned")


class ItRefusesWhatItCannotRefund(unittest.TestCase):
    def test_an_unknown_order_is_404_not_a_stripe_call(self):
        called = []
        response, requests, _f = call(order=None, stripe=lambda *a, **k: called.append(1) or {})
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(called, [], "Stripe must not be asked about an order we do not have")
        self.assertEqual(requests.saved, [], "and no request should be left behind")

    def test_an_order_with_no_payment_intent_is_refused(self):
        response, _requests, refunds = call(order={**ORDER, "payment_intent_id": ""})
        self.assertGreaterEqual(response["statusCode"], 400)
        self.assertEqual(refunds.saved, [])


class TheOrdersScreenOffersIt(unittest.TestCase):
    """Source-level, because the dashboard has no JS test runner."""

    @staticmethod
    def _source():
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1]
                / "dashboard" / "src" / "components" / "Orders.vue").read_text()

    def test_the_button_exists_and_posts_to_the_refund_route(self):
        source = self._source()
        self.assertIn("Issue refund", source)
        self.assertIn("/refund", source)
        self.assertIn('method: "POST"', source)

    def test_it_is_behind_a_confirmation(self):
        """It moves real money, cannot be undone, and sits one row from "Mark shipped"."""
        source = self._source()
        self.assertIn("ConfirmDialog", source)
        self.assertIn("pendingRefund", source)

    def test_it_is_hidden_for_an_order_with_nothing_left_to_return(self):
        source = self._source()
        self.assertIn("canRefund", source)
        self.assertIn("amount_refunded", source)

    def test_a_failure_is_shown_rather_than_swallowed(self):
        """An error assigned and never rendered is how a refusal becomes a button that does nothing.
        This was written that way first."""
        source = self._source()
        self.assertIn("refundError", source)
        self.assertIn("{{ refundError }}", source)

    def test_the_screen_reloads_rather_than_patching_the_row(self):
        """A refund also moves the ledger, the order aggregates and the Refunds queue."""
        source = self._source()
        issue = source[source.index("async function issueRefund"):]
        self.assertIn("await load()", issue[:issue.index("}\n")+400])


class APhysicalOrderStillWaitsForTheGoods(unittest.TestCase):
    """The first version of this button forced `approved` and refunded immediately, which would have
    put the money back while the goods were still with the buyer.

    The two-step flow on the Refunds screen exists for exactly that, and the protection is for the
    SELLER. Collapsing it to one click is right for a download and wrong for a parcel, so the decision
    is delegated to `_approve` — the same function the Refunds screen uses — rather than assumed.
    """

    def _call_physical(self):
        class Products:
            def list_for_tenant(self, _tenant):
                return [{
                    "product_id": "prod_1", "name": "A Heavy Thing",
                    "refund_policy": {"return_method": "return_required"},
                    "fulfillment": {"requires_shipping": True},
                }]

        order = {**ORDER, "line_items": [{"product_id": "prod_1", "quantity": 1, "amount_total": 145}]}
        event = {"httpMethod": "POST", "resource": "/orders/{order_id}/refund",
                 "pathParameters": {"order_id": "ord_1"},
                 "queryStringParameters": {"tenant_id": "t_1", "mode": "live"}}
        requests_repo, refunds_repo = FakeRequests(), FakeRefunds()
        stripe_calls = []
        response = refund_order(
            event, FakeOrders(order), "ord_1", "live", now_fn=lambda: 1781230000,
            products_repo=Products(), requests_repo=requests_repo, refunds_repo=refunds_repo,
            stripe_repo=FakeKeys(), secret_cipher=None,
            caller=lambda *a, **k: stripe_calls.append(1) or {"id": "re_1"},
            credentials_fn=lambda *a, **k: ("sk_live_x", "acct_1"),
        )
        return response, requests_repo, refunds_repo, stripe_calls

    def test_the_money_does_not_move_yet(self):
        response, _requests, refunds, stripe_calls = self._call_physical()
        self.assertEqual(response["statusCode"], 200, response.get("body"))
        self.assertEqual(stripe_calls, [], "Stripe must not be called while the goods are still out")
        self.assertEqual(refunds.saved, [])

    def test_it_says_what_the_seller_has_to_do_next(self):
        response, _r, _f, _s = self._call_physical()
        body = json.loads(response["body"])
        self.assertEqual(body["refund"]["status"], "awaiting_return")
        self.assertIn("mark the return received", body["message"].lower())

    def test_the_request_records_that_a_return_is_owed(self):
        _response, requests, _f, _s = self._call_physical()
        final = requests.saved[-1]
        self.assertTrue(final["policy_snapshot"]["return_required"])
        self.assertEqual(final["status"], "return_pending")


class TheScreenStacksItsActionsAndTellsTheOutcome(unittest.TestCase):
    @staticmethod
    def _css():
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "styles.css").read_text()

    @staticmethod
    def _vue():
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1]
                / "dashboard" / "src" / "components" / "Orders.vue").read_text()

    def test_the_action_controls_stack(self):
        """Three controls in a row crowded the cell, and a destructive one inline beside two routine
        ones is easy to hit by accident."""
        block = self._css()
        start = block.index(".orders-col-actions > *")
        self.assertIn("display: block", block[start:start + 200])

    def test_the_refund_control_is_visibly_not_routine(self):
        self.assertIn(".orders-issue-refund", self._css())
        self.assertIn("--danger", self._css())

    def test_the_outcome_is_shown_to_the_seller(self):
        """Refunded now, or approved and waiting on a parcel. Saying nothing would look like it failed."""
        source = self._vue()
        self.assertIn("refundOutcome", source)
        self.assertIn("{{ refundOutcome }}", source)

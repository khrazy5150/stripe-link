"""Is the address one a carrier will actually deliver to?

The author's spec for "Not Shippable" covers physical orders whose address is incomplete **or not
deliverable**. Completeness is structural and free. Deliverability is a question only a carrier can
answer, and asking costs a provider call -- so the verdict is stored on the order and re-asked only when
the address itself changes.

Why it matters more than it looks: a carrier refusing an undeliverable address at the counter is the GOOD
case. The common one is that it accepts the parcel, fails to deliver, and returns it weeks later at the
tenant's expense, having already charged for the label.
"""
import json
import unittest

from handlers.orders import handler as orders_handler
from stripe_link.domain.address_validation import (
    DELIVERABLE,
    UNCHECKED,
    UNDELIVERABLE,
    UNKNOWN,
    address_fingerprint,
    blocking_reason,
    needs_check,
    record_validation,
    validation_state,
)
from stripe_link.domain.fulfilment import delivery_status, order_fulfilment_state

ADDRESS = {"street1": "1493 Osage St", "street2": "Apt 542-A", "city": "Denver", "state": "CO",
           "postal_code": "80204", "country": "US"}


def _order(address=ADDRESS, verdict=None, **over):
    order = {"order_id": "order_1", "tenant_id": "t1", "shipping_address": address, "line_items": [], **over}
    if verdict is not None:
        order["address_validation"] = verdict
    return order


class FingerprintTests(unittest.TestCase):
    def test_the_same_doorstep_written_differently_is_the_same_fingerprint(self):
        """Re-validating because the buyer used capitals spends a call to learn nothing."""
        loud = {**ADDRESS, "street1": "1493 OSAGE ST", "city": "DENVER"}
        spaced = {**ADDRESS, "street1": "1493  Osage   St "}
        self.assertEqual(address_fingerprint(ADDRESS), address_fingerprint(loud))
        self.assertEqual(address_fingerprint(ADDRESS), address_fingerprint(spaced))

    def test_a_real_correction_is_a_different_fingerprint(self):
        self.assertNotEqual(address_fingerprint(ADDRESS),
                            address_fingerprint({**ADDRESS, "street1": "99 New Road"}))

    def test_no_address_has_no_fingerprint(self):
        self.assertEqual(address_fingerprint({}), "")
        self.assertEqual(address_fingerprint(None), "")


class VerdictTests(unittest.TestCase):
    def test_a_deliverable_address_does_not_block(self):
        order = _order(verdict=record_validation(ADDRESS, {"valid": True}, now=100))
        self.assertEqual(validation_state(order)["status"], DELIVERABLE)
        self.assertEqual(blocking_reason(order), "")

    def test_an_undeliverable_one_blocks_and_says_why(self):
        verdict = record_validation(ADDRESS, {"valid": False, "messages": ["Street not found"]}, now=100)
        order = _order(verdict=verdict)
        self.assertEqual(validation_state(order)["status"], UNDELIVERABLE)
        self.assertIn("Street not found", blocking_reason(order))

    def test_a_provider_that_will_not_SAY_is_UNKNOWN_and_never_blocks(self):
        """"We could not check" and "a carrier will not deliver here" are different facts, and only one
        of them should stop a tenant shipping. A provider outage must not turn a whole list unshippable."""
        order = _order(verdict=record_validation(ADDRESS, {"valid": None}, now=100))
        self.assertEqual(validation_state(order)["status"], UNKNOWN)
        self.assertEqual(blocking_reason(order), "")

    def test_a_verdict_about_a_DIFFERENT_address_is_stale_and_is_not_shown(self):
        """Telling someone their corrected address is undeliverable is worse than saying nothing."""
        verdict = record_validation(ADDRESS, {"valid": False, "messages": ["bad"]}, now=100)
        corrected = _order(address={**ADDRESS, "street1": "99 New Road"}, verdict=verdict)

        state = validation_state(corrected)
        self.assertTrue(state["stale"])
        self.assertEqual(state["status"], UNCHECKED)
        self.assertEqual(blocking_reason(corrected), "")

    def test_an_unvalidated_order_is_unchecked_not_undeliverable(self):
        self.assertEqual(validation_state(_order())["status"], UNCHECKED)
        self.assertEqual(blocking_reason(_order()), "")


class NeedsCheckTests(unittest.TestCase):
    def test_an_order_with_an_address_and_no_verdict_needs_one(self):
        self.assertTrue(needs_check(_order()))

    def test_an_order_with_no_address_never_does(self):
        self.assertFalse(needs_check(_order(address={})))

    def test_an_order_already_KNOWN_undeliverable_is_not_re_asked(self):
        """The tenant has to fix the address; asking the carrier again costs money and changes nothing."""
        verdict = record_validation(ADDRESS, {"valid": False, "messages": ["bad"]}, now=100)
        self.assertFalse(needs_check(_order(verdict=verdict)))

    def test_a_corrected_address_DOES_need_re_checking(self):
        verdict = record_validation(ADDRESS, {"valid": True}, now=100)
        self.assertTrue(needs_check(_order(address={**ADDRESS, "street1": "99 New Road"}, verdict=verdict)))


class GateTests(unittest.TestCase):
    def test_an_undeliverable_address_reads_NOT_SHIPPABLE_in_the_status_column(self):
        verdict = record_validation(ADDRESS, {"valid": False, "messages": ["Street not found"]}, now=100)
        order = _order(verdict=verdict)

        state = order_fulfilment_state(order)

        self.assertEqual(state["status"], "not_shippable")
        self.assertFalse(state["eligible"])
        self.assertEqual(delivery_status(order, state)["label"], "Not Shippable")
        self.assertIn("will not deliver", delivery_status(order, state)["note"])

    def test_a_deliverable_address_is_unaffected(self):
        order = _order(verdict=record_validation(ADDRESS, {"valid": True}, now=100))
        self.assertNotEqual(order_fulfilment_state(order)["status"], "not_shippable")


class Repo:
    def __init__(self, rows=None, key="order_id"):
        self.rows = list(rows or [])
        self.key = key

    def get(self, tenant_id, doc_id=None):
        if doc_id is None:
            return self.rows[0] if self.rows else None
        return next((r for r in self.rows if r.get(self.key) == doc_id), None)

    def list_for_tenant(self, tenant_id):
        return list(self.rows)

    def put(self, document):
        self.rows = [r for r in self.rows if r.get(self.key) != document.get(self.key)] + [document]
        return document


CONFIG = {"tenant_id": "t1", "provider": {"name": "mock", "api_key_ref": ""}}


def _check(orders, config=CONFIG):
    repo = Repo(orders)
    result = orders_handler(
        {"httpMethod": "POST", "resource": "/orders/validate-addresses",
         "queryStringParameters": {"tenant_id": "t1"}, "body": "{}"},
        None, repository=repo, shipping_config_repo=Repo([config], key="tenant_id"),
        secret_cipher=type("C", (), {"decrypt": staticmethod(lambda *a, **k: "")})(),
        now_fn=lambda: 500)
    return result, repo


class EndpointTests(unittest.TestCase):
    def test_it_writes_a_verdict_onto_each_order(self):
        result, repo = _check([_order()])
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["checked"], 1)
        self.assertEqual(repo.rows[0]["address_validation"]["status"], DELIVERABLE)

    def test_an_undeliverable_street_is_recorded_as_such(self):
        bad = _order(address={**ADDRESS, "street1": "1 Invalid Way"})
        _, repo = _check([bad])
        self.assertEqual(repo.rows[0]["address_validation"]["status"], UNDELIVERABLE)

    def test_orders_with_no_address_are_not_checked(self):
        result, _ = _check([_order(address={})])
        self.assertEqual(json.loads(result["body"])["checked"], 0)

    def test_an_already_checked_order_is_not_re_checked(self):
        checked = _order(verdict=record_validation(ADDRESS, {"valid": True}, now=1))
        result, _ = _check([checked])
        self.assertEqual(json.loads(result["body"])["checked"], 0)

    def test_the_batch_is_BOUNDED_so_one_request_cannot_become_a_minute(self):
        from handlers.orders import VALIDATION_BATCH
        many = [_order(address={**ADDRESS, "street1": f"{n} Main St"}, order_id=f"o{n}")
                for n in range(VALIDATION_BATCH + 5)]
        result, _ = _check(many)
        self.assertEqual(json.loads(result["body"])["checked"], VALIDATION_BATCH)

    def test_no_provider_is_refused_rather_than_silently_doing_nothing(self):
        result, _ = _check([_order()], config={"tenant_id": "t1", "provider": {}})
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(json.loads(result["body"])["error"], "no_provider")


if __name__ == "__main__":
    unittest.main()

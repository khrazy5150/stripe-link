"""The manual path: a tenant who posted the parcel themselves, telling the buyer so.

plans/ORDER_FULFILMENT.md F2. This is not a degraded Buy Label -- it is the entire flow for a tenant who
will never connect a provider, and it must produce the same outcome for the buyer.

The trap it is built around: **USPS First-Class Mail carries no tracking**, while USPS parcel service does,
and tenants call both "first class". A required tracking number would leave the tenant who posted a padded
envelope at letter rate unable to mark their own order shipped.
"""
import json
import unittest

from handlers.orders import handler as orders_handler
from stripe_link.domain.carriers import (
    carrier_options,
    detect_carrier,
    service_has_tracking,
    tracking_url,
)
from stripe_link.domain.receipts import shipment_tracking_content
from stripe_link.domain.shipping import build_manual_shipment

ORDER = {
    "order_id": "order_1", "tenant_id": "t1", "stripe_mode": "test",
    "amount_total": 1834, "currency": "usd", "payment_status": "paid",
    "customer": {"name": "Ada", "email": "ada@example.com"},
    "shipping_address": {"name": "Ada", "street1": "1 Main", "city": "Denver", "state": "CO",
                         "postal_code": "80204", "country": "US"},
    "line_items": [{"name": "Creatine Gummies", "quantity": 1, "stripe_product_id": "prod_A"}],
}


class TrackingUrlTests(unittest.TestCase):
    def test_usps_uses_one_url_for_every_service(self):
        # First-Class, Priority and Ground Advantage all track at the same place: the SERVICE changes what
        # the buyer is told, not the link.
        first = tracking_url("usps", "9400111122223333444455")
        self.assertIn("tools.usps.com", first)
        self.assertIn("9400111122223333444455", first)

    def test_spaces_and_dashes_are_how_humans_write_numbers_down(self):
        self.assertEqual(tracking_url("usps", "9400 1111-2222"), tracking_url("usps", "940011112222"))

    def test_an_unknown_carrier_produces_NO_link_rather_than_a_broken_one(self):
        self.assertEqual(tracking_url("other", "123"), "")
        self.assertEqual(tracking_url("", "123"), "")

    def test_a_pasted_link_wins_because_it_is_the_tenant_looking_at_the_real_thing(self):
        self.assertEqual(tracking_url("other", "123", custom_url="https://track.example/123"),
                         "https://track.example/123")

    def test_a_pasted_link_that_is_not_http_is_refused(self):
        """It is rendered as an href in an email to a stranger."""
        self.assertEqual(tracking_url("other", "1", custom_url="javascript:alert(1)"), "")

    def test_no_number_means_no_link(self):
        self.assertEqual(tracking_url("usps", ""), "")


class ServiceTrackingTests(unittest.TestCase):
    def test_usps_first_class_MAIL_has_no_tracking(self):
        self.assertIs(service_has_tracking("usps", "first_class_mail"), False)

    def test_usps_parcel_service_does(self):
        self.assertIs(service_has_tracking("usps", "ground_advantage"), True)

    def test_an_unknown_service_is_UNKNOWN_not_untracked(self):
        """Telling a tenant "this has no tracking" when we simply do not know talks them out of entering a
        number they actually had."""
        self.assertIsNone(service_has_tracking("usps", "some_new_service"))
        self.assertIsNone(service_has_tracking("", ""))

    def test_a_service_can_be_named_by_key_or_by_label(self):
        self.assertIs(service_has_tracking("usps", "First-Class Mail (letter or flat)"), False)

    def test_other_sorts_last_because_it_is_the_exception_not_a_peer(self):
        self.assertEqual(carrier_options()[-1]["key"], "other")

    def test_the_escape_hatch_demands_a_pasted_url(self):
        other = [c for c in carrier_options() if c["key"] == "other"][0]
        self.assertTrue(other.get("requires_tracking_url"))


class CarrierDetectionTests(unittest.TestCase):
    """A PREFILL, never an answer: a silently wrong detection sends a buyer to the wrong website."""

    def test_ups_and_usps_and_fedex_shapes(self):
        self.assertEqual(detect_carrier("1Z999AA10123456784"), "ups")
        self.assertEqual(detect_carrier("9400111122223333444455"), "usps")
        self.assertEqual(detect_carrier("123456789012"), "fedex")

    def test_it_says_nothing_rather_than_guessing(self):
        self.assertEqual(detect_carrier("hello"), "")
        self.assertEqual(detect_carrier(""), "")
        self.assertEqual(detect_carrier("12345"), "")


class TrackingEmailTests(unittest.TestCase):
    def test_a_number_produces_a_link_and_the_number_as_text(self):
        content = shipment_tracking_content(
            business_name="Poliaxis", items="Creatine Gummies", carrier_label="USPS",
            service_label="USPS Ground Advantage", tracking_number="94001",
            tracking_url="https://tools.usps.com/x", has_tracking=True)
        self.assertIn("Track your parcel", content["html"])
        self.assertIn("94001", content["text"])

    def test_a_service_with_no_tracking_SAYS_so_and_shows_no_button(self):
        content = shipment_tracking_content(
            business_name="Poliaxis", items="Creatine Gummies", carrier_label="USPS",
            service_label="First-Class Mail (letter or flat)", has_tracking=False)
        self.assertNotIn("Track your parcel", content["html"])
        self.assertIn("does not include tracking", content["text"])

    def test_an_UNKNOWN_service_says_neither(self):
        """We do not know there is no tracking; the tenant may just not have typed it. Claiming otherwise
        is a second kind of lie."""
        content = shipment_tracking_content(business_name="Poliaxis", items="Gummies")
        self.assertNotIn("Track your parcel", content["html"])
        self.assertNotIn("does not include tracking", content["text"])
        self.assertIn("on its way", content["text"])

    def test_the_carrier_is_not_repeated_when_the_service_already_names_it(self):
        content = shipment_tracking_content(items="Gummies", carrier_label="USPS",
                                            service_label="USPS Ground Advantage")
        self.assertIn("Sent via USPS Ground Advantage.", content["text"])
        self.assertNotIn("USPS USPS", content["text"])
        self.assertNotIn("USPS via", content["text"])


class ManualShipmentTests(unittest.TestCase):
    def test_a_parcel_with_no_tracking_number_is_a_complete_record(self):
        shipment = build_manual_shipment(order=ORDER, carrier="usps", service="first_class_mail", now=100)
        self.assertEqual(shipment["status"], "shipped")
        self.assertEqual(shipment["provider"], "manual")
        self.assertEqual(shipment["tracking_number"], "")

    def test_the_id_is_derived_so_marking_shipped_twice_cannot_make_two_records(self):
        a = build_manual_shipment(order=ORDER, now=1)
        b = build_manual_shipment(order=ORDER, now=2)
        self.assertEqual(a["shipment_id"], b["shipment_id"])

    def test_the_destination_is_snapshotted(self):
        shipment = build_manual_shipment(order=ORDER, now=1)
        self.assertEqual(shipment["to_address"]["city"], "Denver")

    def test_it_does_NOT_demand_a_parcel_the_way_a_label_purchase_does(self):
        """The box is already in the post. Demanding measurements would stop the tenant telling their
        customer the truth about a parcel that has demonstrably shipped."""
        shipment = build_manual_shipment(order={"order_id": "o", "tenant_id": "t"}, now=1)
        self.assertEqual(shipment["status"], "shipped")


class Repo:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def get(self, tenant_id, doc_id):
        return next((r for r in self.rows if r.get("order_id") == doc_id), None)

    def list_for_tenant(self, tenant_id):
        return list(self.rows)

    def put(self, document):
        self.rows.append(document)
        return document


def _ship(body, orders=None, shipments=None, mailer=None):
    sent = []
    result = orders_handler(
        {"httpMethod": "POST", "pathParameters": {"order_id": "order_1"},
         "queryStringParameters": {"tenant_id": "t1"}, "body": json.dumps(body)},
        None,
        repository=Repo(orders if orders is not None else [ORDER]),
        shipments_repo=shipments if shipments is not None else Repo(),
        user_profiles_repo=Repo(),
        mailer_send=mailer or (lambda **kw: sent.append(kw)),
        now_fn=lambda: 1000,
    )
    return result, sent


class MarkShippedEndpointTests(unittest.TestCase):
    def test_marking_shipped_records_it_and_emails_the_buyer(self):
        result, sent = _ship({"carrier": "usps", "service": "ground_advantage",
                              "tracking_number": "9400111122223333444455"})
        self.assertEqual(result["statusCode"], 201)
        body = json.loads(result["body"])
        self.assertEqual(body["shipment"]["status"], "shipped")
        self.assertIn("tools.usps.com", body["shipment"]["tracking_url"])
        self.assertTrue(body["notification"]["sent"])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["to_address"], "ada@example.com")

    def test_no_tracking_number_is_accepted(self):
        result, sent = _ship({"carrier": "usps", "service": "first_class_mail"})
        self.assertEqual(result["statusCode"], 201)
        self.assertIn("does not include tracking", sent[0]["text_body"])

    def test_a_number_without_a_carrier_is_refused_because_it_cannot_become_a_link(self):
        result, sent = _ship({"tracking_number": "94001"})
        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(json.loads(result["body"])["error"], "carrier_required")
        self.assertEqual(sent, [])

    def test_a_failed_email_does_NOT_lose_the_fact_that_the_parcel_shipped(self):
        """P3 says a tracking email must never break what triggered it -- right when a label is already
        bought. Here nothing irreversible happened and the tenant pressed the button IN ORDER TO notify,
        so the shipment is still recorded AND the failure is reported so the screen can offer Resend."""
        def explode(**kwargs):
            raise RuntimeError("SES is down")

        result, _ = _ship({"carrier": "usps", "service": "ground_advantage"}, mailer=explode)

        self.assertEqual(result["statusCode"], 201)
        body = json.loads(result["body"])
        self.assertEqual(body["shipment"]["status"], "shipped")
        self.assertFalse(body["notification"]["sent"])
        self.assertIn("SES is down", body["notification"]["error"])
        self.assertIn("SES is down", body["shipment"]["notify_error"])
        self.assertNotIn("notified_at", body["shipment"])

    def test_an_order_with_no_buyer_email_is_still_shippable(self):
        order = {**ORDER, "customer": {"name": "Ada"}}
        result, sent = _ship({"carrier": "usps"}, orders=[order])
        self.assertEqual(result["statusCode"], 201)
        self.assertEqual(sent, [])
        self.assertEqual(json.loads(result["body"])["notification"]["reason"], "no_customer_email")

    def test_an_unknown_order_is_a_404(self):
        result, _ = _ship({"carrier": "usps"}, orders=[])
        self.assertEqual(result["statusCode"], 404)


class ListCarriesFulfilmentTests(unittest.TestCase):
    def test_every_order_carries_its_state_computed_on_the_SERVER(self):
        """The screen must never compute this: the row and the buy endpoint would then be able to
        disagree about eligibility, and the tenant would find out by pressing a button."""
        result = orders_handler(
            {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"}}, None,
            repository=Repo([ORDER]), products_repo=Repo(), shipments_repo=Repo(),
            shipping_config_repo=Repo())
        body = json.loads(result["body"])
        self.assertIn("fulfilment", body["orders"][0])
        self.assertIn("carriers", body)

    def test_a_shipped_order_reports_shipped(self):
        shipments = Repo([{"order_id": "order_1", "status": "shipped", "tracking_number": "94001",
                           "updated_at": 5}])
        result = orders_handler(
            {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"}}, None,
            repository=Repo([ORDER]), products_repo=Repo(), shipments_repo=shipments,
            shipping_config_repo=Repo())
        self.assertEqual(json.loads(result["body"])["orders"][0]["fulfilment"]["status"], "shipped")


if __name__ == "__main__":
    unittest.main()

"""The Sites editor's "Calculate" button: address -> coordinates.

Nothing here touches the network. `locate` takes its fetcher, so every test states exactly what the
geocoder said and asserts what we made of it.
"""
import json
import unittest

from stripe_link.domain.geocoding import GeocodeError, is_placeable, locate
from handlers import geocode


ST_GEORGE = {"street": "176 W 300 S St Apt 19", "locality": "St. George", "region": "UT",
             "postal_code": "84770", "country": "US"}

#: One Nominatim `jsonv2` result, trimmed to the fields we read.
FOUND = json.dumps([{
    "lat": "37.0965330",
    "lon": "-113.5684164",
    "display_name": "176 West 300 South, St. George, Washington County, Utah, 84770, United States",
}])


def fetcher(payload, *, record=None):
    def fetch(url):
        if record is not None:
            record.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload
    return fetch


class WhatCountsAsAnAddressTests(unittest.TestCase):
    def test_a_town_or_a_postal_code_is_enough(self):
        self.assertTrue(is_placeable({"locality": "St. George"}))
        self.assertTrue(is_placeable({"postal_code": "84770"}))

    def test_a_country_alone_is_refused_rather_than_asked_about(self):
        """THE ONE THAT MATTERS on this side.

        Nominatim answers "US" with the centroid of the United States, near Lebanon, Kansas. That is not
        a slightly imprecise shop location -- it is about an hour of sunset from either coast, and it
        comes back looking exactly like a real result, so nothing downstream could ever tell.
        """
        for address in ({"country": "US"}, {"region": "UT", "country": "US"}, {}, None, "US"):
            with self.subTest(address=address):
                self.assertFalse(is_placeable(address))
                self.assertIsNone(locate(address, fetch=fetcher(FOUND)))

    def test_an_unplaceable_address_never_reaches_the_service(self):
        """A request we know is useless is not one OpenStreetMap should be asked to answer."""
        calls = []
        locate({"country": "US"}, fetch=fetcher(FOUND, record=calls))
        self.assertEqual(calls, [])


class TheQueryTests(unittest.TestCase):
    def test_it_asks_in_structured_fields_not_as_one_string(self):
        """"St. George, UT" as free text competes with St George in Queensland, Ontario and Bermuda."""
        calls = []
        locate(ST_GEORGE, fetch=fetcher(FOUND, record=calls))
        url = calls[0]
        self.assertIn("city=St.+George", url)
        self.assertIn("state=UT", url)
        self.assertIn("postalcode=84770", url)
        self.assertIn("country=US", url)
        self.assertNotIn("q=", url)

    def test_empty_fields_are_left_out_entirely(self):
        calls = []
        locate({"locality": "Brussels", "country": "BE", "street": "", "region": None},
               fetch=fetcher(FOUND, record=calls))
        self.assertNotIn("street=", calls[0])
        self.assertNotIn("state=", calls[0])

    def test_it_asks_for_one_result(self):
        calls = []
        locate(ST_GEORGE, fetch=fetcher(FOUND, record=calls))
        self.assertIn("limit=1", calls[0])


TOWN = json.dumps([{
    "lat": "37.1098772",
    "lon": "-113.5832063",
    "display_name": "St. George, Washington County, Utah, United States",
}])


def sequence(*payloads, record=None):
    """A fetcher that answers each call with the next payload -- for the two-attempt path."""
    remaining = list(payloads)

    def fetch(url):
        if record is not None:
            record.append(url)
        return remaining.pop(0)
    return fetch


class WhenTheStreetDefeatsTheParserTests(unittest.TestCase):
    """A COMPLETE address that returns nothing is the dead end this button exists to remove.

    Probed against the live service, 2026-11-05: the real address "176 W 300 S St Apt 19, St. George UT
    84770" returns `[]` from the structured query -- the unit number and the abbreviations defeat it --
    while the same query without `street` places the town correctly.
    """

    def test_it_retries_without_the_street(self):
        calls = []
        found = locate(ST_GEORGE, fetch=sequence("[]", TOWN, record=calls))
        self.assertEqual(len(calls), 2)
        self.assertIn("street=", calls[0])
        self.assertNotIn("street=", calls[1])
        self.assertEqual(found["latitude"], 37.109877)

    def test_the_fallback_says_it_only_placed_the_AREA(self):
        """So the screen can say which it got, rather than letting the tenant assume the shop door."""
        self.assertEqual(locate(ST_GEORGE, fetch=sequence("[]", TOWN))["matched"], "area")

    def test_a_street_that_DOES_match_is_reported_as_an_address(self):
        self.assertEqual(locate(ST_GEORGE, fetch=sequence(FOUND))["matched"], "address")

    def test_an_address_with_no_street_is_area_from_the_start(self):
        found = locate({"locality": "St. George", "region": "UT", "country": "US"},
                       fetch=sequence(TOWN))
        self.assertEqual(found["matched"], "area")

    def test_the_street_is_never_cleaned_up_and_retried(self):
        """THE ONE THAT MATTERS. Stripping "Apt 19" and asking again was the obvious alternative: asked
        about "176 W 300 S" in St. George, the live service returns *Trailblazer Boulevard* in postcode
        84771. A wrong street presented as a street match is worse than a right town presented as a
        town, so what the tenant typed is either used whole or dropped whole."""
        calls = []
        locate(ST_GEORGE, fetch=sequence("[]", TOWN, record=calls))
        self.assertNotIn("300", calls[1])
        self.assertNotIn("Apt", calls[1])

    def test_it_gives_up_after_two_attempts(self):
        calls = []
        self.assertIsNone(locate(ST_GEORGE, fetch=sequence("[]", "[]", record=calls)))
        self.assertEqual(len(calls), 2)

    def test_an_address_with_no_street_is_asked_about_once(self):
        calls = []
        self.assertIsNone(locate({"locality": "Nowhereville"}, fetch=sequence("[]", record=calls)))
        self.assertEqual(len(calls), 1)


class TheAnswerTests(unittest.TestCase):
    def test_it_returns_the_coordinates_as_numbers(self):
        found = locate(ST_GEORGE, fetch=fetcher(FOUND))
        self.assertEqual(found["latitude"], 37.096533)
        self.assertEqual(found["longitude"], -113.568416)
        self.assertIsInstance(found["latitude"], float)

    def test_it_returns_the_matched_place_so_a_wrong_town_can_be_SEEN(self):
        """The label is not decoration. A geocoder does not fail loudly, it answers confidently about
        somewhere else, and the tenant is the only one who can notice."""
        self.assertIn("St. George", locate(ST_GEORGE, fetch=fetcher(FOUND))["label"])

    def test_no_match_is_None_rather_than_an_error(self):
        self.assertIsNone(locate(ST_GEORGE, fetch=fetcher("[]")))

    def test_an_impossible_coordinate_is_discarded(self):
        payload = json.dumps([{"lat": "991.0", "lon": "0.0", "display_name": "nowhere"}])
        self.assertIsNone(locate(ST_GEORGE, fetch=fetcher(payload)))

    def test_a_result_missing_coordinates_is_discarded(self):
        for payload in ('[{"display_name": "somewhere"}]', '[{"lat": "x", "lon": "y"}]', '[null]',
                        '{"lat": "1"}'):
            with self.subTest(payload=payload):
                self.assertIsNone(locate(ST_GEORGE, fetch=fetcher(payload)))

    def test_nonsense_from_the_service_is_an_error_not_a_coordinate(self):
        with self.assertRaises(GeocodeError):
            locate(ST_GEORGE, fetch=fetcher("<html>502 Bad Gateway</html>"))

    def test_the_service_being_down_raises_rather_than_returning_None(self):
        """Distinct outcomes on purpose: "no such place" is the tenant's to fix, "we could not ask" is
        not, and a single answer for both would send them editing a correct address."""
        with self.assertRaises(GeocodeError):
            locate(ST_GEORGE, fetch=fetcher(GeocodeError("connection refused")))


def event(body, tenant="tenant_1", method="POST"):
    return {
        "httpMethod": method,
        "body": json.dumps(body),
        "headers": {"X-Tenant-Id": tenant},
        "requestContext": {"authorizer": {"claims": {"custom:tenant_id": tenant}}},
    }


class TheEndpointTests(unittest.TestCase):
    def test_it_answers_with_the_coordinates_and_the_label(self):
        response = geocode.handler(event({"address": ST_GEORGE}), None,
                                   locator=lambda address: {"latitude": 37.096533,
                                                            "longitude": -113.568416,
                                                            "label": "St. George, Utah"})
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["latitude"], 37.096533)

    def test_a_bare_address_body_works_too(self):
        seen = {}

        def locator(address):
            seen.update(address)
            return {"latitude": 1.0, "longitude": 2.0, "label": "x"}

        geocode.handler(event(ST_GEORGE), None, locator=locator)
        self.assertEqual(seen["locality"], "St. George")

    def test_an_unplaceable_address_is_a_404_that_names_the_fix(self):
        response = geocode.handler(event({"address": {"country": "US"}}), None,
                                   locator=lambda address: None)
        self.assertEqual(response["statusCode"], 404)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "address_not_found")
        self.assertIn("postal code", body["message"])

    def test_the_service_being_down_is_a_502_not_a_404(self):
        """A tenant told "that address could not be placed" will edit an address that was always right."""
        def explode(address):
            raise GeocodeError("timed out")

        response = geocode.handler(event({"address": ST_GEORGE}), None, locator=explode)
        self.assertEqual(response["statusCode"], 502)
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "geocoder_unavailable")
        self.assertIn("by hand", body["message"])

    def test_it_is_not_an_open_geocoder(self):
        """No tenant, no lookup -- otherwise the path is a free geocoding proxy on our rate limit."""
        anonymous = {"httpMethod": "POST", "body": json.dumps({"address": ST_GEORGE}), "headers": {}}
        response = geocode.handler(anonymous, None, locator=lambda address: self.fail("was looked up"))
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "missing_tenant")

    def test_options_is_answered_for_cors(self):
        self.assertEqual(geocode.handler({"httpMethod": "OPTIONS"}, None)["statusCode"], 200)

    def test_get_is_refused(self):
        response = geocode.handler(event({}, method="GET"), None)
        self.assertEqual(response["statusCode"], 405)

    def test_a_broken_body_is_reported_as_such(self):
        response = geocode.handler({"httpMethod": "POST", "body": "{nope",
                                    "headers": {"X-Tenant-Id": "t"}}, None)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "invalid_body")

    def test_nothing_is_written_anywhere(self):
        """The button hands coordinates back to the FORM. A write from here would be a second writer of
        a document the Sites screen saves whole, and would store a match the tenant had not agreed to."""
        import inspect

        source = inspect.getsource(geocode)
        for forbidden in ("put(", "set_attribute", "update_item", "_repository("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

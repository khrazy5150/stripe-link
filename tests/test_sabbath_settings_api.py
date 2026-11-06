"""`GET`/`PUT /sabbath` — the settings screen's endpoint (plans/TODO.md "Sabbath mode", P2).

Two things here are worth more than the rest of the file:

* **the narrow write.** The setting lives on a document the Configuration screen saves whole, so this
  endpoint must touch exactly one attribute. A read-modify-write would take out refund policies and legal
  links, and would look like it had worked (`feedback_shared_document_read_modify_write`).
* **the preview telling the truth about a store that will never close.** Everything in `domain/sabbath`
  fails open, so an enabled setting with no coordinates is silent — no error, no closure, nothing to look
  at (`feedback_absence_reads_as_safety`). `effective` is the field that breaks that silence.
"""
import datetime
import json
import unittest
from zoneinfo import ZoneInfo

from handlers import sabbath as handler

DENVER = {"latitude": 37.0965, "longitude": -113.5684}
TROMSO = {"latitude": 69.6496, "longitude": 18.9560}


class FakeConfigRepo:
    """Records writes the way the real `SimpleKeyRepository` does: `set_attribute` and nothing else."""

    def __init__(self, document=None):
        self.document = dict(document) if document else None
        self.attribute_writes = []
        self.puts = []

    def get(self, key_value):
        return dict(self.document) if self.document is not None else None

    def set_attribute(self, key_value, name, value, seed=None):
        self.attribute_writes.append((key_value, name, value, seed or {}))
        if self.document is None:
            self.document = dict(seed or {})
        self.document[name] = value
        return value

    def put(self, document):   # pragma: no cover - a failure if it is ever called
        self.puts.append(document)
        return document


class FakeSitesRepo:
    def __init__(self, sites):
        self.sites = sites

    def list_for_tenant(self, tenant_id):
        return list(self.sites)


class FakeTenantRepo:
    def __init__(self, profile=None):
        self.profile = profile or {}

    def get(self, tenant_id, _sk):
        return dict(self.profile)


def _site(site_id, name, geo=None, timezone="America/Denver"):
    organization = {"name": name, "timezone": timezone}
    if geo:
        organization["geo"] = dict(geo)
    return {"site_id": site_id, "name": name, "organization": organization}


def _event(method="GET", body=None, mode="live"):
    event = {"httpMethod": method, "queryStringParameters": {"tenant_id": "tenant-1", "mode": mode}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _call(method="GET", body=None, document=None, sites=(), profile=None):
    config_repo = FakeConfigRepo(document)
    response = handler.handler(_event(method, body), None, repository=config_repo,
                               sites_repo=FakeSitesRepo(list(sites)),
                               tenant_repo=FakeTenantRepo(profile))
    return response, json.loads(response["body"]), config_repo


class TheReadTests(unittest.TestCase):
    def test_a_tenant_with_no_config_document_gets_the_defaults_not_a_404(self):
        """`GET /config` 404s when the document is absent, and the config table starts EMPTY -- so the
        tenant most likely to be switching this on for the first time is the one with no document. A 404
        here would have shown them an error instead of an off switch."""
        response, body, _ = _call()
        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(body["sabbath"]["enabled"])
        self.assertEqual(body["sabbath"]["before_minutes"], 18)
        self.assertEqual(body["sabbath"]["after_minutes"], 40)

    def test_the_limits_come_from_the_server(self):
        """So the maximum the screen lets a tenant type is the maximum the server keeps. A hardcoded 60
        in the dashboard is how the two come to disagree."""
        _, body, _ = _call()
        self.assertEqual(body["limits"]["max_minutes"], 60)
        self.assertEqual((body["limits"]["min_manual_hours"], body["limits"]["max_manual_hours"]), (24, 25))

    def test_it_reports_the_resolved_window_per_SITE(self):
        """The setting is the tenant's; the PLACE is the Site's. A tenant running businesses in two
        countries closes both, at two different moments."""
        document = {"sabbath": {"enabled": True, "before_minutes": 18, "after_minutes": 40}}
        _, body, _ = _call(document=document, sites=[_site("s1", "Delight Finds", DENVER)])
        self.assertEqual(len(body["sites"]), 1)
        site = body["sites"][0]
        self.assertEqual(site["name"], "Delight Finds")
        self.assertEqual(site["timezone"], "America/Denver")
        self.assertEqual(site["source"], "sundown")
        self.assertTrue(site["has_coordinates"])
        self.assertTrue(site["starts_at"] and site["ends_at"])
        self.assertTrue(body["effective"])

    def test_ENABLED_WITH_NO_COORDINATES_reports_that_nothing_will_close(self):
        """THE ONE THAT MATTERS. The gate fails open, so this tenant's store never closes and nothing
        anywhere says why. `effective: false` beside an enabled setting is the whole point of the read."""
        document = {"sabbath": {"enabled": True}}
        _, body, _ = _call(document=document, sites=[_site("s1", "Delight Finds")])
        self.assertTrue(body["sabbath"]["enabled"])
        self.assertFalse(body["effective"])
        self.assertFalse(body["sites"][0]["has_coordinates"])
        self.assertEqual(body["sites"][0]["source"], "none")

    def test_a_polar_site_is_distinguished_from_one_with_no_location(self):
        """Two different problems with two different fixes: add coordinates, or set a manual window.
        Collapsing them into "not closing" would send a Tromso tenant to fill in a field they already had."""
        document = {"sabbath": {"enabled": True}}
        _, body, _ = _call(document=document,
                           sites=[_site("s1", "Nordlys", TROMSO, timezone="Europe/Oslo")])
        site = body["sites"][0]
        self.assertTrue(site["has_coordinates"])
        self.assertIn(site["sun_sets"], (True, False))
        if site["sun_sets"] is False:
            self.assertEqual(site["source"], "none")

    def test_no_sites_is_not_an_error(self):
        _, body, _ = _call(document={"sabbath": {"enabled": True}})
        self.assertEqual(body["sites"], [])
        self.assertFalse(body["effective"])

    def test_an_unavailable_sites_table_still_renders_the_setting(self):
        """A tenant must be able to read and change their own choice while a table they did not ask about
        is throttled. The preview degrades; the switch does not."""
        class Exploding:
            def list_for_tenant(self, tenant_id):
                raise RuntimeError("throttled")

        response = handler.handler(_event(), None, repository=FakeConfigRepo({"sabbath": {"enabled": True}}),
                                   sites_repo=Exploding(), tenant_repo=FakeTenantRepo())
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(body["sabbath"]["enabled"])
        self.assertEqual(body["sites"], [])


class TheWriteTests(unittest.TestCase):
    def test_it_writes_ONE_attribute_and_never_puts_the_document(self):
        """The Configuration screen owns this document whole. A put from here would restore this screen's
        stale copy of the refund policies over whatever Configuration had just saved."""
        document = {"document_type": "tenant_config", "tenant_id": "tenant-1",
                    "legal_defaults": {"terms_url": "https://example.com/terms"}}
        response, body, repo = _call("PUT", {"enabled": True, "before_minutes": 25, "after_minutes": 50},
                                     document=document, sites=[_site("s1", "Delight Finds", DENVER)])
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(repo.puts, [], "the whole document must never be written from here")
        self.assertEqual(len(repo.attribute_writes), 1)
        _key, name, value, _seed = repo.attribute_writes[0]
        self.assertEqual(name, "sabbath")
        self.assertEqual(value["before_minutes"], 25)
        self.assertEqual(value["after_minutes"], 50)
        self.assertEqual(repo.document["legal_defaults"]["terms_url"], "https://example.com/terms")
        self.assertTrue(body["sabbath"]["enabled"])

    def test_the_created_document_carries_the_identity_fields_a_reader_needs(self):
        """An upsert on an empty table must not leave a row that `GET /config` reads as a config with no
        document_type."""
        _, _, repo = _call("PUT", {"enabled": True})
        _key, _name, _value, seed = repo.attribute_writes[0]
        self.assertEqual(seed["document_type"], "tenant_config")
        self.assertEqual(seed["tenant_id"], "tenant-1")
        self.assertTrue(seed["schema_version"])

    def test_buffers_are_clamped_not_refused(self):
        """A tenant who types 90 means "as much as you allow", and the clamp is the gate's own, so what is
        stored is what will be enforced."""
        _, body, repo = _call("PUT", {"enabled": True, "before_minutes": 90, "after_minutes": -5})
        self.assertEqual(body["sabbath"]["before_minutes"], 60)
        self.assertEqual(body["sabbath"]["after_minutes"], 0)

    def test_zero_on_both_survives_the_save(self):
        """A real setting, not an unset value: close exactly at sundown, reopen exactly at sundown."""
        _, body, _ = _call("PUT", {"enabled": True, "before_minutes": 0, "after_minutes": 0})
        self.assertEqual((body["sabbath"]["before_minutes"], body["sabbath"]["after_minutes"]), (0, 0))

    def test_switching_it_off_stores_false_rather_than_removing_the_block(self):
        _, body, repo = _call("PUT", {"enabled": False}, document={"sabbath": {"enabled": True}})
        self.assertFalse(body["sabbath"]["enabled"])
        self.assertIn("sabbath", repo.document)

    def test_an_unusable_manual_window_is_REFUSED_not_stored(self):
        """Everything downstream fails open, so a half-filled window stored here would read to the tenant
        as "the feature does not work" with nothing to say otherwise."""
        response, body, repo = _call("PUT", {"enabled": True, "manual": {"weekday": 4}})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(body["error"], "invalid_sabbath")
        self.assertEqual(repo.attribute_writes, [])

    def test_a_manual_duration_outside_24_to_25_hours_is_refused_not_rewritten(self):
        """Caught a real disagreement. `validate_manual_window` CLAMPS the duration, so normalizing
        before validating turned "3 hours" into 24 and stored it as though the tenant had asked for it --
        while `PUT /config` refuses the same input. The lenient path would have been the one a tenant hit.

        Buffers clamp and this does not, deliberately: 90 minutes is a dial past its maximum, a 3-hour
        "Sabbath" is a different thing being configured."""
        response, body, repo = _call("PUT", {"enabled": True,
                                             "manual": {"weekday": 4, "hour": 18, "minute": 0,
                                                        "duration_hours": 3}})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(repo.attribute_writes, [], "nothing may be stored for a refused window")

    def test_a_usable_manual_window_is_normalized_and_kept(self):
        _, body, repo = _call("PUT", {"enabled": True,
                                      "manual": {"weekday": 4, "hour": 18, "minute": 30,
                                                 "duration_hours": 24.5}})
        self.assertEqual(body["sabbath"]["manual"],
                         {"weekday": 4, "hour": 18, "minute": 30, "duration_hours": 24.5})

    def test_clearing_the_manual_window_removes_it(self):
        """`null` means the tenant switched it off. Keeping it would fire the moment they moved somewhere
        the sun stops setting."""
        document = {"sabbath": {"enabled": True,
                                "manual": {"weekday": 4, "hour": 18, "minute": 0, "duration_hours": 24}}}
        _, body, _ = _call("PUT", {"enabled": True, "manual": None}, document=document)
        self.assertIsNone(body["sabbath"]["manual"])

    def test_the_save_answers_with_the_resolved_preview(self):
        """The tenant has just changed a buffer; the only useful confirmation is the window it produces."""
        _, body, _ = _call("PUT", {"enabled": True, "before_minutes": 18, "after_minutes": 40},
                           sites=[_site("s1", "Delight Finds", DENVER)])
        self.assertTrue(body["sites"][0]["starts_at"])
        self.assertTrue(body["effective"])


class TheRoutingTests(unittest.TestCase):
    def test_a_request_with_no_tenant_is_refused(self):
        response = handler.handler({"httpMethod": "GET"}, None, repository=FakeConfigRepo(),
                                   sites_repo=FakeSitesRepo([]), tenant_repo=FakeTenantRepo())
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "missing_tenant")

    def test_options_is_answered_without_a_tenant(self):
        response = handler.handler({"httpMethod": "OPTIONS"}, None, repository=FakeConfigRepo(),
                                   sites_repo=FakeSitesRepo([]), tenant_repo=FakeTenantRepo())
        self.assertEqual(response["statusCode"], 200)

    def test_delete_is_not_a_method_here(self):
        response = handler.handler(_event("DELETE"), None, repository=FakeConfigRepo(),
                                   sites_repo=FakeSitesRepo([]), tenant_repo=FakeTenantRepo())
        self.assertEqual(response["statusCode"], 405)


class TheSettingIsTheSameInBothModesTests(unittest.TestCase):
    """The closure is a fact about the person who runs the shop, so it is NOT mode-scoped -- the config
    document has no `#mode=` key. Only the SITES the preview resolves against are."""

    def test_the_same_setting_answers_in_test_and_live(self):
        document = {"sabbath": {"enabled": True}}
        bodies = []
        for mode in ("test", "live"):
            config_repo = FakeConfigRepo(document)
            response = handler.handler(_event(mode=mode), None, repository=config_repo,
                                       sites_repo=FakeSitesRepo([]), tenant_repo=FakeTenantRepo())
            bodies.append(json.loads(response["body"])["sabbath"])
        self.assertEqual(bodies[0], bodies[1])


class TheTimezoneFallbackTests(unittest.TestCase):
    def test_a_site_with_no_zone_falls_back_to_the_account_business_address(self):
        """Site before account, resolved by the same `working_day` the shipping cutoff uses."""
        site = {"site_id": "s1", "name": "Delight Finds", "organization": {"geo": DENVER}}
        _, body, _ = _call(document={"sabbath": {"enabled": True}}, sites=[site],
                           profile={"business": {"address": {"country": "US", "region": "UT"}}})
        self.assertEqual(body["sites"][0]["timezone"], "America/Denver")

    def test_an_unnamed_site_still_has_something_to_click(self):
        site = {"site_id": "s1", "organization": {}}
        _, body, _ = _call(document={"sabbath": {"enabled": True}}, sites=[site])
        self.assertEqual(body["sites"][0]["name"], "Untitled Site")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()


class TheUpdateExpressionTests(unittest.TestCase):
    """What a fake repository cannot tell you, checked against the shape DynamoDB actually accepts.

    `set_nested` was bitten by this once already — the obvious one-statement form is illegal and a fake
    that records the expression text accepts it happily. So these assert the *expression*, not the result.
    """

    class RecordingTable:
        def __init__(self):
            self.calls = []

        def update_item(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    def _repo(self):
        from stripe_link.repositories.documents import SimpleKeyRepository
        table = self.RecordingTable()
        return SimpleKeyRepository("jb-platform-config-test", key_field="tenant_id", table=table), table

    def test_the_partition_key_never_appears_in_the_expression(self):
        """DynamoDB: "Cannot update attribute tenant_id. This attribute is part of the key." It 500'd the
        first live save (dev, 2026-11-05) and every unit test passed. `update_item` writes the key from
        `Key=` on a create, so a caller naming it in `seed` is describing the row correctly."""
        repo, table = self._repo()
        repo.set_attribute("tenant-1", "sabbath", {"enabled": True},
                           {"tenant_id": "tenant-1", "document_type": "tenant_config"})
        call = table.calls[0]
        self.assertEqual(call["Key"], {"tenant_id": "tenant-1"})
        self.assertNotIn("tenant_id", call["ExpressionAttributeNames"].values())
        self.assertIn("document_type", call["ExpressionAttributeNames"].values())

    def test_one_statement_sets_the_attribute_and_seeds_the_rest_with_if_not_exists(self):
        """An UPSERT, because the config table starts empty — in dev it is entirely empty, so a
        conditional update would have refused every tenant's first save."""
        repo, table = self._repo()
        repo.set_attribute("tenant-1", "sabbath", {"enabled": True}, {"schema_version": "2026-05-29"})
        expression = table.calls[0]["UpdateExpression"]
        self.assertEqual(len(table.calls), 1)
        self.assertTrue(expression.startswith("SET #a = :v"))
        self.assertIn("if_not_exists", expression)
        self.assertNotIn("ConditionExpression", table.calls[0],
                         "a condition would refuse the tenant most likely to be saving this")

    def test_a_seed_never_overwrites_what_the_document_already_says(self):
        """`if_not_exists` on every seeded field: a seed that assigned them would restamp a document's
        schema version on every unrelated save."""
        repo, table = self._repo()
        seed = {"schema_version": "2026-05-29", "document_type": "tenant_config"}
        repo.set_attribute("tenant-1", "sabbath", {}, seed)
        # One `if_not_exists` per seeded field, and the only bare assignment is the attribute itself.
        expression = table.calls[0]["UpdateExpression"]
        self.assertEqual(expression.count("if_not_exists"), len(seed))
        self.assertEqual(expression.count("= :"), 1, "only the attribute is assigned outright")

    def test_a_missing_tenant_is_refused_before_a_write(self):
        from stripe_link.repositories.documents import RepositoryError
        repo, table = self._repo()
        with self.assertRaises(RepositoryError):
            repo.set_attribute("", "sabbath", {})
        self.assertEqual(table.calls, [])


class AFailedWriteIsReportedTests(unittest.TestCase):
    def test_a_dynamo_fault_becomes_a_502_rather_than_a_blank_500(self):
        """A store setting that silently did not save is the worst outcome of the three: the tenant
        believes their shop closes on Friday and it does not."""
        class Exploding(FakeConfigRepo):
            def set_attribute(self, *args, **kwargs):
                raise RuntimeError("ValidationException")

        response = handler.handler(_event("PUT", {"enabled": True}), None, repository=Exploding(),
                                   sites_repo=FakeSitesRepo([]), tenant_repo=FakeTenantRepo())
        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(json.loads(response["body"])["error"], "save_failed")

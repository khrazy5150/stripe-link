"""The managed-DNS endpoints (plans/MANAGED_DNS.md P3).

Three calls for three moments: create the zone and compare its import against live DNS; poll until
Cloudflare sees the delegation and then wire the serving path; hand the domain back.

The flow's shape is the thing under test. Creating a zone is NOT the irreversible step — the tenant's
nameservers still point at their old provider, so nothing on the internet has changed — which is exactly
what makes it safe to look inside the zone before asking anyone to commit. **Handing over the
nameservers is irreversible**, so that is what the mail review withholds.
"""

import json
import unittest
from unittest.mock import patch

from handlers import managed_dns_api
from stripe_link.domain.custom_domains import CustomDomainError

TENANT = "t1"
SITE = {"site_id": "site_1", "tenant_id": TENANT, "stripe_mode": "live", "name": "Quill"}
MX = {"type": "MX", "name": "example.com", "content": "aspmx.l.google.com", "priority": 1}
WEB = {"type": "A", "name": "example.com", "content": "203.0.113.1"}
ZONE = {"id": "z1", "status": "pending", "name_servers": ["kim.ns.cloudflare.com", "walt.ns.cloudflare.com"],
        "original_name_servers": ["ns-1.awsdns-01.com"]}


class FakeSites:
    def get(self, tenant_id, site_id):
        return dict(SITE) if (tenant_id, site_id) == (TENANT, "site_1") else None


class FakeZones:
    def __init__(self, seed=None):
        self.docs = {(d["tenant_id"], d["domain"]): dict(d) for d in (seed or [])}
        self.deleted = []

    def get(self, tenant_id, domain):
        d = self.docs.get((tenant_id, domain))
        return dict(d) if d else None

    def list_for_tenant(self, tenant_id):
        return [dict(d) for (t, _), d in self.docs.items() if t == tenant_id]

    def put(self, document):
        self.docs[(document["tenant_id"], document["domain"])] = dict(document)
        return document

    def delete(self, tenant_id, domain):
        self.deleted.append(domain)
        return self.docs.pop((tenant_id, domain), None)


def event(method="POST", body=None, query=None):
    return {"httpMethod": method, "pathParameters": {"site_id": "site_1"},
            "queryStringParameters": {"tenant_id": TENANT, **(query or {})},
            "body": json.dumps(body) if body is not None else None}


def body_of(response):
    return json.loads(response["body"])


class StartTests(unittest.TestCase):
    def _start(self, imported, observed, complete=True, zones=None):
        zones = zones or FakeZones()
        with patch.object(managed_dns_api, "_config", return_value=("acct", "tok", "jb-router-dev")), \
             patch.object(managed_dns_api, "create_zone", return_value=ZONE), \
             patch.object(managed_dns_api, "list_zone_dns_records", return_value=imported), \
             patch.object(managed_dns_api, "observe_mail_records", return_value=(observed, complete)):
            return managed_dns_api.start(event(body={"domain": "example.com"}), FakeSites(), "site_1",
                                         repo=zones), zones

    def test_a_clean_comparison_hands_over_the_nameservers(self):
        response, zones = self._start([WEB, MX], [WEB, MX])
        self.assertEqual(response["statusCode"], 201)
        payload = body_of(response)
        self.assertFalse(payload["review"]["blocked"])
        self.assertEqual(payload["name_servers"], ["kim.ns.cloudflare.com", "walt.ns.cloudflare.com"])
        self.assertIn((TENANT, "example.com"), zones.docs)

    def test_a_missed_mx_withholds_them(self):
        """The only irreversible step in the flow, and so the only thing the gate needs to hold back.
        The zone still exists and is still recorded — it changes nothing until the nameservers move."""
        response, zones = self._start([WEB], [WEB, MX])
        payload = body_of(response)
        self.assertTrue(payload["review"]["blocked"])
        self.assertEqual(payload["name_servers"], [])
        self.assertIn((TENANT, "example.com"), zones.docs)

    def test_a_failed_live_lookup_withholds_them_too(self):
        response, _ = self._start([WEB], [], complete=False)
        self.assertEqual(body_of(response)["name_servers"], [])
        self.assertTrue(body_of(response)["review"]["blocked"])

    def test_a_second_call_does_not_create_a_second_zone(self):
        """A tenant refreshing the page is not a request for another zone — and creating one would
        orphan the first on our account while their nameservers may already point at it."""
        seeded = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                             "status": "pending"}])
        with patch.object(managed_dns_api, "_config", return_value=("acct", "tok", "s")), \
             patch.object(managed_dns_api, "create_zone") as created:
            response = managed_dns_api.start(event(body={"domain": "example.com"}), FakeSites(),
                                             "site_1", repo=seeded)
        created.assert_not_called()
        self.assertTrue(body_of(response)["already_started"])

    def test_a_www_domain_creates_a_zone_for_the_root(self):
        """Managed DNS serves the apex AND www from one zone, so the zone is the registrable root
        whatever was typed. Asking Cloudflare for a zone literally named `www.example.com` is asking for
        something it will not create on this plan."""
        zones = FakeZones()
        with patch.object(managed_dns_api, "_config", return_value=("acct", "tok", "s")), \
             patch.object(managed_dns_api, "create_zone", return_value=ZONE) as created, \
             patch.object(managed_dns_api, "list_zone_dns_records", return_value=[]), \
             patch.object(managed_dns_api, "observe_mail_records", return_value=([], True)):
            managed_dns_api.start(event(body={"domain": "www.example.com"}), FakeSites(), "site_1",
                                  mode="live", repo=zones)
        self.assertEqual(created.call_args.args[0], "example.com")
        self.assertIn((TENANT, "example.com"), zones.docs)

    def test_an_invalid_domain_never_reaches_cloudflare(self):
        with patch.object(managed_dns_api, "_config", return_value=("acct", "tok", "s")), \
             patch.object(managed_dns_api, "create_zone") as created:
            response = managed_dns_api.start(event(body={"domain": "not a domain"}), FakeSites(),
                                             "site_1", repo=FakeZones())
        self.assertEqual(response["statusCode"], 400)
        created.assert_not_called()

    def test_an_unconfigured_environment_says_so_rather_than_half_working(self):
        with patch.object(managed_dns_api, "_config", return_value=("", "", "")):
            response = managed_dns_api.start(event(body={"domain": "example.com"}), FakeSites(),
                                             "site_1", repo=FakeZones())
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(body_of(response)["error"], "managed_dns_not_configured")


class StatusTests(unittest.TestCase):
    def _status(self, zone_status, stored_status="pending"):
        zones = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                            "status": stored_status}])
        # The Site attachment is stubbed here so these assertions are about the CLOUDFLARE wiring only;
        # it has its own tests below, and running it against the minimal fixture would test the Site
        # validator rather than this.
        with patch.object(managed_dns_api, "_config", return_value=("acct", "tok", "jb-router-dev")), \
             patch.object(managed_dns_api, "get_zone", return_value={"id": "z1", "status": zone_status}), \
             patch.object(managed_dns_api, "_attach_to_site", return_value=True), \
             patch.object(managed_dns_api, "create_dns_record") as rec, \
             patch.object(managed_dns_api, "create_worker_route") as route:
            response = managed_dns_api.status(event("GET", query={"domain": "example.com"}),
                                              FakeSites(), "site_1", mode="live", repo=zones)
        return response, rec, route, zones

    def test_pending_says_it_is_propagating_rather_than_failing(self):
        """What a tenant waits for is someone else's resolver cache. On the first real run Google and
        Quad9 had the new delegation within minutes while Cloudflare's own 1.1.1.1 still served the old
        one — reporting that as a fault would be reporting DNS working normally."""
        response, rec, route, _ = self._status("pending")
        payload = body_of(response)
        self.assertTrue(payload["propagating"])
        self.assertFalse(payload["activated"])
        rec.assert_not_called()
        route.assert_not_called()

    def test_going_active_wires_the_serving_path_once(self):
        response, rec, route, zones = self._status("active")
        payload = body_of(response)
        self.assertTrue(payload["activated"])
        self.assertFalse(payload["propagating"])
        self.assertEqual(rec.call_count, 2)                       # apex + www
        # BOTH patterns: `*.example.com/*` does not match the apex, and losing the apex route gives a
        # dead root beside a working www, which reads as a DNS fault and is not one.
        self.assertEqual([c.args[1] for c in route.call_args_list],
                         ["example.com/*", "*.example.com/*"])
        self.assertEqual(zones.docs[(TENANT, "example.com")]["status"], "active")

    def test_activation_attaches_the_domain_to_the_site(self):
        """THE HALF THAT WAS MISSING. Cloudflare records and Worker routes get a request to our edge;
        they do not tell the edge what to answer with. Without the Site attachment there is no
        custom_domain index record, and a tenant who did everything right -- zone active, certificate
        issued, nameservers changed -- gets a 404 on their own domain. That is exactly what the first
        run through the UI produced."""
        zones = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                            "status": "pending"}])
        with patch.object(managed_dns_api, "_config", return_value=("a", "t", "s")), \
             patch.object(managed_dns_api, "get_zone", return_value={"id": "z1", "status": "active"}), \
             patch.object(managed_dns_api, "create_dns_record"), \
             patch.object(managed_dns_api, "create_worker_route"), \
             patch.object(managed_dns_api, "_attach_to_site", return_value=True) as attached:
            managed_dns_api.status(event("GET", query={"domain": "example.com"}), FakeSites(),
                                   "site_1", mode="live", repo=zones)
        attached.assert_called_once()

    def test_a_failed_attachment_is_not_reported_as_activated(self):
        # Half-wired must not read as done: the zone would serve 404 while the screen said "live".
        zones = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                            "status": "pending"}])
        with patch.object(managed_dns_api, "_config", return_value=("a", "t", "s")), \
             patch.object(managed_dns_api, "get_zone", return_value={"id": "z1", "status": "active"}), \
             patch.object(managed_dns_api, "create_dns_record"), \
             patch.object(managed_dns_api, "create_worker_route"), \
             patch.object(managed_dns_api, "_attach_to_site", return_value=False):
            response = managed_dns_api.status(event("GET", query={"domain": "example.com"}),
                                              FakeSites(), "site_1", mode="live", repo=zones)
        self.assertFalse(body_of(response)["activated"])

    def test_an_already_active_zone_is_not_rewired_on_every_poll(self):
        _, rec, route, _ = self._status("active", stored_status="active")
        rec.assert_not_called()
        route.assert_not_called()

    def test_the_panel_can_find_an_in_progress_zone_without_knowing_the_domain(self):
        """What a returning tenant needs. Someone who starts the flow and closes the tab has a zone on
        our account and their nameservers already moved; asking by domain is useless because not knowing
        the domain is exactly their situation."""
        zones = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                            "status": "pending", "site_id": "site_1"}])
        with patch.object(managed_dns_api, "_config", return_value=("a", "t", "s")), \
             patch.object(managed_dns_api, "get_zone", return_value={"id": "z1", "status": "pending"}):
            response = managed_dns_api.status(event("GET"), FakeSites(), "site_1", mode="live", repo=zones)
        self.assertEqual(body_of(response)["zone"]["domain"], "example.com")

    def test_another_sites_zone_is_not_offered_up(self):
        zones = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                            "status": "pending", "site_id": "site_OTHER"}])
        with patch.object(managed_dns_api, "_config", return_value=("a", "t", "s")):
            response = managed_dns_api.status(event("GET"), FakeSites(), "site_1", mode="live", repo=zones)
        self.assertEqual(response["statusCode"], 404)

    def test_an_unknown_domain_is_a_404_not_a_crash(self):
        with patch.object(managed_dns_api, "_config", return_value=("a", "t", "s")):
            response = managed_dns_api.status(event("GET", query={"domain": "nope.com"}),
                                              FakeSites(), "site_1", mode="live", repo=FakeZones())
        self.assertEqual(response["statusCode"], 404)


class StopTests(unittest.TestCase):
    def _stop(self, export_fails=False):
        zones = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                            "status": "active",
                            "original_name_servers": ["ns-1.awsdns-01.com", "ns-2.awsdns-02.net"]}])
        lister = (CustomDomainError("Cloudflare is down") if export_fails
                  else None)
        with patch.object(managed_dns_api, "_config", return_value=("acct", "tok", "s")), \
             patch.object(managed_dns_api, "list_zone_dns_records",
                          side_effect=lister, return_value=[MX, WEB]) as listed, \
             patch.object(managed_dns_api, "_detach_from_site"), \
             patch.object(managed_dns_api, "delete_zone") as deleted:
            response = managed_dns_api.stop(event("DELETE", query={"domain": "example.com"}),
                                            FakeSites(), "site_1", mode="live", repo=zones)
        return response, deleted, zones, listed

    def test_leaving_returns_the_zone_file_and_the_old_nameservers(self):
        response, deleted, zones, _ = self._stop()
        payload = body_of(response)
        self.assertTrue(payload["deleted"])
        self.assertIn("IN\tMX\t1 aspmx.l.google.com", payload["zone_file"])
        # Their own nameservers, stored at provisioning. Without these a tenant cannot go back.
        self.assertEqual(payload["restore_name_servers"], ["ns-1.awsdns-01.com", "ns-2.awsdns-02.net"])
        deleted.assert_called_once()
        self.assertEqual(zones.deleted, ["example.com"])

    def test_leaving_also_detaches_the_site(self):
        """Deleting the zone stops the domain serving; it does not stop the SITE claiming it.

        Without this the Site goes on saying "Connected & verified", stays index-eligible, keeps a
        resolver index record pointing at a zone that no longer exists -- and the panel renders the
        custom-hostname screen instead of the managed-DNS flow, which is how it was found.
        """
        zones = FakeZones([{"tenant_id": TENANT, "domain": "example.com", "zone_id": "z1",
                            "status": "active"}])
        with patch.object(managed_dns_api, "_config", return_value=("a", "t", "s")), \
             patch.object(managed_dns_api, "list_zone_dns_records", return_value=[WEB]), \
             patch.object(managed_dns_api, "delete_zone"), \
             patch.object(managed_dns_api, "_detach_from_site") as detached:
            managed_dns_api.stop(event("DELETE", query={"domain": "example.com"}), FakeSites(),
                                 "site_1", mode="live", repo=zones)
        detached.assert_called_once()
        self.assertEqual(detached.call_args.args[0], "example.com")

    def test_a_failed_export_aborts_the_delete(self):
        """A tenant leaving must leave WITH their DNS. Deleting a zone we could not export turns 'you
        can go whenever you like' into a sentence that was only ever true on paper."""
        response, deleted, zones, _ = self._stop(export_fails=True)
        self.assertEqual(body_of(response)["error"], "export_failed")
        deleted.assert_not_called()
        self.assertEqual(zones.deleted, [])                       # still ours, still tracked


class ModeTests(unittest.TestCase):
    """`live` is a STRIPE MODE; `dev` and `prod` are deployments. Independent axes.

    `_attach_to_site` and `_detach_from_site` both re-publish the Site's pages, and a hardcoded "live"
    there would read the right documents on a live Site by luck and the wrong ones the moment that
    stopped being the only case. The mode is read from the request and threaded through.
    """

    def test_the_router_hands_the_mode_down(self):
        seen = {}
        with patch.object(managed_dns_api, "start",
                          side_effect=lambda e, r, s, mode="test", **kw: seen.setdefault("mode", mode)):
            managed_dns_api.handle(event(), FakeSites(), "site_1", "POST", "live")
        self.assertEqual(seen["mode"], "live")

    def test_nothing_in_the_module_hardcodes_a_mode(self):
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1] / "src" / "handlers"
                  / "managed_dns_api.py").read_text(encoding="utf-8")
        self.assertNotIn('mode="live"', source)
        self.assertNotIn("mode='live'", source)


class RoutingTests(unittest.TestCase):
    def test_the_sites_handler_dispatches_all_three_methods(self):
        import handlers.sites as sites

        seen = []
        with patch.object(sites, "sites_repository", return_value=FakeSites()), \
             patch("handlers.managed_dns_api.handle",
                   side_effect=lambda e, r, s, m, mode="test": seen.append(m) or {"statusCode": 200, "body": "{}"}):
            for method in ("POST", "GET", "DELETE"):
                sites.handler({"httpMethod": method, "resource": "/sites/{site_id}/managed-dns",
                               "pathParameters": {"site_id": "site_1"},
                               "queryStringParameters": {"tenant_id": TENANT}}, None)
        self.assertEqual(seen, ["POST", "GET", "DELETE"])


if __name__ == "__main__":
    unittest.main()

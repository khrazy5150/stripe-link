"""The scheduled re-check of verified custom domains (plans/DOMAIN_HEALTH_SWEEP.md).

Verification used to be one-shot, so a store could go dark while the dashboard still read
"Connected & verified". These cover the plan's definition of done: healthy is silent, unhealthy
reports once naming the record to fix, nothing is auto-disconnected, and a tenant pointing at
superseded-but-working apex IPs is not reported as broken.
"""

import unittest
from pathlib import Path

from handlers.domain_health_sweep import handler as sweep
from stripe_link.domain.custom_domains import CustomDomainError
from stripe_link.domain.domain_health import (
    HEALTHY,
    UNHEALTHY,
    domain_health_notification,
    health_record,
    hostname_health,
    should_notify,
)


def _site(domain="shop.example.com", verified=True, health=None, records=None, **over):
    site = {
        "document_type": "site",
        "tenant_id": "t1",
        "site_id": "site_1",
        "stripe_mode": "live",
        "hosting": {"custom_domain": domain, "verification": {"verified": verified}},
        "domain_provisioning": {
            "dns_records": records if records is not None else [
                {"type": "CNAME", "name": domain, "value": "domains.jbay.uk"},
                {"type": "CNAME", "name": f"_acme-challenge.{domain}", "value": "dcv.cloudflare.com"},
            ],
        },
    }
    if health is not None:
        site["domain_provisioning"]["health"] = health
    site.update(over)
    return site


class FakeSites:
    def __init__(self, sites):
        self.docs = [dict(s) for s in sites]
        self.puts = []
        self.health_writes = []

    def scan_type(self):
        return [dict(s) for s in self.docs]

    def put(self, document):            # the sweep must never reach this
        self.puts.append(document)
        return document

    def update_domain_health(self, tenant_id, document_id, health):
        self.health_writes.append((tenant_id, document_id, dict(health)))


class FakeNotifications:
    def __init__(self):
        self.docs = []

    def put(self, document):
        self.docs.append(dict(document))
        return document


ACTIVE = {"hostname": "shop.example.com", "status": "active", "ssl": {"status": "active"}}


def _run(sites, notifications=None, hostname=ACTIVE, diagnostics=None, now=1_000):
    notifications = notifications or FakeNotifications()
    return sweep(
        {"source": "aws.events"}, None,
        sites_repo=sites, notifications_repo=notifications,
        hostname_fetcher=(hostname if callable(hostname) else (lambda domain: hostname)),
        diagnoser=(lambda records: diagnostics if diagnostics is not None
                   else [{**r, "resolved": True} for r in records]),
        now_fn=lambda: now,
    ), notifications


class HostnameHealthTests(unittest.TestCase):
    def test_active_hostname_with_active_cert_is_healthy(self):
        self.assertEqual(hostname_health(ACTIVE), (HEALTHY, ""))

    def test_pending_routing_and_failed_cert_each_say_which(self):
        self.assertEqual(hostname_health({"status": "pending", "ssl": {"status": "active"}}),
                         (UNHEALTHY, "status_pending"))
        self.assertEqual(hostname_health({"status": "active", "ssl": {"status": "validation_timed_out"}}),
                         (UNHEALTHY, "ssl_validation_timed_out"))

    def test_hostname_deleted_out_from_under_us(self):
        self.assertEqual(hostname_health(None), (UNHEALTHY, "no_hostname"))


class NotifyOnceTests(unittest.TestCase):
    def test_transition_notifies_and_steady_state_does_not(self):
        self.assertTrue(should_notify(None, UNHEALTHY))
        self.assertTrue(should_notify({"state": HEALTHY}, UNHEALTHY))
        self.assertFalse(should_notify({"state": UNHEALTHY}, UNHEALTHY))

    def test_recovery_is_silent_but_re_arms(self):
        self.assertFalse(should_notify({"state": UNHEALTHY}, HEALTHY))
        recovered = health_record(HEALTHY, "", 500, {"state": UNHEALTHY, "notified_at": 100}, notified=False)
        self.assertNotIn("notified_at", recovered)          # cleared, so a later failure notifies again
        self.assertTrue(should_notify(recovered, UNHEALTHY))


class SweepTests(unittest.TestCase):
    def test_healthy_domain_is_silent(self):
        sites = FakeSites([_site()])
        result, notifications = _run(sites)
        self.assertEqual((result["checked"], result["unhealthy"], result["notified"]), (1, 0, 0))
        self.assertEqual(notifications.docs, [])
        self.assertEqual(sites.health_writes[0][2]["state"], HEALTHY)

    def test_unverified_and_domainless_sites_are_not_swept(self):
        sites = FakeSites([_site(verified=False), _site(domain=""), {"tenant_id": "t1", "site_id": "s3"}])
        result, notifications = _run(sites, hostname=None)
        self.assertEqual(result["checked"], 0)
        self.assertEqual(notifications.docs, [])

    def test_missing_routing_record_is_named_in_the_notice(self):
        sites = FakeSites([_site()])
        result, notifications = _run(
            sites, hostname={"status": "pending", "ssl": {"status": "pending_validation"}},
            diagnostics=[{"type": "CNAME", "name": "shop.example.com", "resolved": False},
                         {"type": "CNAME", "name": "_acme-challenge.shop.example.com", "resolved": True}])
        self.assertEqual((result["unhealthy"], result["notified"]), (1, 1))
        message = notifications.docs[0]["message"]
        self.assertIn("the CNAME record for shop.example.com", message)
        self.assertNotIn("_acme-challenge", message)        # only the record that actually failed

    def test_missing_dcv_record_is_named_in_the_notice(self):
        sites = FakeSites([_site()])
        _, notifications = _run(
            sites, hostname={"status": "active", "ssl": {"status": "pending_validation"}},
            diagnostics=[{"type": "CNAME", "name": "shop.example.com", "resolved": True},
                         {"type": "CNAME", "name": "_acme-challenge.shop.example.com", "resolved": False}])
        self.assertIn("_acme-challenge.shop.example.com", notifications.docs[0]["message"])

    def test_deleted_hostname_tells_them_to_reconnect(self):
        sites = FakeSites([_site()])
        _, notifications = _run(sites, hostname=None, diagnostics=[])
        self.assertIn("no longer registered", notifications.docs[0]["message"])

    def test_reports_once_not_every_day(self):
        sites = FakeSites([_site(health={"state": UNHEALTHY, "checked_at": 1, "notified_at": 1})])
        result, notifications = _run(sites, hostname=None)
        self.assertEqual((result["unhealthy"], result["notified"]), (1, 0))
        self.assertEqual(notifications.docs, [])

    def test_notice_is_keyed_on_the_site_so_it_replaces_rather_than_stacks(self):
        notice = domain_health_notification(_site(), "no_hostname", [], 1_000)
        self.assertEqual(notice["notification_id"], "notif_domain_site_1")
        self.assertEqual(notice["type"], "domain_health")
        self.assertEqual(notice["related"], {"site_id": "site_1", "domain": "shop.example.com"})

    def test_nothing_is_disconnected_unpublished_or_de_indexed(self):
        sites = FakeSites([_site()])
        _run(sites, hostname=None, diagnostics=[])
        self.assertEqual(sites.puts, [])                    # never rewrites the Site document
        for _, _, health in sites.health_writes:
            self.assertEqual(set(health) - {"state", "reason", "checked_at", "notified_at"}, set())
        self.assertTrue(sites.docs[0]["hosting"]["verification"]["verified"])

    def test_cloudflare_outage_blames_nobody(self):
        sites = FakeSites([_site()])

        def boom(domain):
            raise CustomDomainError("cloudflare 500")

        result, notifications = _run(sites, hostname=boom)
        self.assertEqual((result["checked"], result["unhealthy"], result["notified"]), (1, 0, 0))
        self.assertEqual(notifications.docs, [])
        self.assertEqual(sites.health_writes, [])           # no verdict recorded from our own outage

    def test_one_bad_site_does_not_stop_the_sweep(self):
        sites = FakeSites([_site(domain="bad.example.com"), _site(domain="good.example.com")])
        calls = []

        def fetch(domain):
            calls.append(domain)
            if domain == "bad.example.com":
                raise RuntimeError("unexpected")
            return ACTIVE

        result, _ = _run(sites, hostname=fetch)
        self.assertEqual(calls, ["bad.example.com", "good.example.com"])
        self.assertEqual(result["checked"], 2)

    def test_superseded_but_working_apex_ips_are_not_reported(self):
        # The apex-migration case the plan calls out: the tenant points at the anycast pair they were
        # given, which is no longer the pair we would hand out today. Cloudflare is serving, and
        # Cloudflare is the authority -- so nothing may look at the stored records at all. Re-deriving
        # and comparing would flag every tenant mid-migration, which is the whole population.
        sites = FakeSites([_site(records=[{"type": "A", "name": "example.com", "value": "198.51.100.9",
                                           "apex": True}])])
        notifications = FakeNotifications()

        def must_not_run(records):
            raise AssertionError("a serving domain must not have its DNS re-examined")

        result = sweep({"source": "aws.events"}, None, sites_repo=sites,
                       notifications_repo=notifications, hostname_fetcher=lambda d: ACTIVE,
                       diagnoser=must_not_run, now_fn=lambda: 1_000)
        self.assertEqual((result["checked"], result["unhealthy"], result["notified"]), (1, 0, 0))
        self.assertEqual(notifications.docs, [])

    def test_the_sweep_never_derives_the_expected_records(self):
        # Same guard, structural: the module must not reach for the record builders at all. The one that
        # tempts a future change is `custom_hostname_dns_records`, which is what connect_domain uses.
        source = (Path(__file__).resolve().parents[1] / "src" / "handlers"
                  / "domain_health_sweep.py").read_text()
        self.assertNotIn("custom_hostname_dns_records", source)
        self.assertNotIn("_apex_routing_records", source)


class DispatchTests(unittest.TestCase):
    def test_sites_handler_routes_the_scheduled_event_to_the_sweep(self):
        import handlers.sites as sites_handler

        called = {}

        import handlers.domain_health_sweep as sweep_module

        def fake(event, context):
            called["event"] = event
            return {"checked": 0}

        original = sweep_module.handler
        sweep_module.handler = fake
        try:
            result = sites_handler.handler({"source": "aws.events"}, None)
        finally:
            sweep_module.handler = original
        self.assertEqual(result, {"checked": 0})
        self.assertEqual(called["event"], {"source": "aws.events"})


if __name__ == "__main__":
    unittest.main()

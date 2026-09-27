"""An event is kept by the SILO that owns it, and the mode then picks the partition inside that silo.

Settled with the author on 2026-09-26, after two wrong readings of my own. The two axes both use the
words "dev" and "prod", which is what made it hard to say:

  SILO         sandbox | production | (staging)    one DEPLOYMENT, its own 42 tables and hostname.
                                                   `jb-orders-dev` is the SANDBOX silo's orders table.
  stripe_mode  test | live                         the money axis INSIDE a silo, in the sort key.

So a sandbox tenant's LIVE sale belongs in jb-orders-dev under ORDER#live#. An earlier version of this
file asserted routing by MODE -- live to prod, test to dev -- which would have put that sale in the
production silo's tables. That was my misreading; this is the rule.

One Connect endpoint cannot express a silo, since Stripe splits endpoints by mode. So every silo
registers its own endpoint in both modes, every endpoint receives everything, and each deployment keeps
only what resolves to itself.
"""
import unittest

from stripe_link.domain.silo_routing import BY_DEFAULT, BY_STAMP, event_belongs_here


class OwnershipTests(unittest.TestCase):
    def test_a_deployment_keeps_what_resolves_to_itself(self):
        self.assertTrue(event_belongs_here({"silo": "sandbox"}, "sandbox")[0])
        self.assertTrue(event_belongs_here({"silo": "production"}, "production")[0])

    def test_and_declines_another_silos_event(self):
        ok, why = event_belongs_here({"silo": "sandbox"}, "production")
        self.assertFalse(ok)
        self.assertIn("sandbox", why)
        self.assertIn("production", why)

    def test_MODE_does_not_decide_ownership(self):
        """The correction. A sandbox tenant's LIVE sale is still sandbox's -- it lands in jb-orders-dev
        under ORDER#live#, not in the production silo."""
        self.assertTrue(event_belongs_here({"silo": "sandbox", "mode": "live"}, "sandbox")[0])
        self.assertFalse(event_belongs_here({"silo": "sandbox", "mode": "live"}, "production")[0])

    def test_an_unresolved_event_FAILS_OPEN(self):
        """Dropping a paid order on a guess is the expensive direction: a row in the wrong table costs a
        migration, a dropped one costs a sale nobody recorded."""
        self.assertTrue(event_belongs_here({"silo": ""}, "production")[0])
        self.assertTrue(event_belongs_here({}, "production")[0])

    def test_a_deployment_that_does_not_know_its_own_silo_also_fails_open(self):
        self.assertTrue(event_belongs_here({"silo": "sandbox"}, "")[0])
        self.assertTrue(event_belongs_here({"silo": "sandbox"}, "not-a-silo")[0])


class UnstampedFallbackTests(unittest.TestCase):
    """An event with no stamp and no order we hold carries no evidence at all.

    Sending those to sandbox -- what the READ-side default says -- would put a legacy PRODUCTION tenant's
    live sale in the sandbox silo, and production would decline it, so nobody would record it. The
    fallback is the correspondence the legacy app was built on: dev meant test, prod meant live. It is
    the right one precisely because it is what every unstamped record was written under.
    """

    UNSTAMPED = {"silo": "sandbox", "source": BY_DEFAULT}

    def test_an_unstamped_LIVE_event_falls_to_production(self):
        self.assertTrue(event_belongs_here(self.UNSTAMPED, "production", "live")[0])
        self.assertFalse(event_belongs_here(self.UNSTAMPED, "sandbox", "live")[0])

    def test_an_unstamped_TEST_event_falls_to_sandbox(self):
        self.assertTrue(event_belongs_here(self.UNSTAMPED, "sandbox", "test")[0])
        self.assertFalse(event_belongs_here(self.UNSTAMPED, "production", "test")[0])

    def test_exactly_one_silo_keeps_any_given_event(self):
        """The property that matters: no event is dropped by both, and none is taken by both."""
        for source in (BY_STAMP, BY_DEFAULT):
            for silo in ("sandbox", "production"):
                for mode in ("test", "live"):
                    resolution = {"silo": silo, "source": source}
                    keepers = [d for d in ("sandbox", "production")
                               if event_belongs_here(resolution, d, mode)[0]]
                    self.assertEqual(len(keepers), 1,
                                     f"source={source} silo={silo} mode={mode} kept by {keepers}")

    def test_a_STAMPED_event_ignores_the_mode_entirely(self):
        """A sandbox tenant's live sale is sandbox's. That is the whole correction."""
        stamped = {"silo": "sandbox", "source": BY_STAMP}
        self.assertTrue(event_belongs_here(stamped, "sandbox", "live")[0])
        self.assertFalse(event_belongs_here(stamped, "production", "live")[0])


if __name__ == "__main__":
    unittest.main()

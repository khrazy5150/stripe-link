""""Enable shipping" is a real switch now, and it ticks itself.

Until 2026-10-11 the checkbox was declared in the schema, rendered on the screen, saved to the document
— and **read by nothing**. Ticking or unticking it changed no behaviour whatsoever. The second control
on that screen to be found in that state the same afternoon (`test_mode` was the first), and on a page
that decides whether real postage gets bought.

The author's design, in their words:

> "it should auto-tick when a valid Shippo key is entered and tested. The tenant should have the option
>  to untick it. Once that's done, the tenant must manually tick it back."

**The migration trap, and why there are two fields.** Every config in existence carries `enabled: false`
— the default of a checkbox nobody had reason to tick, because it did nothing. Making `false` block
shipping would have switched it off for every tenant the moment this deployed. So the gate reads
`enabled_opt_out`, which is written ONLY on a transition from on to off. Absent means "never decided"
and behaves exactly as before.
"""
import unittest

from stripe_link.domain.shipping import label_readiness, shipping_opted_out


class ADefaultFalseIsNotADecision(unittest.TestCase):
    """The whole migration rests on this distinction."""

    def test_a_config_that_was_never_decided_is_not_opted_out(self):
        self.assertFalse(shipping_opted_out({"enabled": False}))
        self.assertFalse(shipping_opted_out({}))
        self.assertFalse(shipping_opted_out(None))

    def test_only_an_explicit_opt_out_counts(self):
        self.assertTrue(shipping_opted_out({"enabled": False, "enabled_opt_out": True}))

    def test_an_untouched_legacy_config_is_not_blocked(self):
        """Every tenant carried `enabled: false` on the day this shipped. If this fails, their shipping
        stopped."""
        legacy = {"enabled": False, "provider": {"name": "mock"},
                  "ship_from_address": {"name": "A", "street1": "1 St", "city": "C", "state": "WY",
                                        "postal_code": "82009", "country": "US"}}
        self.assertNotIn("Shipping is turned off.", " ".join(label_readiness(legacy)))


class TurningItOffStopsEverything(unittest.TestCase):
    def test_readiness_says_so_and_says_nothing_else(self):
        """Listing "add a ship-from address" beside a deliberate off switch reads as a to-do list for
        something the tenant has already decided against."""
        blockers = label_readiness({"enabled_opt_out": True})
        self.assertEqual(len(blockers), 1)
        self.assertIn("Shipping is turned off", blockers[0])
        self.assertIn("Enable shipping", blockers[0], "name the control that fixes it")

    def test_the_buyer_facing_quote_is_gated_too(self):
        """The one place the switch HAS to bite, and it never calls `label_readiness`."""
        from handlers.shipping import live_rates_for
        result = live_rates_for({"enabled_opt_out": True}, "t1", parcels=[], destination={},
                                secret_cipher=None)
        self.assertEqual(result, {"options": [], "error": "shipping_off"})


class ItTicksItselfOnAProvenKey(unittest.TestCase):
    def _test_connection(self, existing, status_ok=True):
        import json

        from handlers import shipping

        class Repo:
            def __init__(self):
                self.doc = existing

            def get(self, tenant_id):
                return self.doc

            def put(self, document):
                self.doc = document
                return document

        class Cipher:
            def decrypt(self, ref, **kwargs):
                return "shippo_test_SANDBOX"

            def encrypt(self, value, **kwargs):
                return "kms:v1:" + value

        repo = Repo()
        event = {"httpMethod": "POST", "path": "/shipping/test",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "headers": {"X-Stripe-Mode": "test"}}
        shipping.handler(event, None, repository=repo, secret_cipher=Cipher())
        return repo.doc

    BASE = {
        "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
        "provider": {"name": "mock", "keys": {"test": {"api_key_ref": "kms:v1:test_ref"}}},
        "ship_from_address": {"name": "A", "street1": "1 St", "city": "Cheyenne", "state": "WY",
                              "postal_code": "82009", "country": "US"},
    }

    def test_a_successful_test_enables_shipping(self):
        """A tenant who has connected a carrier wants to ship. A second checkbox saying so is a step the
        software can infer."""
        saved = self._test_connection({**self.BASE, "enabled": False})
        self.assertTrue(saved["enabled"])

    def test_it_does_NOT_override_a_deliberate_opt_out(self):
        """The author's rule: once unticked, it must be ticked back by hand."""
        saved = self._test_connection({**self.BASE, "enabled": False, "enabled_opt_out": True})
        self.assertFalse(saved.get("enabled"))
        self.assertTrue(saved["enabled_opt_out"])


class TheOptOutIsOnlyWrittenOnARealTransition(unittest.TestCase):
    def _save(self, existing, enabled):
        from handlers.shipping import record_shipping_opt_out
        return record_shipping_opt_out({"enabled": enabled}, existing)

    def test_turning_it_off_is_remembered(self):
        self.assertTrue(self._save({"enabled": True}, False)["enabled_opt_out"])

    def test_leaving_it_off_is_not_a_decision(self):
        """Every existing config is in this state. Recording it as a choice would freeze shipping off
        for everyone on the first save after deploy -- including a tenant who only changed a box size."""
        self.assertNotIn("enabled_opt_out", self._save({"enabled": False}, False))
        self.assertNotIn("enabled_opt_out", self._save({}, False))

    def test_ticking_it_back_clears_the_opt_out(self):
        """Otherwise the switch is a trapdoor."""
        self.assertNotIn("enabled_opt_out", self._save({"enabled": False, "enabled_opt_out": True}, True))

    def test_an_existing_opt_out_survives_an_unrelated_save(self):
        """Changing a box size must not silently re-enable shipping."""
        self.assertTrue(self._save({"enabled": False, "enabled_opt_out": True}, False)["enabled_opt_out"])


class TheScreenExplainsIt(unittest.TestCase):
    import pathlib as _pathlib
    VIEW = (_pathlib.Path(__file__).resolve().parents[1]
            / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    @staticmethod
    def _words(text):
        """Whitespace collapsed: the copy is line-wrapped in the template, and a guard that breaks when
        a sentence is re-flowed is testing the indentation rather than the message."""
        return " ".join(text.split())

    def test_it_says_the_box_ticks_itself(self):
        """A control that gated nothing taught the tenant nothing. It has to say what it does."""
        self.assertIn("ticks itself when a carrier key passes its connection test",
                      self._words(self.VIEW))

    def test_it_says_an_opt_out_sticks(self):
        self.assertIn("we will not turn it back on by itself", self._words(self.VIEW))


if __name__ == "__main__":
    unittest.main()

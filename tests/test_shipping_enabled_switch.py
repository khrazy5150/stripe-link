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


class TheCheckboxMovesWithoutAReload(unittest.TestCase):
    """The server ticked it; the screen did not show it until a refresh (reported 2026-10-11).

    `/shipping/test` WRITES: it records the result and, on success, enables shipping for a tenant who
    has not opted out. Its response carries the saved config — but only `rawDoc` was updated, and the
    checkbox is bound to `form`. So the box stayed visibly unticked while the server said otherwise,
    which looks exactly like the feature not working.
    """

    import pathlib as _pathlib
    VIEW = (_pathlib.Path(__file__).resolve().parents[1]
            / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    def test_the_test_response_is_adopted_into_the_form(self):
        self.assertIn("adoptSavedConfig(body.shipping_config)", self.VIEW)
        self.assertIn("form.enabled = config.enabled", self.VIEW)

    def test_a_failed_test_adopts_it_too(self):
        """A failure is an answer, and the server's view of `enabled` is still authoritative."""
        self.assertIn("adoptSavedConfig(err.body.shipping_config)", self.VIEW)

    def test_it_does_not_swallow_unsaved_edits(self):
        """A test is not a save. Adopting the whole document would discard whatever the tenant has
        typed into the dozen other fields on this screen for pressing a button meant to check a key."""
        body = self.VIEW[self.VIEW.index("function adoptSavedConfig"):]
        body = body[:body.index("\n}") + 2]
        assignments = [line for line in body.splitlines() if "form." in line and "=" in line]
        self.assertEqual(len(assignments), 1, f"only `enabled` may be adopted: {assignments}")


class TheScreenSaysWHYItIsOff(unittest.TestCase):
    """Off because nobody turned it on, and off because somebody turned it OFF, are different states
    with different fixes — and the hint said "this ticks itself when a carrier key passes its connection
    test" in both.

    That sentence is FALSE for a tenant who opted out, and it sent the author re-entering a Shippo key
    and re-testing it because the software told them that would work (reported 2026-10-11). The system
    was behaving exactly as specified; the screen was lying about it.
    """

    import pathlib as _pathlib
    VIEW = (_pathlib.Path(__file__).resolve().parents[1]
            / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    @staticmethod
    def _words(text):
        return " ".join(text.split())

    def test_an_opted_out_tenant_is_told_they_did_it(self):
        self.assertIn("Shipping is off because you turned it off", self._words(self.VIEW))

    def test_and_told_that_testing_a_key_will_not_fix_it(self):
        """The precise correction: the other branch's promise does not apply to them."""
        self.assertIn("testing a carrier key will not do it", self._words(self.VIEW))

    def test_the_auto_tick_promise_is_only_made_where_it_is_true(self):
        """It must sit in the branch for a tenant who has NOT opted out."""
        # Just THAT branch: from its opening template to the first closing one. Slicing to `</p>`
        # overshot into the `v-else` and swept up the very sentence being checked for.
        block = self.VIEW[self.VIEW.index('v-else-if="shippingOptedOut"'):]
        block = block[:block.index("</template>")]
        self.assertNotIn("ticks itself", block,
                         "the auto-tick promise must not appear in the opted-out branch")

    def test_the_flag_reaches_the_browser(self):
        """A hint keyed on a field the server never returns is a hint that never fires."""
        from handlers.shipping import redact_shipping_config
        redacted = redact_shipping_config({"enabled": False, "enabled_opt_out": True,
                                           "provider": {"name": "shippo"}})
        self.assertTrue(redacted["enabled_opt_out"])


class TickingItBackRestoresEverything(unittest.TestCase):
    """The switch must not be a trapdoor: one click returns a tenant to normal service, including the
    auto-tick they had turned off."""

    def test_ticking_clears_the_opt_out_and_re_arms_the_auto_tick(self):
        from handlers.shipping import record_shipping_opt_out
        from stripe_link.domain.shipping import shipping_opted_out

        opted_out = {"enabled": False, "enabled_opt_out": True}
        after = record_shipping_opt_out({"enabled": True}, opted_out)
        self.assertNotIn("enabled_opt_out", after)
        self.assertFalse(shipping_opted_out(after), "a later connection test may tick it again")


if __name__ == "__main__":
    unittest.main()


class TheScreenHasNoControlsThatDoNothing(unittest.TestCase):
    """An audit, after three dead controls turned up on this one screen in an afternoon.

    Each was saved, displayed, and read by nothing — and each cost real time, because a control that
    appears to govern money behaves, to the person using it, exactly like one that does. `test_mode` sent
    the author looking for a provider test environment that does not exist;
    `auto_fulfill_after_label_purchase` told them fulfilment was optional when it is derived.

    This is the guard that turns "we found three" into "there are none".
    """

    import json as _json
    import pathlib as _pathlib
    import re as _re

    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    SCHEMA = _json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))
    SOURCE = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))

    # Structural fields every document carries; they are read by the repository, not by shipping code.
    STRUCTURAL = {"schema_version", "document_type", "tenant_id", "created_at", "updated_at"}

    def test_every_live_field_is_read_by_something(self):
        dead = []
        for field, spec in self.SCHEMA["properties"].items():
            if field in self.STRUCTURAL or spec.get("deprecated"):
                continue
            quoted = len(self._re.findall(rf'["\']{self._re.escape(field)}["\']', self.SOURCE))
            declared = len(self._re.findall(
                rf'(?:optional|require)_\w+\([^)]*["\']{self._re.escape(field)}["\']', self.SOURCE))
            if quoted - declared <= 0:
                dead.append(field)
        self.assertEqual([], dead,
                         f"declared, saved, rendered -- and read by nothing: {dead}")

    def test_the_retired_ones_are_marked_and_not_merely_deleted(self):
        """Still declared, so documents written before the audit keep validating; marked, so nobody
        wires them up again."""
        for field in ("test_mode", "auto_fulfill_after_label_purchase"):
            spec = self.SCHEMA["properties"][field]
            self.assertTrue(spec.get("deprecated"), field)
            self.assertIn("RETIRED", spec["description"], field)

    def test_retired_fields_are_dropped_on_save(self):
        """Stored documents heal the next time a tenant touches the screen -- no migration to run."""
        from handlers.shipping import drop_retired_fields
        cleaned = drop_retired_fields({"tenant_id": "t1", "test_mode": True,
                                       "auto_fulfill_after_label_purchase": False, "enabled": True})
        self.assertEqual(cleaned, {"tenant_id": "t1", "enabled": True})

    def test_the_dashboard_no_longer_sends_them(self):
        view = (self.ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")
        self.assertNotIn('v-model="form.test_mode"', view)
        self.assertNotIn('v-model="form.auto_fulfill_after_label_purchase"', view)
        self.assertNotIn("doc.auto_fulfill_after_label_purchase", view)

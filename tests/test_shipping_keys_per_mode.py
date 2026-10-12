"""One carrier credential per Stripe mode, so TEST never spends real postage.

Reported by the author 2026-10-11, and the reasons are theirs:

> "Test mode means sandbox for tenants even if we are in production. Since it's sandbox that uses
>  Shippo's test API, the labels will show as TEST LABELS, which prevents accidental real money."
>
> "Most tenants will work on Live mode and only later switch to Test. It would be a real tragedy if
>  they add a test Shippo API that overrides their live API."

`ShippingConfig` held one `provider.api_key_ref`, keyed on tenant alone, and there was no mode anywhere
in the shipping path: `shipping_config_repository()` takes no mode and `provider_for(name, api_key)` is
never given one. The dashboard's TEST/LIVE toggle moved products and orders and left the carrier key
exactly where it was. So the screen said TEST while the money path had no idea, and one slot meant the
second key you saved destroyed the first.

The `test_mode` checkbox did not help: saved, displayed, read by nothing. It could not have worked —
Shippo uses one base URL and decides the environment from the key's own prefix.
"""
import unittest

from stripe_link.domain.shipping_keys import (adopt_legacy, configured_modes, key_mismatch, key_slot,
                                              mode_of_key, normalize_mode, with_key_slot)


class SavingOneModeNeverTouchesTheOther(unittest.TestCase):
    """The author's second reason, and the one with a real victim."""

    def test_a_test_key_cannot_displace_a_live_one(self):
        provider = {"name": "shippo", "keys": {"live": {"api_key_ref": "ref_live"}}}
        after = with_key_slot(provider, "test", {"api_key_ref": "ref_test"})
        self.assertEqual(after["keys"]["live"]["api_key_ref"], "ref_live")
        self.assertEqual(after["keys"]["test"]["api_key_ref"], "ref_test")

    def test_clearing_one_mode_leaves_the_other(self):
        provider = {"name": "shippo",
                    "keys": {"live": {"api_key_ref": "ref_live"}, "test": {"api_key_ref": "ref_test"}}}
        after = with_key_slot(provider, "test", {})
        self.assertNotIn("test", after["keys"])
        self.assertEqual(after["keys"]["live"]["api_key_ref"], "ref_live")

    def test_a_live_key_is_invisible_in_test_mode(self):
        """The first reason: nothing in test mode may reach a credential that spends real money."""
        provider = {"name": "shippo", "keys": {"live": {"api_key_ref": "ref_live"}}}
        self.assertEqual(key_slot(provider, "test"), {})
        self.assertEqual(key_slot(provider, "live")["api_key_ref"], "ref_live")

    def test_the_dashboard_can_say_which_modes_are_set_up(self):
        provider = {"keys": {"live": {"api_key_ref": "r"}, "test": {}}}
        self.assertEqual(configured_modes(provider), ["live"])


class AKeyForTheWrongModeIsRefused(unittest.TestCase):
    """Shippo says which environment a key is for in the key itself, so a mismatch is catchable at the
    moment somebody can still fix it — rather than when a real label is bought in a window marked TEST."""

    def test_a_live_key_saved_under_test_is_refused(self):
        message = key_mismatch("shippo", "shippo_live_abc", "test")
        self.assertIn("live key", message)
        self.assertIn("test mode", message)

    def test_a_test_key_saved_under_live_is_refused(self):
        self.assertTrue(key_mismatch("shippo", "shippo_test_abc", "live"))

    def test_a_matching_key_is_accepted(self):
        self.assertEqual(key_mismatch("shippo", "shippo_test_abc", "test"), "")
        self.assertEqual(key_mismatch("shippo", "shippo_live_abc", "live"), "")

    def test_easypost_is_recognised_too(self):
        """Not wired yet, but the prefixes are a lookup rather than a special case, so the day it is
        wired this does not need remembering."""
        self.assertTrue(key_mismatch("easypost", "EZAKlive123", "test"))
        self.assertEqual(key_mismatch("easypost", "EZTKtest123", "test"), "")

    def test_a_provider_that_does_not_advertise_is_not_second_guessed(self):
        self.assertEqual(key_mismatch("shipstation", "anything", "test"), "")
        self.assertEqual(mode_of_key("shipstation", "anything"), "")


class APreSplitConfigIsClassifiedByItsOwnKey(unittest.TestCase):
    """An existing config has one key and no record of which environment it was for. The key usually
    knows."""

    LEGACY = {"name": "shippo", "api_key_ref": "ref", "connection_status": "connected"}

    def test_a_live_key_is_adopted_only_by_live_mode(self):
        self.assertIsNone(adopt_legacy(self.LEGACY, "test", "shippo_live_abc"))
        adopted = adopt_legacy(self.LEGACY, "live", "shippo_live_abc")
        self.assertEqual(adopted["api_key_ref"], "ref")
        self.assertEqual(adopted["connection_status"], "connected",
                         "the key has not changed, so what we knew about it still holds")

    def test_a_test_key_is_adopted_only_by_test_mode(self):
        self.assertIsNone(adopt_legacy(self.LEGACY, "live", "shippo_test_abc"))
        self.assertTrue(adopt_legacy(self.LEGACY, "test", "shippo_test_abc"))

    def test_an_unclassifiable_key_keeps_working_in_both(self):
        """Refuse only what can be POSITIVELY identified as wrong. Two earlier versions got this wrong
        in both directions: refusing everything unclassifiable stopped real shipping for anyone whose
        provider does not advertise the environment, and defaulting it to live broke the same tenants in
        test mode for a risk they may not have had."""
        unknown = {"name": "shipstation", "api_key_ref": "ref"}
        self.assertTrue(adopt_legacy(unknown, "test", "plain-key"))
        self.assertTrue(adopt_legacy(unknown, "live", "plain-key"))


class TheModeItselfFailsSafe(unittest.TestCase):
    def test_anything_not_live_is_test(self):
        for value in ("test", "", None, "TEST", "nonsense", "sandbox"):
            self.assertEqual(normalize_mode(value), "test", repr(value))

    def test_only_live_is_live(self):
        self.assertEqual(normalize_mode("live"), "live")
        self.assertEqual(normalize_mode(" LIVE "), "live")

    def test_the_default_direction_is_the_one_that_cannot_spend_money(self):
        """Same rule as `normalize_stripe_mode`. Guessing `live` on an unreadable value would be
        guessing toward buying a real label."""
        self.assertEqual(normalize_mode(object()), "test")


if __name__ == "__main__":
    unittest.main()


class TheScreenNamesTheModeItIsSaving(unittest.TestCase):
    """Static guards, in the shape of the other dashboard tests (no JS runner here).

    A field labelled just "API Key", on a screen with a TEST/LIVE toggle that used to do nothing to it,
    is how a tenant pastes a test key over their live one without ever being told that is what they are
    doing.
    """

    import pathlib as _pathlib
    VIEW = (_pathlib.Path(__file__).resolve().parents[1]
            / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    def test_the_key_field_names_the_mode(self):
        self.assertIn("API Key — {{ modeLabel }} mode", self.VIEW)

    def test_it_says_the_other_mode_is_untouched(self):
        """The reassurance that matters: a tenant must be able to see that saving here is safe."""
        self.assertIn("is saved separately and is not affected by changes here", self.VIEW)

    def test_it_says_when_the_other_mode_has_no_key(self):
        self.assertIn("switch the dashboard to", self.VIEW.lower())

    def test_configured_state_is_read_per_mode(self):
        """`keyConfigured` used to read the flat `api_key_ref`, which after the split would have said
        "Saved" in Test mode because a Live key existed."""
        body = self.VIEW[self.VIEW.index("const keyConfigured"):][:420]
        self.assertIn("getStripeMode()", body)
        self.assertIn("has_key", body)

    def test_the_dead_test_mode_checkbox_is_gone(self):
        """Saved, displayed, read by nothing server-side -- and unable to work even in principle, since
        Shippo decides the environment from the key's own prefix. A control that does nothing beside the
        control that actually decides is worse than no control."""
        self.assertNotIn('v-model="form.test_mode"', self.VIEW)
        self.assertNotIn("use the provider's test environment", self.VIEW)


class TheServerKeepsBothModesApart(unittest.TestCase):
    """The end-to-end property, through the real handler."""

    def _save(self, repository, cipher, key, mode):
        import json

        from handlers.shipping import handler
        document = {
            "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
            "provider": {"name": "shippo", "api_key_ref": key},
            "ship_from_address": {"name": "A", "street1": "1 St", "city": "Cheyenne", "state": "WY",
                                  "postal_code": "82009", "country": "US"},
        }
        return handler({"httpMethod": "PUT", "path": "/shipping", "body": json.dumps(document),
                        "headers": {"X-Stripe-Mode": mode}},
                       None, repository=repository, secret_cipher=cipher)

    def test_a_test_save_leaves_the_live_key_standing(self):
        class Repo:
            doc = None

            def get(self, tenant_id):
                return self.doc

            def put(self, document):
                self.doc = document
                return document

        class Cipher:
            def encrypt(self, value, **kwargs):
                return "kms:v1:" + value

        repo, cipher = Repo(), Cipher()
        self.assertEqual(self._save(repo, cipher, "shippo_live_REAL", "live")["statusCode"], 201)
        self.assertEqual(self._save(repo, cipher, "shippo_test_SANDBOX", "test")["statusCode"], 201)
        keys = repo.doc["provider"]["keys"]
        self.assertEqual(keys["live"]["api_key_ref"], "kms:v1:shippo_live_REAL",
                         "THE tragedy this prevents")
        self.assertEqual(keys["test"]["api_key_ref"], "kms:v1:shippo_test_SANDBOX")

    def test_a_live_key_pasted_in_test_mode_is_refused_and_nothing_is_stored(self):
        import json

        class Repo:
            doc = None

            def get(self, tenant_id):
                return self.doc

            def put(self, document):
                self.doc = document
                return document

        class Cipher:
            def encrypt(self, value, **kwargs):
                return "kms:v1:" + value

        repo = Repo()
        response = self._save(repo, Cipher(), "shippo_live_REAL", "test")
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "provider_key_mode_mismatch")
        self.assertIsNone(repo.doc)


class TestingAConnectionRecordsItAgainstTheRIGHTMode(unittest.TestCase):
    """Found on live data minutes after shipping, by the author: after testing Live and then saving a
    Test key, Live asked for a key that was sitting right there.

    `test_shipping_connection` read its config from `config_for_mode`, which FLATTENS the resolved key
    onto `provider.api_key_ref` so the twelve readers can stay as they are — a read-only shape. Writing
    it back re-introduced the flat field the split exists to remove, and recorded the result at provider
    level where the other mode reads it, so both slots stayed "untested".

    The suite did not catch it because every test of this endpoint predates the split and asserts the
    provider-level status, which is still written. This asserts the slot.
    """

    def _run(self, mode, existing):
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
                return "shippo_live_REAL" if "live" in ref else "shippo_test_SANDBOX"

            def encrypt(self, value, **kwargs):
                return "kms:v1:" + value

        repo = Repo()
        # The tenant arrives as a QUERY parameter on this endpoint, not in the body.
        event = {"httpMethod": "POST", "path": "/shipping/test",
                 "queryStringParameters": {"tenant_id": "t1"},
                 "headers": {"X-Stripe-Mode": mode}}
        shipping.handler(event, None, repository=repo, secret_cipher=Cipher())
        return repo.doc

    BOTH = {
        "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
        "provider": {"name": "shippo", "keys": {
            "live": {"api_key_ref": "kms:v1:live_ref"},
            "test": {"api_key_ref": "kms:v1:test_ref"}}},
        "ship_from_address": {"name": "A", "street1": "1 St", "city": "Cheyenne", "state": "WY",
                              "postal_code": "82009", "country": "US"},
    }

    def test_the_result_lands_in_the_tested_modes_slot(self):
        saved = self._run("live", dict(self.BOTH))
        keys = saved["provider"]["keys"]
        self.assertIn(keys["live"]["connection_status"], {"connected", "failed"},
                      "the mode that was tested records a result")
        self.assertNotIn("connection_status", keys["test"],
                         "the mode that was NOT tested is left alone")

    def test_it_does_not_reintroduce_the_flat_key(self):
        """The flattened shape is for reading. Written back, it puts a stale secret reference in the
        field the split removed -- and the live config had one within minutes."""
        saved = self._run("live", dict(self.BOTH))
        self.assertNotIn("api_key_ref", saved["provider"],
                         "config_for_mode's flattened output must never be persisted")

    def test_both_keys_survive_a_connection_test(self):
        saved = self._run("test", dict(self.BOTH))
        keys = saved["provider"]["keys"]
        self.assertEqual(keys["live"]["api_key_ref"], "kms:v1:live_ref")
        self.assertEqual(keys["test"]["api_key_ref"], "kms:v1:test_ref")

    def test_a_pre_split_key_is_migrated_when_it_is_proven(self):
        """The cheapest moment to migrate: the plaintext is in hand and the key has just been shown to
        work for this mode."""
        legacy = {
            "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
            "provider": {"name": "shippo", "api_key_ref": "kms:v1:live_ref",
                         "connection_status": "connected"},
            "ship_from_address": {"name": "A", "street1": "1 St", "city": "Cheyenne", "state": "WY",
                                  "postal_code": "82009", "country": "US"},
        }
        saved = self._run("live", legacy)
        self.assertEqual(saved["provider"]["keys"]["live"]["api_key_ref"], "kms:v1:live_ref")
        self.assertNotIn("api_key_ref", saved["provider"], "the legacy field is retired once proven")


class EveryPathThatOPENSAKeyResolvesTheMode(unittest.TestCase):
    """The per-mode split rewired twelve load sites inside `handlers/shipping.py` and missed five
    outside it.

    One of those five is the BUYER's rate quote in `handlers/checkout.py`. So the split shipped with
    landing pages stuck on "Checking rates..." for any tenant whose key had moved into a slot — while
    their own Shipping screen said "Connected" at the same moment. Found on a live page, not by the
    suite, because every test of the quote path supplies its own config fixture and never exercises the
    real loader (reported 2026-10-11).

    The commit message for the split claimed "one seam". It was one seam in one module.
    """

    import pathlib as _pathlib
    import re as _re

    ROOT = _pathlib.Path(__file__).resolve().parents[1]

    def _module(self, name):
        return (self.ROOT / "src" / name).read_text(encoding="utf-8")

    def test_the_buyer_quote_resolves_the_key(self):
        source = self._module("handlers/checkout.py")
        self.assertIn("resolve_for_mode(_tenant_shipping_config(tenant_id), tenant_id, mode", source)

    def test_the_orders_address_check_resolves_the_key(self):
        """It calls `provider_for`, so it opens a credential and needs the mode's one."""
        source = self._module("handlers/orders.py")
        self.assertIn("resolve_for_mode(config, tenant_id, resolve_stripe_mode(event)", source)

    def test_every_module_that_reads_api_key_ref_also_resolves(self):
        """The structural guard, so the SIXTH site cannot be missed the way the fifth was: a module that
        opens a carrier key must also resolve which mode's key it is opening."""
        offenders = []
        for path in (self.ROOT / "src").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "shipping_keys" in path.name or "api_key_ref" not in source:
                continue
            # Only modules that OPEN the key -- naming the field is not the same as decrypting it.
            if "provider_for(" not in source and "live_rates_for(" not in source:
                continue
            if "resolve_for_mode" not in source:
                offenders.append(str(path.relative_to(self.ROOT)))
        self.assertEqual([], offenders,
                         f"these open a carrier key without resolving its mode: {offenders}")

    def test_modules_that_only_read_boxes_are_left_alone(self):
        """`upsell` and `ai_generate` load a shipping config for parcel and address defaults, which are
        the same in both modes. Forcing a cipher on them would be ceremony for a key they never open."""
        for name in ("handlers/upsell.py", "handlers/ai_generate.py"):
            source = self._module(name)
            self.assertIn("shipping_config_repository()", source, name)
            self.assertNotIn("api_key_ref", source, f"{name} should not be opening a carrier key")

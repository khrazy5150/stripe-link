"""The ship-from and the label's sender follow the business that sold it (plans/SHIPPING_PER_SITE.md §S2/§S3).

A tenant running two shops had ONE shipping setup: both businesses' labels carried the same warehouse and
the same sender email. The address a carrier reads off a parcel is the business that posted it.

The shape is an OVERRIDE MODEL, not a per-Site document, and that choice is the codebase's own: when
`domain/shipping_keys.py` faced the same question for Stripe MODE it answered *"the provider stays shared
and only the credential splits... making the whole document mode-scoped would force them to re-enter their
address to flip a toggle, which is how a safety feature becomes the thing people route around."*

Resolution happens where the config is LOADED, which is the other precedent this follows —
`config_for_mode`'s *"twelve places decrypt `provider.api_key_ref`... adding the mode to each would have
been twelve chances to miss one."*
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_shipping_config
from stripe_link.domain.shipping import SITE_OVERRIDABLE, config_for_site, sender_address

ROOT = pathlib.Path(__file__).resolve().parents[1]
HQ = {"name": "HQ", "street1": "1 A St", "city": "Seattle", "state": "WA",
      "postal_code": "98101", "country": "US"}
QUILL = {"name": "Quill", "street1": "2 B St", "city": "Austin", "state": "TX",
         "postal_code": "73301", "country": "US"}


def config(**over):
    doc = {"schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
           "provider": {"name": "shippo", "api_key_ref": "ref"}, "ship_from_address": dict(HQ),
           "boxes": [], "zones": []}
    doc.update(over)
    return doc


class TheOverrideResolvesAtLoadTests(unittest.TestCase):
    def test_no_site_gets_the_accounts_config(self):
        self.assertEqual(config_for_site(config(), "")["ship_from_address"]["city"], "Seattle")

    def test_a_site_with_an_override_gets_its_own(self):
        resolved = config_for_site(config(sites={"site_qui": {"ship_from_address": QUILL}}), "site_qui")
        self.assertEqual(resolved["ship_from_address"]["city"], "Austin")

    def test_a_DIFFERENT_site_is_unaffected(self):
        cfg = config(sites={"site_qui": {"ship_from_address": QUILL}})
        self.assertEqual(config_for_site(cfg, "site_pol")["ship_from_address"]["city"], "Seattle")

    def test_it_is_FIELD_LEVEL(self):
        """A Site that states an address but no zones keeps the account's zones — resolving the whole
        document would hand it an empty one."""
        cfg = config(zones=[{"id": "z1"}], sites={"site_qui": {"ship_from_address": QUILL}})
        resolved = config_for_site(cfg, "site_qui")
        self.assertEqual(resolved["ship_from_address"]["city"], "Austin")
        self.assertEqual(resolved["zones"], [{"id": "z1"}])

    def test_an_EMPTY_override_means_inherit(self):
        """`{}` and `[]` are what a half-filled form produces. Shipping from nowhere is worse than
        inheriting, so an empty value is not a statement."""
        cfg = config(zones=[{"id": "z1"}],
                     sites={"site_qui": {"ship_from_address": {}, "zones": []}})
        resolved = config_for_site(cfg, "site_qui")
        self.assertEqual(resolved["ship_from_address"]["city"], "Seattle")
        self.assertEqual(resolved["zones"], [{"id": "z1"}])

    def test_the_PROVIDER_is_never_overridable(self):
        """Per §2: nobody runs Shippo for one business and EasyPost for another, and per-Site credentials
        would multiply the key slots while the KMS encryption context stays deliberately unscoped."""
        self.assertNotIn("provider", SITE_OVERRIDABLE)
        for account_level in ("provider", "label_options", "rate_options", "boxes", "default_parcel"):
            with self.subTest(field=account_level):
                self.assertNotIn(account_level, SITE_OVERRIDABLE)

    def test_the_SITES_MAP_is_stripped_from_the_result(self):
        """A reader handed the whole map could resolve a second time and reach a different answer — and
        nothing downstream has any business knowing the other businesses exist."""
        resolved = config_for_site(config(sites={"site_qui": {"ship_from_address": QUILL}}), "site_qui")
        self.assertNotIn("sites", resolved)

    def test_a_missing_or_malformed_override_is_not_an_error(self):
        for sites in (None, {}, {"site_qui": "nonsense"}, {"site_qui": None}):
            with self.subTest(sites=sites):
                self.assertEqual(config_for_site(config(sites=sites), "site_qui")
                                 ["ship_from_address"]["city"], "Seattle")

    def test_a_None_config_does_not_raise(self):
        self.assertEqual(config_for_site(None, "site_qui"), {})


class TheValidatorGuardsTheOverrideTests(unittest.TestCase):
    def test_a_well_formed_override_is_accepted(self):
        validate_shipping_config(config(sites={"site_qui": {"ship_from_address": QUILL}}))

    def test_the_KEY_must_look_like_a_site_id(self):
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config(config(sites={"quill": {"ship_from_address": QUILL}}))

    def test_an_override_may_NOT_smuggle_a_provider(self):
        """The override map must not become the way around the account-level rule."""
        with self.assertRaises(DocumentValidationError) as caught:
            validate_shipping_config(config(sites={"site_qui": {"provider": {"name": "easypost"}}}))
        self.assertIn("may only override", str(caught.exception))

    def test_a_PARTIAL_override_address_is_refused(self):
        """Half an address buys a label that cannot be delivered — the same rule the account's own
        ship-from has, applied to the override so it cannot be the softer path."""
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config(config(sites={"site_qui": {"ship_from_address": {"city": "Austin"}}}))

    def test_an_overrides_ZONES_go_through_the_SAME_zone_validator(self):
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config(config(sites={"site_qui": {"zones": "everywhere"}}))

    def test_NO_sites_key_is_valid(self):
        """Every config that exists today has none."""
        validate_shipping_config(config())


class TheLabelsSenderEmailTests(unittest.TestCase):
    """Shippo rejects a purchase with an empty `address_from.email` and does NOT reject a rate request, so
    this gap only ever appears at the moment a tenant tries to post something."""

    def test_the_addresss_OWN_email_still_wins(self):
        address = {**HQ, "email": "warehouse@quill.test"}
        got = sender_address(address, {"email": "acct@p.test"}, "signin@p.test",
                             organization={"email": "hi@quill.test", "email_verified": True})
        self.assertEqual(got["email"], "warehouse@quill.test")

    def test_a_VERIFIED_site_address_comes_next(self):
        got = sender_address(dict(HQ), {"email": "acct@p.test"}, "signin@p.test",
                             organization={"email": "hi@quill.test", "email_verified": True})
        self.assertEqual(got["email"], "hi@quill.test")

    def test_an_UNVERIFIED_site_address_is_IGNORED(self):
        """Same rule as the Reply-To: nobody has proven it is reachable, and a carrier's "we could not
        deliver" notice going nowhere is worse than one going to the account owner."""
        got = sender_address(dict(HQ), {"email": "acct@p.test"}, "signin@p.test",
                             organization={"email": "hi@quill.test"})
        self.assertEqual(got["email"], "acct@p.test")

    def test_then_the_account_then_the_signin_address(self):
        self.assertEqual(sender_address(dict(HQ), {"email": "acct@p.test"}, "signin@p.test")["email"],
                         "acct@p.test")
        self.assertEqual(sender_address(dict(HQ), {}, "signin@p.test")["email"], "signin@p.test")

    def test_nothing_anywhere_leaves_NO_email_rather_than_a_guess(self):
        """`buy_label` then names the gap where it can be fixed instead of relaying the carrier's wording."""
        self.assertNotIn("email", sender_address(dict(HQ), {}, ""))


class TheSeamIsONEReadTests(unittest.TestCase):
    SOURCE = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")

    def test_both_label_paths_resolve_the_selling_site(self):
        """`quote_rates` as well as `buy_label`: a rate created without the right sender produces a rate id
        that cannot be bought, and fixing only the purchase looked right and changed nothing (2026-10-05)."""
        self.assertEqual(self.SOURCE.count("site = selling_site(order, mode)"), 2)
        self.assertEqual(self.SOURCE.count("site_config = config_for_site(config,"), 2)

    def test_the_sender_email_and_the_overrides_come_from_the_SAME_read(self):
        """Two reads could disagree and put one business's warehouse on another's label."""
        block = self.SOURCE.split("def selling_site(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("find_site_for_page", block)
        self.assertIn("site_id", block)
        self.assertIn("organization", self.SOURCE.split("def buy_label(", 1)[1][:4000])

    def test_an_unreadable_site_costs_the_OVERRIDE_not_the_LABEL(self):
        block = self.SOURCE.split("def selling_site(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("except Exception as exc:", block)
        self.assertIn("return {}", block)

    def test_the_ACCOUNT_LEVEL_fields_still_come_from_the_account(self):
        """`site_config` is not a blanket replacement: the provider, the label format and the rate policy
        are the account's equipment and reading them per Site would be wrong, not just unnecessary."""
        for function in ("def quote_rates(", "def buy_label("):
            block = self.SOURCE.split(function, 1)[1].split("\ndef ", 1)[0]
            with self.subTest(function=function):
                self.assertIn('config.get("provider")', block)
                self.assertNotIn('site_config.get("provider")', block)


class TheSchemaDeclaresTheMapTests(unittest.TestCase):
    def test_it_is_keyed_by_site_and_closed(self):
        schema = json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))
        sites = schema["properties"]["sites"]
        self.assertEqual(sites["type"], "object")
        self.assertFalse(sites["additionalProperties"]["additionalProperties"],
                         "an override must not accept arbitrary fields")

    def test_the_schema_and_the_code_agree_on_what_is_overridable(self):
        """Two lists that must match, with nothing forcing them to — so this forces them."""
        schema = json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))
        declared = set(schema["properties"]["sites"]["additionalProperties"]["properties"])
        self.assertEqual(declared, set(SITE_OVERRIDABLE))


if __name__ == "__main__":
    unittest.main()

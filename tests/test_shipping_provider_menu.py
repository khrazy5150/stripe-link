"""The Shipping screen only offers providers whose integration can be tested.

The schema lists five provider names, the dashboard offered all five, and NOT ONE was wired -- there is no
HTTP call to any carrier in this codebase. The menu advertised four integrations that had never run.

Only two can be proven end to end without spending money: Shippo and EasyPost put test mode in the API KEY,
so a test token buys free labels on the production host. ShipStation needs a real paid account before its
`testLabel` flag can even be sent, and Easyship's sandbox story is unknown.

A UI-only gate on purpose: the schema still accepts every name, so restoring a provider is one edit to the
template and nothing that is already stored is stranded.
"""
import pathlib
import re
import unittest

SCREEN = pathlib.Path(__file__).resolve().parents[1] / "dashboard/src/components/Shipping.vue"


def _selectable_options(markup: str) -> list[str]:
    """The provider values a tenant can actually pick -- comments excluded.

    Stripping comments is the point: the withdrawn providers stay in the file as commented-out lines, ready
    to restore, and a naive grep would report them as still on offer.
    """
    select = re.search(r"<select v-model=\"form\.provider\.name\">(.*?)</select>", markup, re.S).group(1)
    select = re.sub(r"<!--.*?-->", "", select, flags=re.S)
    return [value for value in re.findall(r'<option value="([^"]*)"', select) if value]


class ProviderMenuTests(unittest.TestCase):
    MARKUP = SCREEN.read_text(encoding="utf-8")

    def test_only_testable_providers_are_offered(self):
        self.assertEqual(_selectable_options(self.MARKUP), ["shippo", "mock"])

    def test_the_untestable_ones_are_not_pickable(self):
        offered = _selectable_options(self.MARKUP)
        for provider in ("shipstation", "easyship"):
            with self.subTest(provider=provider):
                self.assertNotIn(provider, offered)

    def test_they_are_kept_in_the_file_ready_to_restore(self):
        # Deleting them outright would lose the reason they were withdrawn, and the next person would add
        # them back without knowing they had never been exercised.
        for provider in ("easypost", "shipstation", "easyship"):
            with self.subTest(provider=provider):
                self.assertIn(f'<option value="{provider}"', self.MARKUP)

    def test_the_schema_still_accepts_all_five(self):
        """UI-only, so nothing already stored is stranded and restoring one is a template edit."""
        from stripe_link.domain.documents import validate_shipping_config
        base = {
            "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
            "ship_from_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                                  "postal_code": "90001", "country": "US"},
            "return_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                               "postal_code": "90001", "country": "US"},
            "default_parcel": {"length": 10, "width": 10, "height": 10, "weight": 1,
                               "distance_unit": "in", "mass_unit": "lb"},
        }
        for provider in ("shippo", "easypost", "shipstation", "easyship", "mock"):
            with self.subTest(provider=provider):
                validate_shipping_config({**base, "provider": {"name": provider}})


if __name__ == "__main__":
    unittest.main()

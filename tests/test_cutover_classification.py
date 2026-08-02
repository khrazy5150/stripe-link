"""Guards the cutover script's table classification (scripts/mode_decoupling_cutover.py) so the safety
invariants can't silently regress: the jb- prefix guard, full coverage of every table, and — above all — that
the platform reference tables (categories, app-config, ...) are NEVER in the wipe set."""
import importlib.util
import os
import unittest

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "mode_decoupling_cutover.py")


def _load():
    spec = importlib.util.spec_from_file_location("mode_decoupling_cutover", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The full jb- table set (mirrors template.yaml DynamoDB::Table resources).
ALL_TABLES = [
    "app-config", "calendar-connections", "carts", "checkout-sessions", "collections", "coupons",
    "custom-domains", "customers", "document-events", "experiments", "invoices", "lead-capture", "ledger",
    "legal-pages", "media", "notifications", "offers", "orders", "pages", "platform-config",
    "product-categories", "products", "refunds", "reviews", "routes", "services", "shipping-config", "sites",
    "stripe-keys", "tenant-profiles", "themes", "tier-policies", "user-preferences", "user-profiles",
    "webhook-events",
]


class CutoverClassificationTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_jb_prefix_and_env_guard_rejects_stripe_cart_and_wrong_env(self):
        # stripe-cart's unprefixed table (same name, no jb-) must never be recognised.
        self.assertIsNone(self.m.base_name("platform-config-prod", "prod"))
        # A jb- table for the OTHER env must not match this env.
        self.assertIsNone(self.m.base_name("jb-products-dev", "prod"))
        self.assertEqual(self.m.base_name("jb-product-categories-dev", "dev"), "product-categories")

    def test_every_table_is_classified_no_unclassified(self):
        buckets = {"PRESERVE": [], "REVIEW": [], "WIPE": [], "UNCLASSIFIED": []}
        for base in ALL_TABLES:
            buckets[self.m.classify(base)].append(base)
        self.assertEqual(buckets["UNCLASSIFIED"], [])
        self.assertEqual(len(ALL_TABLES), 35)
        self.assertEqual(len(buckets["WIPE"]), 30)

    def test_reference_tables_are_never_wiped(self):
        # The whole point of the operator's flag: these must never be deletable, even with the legal-pages opt-in.
        wipe_set = set(self.m.WIPE) | {"legal-pages"}
        self.assertFalse(wipe_set & self.m.PRESERVE)
        for reference in ("product-categories", "app-config", "tier-policies", "themes"):
            self.assertIn(reference, self.m.PRESERVE)
            self.assertNotIn(reference, wipe_set)

    def test_categories_is_preserved(self):
        self.assertEqual(self.m.classify("product-categories"), "PRESERVE")

    def test_legal_pages_defaults_to_review_not_wipe(self):
        self.assertEqual(self.m.classify("legal-pages"), "REVIEW")


if __name__ == "__main__":
    unittest.main()

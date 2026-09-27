"""A Stripe-mode-scoped repository built without a mode is refused, not tolerated.

Found 2026-09-26 in the refund return gate. `products_repository()` with no mode does not read across
test and live -- it reads a THIRD, empty key space:

    mode=live  ->  SK "ORDER#live#order_1"    list prefix "ORDER#live#"
    mode=test  ->  SK "ORDER#test#order_1"    list prefix "ORDER#test#"
    no mode    ->  SK "ORDER#order_1"         list prefix "ORDER#"

So the unmoded read found nothing, the policy snapshot concluded "no return required", and every refund
would have skipped its gate. A confident empty answer is the worst failure available -- worse than an
error, because nothing reports it -- so it is loud now.

The attribute-filtered repositories (orders, customers) refuse it for a worse reason again: an unfiltered
read returns test money ALONGSIDE real money, which is how a revenue total silently includes transactions
that never happened.
"""
import os
import pathlib
import re
import unittest
from unittest.mock import patch

from stripe_link.repositories.documents import (
    DynamoDocumentRepository,
    RepositoryError,
    TenantRangeRepository,
    orders_repository,
    products_repository,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

MODE_SCOPED_FACTORIES = """products_repository shipments_repository offers_repository coupons_repository
coupon_grants_repository coupon_redemptions_repository pages_repository sites_repository
customers_repository orders_repository notifications_repository collections_repository
carts_repository cart_tokens_repository tip_tokens_repository purchase_tokens_repository
review_invites_repository services_repository appointments_repository invoices_repository
experiments_repository booking_credits_repository""".split()


class KeyScopedTests(unittest.TestCase):
    def test_the_three_key_spaces_are_genuinely_different(self):
        live = DynamoDocumentRepository("jb-orders-dev", document_type="order", id_field="order_id",
                                        table=object(), mode="live")
        test = DynamoDocumentRepository("jb-orders-dev", document_type="order", id_field="order_id",
                                        table=object(), mode="test")
        none = DynamoDocumentRepository("jb-orders-dev", document_type="order", id_field="order_id",
                                        table=object())
        self.assertEqual(live._sk("o1"), "ORDER#live#o1")
        self.assertEqual(test._sk("o1"), "ORDER#test#o1")
        self.assertEqual(none._sk("o1"), "ORDER#o1")
        self.assertEqual(len({live._sk("o1"), test._sk("o1"), none._sk("o1")}), 3)

    def test_a_mode_scoped_type_without_a_mode_RAISES(self):
        with patch.dict(os.environ, {"PRODUCTS_TABLE": "jb-products-dev"}, clear=False):
            with self.assertRaises(RepositoryError) as caught:
                products_repository(table=object())
        self.assertIn("mode-scoped", str(caught.exception))

    def test_with_a_mode_it_builds(self):
        with patch.dict(os.environ, {"PRODUCTS_TABLE": "jb-products-dev"}, clear=False):
            for mode in ("test", "live"):
                self.assertIsNotNone(products_repository(table=object(), mode=mode))

    def test_a_mode_AGNOSTIC_type_is_untouched(self):
        """Legal pages, tenant profiles and user profiles are genuinely not mode-scoped; requiring one
        there would be ceremony, not safety."""
        repo = DynamoDocumentRepository("jb-legal-dev", document_type="legal_page", id_field="page_id",
                                        table=object())
        self.assertEqual(repo._sk("p1"), "LEGAL_PAGE#p1")


class AttributeFilteredTests(unittest.TestCase):
    def test_orders_and_customers_also_require_one(self):
        with patch.dict(os.environ, {"ORDERS_TABLE": "jb-orders-dev"}, clear=False):
            with self.assertRaises(RepositoryError) as caught:
                orders_repository(table=object())
        self.assertIn("test and live rows together", str(caught.exception))

    def test_the_class_itself_refuses_it(self):
        with self.assertRaises(RepositoryError):
            TenantRangeRepository("jb-customers-dev", id_field="customer_id", table=object())


class NoCallerOmitsItTests(unittest.TestCase):
    """The guard turns an omission into a runtime error, and several were being SWALLOWED -- the refund
    gate's own `except Exception` would have hidden it. So the call sites are checked statically too."""

    def test_no_handler_builds_a_mode_scoped_repository_without_a_mode(self):
        offenders = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            if path.name == "documents.py":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for factory in MODE_SCOPED_FACTORIES:
                    for match in re.finditer(rf"\b{factory}\(([^)]*)\)", line):
                        if "mode" not in match.group(1):
                            offenders.append(f"{path.relative_to(ROOT)}:{n} {factory}()")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_scan_actually_finds_the_factories(self):
        """A silently empty scan would pass forever."""
        source = (ROOT / "src" / "handlers" / "orders.py").read_text(encoding="utf-8")
        self.assertIn("orders_repository(mode=", source)


if __name__ == "__main__":
    unittest.main()

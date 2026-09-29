"""No email may show its own markup to a customer.

Two shipped that way. `paragraph()` escapes what it is given -- rightly, since these bodies carry
tenant-supplied product names and buyer-entered refund reasons -- so markup handed to it reaches the
inbox as visible <strong> tags. Both were caught by a human reading a real email on a phone, one
after the other, which is the slowest possible feedback loop for a one-line mistake.

So this sweeps EVERY email builder in the product rather than the two that were reported, and it
checks the two directions that matter: our own markup must not be escaped, and a customer's text must
not be able to inject markup of its own.
"""

import inspect
import unittest

from stripe_link.domain import receipts
from stripe_link.domain.email_layout import emphasis, paragraph

# The shapes an escaped tag takes in a rendered body. If any appears, a caller passed HTML to
# something that escapes.
LEAKS = ("&lt;strong&gt;", "&lt;/strong&gt;", "&lt;p&gt;", "&lt;br", "&lt;a ", "&lt;em&gt;",
         "&lt;div", "&lt;span")

# Builders that render a whole email, with arguments that exercise their optional branches.
BUILDERS = {
    "receipt_content": dict(
        order={"order_id": "order_1", "amount_total": 3291, "currency": "usd",
               "customer": {"name": "Sam"}, "product": {"name": "Creatine Gummies"},
               "metadata": {"tip_keyed_amount": "1000"}},
        business_name="Poliaxis Nutrition", support_email="hi@poliaxis.com",
        download_links=[{"label": "Your guide", "url": "https://example.com/g.pdf"}],
        manage_url="https://example.com/manage?t=abc"),
    "cancellation_content": dict(
        business_name="Poliaxis Nutrition", product="Creatine Gummies", ends_at=1790714125,
        manage_url="https://example.com/manage?t=abc", support_email="hi@poliaxis.com"),
    "tip_renewal_content": dict(
        business_name="Poliaxis Nutrition", amount_total=1000, currency="usd",
        interval="month", manage_url="https://example.com/manage?t=abc"),
}


def _callable(name):
    fn = getattr(receipts, name, None)
    return fn if callable(fn) else None


class NoMarkupLeaksTests(unittest.TestCase):
    def test_every_builder_under_test_still_exists(self):
        # A renamed builder must fail loudly here rather than quietly stop being checked.
        for name in BUILDERS:
            with self.subTest(name=name):
                self.assertIsNotNone(_callable(name), f"{name} is gone; update this sweep")

    def test_no_email_shows_its_own_markup(self):
        for name, kwargs in BUILDERS.items():
            fn = _callable(name)
            if not fn:
                continue
            accepted = set(inspect.signature(fn).parameters)
            content = fn(**{k: v for k, v in kwargs.items() if k in accepted})
            for leak in LEAKS:
                with self.subTest(builder=name, leak=leak):
                    self.assertNotIn(leak, content["html"])

    def test_no_plain_text_version_carries_markup(self):
        # The text part is what a plain-text client shows; tags there are just as visible.
        for name, kwargs in BUILDERS.items():
            fn = _callable(name)
            if not fn:
                continue
            accepted = set(inspect.signature(fn).parameters)
            content = fn(**{k: v for k, v in kwargs.items() if k in accepted})
            for tag in ("<strong>", "<p>", "<br", "</a>"):
                with self.subTest(builder=name, tag=tag):
                    self.assertNotIn(tag, content["text"])

    def test_every_builder_returns_a_sendable_email(self):
        for name, kwargs in BUILDERS.items():
            fn = _callable(name)
            if not fn:
                continue
            accepted = set(inspect.signature(fn).parameters)
            content = fn(**{k: v for k, v in kwargs.items() if k in accepted})
            with self.subTest(builder=name):
                self.assertTrue(content["subject"].strip())
                self.assertTrue(content["html"].strip())
                self.assertTrue(content["text"].strip())


class LayerContractTests(unittest.TestCase):
    """The reason both bugs happened: there was no correct way to bold a line."""

    def test_paragraph_escapes_what_it_is_given(self):
        # It must. These bodies carry product names a tenant typed and reasons a buyer typed.
        self.assertIn("&lt;script&gt;", paragraph("<script>alert(1)</script>"))

    def test_emphasis_bolds_without_the_caller_writing_markup(self):
        out = emphasis("You will not be charged again.")
        self.assertIn("font-weight:700", out)
        self.assertNotIn("<strong>", out)

    def test_emphasis_escapes_too(self):
        # The point is to remove the REASON to pass HTML, not to open a hole for it.
        self.assertIn("&lt;script&gt;", emphasis("<script>alert(1)</script>"))

    def test_both_ignore_empty_input(self):
        self.assertEqual(paragraph(""), "")
        self.assertEqual(emphasis("   "), "")

    def test_a_tenants_product_name_cannot_inject_markup(self):
        # The direction that matters for safety, not just for looks.
        content = receipts.cancellation_content(product="<img src=x onerror=alert(1)>")
        self.assertNotIn("<img", content["html"])
        self.assertIn("&lt;img", content["html"])

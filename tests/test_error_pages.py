import unittest

from stripe_link.runtime.error_pages import render_error_page


class ErrorPageTests(unittest.TestCase):
    def test_renders_status_message_and_badge(self):
        html = render_error_page(404, "This test link is no longer available.", title="Page not found", badge="Test Environment")
        self.assertIn("<!doctype html>", html)
        self.assertIn("<h1>404</h1>", html)
        self.assertIn("This test link is no longer available.", html)
        self.assertIn("Test Environment", html)
        self.assertIn("linear-gradient", html)  # the ported stripe-cart styling
        self.assertIn("noindex", html)          # error pages must never be indexed
        self.assertIn("<title>Page not found</title>", html)

    def test_badge_omitted_when_empty(self):
        self.assertNotIn('class="badge"', render_error_page(403, "Nope"))

    def test_escapes_message(self):
        self.assertIn("&lt;script&gt;", render_error_page(404, "<script>x</script>"))


if __name__ == "__main__":
    unittest.main()

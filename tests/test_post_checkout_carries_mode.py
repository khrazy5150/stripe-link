"""Every post-checkout funnel URL has to carry the Stripe mode.

`post_checkout.next` is a LOOKUP: it resolves the mode from the request and reads pages, offers and
products in it. `resolve_stripe_mode` deliberately falls back to TEST when the mode is absent, so that a
caller who forgets one can never mutate live data — which means a modeless funnel URL does not fail
loudly, it silently searches the wrong partition.

Measured 2026-10-07: a live sale's thank-you page answered `{"error": "not_found"}` because the island
sent `outcome`/`tenant_id`/`session_id`/`origin` and no mode. The page existed at
`SK = PAGE#live#page_xuePD8RMInv`; the lookup asked for `PAGE#test#page_xuePD8RMInv`.

A TEST purchase matches the fallback and works, so this is invisible to every test-mode rehearsal. That
is exactly why it needs a test.
"""
import json
import re
import unittest
from pathlib import Path

from stripe_link.runtime.html import render_page

ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name):
    with (ROOT / "schemas" / "examples" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def funnel_builders(html):
    """Each post-checkout/next URL paired with the lines that built its params.

    Scoped per BUILDER, not globally: two builders both name their params `next`, so a global substring
    check for "next.set('mode'" stays green when one of them loses it. Verified by deleting the mode from
    one builder — the global version passed, this one fails.
    """
    lines = html.replace('"', "'").splitlines()
    out = []
    for i, line in enumerate(lines):
        if "post-checkout/next" not in line:
            continue
        m = re.search(r"post-checkout/next\?\$\{(\w+)\.toString\(\)\}", line)
        if not m:
            continue
        var = m.group(1)
        for j in range(i, -1, -1):
            if re.search(rf"\b{var}\s*=\s*new URLSearchParams\(\)", lines[j]):
                out.append((var, "\n".join(lines[j:i + 1])))
                break
        else:
            raise AssertionError(f"could not find where `{var}` was built, for line: {line}")
    return out


class EveryFunnelUrlCarriesTheModeTests(unittest.TestCase):
    def _html(self):
        product = load_fixture("product-creatine-gummies.json")
        offer = load_fixture("offer-creatine-standard.json")
        page = load_fixture("page-creatine-standard.json")
        page["post_checkout"] = {"thank_you_page": {"page_id": "page_ty"}}
        return render_page(page, offer, {"prod_creatine_gummies": product},
                           api_base_url="https://api-dev.example.com")

    def test_the_island_sets_a_mode_on_every_post_checkout_url(self):
        builders = funnel_builders(self._html())
        self.assertTrue(builders, "expected the page to build at least one post-checkout/next URL")
        for var, block in builders:
            self.assertIn(f"{var}.set('mode'", block,
                          f"this builder sends no mode, so it resolves to TEST and 404s a live page:\n{block}")

    def test_the_mode_comes_from_the_page_not_a_literal(self):
        for var, block in funnel_builders(self._html()):
            m = re.search(rf"{var}\.set\('mode',\s*([^)]+)\)", block)
            self.assertIsNotNone(m, f"{var} sets no mode")
            value = m.group(1).strip()
            self.assertNotIn("'live'", value, "the mode must be read from the page, never hardcoded")
            self.assertNotEqual(value, "'test'", "the mode must be read from the page, never hardcoded")

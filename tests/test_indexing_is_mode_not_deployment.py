"""Whether a page may be indexed is a question about the Stripe MODE, never about the deployment.

`dev` is a deployment. `test` is a Stripe mode. `sandbox` is a silo (`stripe_link/silo.py`). The three
were one word for a long time, and this file guards the last place the old conflation survived.

The dev stack carried a CloudFront response-headers policy stamping
`X-Robots-Tag: noindex, nofollow, noarchive` with `Override: true` on EVERY published page, justified as
"non-prod published pages so test pages can't be indexed". But the dev deployment serves live-mode Sites
on verified custom domains -- that is a deliberate decision, not an accident -- and the policy de-indexed
them too. The renderer emitted `index,follow` in the HTML, CloudFront overrode it in the header, crawlers
take the more restrictive of the two, and the dashboard went on reporting the Site as eligible. Found on
www.coderbay.net, 2026-10-25, after a tenant had done everything asked of them.

Removed rather than replaced, because the per-page decision was always the real one and it already asks
the right question.
"""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "template.yaml").read_text(encoding="utf-8")


class NoBlanketNoIndexTests(unittest.TestCase):
    def test_the_pages_distribution_does_not_stamp_noindex_on_everything(self):
        # A response-headers policy with Override: true beats anything the renderer decided, so there is
        # no version of this that a correct per-page decision can survive.
        self.assertNotIn("PagesNoIndexHeadersPolicy", TEMPLATE)
        pages_block = TEMPLATE.split("PagesDistribution:", 1)[1].split("\n  Pages", 1)[0]
        self.assertNotIn("X-Robots-Tag", pages_block)

    def test_the_two_deployments_treat_indexing_identically(self):
        # Prod never had the policy. The bug was dev behaving DIFFERENTLY, so the guard is that no
        # IsNonProd condition decides a robots header anywhere.
        for line in TEMPLATE.splitlines():
            if "X-Robots-Tag" in line or "ResponseHeadersPolicyId" in line:
                self.assertNotIn("IsNonProd", line, line.strip())

    def test_the_reason_is_recorded_where_someone_would_put_it_back(self):
        self.assertIn("REMOVED 2026-10-25", TEMPLATE)
        self.assertIn("page_robots_directive", TEMPLATE)


class TheRealGateStillHoldsTests(unittest.TestCase):
    """What now carries the whole decision. Each of these is the mode-aware question the blanket policy
    was standing in front of."""

    def test_only_a_live_mode_page_on_a_verified_domain_may_be_indexed(self):
        from stripe_link.runtime.html import page_robots_directive

        # `kind` is the ARTIFACT kind: only a published artifact is a candidate at all, which is what
        # keeps previews out without any help from a CDN header.
        allowed = dict(kind="published", mode="live", eligibility="eligible", page_type="landing",
                       on_custom_domain=True, site_archived=False, seo_enabled=True)
        self.assertEqual(page_robots_directive(**allowed).split(",")[0], "index")
        # Each refusal on its own merit -- and note `mode`, not an environment.
        for override in ({"mode": "test"}, {"kind": "preview"}, {"on_custom_domain": False},
                         {"eligibility": "ineligible"}, {"site_archived": True},
                         {"seo_enabled": False}):
            self.assertIn("noindex", page_robots_directive(**{**allowed, **override}), override)

    def test_a_platform_host_is_refused_by_the_resolver_not_by_the_deployment(self):
        src = (ROOT / "src" / "handlers" / "custom_domains_resolve.py").read_text(encoding="utf-8")
        self.assertIn('record.get("host_kind") in ("platform", "creator")', src)
        self.assertIn('route["noindex"] = True', src)


if __name__ == "__main__":
    unittest.main()

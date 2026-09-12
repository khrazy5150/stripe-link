"""A link hub can carry its own links, and those links never become an identity claim.

Decided 2026-09-11. The friction was never SEO: `social_links` read the Site because that is where the
profile URLs are stored, and a creator had to leave the builder for a screen headed "Business identity
(Organization)" to add an Instagram. So the section may now carry its own list, falling back to the Site's --
the same override-or-inherit rule the page avatar already uses.

The proposal on the table was that ATTACHMENT should decide: page-local links when standalone, Site links
once attached. Rejected, because a page would then silently change what it displays when it joined a Site --
the same invisible dependency that made this element confusing in the first place -- and because auto-
attaching a Site (the planned fix for the setup friction) would have made page-local links unreachable.
Attachment is not part of the rule at all.

The separation the author wanted survives intact, but it falls out of WHERE THE LINKS LIVE rather than a
hidden branch: inherited links can earn `sameAs`, page-local ones can never.
"""
import pathlib
import unittest

from stripe_link.domain.social_links import (
    SAME_AS_HOSTS,
    section_link_entries,
    section_own_links,
    verified_urls,
)
from stripe_link.runtime import html as html_module
from stripe_link.runtime.publishing import page_has_own_social_links

ORG = {
    "name": "Poliaxis Nutrition",
    "same_as": [
        {"url": "https://github.com/acme", "verification": {"state": "verified"}},
        {"url": "https://instagram.com/acme", "verification": {"state": "unverifiable"}},
    ],
}


class ResolutionTests(unittest.TestCase):
    def test_its_own_links_win(self):
        section = {"items": [{"url": "https://onlyfans.com/acme"}]}
        self.assertEqual([e["url"] for e in section_link_entries(section, ORG)],
                         ["https://onlyfans.com/acme"])

    def test_no_links_of_its_own_means_inherit(self):
        for section in ({}, {"items": []}, {"items": [{"url": "  "}]}):
            self.assertEqual(
                [e["url"] for e in section_link_entries(section, ORG)],
                ["https://github.com/acme", "https://instagram.com/acme"], section)

    def test_inheriting_is_the_default_so_nothing_changes_under_anyone(self):
        # Every page that existed before this had no items key at all. That must keep resolving to the Site's
        # list, or shipping the feature would silently empty every link row in production.
        self.assertEqual(section_own_links({"type": "social_links", "heading": ""}), [])

    def test_attachment_is_not_part_of_the_rule(self):
        # The resolver takes a section and an organization. There is deliberately nothing here to branch on:
        # a page cannot change what it displays by being attached to a Site.
        import inspect
        self.assertEqual(list(inspect.signature(section_link_entries).parameters), ["section", "organization"])


class IdentityBoundaryTests(unittest.TestCase):
    """The line that makes the whole split safe."""

    def test_the_emitted_same_as_ignores_page_local_links(self):
        # sameAs is a machine-readable claim about who the tenant IS, so the node is built from the SITE's
        # VERIFIED list and nothing else. Asserted on the emitted JSON-LD rather than on the helper, because
        # the claim that matters is what ships in the markup.
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG.update(ORG)
        node = html_module.organization_node(ORG, "https://acme.com")
        self.assertEqual(node.get("sameAs"), ["https://github.com/acme"])

        # Rendering a page whose section overrides with an unverifiable host changes nothing about it. The
        # section is not an input to the node -- there is no path from one to the other.
        markup = html_module.render_social_links({"id": "s1", "items": [{"url": "https://onlyfans.com/acme"}]})
        self.assertIn('aria-label="OnlyFans"', markup)  # rendered -- as an unlinked tile on a platform host
        self.assertEqual(html_module.organization_node(ORG, "https://acme.com").get("sameAs"),
                         ["https://github.com/acme"])

    def test_only_verified_entries_are_claimed(self):
        # The Site's own list is not a "validated list" either -- display was never gated on verification
        # (Instagram can never be confirmed and still shows). Verification gates the CLAIM alone.
        self.assertEqual(verified_urls(ORG), ["https://github.com/acme"])

    def test_a_page_local_link_needs_no_allowlist(self):
        # The point of the split. SAME_AS_HOSTS protects the identity claim; a link that makes no claim is
        # free, which is exactly what a creator promoting a Substack or an OnlyFans needs.
        self.assertNotIn("onlyfans.com", SAME_AS_HOSTS)
        self.assertNotIn("substack.com", SAME_AS_HOSTS)
        self.assertEqual(len(section_own_links({"items": [{"url": "https://onlyfans.com/acme"}]})), 1)


class RenderTests(unittest.TestCase):
    def _render(self, section, org=ORG, own_domain=False):
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG.update(org)
        # The §7 boundary keys on whose domain this is, NOT on whether the Site has a serving origin --
        # a free *.jbay.uk address has one of those too.
        html_module._RENDER_STATE["own_domain"] = own_domain
        try:
            return html_module.render_social_links({"id": "s1", **section})
        finally:
            html_module._RENDER_STATE.pop("own_domain", None)

    def test_own_links_render_instead_of_the_sites(self):
        markup = self._render({"items": [{"url": "https://youtube.com/@acme"}]})
        self.assertIn("youtube.com/@acme", markup)
        self.assertNotIn("github.com/acme", markup)

    def test_a_page_with_no_site_at_all_still_renders_its_own(self):
        # The standalone case: no Organization anywhere, and the hub still works.
        markup = self._render({"items": [{"url": "https://instagram.com/acme"}]}, org={})
        self.assertIn("instagram.com/acme", markup)
        self.assertIn("sl-social-glyph", markup)

    def test_an_uncurated_host_shows_but_does_not_link_on_the_platform_host(self):
        # §7, the same boundary render_link_cards applies: on shared infrastructure a phishing link is a
        # browser-blocklist problem for our domain and every tenant on it. Unlinked rather than dropped -- a
        # tile that silently vanishes tells the tenant nothing about why.
        # OnlyFans stood here until §4 curated it onto the list -- linkable BECAUSE it is age-gated. The
        # case is really about a host nobody has reviewed.
        markup = self._render({"items": [{"url": "https://shop.example.org/acme"}]})
        self.assertIn("is-unlinked", markup)
        self.assertNotIn("<a ", markup)
        self.assertIn('aria-label="shop.example.org"', markup)  # still visible, and still named

    def test_the_same_link_is_tappable_on_the_tenants_own_domain(self):
        # There the reputation at stake is theirs.
        markup = self._render({"items": [{"url": "https://shop.example.org/acme"}]}, own_domain=True)
        self.assertIn('href="https://shop.example.org/acme"', markup)
        self.assertIn('rel="nofollow ugc noopener"', markup)
        self.assertNotIn("is-unlinked", markup)


class PublishGuardTests(unittest.TestCase):
    def test_a_page_carrying_its_own_links_counts(self):
        page = {"sections": [{"type": "social_links", "items": [{"url": "https://instagram.com/a"}]}]}
        self.assertTrue(page_has_own_social_links(page))

    def test_an_inheriting_page_does_not(self):
        self.assertFalse(page_has_own_social_links({"sections": [{"type": "social_links"}]}))
        self.assertFalse(page_has_own_social_links({"sections": [{"type": "social_links", "items": []}]}))
        self.assertFalse(page_has_own_social_links({}))

    def test_another_sections_items_do_not_count(self):
        # link_cards also has items[]. Counting them would let a page with cards but no profiles publish as a
        # hub with no links on it, which is the exact state the guard exists to catch.
        page = {"sections": [{"type": "link_cards", "items": [{"url": "https://x.com/a", "label": "X"}]}]}
        self.assertFalse(page_has_own_social_links(page))


if __name__ == "__main__":
    unittest.main()


class TrustBoundarySourceTests(unittest.TestCase):
    """§7 keys on WHOSE domain this is, not on whether the Site has a serving origin.

    Reported 2026-09-11 as "the outline shows broken on the Preview but solid on the saved page". The preview
    was right. `on_custom_domain` was inferred from `_RENDER_STATE["home_url"]`, and home_url became true for
    a free *.jbay.uk address when platform hostname serving shipped -- so the check silently switched OFF on
    exactly the shared hosts it exists to protect, and every destination became a live anchor there.

    publishing.py had the correct value all along (`site_domain_verified(site) and page_site_slug`) and simply
    never passed it; the renderer re-derived a different thing from a neighbouring field. Two things that had
    to agree, with nothing making them.
    """

    def test_a_platform_host_does_not_count_as_the_tenants_own(self):
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG.update(ORG)
        # A Site serving on the free platform host: it HAS a home_url, and that must not unlock the boundary.
        html_module._RENDER_STATE["home_url"] = "https://acme.jbay.uk/"
        html_module._RENDER_STATE["own_domain"] = False
        try:
            markup = html_module.render_social_links(
                {"id": "s1", "items": [{"url": "https://shop.example.org/a"}]})
        finally:
            html_module._RENDER_STATE["home_url"] = ""
            html_module._RENDER_STATE.pop("own_domain", None)
        self.assertIn("is-unlinked", markup)

    def test_the_renderer_reads_the_dedicated_flag(self):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        self.assertNotIn('on_custom_domain = bool(_RENDER_STATE.get("home_url"))', source)
        self.assertEqual(source.count('on_custom_domain = bool(_RENDER_STATE.get("own_domain"))'), 2)

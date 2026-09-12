"""The 18+ interstitial on links to predominantly-adult platforms.

plans/CREATOR_LINK_POLICY.md §5. It is an attestation, not age verification -- a one-tap "Continue" stops
nobody who means it. It earns its place by preventing accidental exposure (a bio link tapped on a shared
screen) and by demonstrating a content policy, which is what a registrar abuse desk actually asks about, and
which is what keeps the shared creator domain alive.
"""
import unittest

from stripe_link.domain.social_links import ADULT_HOSTS, ADULT_HOSTS_REVIEWED, SAME_AS_HOSTS, is_adult_host
from stripe_link.runtime import html as html_module


class WarnListTests(unittest.TestCase):
    def test_the_test_is_predominantly_adult_not_permits_adult(self):
        # "Does the platform permit adult content" is true of most large UGC platforms and over-fires so badly
        # the warning stops carrying information -- people click through reflexively, which destroys the value
        # of the one that matters.
        for url in ("https://onlyfans.com/acme", "https://fansly.com/acme"):
            self.assertTrue(is_adult_host(url), url)
        for url in ("https://x.com/acme", "https://twitter.com/acme", "https://reddit.com/u/acme",
                    "https://instagram.com/acme", "https://patreon.com/acme", "https://example.org/acme"):
            self.assertFalse(is_adult_host(url), url)

    def test_x_is_absent_deliberately(self):
        # It permits adult content and is overwhelmingly not that: the same domain hosts news organisations,
        # governments and every B2B brand, so an adult warning on a nutrition store's X profile is a bug.
        # Accepted consequence, written down so it is not rediscovered as an oversight: an adult X profile on
        # a hub will not warn.
        self.assertNotIn("x.com", ADULT_HOSTS)
        self.assertNotIn("twitter.com", ADULT_HOSTS)

    def test_it_matches_subdomains(self):
        self.assertTrue(is_adult_host("https://www.onlyfans.com/acme"))

    def test_warning_is_independent_of_the_identity_allowlist(self):
        # Three separate questions (CREATOR_LINK_POLICY §2): may this be LINKED, should it be WARNED about,
        # and may it be CLAIMED as identity. These hosts can never be a sameAs and still must warn.
        self.assertFalse(set(ADULT_HOSTS) & set(SAME_AS_HOSTS))

    def test_every_entry_carries_its_reason_and_a_review_date(self):
        # Platform policy CHANGES -- X's did -- so a table encoding it goes stale silently. The reason travels
        # with the entry so a reviewer can re-check the claim instead of re-deriving the decision.
        for host, why in ADULT_HOSTS.items():
            self.assertTrue(why.strip(), host)
        self.assertRegex(ADULT_HOSTS_REVIEWED, r"^\d{4}-\d{2}-\d{2}$")


class MarkupTests(unittest.TestCase):
    ORG = {"same_as": [{"url": "https://onlyfans.com/acme"}, {"url": "https://instagram.com/acme"}]}

    def _row(self, own_domain=True):
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG.update(self.ORG)
        html_module._RENDER_STATE["own_domain"] = own_domain
        try:
            return html_module.render_social_links({"id": "s1"})
        finally:
            html_module._RENDER_STATE.pop("own_domain", None)

    def test_only_the_adult_link_is_flagged(self):
        markup = self._row()
        self.assertEqual(markup.count('data-sl-adult="1"'), 1)
        flagged = [chunk for chunk in markup.split("<li>") if 'data-sl-adult' in chunk][0]
        self.assertIn("onlyfans.com", flagged)

    def test_link_cards_are_flagged_too(self):
        # Same destinations, same risk. A hub's cards are where a creator puts exactly these links.
        html_module._RENDER_STATE["own_domain"] = True
        try:
            markup = html_module.render_link_cards(
                {"id": "lc", "items": [{"url": "https://fansly.com/acme", "label": "My Fansly"},
                                       {"url": "https://youtube.com/@acme", "label": "Videos"}]})
        finally:
            html_module._RENDER_STATE.pop("own_domain", None)
        self.assertEqual(markup.count('data-sl-adult="1"'), 1)


class InterstitialTests(unittest.TestCase):
    PAGE = {"page_id": "page_abc"}

    def script(self, kind="published"):
        return html_module.render_outbound_link_script(self.PAGE, kind, "https://api.example")

    def test_the_gate_renders_on_every_artifact(self):
        # It is a SAFETY control, not analytics. Gating it to published -- which it inherited from the counting
        # script it shares -- meant it could not be tested from a draft's preview link, and anyone the tenant
        # sent that link to got no warning at all.
        for kind in ("published", "preview", "", "draft"):
            self.assertIn("sl-age-gate", self.script(kind), kind)

    def test_it_survives_having_no_page_id_or_api_base(self):
        # The gate needs neither. Requiring them would make a safety control depend on analytics plumbing.
        self.assertIn("sl-age-gate", html_module.render_outbound_link_script({}, "preview", None))

    def test_counting_stays_published_only(self):
        # A tenant editing their own hub all afternoon must not inflate their own numbers.
        self.assertIn("COUNT = true", self.script("published"))
        for kind in ("preview", "", "draft"):
            self.assertIn("COUNT = false", self.script(kind), kind)

    def test_it_uses_the_pages_own_dialog_not_the_browsers(self):
        # window.confirm on a creator's page reads as a malware warning. The page already has a themed dialog,
        # added when the checkout script needed one because a server-rendered page cannot use ConfirmDialog.vue.
        s = self.script()
        self.assertIn("sl-notice-backdrop", s)
        self.assertIn("sl-notice-card", s)
        self.assertNotIn("window.confirm", s)
        self.assertNotIn("alert(", s)

    def test_declining_is_as_reachable_as_continuing(self):
        # A dialog where only the affirmative answer is a real button is a dark pattern, and this one exists
        # to let someone say no.
        s = self.script()
        self.assertIn("sl-notice-cancel", s)
        self.assertIn("Cancel", s)
        self.assertIn("Continue (18+)", s)
        self.assertIn("Escape", s)

    def test_the_badge_names_a_minimum_not_an_age(self):
        # "18" alone reads as an age; "18+" reads as the threshold, which is what it is (author, 2026-09-11).
        s = self.script()
        self.assertIn(">18+</div>", s)

    def test_the_wording_is_hedged(self):
        # "May contain" is a claim about the PLATFORM, which is what we know. "Contains" would be a claim
        # about the creator, which we do not know and must not assert about a named person.
        s = self.script()
        self.assertIn("may contain adult content", s)

    def test_it_asks_every_time(self):
        # Matches what linkcloud.ai and link.me actually do, AND avoids storage on a shared creator origin --
        # the hazard SOCIAL_MEDIA_PAGES.md §6 flags for the cart keys. Norm and architecture agree here.
        s = self.script()
        gate = s.split("data-sl-adult", 1)[1]
        for remembered in ("localStorage.setItem", "sessionStorage", "document.cookie"):
            self.assertNotIn(remembered, gate, remembered)

    def test_a_declined_link_is_not_counted(self):
        # The reason the gate and the counter are ONE script. A visitor who backs out did not click through to
        # anything, and reporting that they did would put a number in the dashboard nobody earned.
        s = self.script()
        pointer = s.split("'pointerdown'", 1)[1].split("}, true);", 1)[0]
        self.assertIn("!a.hasAttribute('data-sl-adult')", pointer)
        # ...and Continue counts it instead, so the click is not simply lost.
        self.assertIn("count({ getAttribute", s)

    def test_it_opens_the_destination_itself(self):
        # The click is prevented, so nothing navigates unless Continue does it.
        s = self.script()
        self.assertIn("e.preventDefault();", s)
        self.assertIn("window.open(href, '_blank', 'noopener')", s)


if __name__ == "__main__":
    unittest.main()


class CreatorAllowlistTests(unittest.TestCase):
    """§4: what may be LINKED from a page on shared platform infrastructure.

    Widened 2026-09-11 from SAME_AS_HOSTS -- a list built to answer "which hosts can make a credible IDENTITY
    claim", which is a different question. That list carries Crunchbase, the BBB and Wikidata and carries no
    Substack, Patreon, Amazon or Etsy, so a creator on the free host could not link the places creators link.
    One list answering two questions was wrong for both.
    """

    def test_every_identity_host_stays_linkable(self):
        # A host trusted enough to be asserted as who the tenant IS cannot be too dangerous to link to.
        from stripe_link.domain.social_links import PLATFORM_LINKABLE_HOSTS

        self.assertTrue(SAME_AS_HOSTS <= PLATFORM_LINKABLE_HOSTS)

    def test_the_places_creators_actually_link_now_work(self):
        from stripe_link.domain.social_links import linkable_on_platform_host

        for url in ("https://substack.com/@acme", "https://patreon.com/acme", "https://ko-fi.com/acme",
                    "https://www.amazon.com/shops/acme", "https://etsy.com/shop/acme",
                    "https://twitch.tv/acme", "https://open.spotify.com/artist/x",
                    "https://discord.gg/abc", "https://calendly.com/acme"):
            self.assertTrue(linkable_on_platform_host(url), url)

    def test_adult_platforms_are_linkable_because_they_are_gated(self):
        # §5e: we label rather than host, which is defensible where a quiet ban decided by omission is not.
        from stripe_link.domain.social_links import linkable_on_platform_host

        for url in ("https://onlyfans.com/acme", "https://fansly.com/acme"):
            self.assertTrue(linkable_on_platform_host(url), url)
            self.assertTrue(is_adult_host(url), url)

    def test_payment_handles_are_deliberately_absent(self):
        # A payment request is the highest-value phishing target there is, and one on a domain shared with
        # every other tenant is the single thing most likely to cost us the domain. They want their own
        # decision, not inclusion by association with "creator stuff".
        from stripe_link.domain.social_links import linkable_on_platform_host

        for url in ("https://paypal.me/acme", "https://venmo.com/acme", "https://cash.app/$acme"):
            self.assertFalse(linkable_on_platform_host(url), url)

    def test_an_uncurated_host_is_still_refused(self):
        # The list is curated by hand, entry by entry. It is not an open redirect.
        from stripe_link.domain.social_links import linkable_on_platform_host

        self.assertFalse(linkable_on_platform_host("https://shop.example.org/acme"))

    def test_the_list_carries_a_review_date(self):
        from stripe_link.domain.social_links import CREATOR_LINKABLE_HOSTS, PLATFORM_LINKABLE_REVIEWED

        self.assertRegex(PLATFORM_LINKABLE_REVIEWED, r"^\d{4}-\d{2}-\d{2}$")
        for host, why in CREATOR_LINKABLE_HOSTS.items():
            self.assertTrue(why.strip(), host)


class AdultHostInterimTests(unittest.TestCase):
    """Adult hosts are linkable on platform infrastructure ON PURPOSE, and only for now.

    plans/CREATOR_LINK_POLICY.md §4a: they belong on the CREATOR domain (jbay.page) and not on jbay.uk /
    jbay.be, which serve commerce Sites -- blocklists act per registered domain, and the creator domain exists
    to absorb exactly the risk commerce must not carry. The §7 boundary is binary today (own domain vs "a
    platform host") with no way to tell WHICH platform host, so the rule cannot be expressed yet.

    Pinned so the interim is not mistaken for the final answer, and so whoever implements the third tier finds
    this test rather than rediscovering the decision.
    """

    def test_adult_hosts_are_currently_linkable_anywhere_they_are_gated(self):
        from stripe_link.domain.social_links import linkable_on_platform_host

        for host in ADULT_HOSTS:
            self.assertTrue(linkable_on_platform_host(f"https://{host}/acme"), host)

    def test_the_gate_travels_with_them(self):
        # The condition on which the interim is acceptable: they are linkable BECAUSE they are labelled.
        for host in ADULT_HOSTS:
            self.assertTrue(is_adult_host(f"https://{host}/acme"), host)

    def test_the_boundary_still_has_only_two_tiers(self):
        # When this starts failing, §4a is implementable: something now distinguishes one platform host from
        # another, and the adult entries should move behind it.
        import inspect

        from stripe_link.runtime import html

        source = inspect.getsource(html.render_social_links)
        self.assertIn('_RENDER_STATE.get("own_domain")', source)
        self.assertNotIn("jbay.page", source)

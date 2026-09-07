"""YouTube and Vimeo links in the hero media list.

The field used to want a bare `.mp4` while being labelled "Video URL", so pasting the obvious thing -- a
YouTube link -- was accepted and then rendered as a BROKEN IMAGE on the published page. Recognising the
providers is what closes that, and the parse is the security boundary: the id is interpolated into an
iframe src, so it is matched, never trusted.
"""

import unittest

from stripe_link.domain.video_embeds import is_video_embed, parse_video_embed
from stripe_link.runtime.html import (
    render_media_slide,
    render_page_interactions_script,
    render_template_styles,
)


class ParsingTests(unittest.TestCase):
    def test_every_shape_a_tenant_might_paste(self):
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://youtube.com/embed/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=42": "dQw4w9WgXcQ",
            "youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                parsed = parse_video_embed(url)
                self.assertIsNotNone(parsed, url)
                self.assertEqual(parsed["video_id"], expected)
                self.assertEqual(parsed["provider"], "youtube")

    def test_vimeo_shapes(self):
        for url in ("https://vimeo.com/123456789",
                    "https://player.vimeo.com/video/123456789",
                    "https://vimeo.com/channels/staffpicks/123456789"):
            with self.subTest(url=url):
                parsed = parse_video_embed(url)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed["video_id"], "123456789")
                self.assertEqual(parsed["provider"], "vimeo")

    def test_a_video_file_is_not_an_embed(self):
        # It still has to reach the <video> branch, which is a different and still-supported thing.
        self.assertIsNone(parse_video_embed("https://cdn.example.com/clip.mp4"))

    def test_only_the_real_providers_count(self):
        # A lookalike host must not get an iframe pointed at it.
        for url in ("https://evil.com/watch?v=abc", "https://youtube.com.evil.com/watch?v=abc",
                    "https://notvimeo.com/123456789", "", None, "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertFalse(is_video_embed(url))

    def test_the_id_is_matched_not_trusted(self):
        """It is interpolated into an iframe src, so anything outside [A-Za-z0-9_-] must be refused."""
        for bad in ("https://youtube.com/watch?v=../../etc",
                    "https://youtube.com/watch?v=abc&evil=1#x",
                    "https://youtube.com/embed/a b c",
                    "https://vimeo.com/12"):
            with self.subTest(bad=bad):
                parsed = parse_video_embed(bad)
                if parsed:
                    self.assertRegex(parsed["video_id"], r"^[A-Za-z0-9_-]+$")

    def test_youtube_uses_the_no_cookie_host(self):
        # No tracking cookie is set on the tenant's customers unless someone actually plays.
        parsed = parse_video_embed("https://youtu.be/dQw4w9WgXcQ")
        self.assertIn("youtube-nocookie.com", parsed["embed_url"])


class FacadeTests(unittest.TestCase):
    """Click-to-load, not a bare iframe.

    A provider iframe pulls roughly a megabyte of script and sets third-party cookies whether or not
    anyone watches. The facade costs one image and shares nothing until a visitor asks.
    """

    def test_nothing_from_the_provider_loads_until_a_click(self):
        html = render_media_slide("https://youtu.be/dQw4w9WgXcQ", "Our story", autoplay=False)
        self.assertNotIn("<iframe", html, "the iframe must be created by the click, not shipped in the page")
        self.assertIn("data-sl-embed", html)

    def test_the_poster_comes_from_a_deterministic_url(self):
        # hqdefault always exists; maxresdefault does not, and a missing one renders as a grey 404 image.
        html = render_media_slide("https://youtu.be/dQw4w9WgXcQ", "x", autoplay=False)
        self.assertIn("hqdefault.jpg", html)

    def test_vimeo_falls_back_to_a_neutral_poster(self):
        # Vimeo thumbnails need an oEmbed lookup; adding a network call to publish is the wrong trade.
        html = render_media_slide("https://vimeo.com/123456789", "x", autoplay=False)
        self.assertIn("is-blank", html)
        self.assertNotIn("<img", html)

    def test_play_is_a_real_button(self):
        html = render_media_slide("https://youtu.be/dQw4w9WgXcQ", "Our story", autoplay=False)
        self.assertIn("<button", html)
        self.assertIn('aria-label="Play Our story"', html)

    def test_the_title_is_escaped(self):
        html = render_media_slide("https://youtu.be/dQw4w9WgXcQ", '"><script>x</script>', autoplay=False)
        self.assertNotIn("<script>", html)

    def test_a_file_url_still_renders_a_video_element(self):
        html = render_media_slide("https://cdn/clip.mp4", "x", autoplay=False)
        self.assertIn("<video", html)
        self.assertNotIn("sl-embed", html)

    def test_the_stylesheet_covers_what_the_markup_uses(self):
        css = "\n".join(render_template_styles({}))
        for cls in (".sl-embed{", ".sl-embed-play", ".sl-embed-poster", ".sl-embed iframe"):
            with self.subTest(cls=cls):
                self.assertIn(cls, css)


class ScriptTests(unittest.TestCase):
    def test_a_page_with_an_embed_gets_the_handler(self):
        page = {"page_id": "p", "sections": [{"type": "hero_media",
                                              "images": ["https://youtu.be/dQw4w9WgXcQ"]}]}
        self.assertIn("data-sl-embed", render_page_interactions_script(page))

    def test_a_page_without_one_carries_no_dead_handler(self):
        page = {"page_id": "p", "sections": [{"type": "hero_media", "images": ["https://x/a.jpg"]}]}
        self.assertEqual(render_page_interactions_script(page), "")


class PosterTests(unittest.TestCase):
    """A tenant-supplied poster, because the provider's is not always available or good.

    Vimeo has no deterministic thumbnail without an oEmbed lookup, so without this it has no poster at all.
    YouTube's exists but is an auto-picked frame, often a blurred mid-sentence.
    """

    SECTION = {"id": "h", "type": "hero_media", "images": ["https://vimeo.com/123456789"]}

    def test_vimeo_without_a_poster_falls_back_to_the_neutral_one(self):
        from stripe_link.runtime.html import render_hero_media
        self.assertIn("is-blank", render_hero_media(self.SECTION, {"name": "X"}, {}, {}))

    def test_a_supplied_poster_is_used(self):
        from stripe_link.runtime.html import render_hero_media
        html = render_hero_media(self.SECTION, {"name": "X"}, {}, {},
                                 {"https://vimeo.com/123456789": "https://cdn/poster.webp"})
        self.assertIn("cdn/poster.webp", html)
        self.assertNotIn("is-blank", html)

    def test_a_poster_overrides_youtubes_own(self):
        from stripe_link.runtime.html import render_hero_media
        section = {**self.SECTION, "images": ["https://youtu.be/dQw4w9WgXcQ"]}
        html = render_hero_media(section, {"name": "X"}, {}, {},
                                 {"https://youtu.be/dQw4w9WgXcQ": "https://cdn/better.webp"})
        self.assertIn("cdn/better.webp", html)
        self.assertNotIn("hqdefault", html)

    def test_posters_for_other_urls_do_not_leak(self):
        from stripe_link.runtime.html import render_hero_media
        html = render_hero_media(self.SECTION, {"name": "X"}, {}, {},
                                 {"https://youtu.be/somethingelse": "https://cdn/wrong.webp"})
        self.assertNotIn("cdn/wrong.webp", html)

    def test_the_builder_persists_them(self):
        # The save payload is an ALLOW-LIST: a field the builder holds but does not list is dropped without
        # complaint, and the poster would vanish on the first save.
        import pathlib
        builder = (pathlib.Path(__file__).resolve().parents[1]
                   / "dashboard/src/components/LandingPages.vue").read_text()
        self.assertIn("video_posters: { ...builder.video_posters }", builder)
        self.assertIn("builder.video_posters = { ...(page.video_posters || {}) }", builder)


class CarouselTests(unittest.TestCase):
    """Leaving a slide has to silence it.

    Two embeds could otherwise play over each other, and the visitor cannot find the one making noise --
    by then its iframe has scrolled off screen.
    """

    def _script(self):
        page = {"page_id": "p", "sections": [{"type": "hero_media",
                                              "images": ["https://youtu.be/dQw4w9WgXcQ",
                                                         "https://vimeo.com/123456789"]}]}
        return render_page_interactions_script(page)

    def test_changing_slide_removes_other_slides_iframes(self):
        self.assertIn("slide.querySelectorAll('[data-sl-embed] iframe').forEach((f) => f.remove())",
                      self._script())

    def test_changing_slide_pauses_file_video(self):
        self.assertIn("v.pause()", self._script())

    def test_the_facade_survives_playing_so_it_can_be_returned_to(self):
        # replaceChildren destroyed the poster and button, leaving nothing to restore after stopping.
        script = self._script()
        self.assertIn("box.appendChild(frame)", script)
        self.assertNotIn("box.replaceChildren(frame)", script)


class BuilderContractTests(unittest.TestCase):
    """The builder refuses what the renderer cannot draw, and vice versa."""

    def _field(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1]
                / "dashboard/src/components/shared/MediaListField.vue").read_text()

    def test_the_builder_validates_before_accepting(self):
        source = self._field()
        self.assertIn("VIDEO_LINK", source)
        self.assertIn("Paste a YouTube or Vimeo link", source,
                      "silently accepting an unusable link is what produced a broken published page")

    def test_the_button_says_what_it_takes(self):
        self.assertIn("YouTube / Vimeo", self._field(),
                      '"Video URL" invited the very links it could not render')

    def test_the_stale_no_video_upload_comment_is_gone(self):
        # Video upload works (verified 2026-08-30); the comment claimed otherwise.
        self.assertNotIn("stripe-link doesn't have yet", self._field())


if __name__ == "__main__":
    unittest.main()

"""The standalone Video element: one video anywhere on the page.

Almost entirely placement. Choosing between an uploaded file and a YouTube/Vimeo link already lives in
render_media_slide, so this element inherits the click-to-load facade, the poster handling and the provider
parsing without restating any of them -- which is the point of having built embeds first.
"""

import unittest

from stripe_link.runtime.html import render_template_styles, render_video

EMBED = {"id": "v", "type": "video", "url": "https://youtu.be/dQw4w9WgXcQ"}
FILE = {"id": "v", "type": "video", "url": "https://cdn.example.com/clip.mp4"}


class RenderTests(unittest.TestCase):
    def test_a_link_renders_the_click_to_load_facade(self):
        html = render_video(EMBED)
        self.assertIn("data-sl-embed", html)
        self.assertNotIn("<iframe", html, "nothing reaches the provider until a visitor asks")

    def test_a_file_renders_a_video_element(self):
        self.assertIn("<video", render_video(FILE))

    def test_without_a_url_it_renders_nothing(self):
        for section in ({"id": "v"}, {"id": "v", "url": "   "}):
            with self.subTest(section=section):
                self.assertEqual(render_video(section), "")

    def test_the_heading_and_caption_are_optional(self):
        html = render_video(EMBED)
        self.assertNotIn("sl-video-heading", html)
        self.assertNotIn("sl-video-caption", html)

    def test_they_render_when_given(self):
        html = render_video({**EMBED, "heading": "See it work", "caption": "Two minutes."})
        self.assertIn("sl-video-heading", html)
        self.assertIn("Two minutes.", html)

    def test_the_caption_is_escaped(self):
        html = render_video({**EMBED, "caption": '<script>alert(1)</script>'})
        self.assertNotIn("<script>", html)

    def test_a_poster_is_used_for_an_embed(self):
        html = render_video({**EMBED, "poster": "https://cdn/poster.webp"})
        self.assertIn("cdn/poster.webp", html)
        self.assertNotIn("hqdefault", html, "the tenant's poster wins over the provider's frame")


class AutoplayTests(unittest.TestCase):
    def test_it_never_autoplays(self):
        """A video that starts itself halfway down a page is noise the reader did not ask for, and content
        playing more than five seconds with no way to stop it fails WCAG 2.2.2. The hero is a different
        case -- the visitor has just arrived and the media IS the first impression."""
        html = render_video(FILE)
        self.assertIn("<video", html)
        self.assertNotIn("autoplay", html)

    def test_the_file_player_keeps_its_controls(self):
        self.assertIn("controls", render_video(FILE))


class StyleTests(unittest.TestCase):
    def test_the_stylesheet_covers_the_markup(self):
        css = "\n".join(render_template_styles({}))
        for cls in (".sl-video-block", ".sl-video-frame", ".sl-video-heading", ".sl-video-caption"):
            with self.subTest(cls=cls):
                self.assertIn(cls, css)

    def test_an_uploaded_file_is_given_a_shape(self):
        # An embed brings its own aspect-ratio box; a bare <video> would otherwise size to its intrinsic
        # dimensions and jump the layout once metadata loads.
        css = "\n".join(render_template_styles({}))
        self.assertIn(".sl-video-frame>video", css)
        self.assertIn("aspect-ratio:16/9", css)


class RegistrationTests(unittest.TestCase):
    def test_it_is_registered_for_rendering(self):
        # Registering in composition_rules without registering a renderer makes an element addable and then
        # invisible -- caught by the shared guard, asserted here too so the reason is written down.
        from stripe_link.runtime.html import SECTION_REGISTRY
        self.assertIn("video", SECTION_REGISTRY)

    def test_the_builder_agrees_about_what_a_link_is(self):
        """The builder offers a poster field only for embeds. If its idea of a link differed from the
        renderer's, it would promise a poster for something rendered as a file, or withhold one from a
        video that needs it."""
        import pathlib
        builder = (pathlib.Path(__file__).resolve().parents[1]
                   / "dashboard/src/components/LandingPages.vue").read_text()
        self.assertIn("EMBED_LINK", builder)
        for provider in ("youtube", "youtu\\.be", "vimeo"):
            with self.subTest(provider=provider):
                self.assertIn(provider, builder)


if __name__ == "__main__":
    unittest.main()

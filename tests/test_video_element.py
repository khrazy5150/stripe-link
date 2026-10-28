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
    """Autoplay and the control bar are the tenant's choice, and the QUIET setting is the default.

    A video that starts itself halfway down a page is noise the reader did not ask for, so an element that
    says nothing autoplays nothing -- which also means every page published before these options existed
    renders exactly as it did.
    """

    def test_it_does_not_autoplay_unless_asked(self):
        html = render_video(FILE)
        self.assertIn("<video", html)
        self.assertNotIn("autoplay", html)

    def test_asking_for_autoplay_gets_it(self):
        self.assertIn("autoplay", render_video({**FILE, "autoplay": True}))

    def test_autoplay_is_always_muted_and_looping(self):
        """`muted` is not a taste decision. Every browser refuses to autoplay a video with sound, so an
        autoplay attribute without it is a checkbox that silently does nothing -- the tenant ticks it,
        nothing moves, and no error anywhere explains why. `loop` because a silent clip that stops dead on
        its last frame reads as broken."""
        html = render_video({**FILE, "autoplay": True})
        for attribute in ("muted", "loop", "autoplay"):
            self.assertIn(attribute, html, attribute)

    def test_autoplay_never_appears_without_muted(self):
        """The invariant stated as its own test, because this is the one that can rot: a later edit that
        reorders the attribute list could drop `muted` and nothing else here would notice."""
        for section in (FILE, {**FILE, "autoplay": True}, {**FILE, "autoplay": True, "hide_controls": True}):
            html = render_video(section)
            if "autoplay" in html:
                self.assertIn("muted", html, section)

    def test_autoplay_preloads_the_file(self):
        """`preload="metadata"` with autoplay asks the browser to start something it was told not to
        fetch."""
        self.assertIn('preload="auto"', render_video({**FILE, "autoplay": True}))


class ControlBarTests(unittest.TestCase):
    """Hiding the bar REPLACES it rather than removing the ability to stop the video.

    A chromeless looping product clip is a real design; a muted video playing with no way to pause it is a
    WCAG 2.2.2 failure. The difference between the two is entirely whether something else can still pause
    it, so that something is what these tests are about.
    """

    def test_the_bar_is_there_by_default(self):
        self.assertIn("controls", render_video(FILE))

    def test_hiding_it_removes_the_attribute(self):
        self.assertNotIn("controls", render_video({**FILE, "hide_controls": True}))

    def test_hiding_it_makes_the_video_its_own_control(self):
        html = render_video({**FILE, "hide_controls": True})
        self.assertIn("data-sl-video-tap", html)
        self.assertIn('tabindex="0"', html, "a keyboard must be able to reach the only remaining control")

    def test_a_video_keeping_its_bar_is_not_made_tappable(self):
        """Two controls for one action, one of them invisible: a click would pause a video whose own
        button says it is playing."""
        self.assertNotIn("data-sl-video-tap", render_video(FILE))

    def test_the_page_script_carries_the_handler(self):
        """The attribute alone is inert -- without the listener, hiding the bar really would remove the
        only way to stop the video."""
        from stripe_link.runtime.html import render_page_interactions_script

        page = {"sections": [{"id": "v", "type": "video", "url": FILE["url"], "hide_controls": True}]}
        script = render_page_interactions_script(page)
        self.assertIn("data-sl-video-tap", script)
        self.assertIn("video.pause()", script)

    def test_a_page_whose_only_interaction_is_the_video_still_gets_the_script(self):
        """The script has an early return for a page that needs no interactions. A chromeless video needs
        one -- the tap handler is the only remaining way to pause it -- so it has to count as a reason to
        emit the script, or the attribute ships inert and the bar really was just removed."""
        from stripe_link.runtime.html import render_page_interactions_script

        page = {"sections": [{"id": "v", "type": "video", "url": FILE["url"], "hide_controls": True}]}
        self.assertNotEqual(render_page_interactions_script(page), "")

    def test_a_page_with_a_normal_video_needs_no_script_for_it(self):
        """The flag is specific to the chromeless case; a video keeping its own bar adds no JavaScript."""
        from stripe_link.runtime.html import render_page_interactions_script

        page = {"sections": [{"id": "v", "type": "video", "url": FILE["url"]}]}
        self.assertEqual(render_page_interactions_script(page), "")

    def test_the_stylesheet_says_it_is_clickable(self):
        styles = "\n".join(render_template_styles({}))
        self.assertIn("video[data-sl-video-tap]{cursor:pointer}", styles)
        self.assertIn("video[data-sl-video-tap]:focus-visible", styles)


class EmbedsIgnoreBothTests(unittest.TestCase):
    """A YouTube/Vimeo link is a click-to-load facade, and that is a PRIVACY decision, not a style one.

    Autoplaying one would mean loading a megabyte of third-party script and setting cookies on the
    tenant's customers before anyone chose to watch. The builder hides both checkboxes for an embed; these
    pin that the renderer would not honour them even if a stored document carried them.
    """

    def test_neither_flag_changes_what_an_embed_renders(self):
        """Asserted as equality rather than by hunting for the word "autoplay": the facade's own embed URL
        legitimately carries `autoplay=1`, because the click a visitor makes IS the gesture the browser
        requires, and the iframe is built only then. Equality says the thing that matters -- the tenant's
        flags reached nothing."""
        plain = render_video(EMBED)
        self.assertEqual(render_video({**EMBED, "autoplay": True}), plain)
        self.assertNotIn("<video", plain)
        self.assertNotIn("<iframe", plain, "nothing reaches the provider until a visitor asks")

    def test_an_embed_is_unaffected_by_hiding_controls(self):
        self.assertEqual(render_video({**EMBED, "hide_controls": True}), render_video(EMBED))


class TheHeroIsUntouchedTests(unittest.TestCase):
    """`controls` gained a default rather than a caller. Every existing call site must emit what it did."""

    def test_the_hero_player_is_byte_identical(self):
        from stripe_link.runtime.html import render_media_slide

        url = "https://cdn.example.com/clip.mp4"
        self.assertEqual(
            render_media_slide(url, "Hero", autoplay=True),
            '<video class="sl-hero-video" src="https://cdn.example.com/clip.mp4" '
            'controls playsinline muted loop autoplay preload="auto" aria-label="Hero"></video>',
        )

    def test_a_still_hero_is_byte_identical(self):
        from stripe_link.runtime.html import render_media_slide

        url = "https://cdn.example.com/clip.mp4"
        self.assertEqual(
            render_media_slide(url, "Hero", autoplay=False),
            '<video class="sl-hero-video" src="https://cdn.example.com/clip.mp4" '
            'controls playsinline preload="metadata" aria-label="Hero"></video>',
        )


class BuilderRoundTripTests(unittest.TestCase):
    """Source assertions, because this is Vue. A write-only field is lost on reload, which reads to the
    tenant as the builder throwing away what they just set."""

    BUILDER = ""

    @classmethod
    def setUpClass(cls):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
        cls.BUILDER = (root / "components" / "LandingPages.vue").read_text(encoding="utf-8")

    def test_the_element_starts_with_both_switched_off(self):
        self.assertIn("autoplay: false, hide_controls: false", self.BUILDER)

    def test_both_are_sent_on_save(self):
        self.assertIn("autoplay: element.autoplay || undefined", self.BUILDER)
        self.assertIn("hide_controls: element.hide_controls || undefined", self.BUILDER)

    def test_both_are_read_back_on_load(self):
        self.assertIn("autoplay: Boolean(section.autoplay)", self.BUILDER)
        self.assertIn("hide_controls: Boolean(section.hide_controls)", self.BUILDER)

    def test_the_switches_are_hidden_for_an_embed(self):
        """Offering a control that would quietly do nothing is worse than not offering it."""
        self.assertIn('<template v-if="!isEmbedLink(element.url)">', self.BUILDER)


class StyleTests(unittest.TestCase):
    def test_the_stylesheet_covers_the_markup(self):
        css = "\n".join(render_template_styles({}))
        for cls in (".sl-video-block", ".sl-video-frame", ".sl-video-heading", ".sl-video-caption"):
            with self.subTest(cls=cls):
                self.assertIn(cls, css)

    def test_the_frame_carries_the_shape_so_the_layout_does_not_jump(self):
        # A bare <video> sizes to its intrinsic dimensions and jumps the layout once metadata loads, so the
        # FRAME holds the shape and the player fills it.
        css = "\n".join(render_template_styles({}))
        self.assertIn(".sl-video-frame{aspect-ratio:var(--sl-video-ar,16/9)}", css)


class ShapeTests(unittest.TestCase):
    """The frame follows the VIDEO, not the page.

    Vertical video is the common case now. Forcing 16/9 on it either letterboxes it into a stripe or, with
    object-fit: cover, crops the subject straight out of frame -- which is what this element did at first.
    """

    def test_the_default_is_landscape(self):
        self.assertIn("--sl-video-ar:1.77778", render_video(FILE))

    def test_a_vertical_video_gets_a_vertical_frame(self):
        html = render_video({**FILE, "aspect": 9 / 16})
        self.assertIn("--sl-video-ar:0.5625", html)

    def test_the_shape_reaches_an_embed_too(self):
        # The embed box has its own aspect-ratio, so the element has to override it or a linked vertical
        # video sits letterboxed inside a landscape box.
        html = render_video({**EMBED, "aspect": 9 / 16})
        self.assertIn("--sl-embed-ar:0.5625", html)

    def test_a_tall_video_is_bounded(self):
        # Unbounded, a 9:16 frame at full page width runs several screens tall on a desktop.
        self.assertIn("is-tall", render_video({**FILE, "aspect": 9 / 16}))
        self.assertNotIn("is-tall", render_video({**FILE, "aspect": 16 / 9}))

    def test_a_nonsense_shape_falls_back(self):
        for aspect in ("wide", 0, -3, 50, 0.01, None):
            with self.subTest(aspect=aspect):
                self.assertIn("--sl-video-ar:1.77778", render_video({**FILE, "aspect": aspect}))

    def test_a_mismatched_shape_letterboxes_rather_than_crops(self):
        """contain, not cover. If the chosen shape does not match the source, black bars are honest --
        cropping silently removes whatever the tenant was pointing at."""
        css = "\n".join(render_template_styles({}))
        self.assertIn(".sl-video-frame>video{display:block;width:100%;height:100%;object-fit:contain", css)

    def test_the_embed_default_is_unchanged_for_everyone_else(self):
        # The hero and every page published before today must keep their 16/9 box.
        css = "\n".join(render_template_styles({}))
        self.assertIn("aspect-ratio:var(--sl-embed-ar,16/9)", css)

    def test_the_builder_measures_a_file_rather_than_asking(self):
        import pathlib
        builder = (pathlib.Path(__file__).resolve().parents[1]
                   / "dashboard/src/components/LandingPages.vue").read_text()
        self.assertIn("videoAspectOf", builder)
        self.assertIn("probe.videoWidth", builder,
                      "the browser knows the real shape; asking the tenant for it is a worse default")


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

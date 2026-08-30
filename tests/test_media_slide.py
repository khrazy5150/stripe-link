import unittest

from stripe_link.runtime.html import render_media_slide


class MediaSlideTests(unittest.TestCase):
    VIDEO = "https://images.juniorbay.net/videos/x/original.mp4"
    IMAGE = "https://images.juniorbay.net/photos/x/original.jpg"

    def test_autoplay_video_still_offers_controls(self):
        # Autoplay must start muted (browser policy), so without controls a visitor has no way to hear
        # the audio, pause, or scrub. Reported from sandbox 2026-08-30: the only workaround was for the
        # tenant to disable autoplay and re-save the page.
        html = render_media_slide(self.VIDEO, "Demo", autoplay=True)
        self.assertIn("controls", html)
        self.assertIn("muted", html)
        self.assertIn("autoplay", html)
        self.assertIn("loop", html)

    def test_non_autoplay_video_is_unchanged(self):
        html = render_media_slide(self.VIDEO, "Demo", autoplay=False)
        self.assertIn("controls", html)
        for attr in ("autoplay", "loop"):
            self.assertNotIn(attr, html)
        # Not muted either — a click-to-play video should have sound.
        self.assertNotIn("muted", html)

    def test_video_carries_playsinline_either_way(self):
        # Without it, iOS Safari takes the video fullscreen on play and the page is lost.
        for autoplay in (True, False):
            with self.subTest(autoplay=autoplay):
                self.assertIn("playsinline", render_media_slide(self.VIDEO, "Demo", autoplay=autoplay))

    def test_an_image_url_is_not_rendered_as_video(self):
        self.assertNotIn("<video", render_media_slide(self.IMAGE, "Photo", autoplay=True))


if __name__ == "__main__":
    unittest.main()

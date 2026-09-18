"""The crop dialog says when it is working.

Author, 2026-09-17: "when an image is cropped, the button doesn't disable/change while the process is taking
place. This gives the false impression to the user that nothing is happening."

Applying a crop is a round trip to the image service and the DIALOG STAYS OPEN for it. Every caller already
tracked that work for its own buttons -- `uploading` in ImageUploadField, `cropBusy` in the other two -- and
none of them passed it to the dialog, which is the only thing the tenant is looking at while it runs. The
state existed; it just never reached the screen.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components"
CROPPER = (ROOT / "shared" / "ImageCropper.vue").read_text(encoding="utf-8")
# Every surface that opens the cropper, and the in-flight flag it already had.
CALLERS = {
    "shared/ImageUploadField.vue": "uploading",
    "shared/MediaListField.vue": "cropBusy",
    "Products.vue": "cropBusy",
}


class DialogTests(unittest.TestCase):
    def test_the_apply_button_disables_and_says_so(self):
        self.assertIn(':disabled="!natural.width || busy"', CROPPER)
        self.assertIn('busy ? "Applying…" : "Use this photo"', CROPPER)

    def test_a_second_click_cannot_upload_the_same_crop_twice(self):
        # Belt and braces with the disabled attribute, which a keyboard submit can still slip past.
        self.assertIn("if (props.busy) return;", CROPPER)

    def test_it_cannot_be_dismissed_mid_flight(self):
        """Cancelling does not abort the request.

        Closing the dialog would leave the tenant looking at the old image while the new one was still being
        written -- the same false impression, one step later.
        """
        self.assertIn("busy || emit('cancel')", CROPPER)
        self.assertIn('class="secondary-action" :disabled="busy"', CROPPER)

    def test_assistive_tech_is_told_as_well(self):
        self.assertIn(':aria-busy="busy"', CROPPER)


class CallerTests(unittest.TestCase):
    def test_every_caller_passes_its_flag(self):
        for name, flag in CALLERS.items():
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("<ImageCropper", source, name)
            self.assertIn(f':busy="{flag}"', source, name)

    def test_and_that_flag_is_a_real_ref_in_that_component(self):
        """A template referencing an undefined name builds clean and renders nothing.

        This dashboard has no linter (plans/TODO.md), so the one thing a test can do cheaply is check that
        what the template reads is actually declared where it is read.
        """
        for name, flag in CALLERS.items():
            setup = (ROOT / name).read_text(encoding="utf-8").rsplit("<script setup>", 1)[-1]
            self.assertRegex(setup, r"\b(?:const|let)\s+" + flag + r"\s*=\s*ref\(", name)

    def test_the_flag_is_held_for_the_whole_round_trip(self):
        # Set before the await and cleared in a finally, or the dialog would flicker rather than wait.
        for name, flag in CALLERS.items():
            source = (ROOT / name).read_text(encoding="utf-8")
            handler = re.search(r"async function apply\w*\(rect\) \{(.+?)\n\}", source, re.S).group(1)
            self.assertLess(handler.index(f"{flag}.value = true"), handler.index("await cropImage("), name)
            self.assertIn(f"{flag}.value = false", handler.split("finally", 1)[-1], name)


if __name__ == "__main__":
    unittest.main()

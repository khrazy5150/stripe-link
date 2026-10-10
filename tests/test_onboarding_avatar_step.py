"""Onboarding asks for a store photo, and the cropper is finally wired to it.

A tenant who is asked once, while already setting things up, will add a photo. One who is not will never
go looking for it in Preferences — which is why this is a wizard step rather than a nudge.

The cropper existed the whole time and said so in its own docstring ("a circular avatar is not
negotiable"). Preferences had a bare file input and the advice "A square image works best; it is shown
as a circle", which is the software asking the tenant to crop in their head and then centre-cropping
whatever they gave it anyway. Both surfaces now use one field.

Source-level, because the dashboard has no JS test runner.
"""
import pathlib
import unittest

UI = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components"


def read(name):
    return (UI / name).read_text()


class TheWizardHasAPhotoStep(unittest.TestCase):
    def test_the_step_is_named_in_the_progress_rail(self):
        """Named, not numbered: the rail tells a tenant what is left, not just how far along."""
        self.assertIn('"Photo"', read("Dashboard.vue"))

    def test_it_renders_as_its_own_step(self):
        self.assertIn("wizardStep === 4", read("Dashboard.vue"))

    def test_the_previous_step_stops_being_the_catch_all(self):
        """Step 3 was `v-else`. Leaving it that way would render it alongside step 4."""
        source = read("Dashboard.vue")
        self.assertIn('v-else-if="wizardStep === 3"', source)

    def test_it_is_optional_and_says_so(self):
        source = read("Dashboard.vue")
        self.assertIn("Optional", source)
        self.assertIn("Skip for now", source)

    def test_it_saves_through_the_store_not_a_local_copy(self):
        """The topbar pill reads profileStore.storeAvatarUrl; a second copy would leave it stale."""
        source = read("Dashboard.vue")
        self.assertIn("profileStore.storeAvatarUrl", source)
        self.assertIn("/tenant/avatar", source)


class BothSurfacesUseOneField(unittest.TestCase):
    def test_onboarding_and_preferences_share_it(self):
        for screen in ("Dashboard.vue", "Preferences.vue"):
            self.assertIn("StoreAvatarField", read(screen), screen)

    def test_the_old_bare_file_input_is_gone(self):
        """Not left behind: a second upload path is one someone wires back up."""
        source = read("Preferences.vue")
        for dead in ("storeAvatarInput", "onStoreAvatarPicked", "clearStoreAvatar"):
            self.assertNotIn(dead, source, f"{dead} survived the conversion")

    def test_the_stale_advice_is_gone(self):
        self.assertNotIn("A square image works best", read("Preferences.vue"))


class TheCropIsCircularAndBaked(unittest.TestCase):
    def test_the_ratio_is_locked_to_a_square(self):
        """A circular avatar is not negotiable — the cropper's own words."""
        self.assertIn(':ratios="1"', read("shared/StoreAvatarField.vue"))

    def test_the_crop_is_baked_into_the_file(self):
        """The avatar reaches the page ribbon and eventually og:image, where no stylesheet can follow,
        so a CSS crop would send the uncropped photo to Facebook."""
        source = read("shared/StoreAvatarField.vue")
        self.assertIn("bake", source)
        self.assertIn("bake-width", source)

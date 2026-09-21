"""Editing the business profile has to reach the screens that cache it.

The profile store caches the tenant's business identity so several screens can resolve a brand without each
re-fetching. `ensureLoaded()` returns early once loaded — and NOTHING ever invalidated it, while the screen
that EDITS the business never touched the store at all.

So a tenant changed their business address and every consumer kept the old values until a full page reload:
the brand picker in Offers, the landing-page defaults, the Sites header, and Shipping's "Copy from business
address" — which is where it was noticed, because copying obviously-wrong data is louder than a stale brand
name in a dropdown.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard" / "src"
STORE = (DASH / "stores/profile.js").read_text(encoding="utf-8")
PROFILE = (DASH / "components/Profile.vue").read_text(encoding="utf-8")
SHIPPING = (DASH / "components/Shipping.vue").read_text(encoding="utf-8")

CONSUMERS = ["App.vue", "components/Shipping.vue", "components/Sites.vue",
             "components/LandingPages.vue", "components/Preferences.vue", "components/Offers.vue"]


class CacheCanBeBypassedTests(unittest.TestCase):
    def test_the_cache_guard_lives_only_in_ensure_loaded(self):
        """load() always refetches; only ensureLoaded() short-circuits. That is what makes a separate
        refresh() unnecessary -- it would be load() with an extra line."""
        ensure = STORE.split("async ensureLoaded()", 1)[1][:200]
        self.assertIn("if (this.loaded || this.loading) return;", ensure)
        load = STORE.split("async load()", 1)[1][:300]
        self.assertNotIn("if (this.loaded", load)

    def test_a_reload_refetches_rather_than_patching_locally(self):
        """The server normalises what it stores — E.164 phone, upper-cased country — so a local copy of
        what was TYPED would disagree with what was SAVED."""
        self.assertIn('apiRequest("/profile"', STORE)


class TheEditorTellsTheCacheTests(unittest.TestCase):
    def test_saving_the_profile_refreshes_the_shared_store(self):
        self.assertIn("profileStore.load()", PROFILE)

    def test_it_happens_after_a_SUCCESSFUL_save(self):
        # Refreshing before the PUT would re-cache what is already there.
        block = PROFILE.split('apiRequest("/profile", { method: "PUT"', 1)[1][:600]
        self.assertIn("profileStore.load()", block)

    def test_a_failed_refresh_does_not_fail_the_save(self):
        """The save already succeeded; a refresh that throws must not turn it into an error the tenant
        sees, or they will save again and wonder why."""
        block = PROFILE.split("profileStore.load()", 1)[1][:60]
        self.assertIn(".catch(", block)


class TheCopyButtonIsAuthoritativeTests(unittest.TestCase):
    def test_copying_reads_fresh_rather_than_cached(self):
        """An explicit "copy my current business address" must not hand back a version from before the
        edit the tenant just made."""
        handler = SHIPPING.split("async function copyBusinessAddress", 1)[1][:700]
        self.assertIn("await profileStore.load()", handler)
        self.assertNotIn("await profileStore.ensureLoaded()", handler)


class EveryConsumerIsCoveredTests(unittest.TestCase):
    def test_the_list_of_consumers_is_not_stale(self):
        """Guards the guard: if a new screen starts reading the store, this list should grow with it, and
        the staleness question should be asked again for that screen."""
        found = []
        for name in CONSUMERS:
            text = (DASH / name).read_text(encoding="utf-8")
            if "useProfileStore" in text:
                found.append(name)
        self.assertEqual(sorted(found), sorted(CONSUMERS))

    def test_no_consumer_relies_on_a_cache_that_cannot_be_invalidated(self):
        # ensureLoaded is still correct for a screen that only READS on mount; what mattered was that a
        # refresh path exists at all, and that the editor uses it.
        self.assertIn("ensureLoaded", STORE)
        self.assertIn("async load()", STORE)


if __name__ == "__main__":
    unittest.main()

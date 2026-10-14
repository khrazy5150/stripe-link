"""The Events screen (plans/WEBINAR.md P1 §12.1).

Until this exists a tenant cannot create an event at all, so it is the gating piece of P1. Checked the way
this repo checks its other Vue surfaces — by reading the source — because the logic worth protecting here is
what the screen SENDS, not how it looks.
"""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = (ROOT / "dashboard" / "src" / "components" / "Events.vue").read_text(encoding="utf-8")
STORE = (ROOT / "dashboard" / "src" / "stores" / "events.js").read_text(encoding="utf-8")
MENU = (ROOT / "dashboard" / "src" / "config" / "menu.js").read_text(encoding="utf-8")
APP = (ROOT / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")


class ItIsReachable(unittest.TestCase):
    def test_the_menu_has_an_entry(self):
        self.assertIn('key: "events"', MENU)
        self.assertIn('view: "events"', MENU)

    def test_the_entry_is_in_a_GROUP_and_therefore_rendered(self):
        """The bug this exists to prevent, found 2026-10-14 from a screenshot of the sidebar: the item map
        and the GROUPS are two separate lists, and only the groups decide what is drawn. The entry existed,
        was correct, and appeared nowhere -- and the first version of this test checked only the map."""
        import re
        groups = re.search(r"groups: \[(.*?)\n  \]", MENU, re.S).group(1)
        self.assertIn('"events"', groups)

    def test_every_item_is_reachable_from_some_group(self):
        """Derived rather than listed, so the next entry added to the map cannot go unrendered either."""
        import re
        groups = re.search(r"groups: \[(.*?)\n  \]", MENU, re.S).group(1)
        grouped = set(re.findall(r'"(\w+)"', groups))
        declared = set(re.findall(r"^    (\w+): \{", MENU, re.M))
        self.assertEqual(declared - grouped, set(),
                         "these menu items are defined but in no group, so nothing draws them")

    def test_its_icon_exists(self):
        """A menu entry naming a glyph the icon map lacks renders an empty square."""
        icon = MENU[MENU.index('key: "events"'):][:200]
        name = icon.split('icon: "')[1].split('"')[0]
        self.assertIn(f"  {name}:", MENU)

    def test_the_view_is_mounted(self):
        self.assertIn("activeView === 'events'", APP)
        self.assertIn('import Events from "./components/Events.vue"', APP)

    def test_it_is_not_keyed_on_the_environment(self):
        """Events are not mode-scoped: a tenant flipping test/live must not find their sessions gone."""
        mount = APP[APP.index("activeView === 'events'"):][:200]
        self.assertNotIn("activeEnvironment", mount)


class WhatItSends(unittest.TestCase):
    def test_a_session_with_no_date_is_dropped_not_refused(self):
        """A half-filled row is a tenant who changed their mind; failing the save over it would lose
        everything else they typed."""
        self.assertIn("filter((row) => row.starts_at)", SCREEN)

    def test_numbers_are_sent_as_numbers(self):
        """The validator refuses a string capacity, and the tenant would see a save fail with no clue."""
        self.assertIn("capacity: Number(row.capacity) || 0", SCREEN)

    def test_each_session_gets_its_own_id(self):
        """Registrations point at an occurrence by id, and the validator refuses duplicates."""
        self.assertIn('localId("occ")', SCREEN)

    def test_the_zone_defaults_from_the_business_but_is_per_session(self):
        """A Denver business can run one sitting announced in EST and another in AEST."""
        self.assertIn("profileStore.business?.timezone", SCREEN)
        self.assertIn("timeZoneOptions(row.timezone)", SCREEN)


class WhatItProtects(unittest.TestCase):
    def test_cancel_really_cancels(self):
        """Editing the stored object would leave the list showing changes that were never saved."""
        self.assertIn("occurrences: (item.occurrences || []).map((row) => ({ ...row }))", SCREEN)

    def test_deleting_an_event_with_registrations_says_how_many(self):
        """Those people are expecting to attend something."""
        self.assertIn("registered_count", SCREEN)
        self.assertIn("Delete it anyway?", SCREEN)

    def test_a_title_is_required_before_saving(self):
        self.assertIn("!editing.title", SCREEN)

    def test_it_says_when_a_session_will_not_be_offered(self):
        self.assertIn("Pick a date, or this session is not offered.", SCREEN)


class TheStore(unittest.TestCase):
    def test_it_talks_to_the_events_route(self):
        self.assertIn('apiRequest("/events")', STORE)
        self.assertIn('apiRequest("/events", { method: "POST"', STORE)
        self.assertIn("method: \"DELETE\"", STORE)

    def test_the_delete_path_is_encoded(self):
        """An id is ours, but building a URL by concatenation is how the next one is not."""
        self.assertIn("encodeURIComponent(eventId)", STORE)

    def test_it_replaces_rather_than_appends_on_resave(self):
        """Saving twice must not show the event twice."""
        self.assertIn("this.events.splice(index, 1, saved)", STORE)


if __name__ == "__main__":
    unittest.main()

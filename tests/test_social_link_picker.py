"""The Sites form and domain/social_links.py must agree about which hosts exist and which are confirmable.

The dashboard cannot import Python, so the host allowlist and the two unconfirmable groups are a second
copy living in Sites.vue. A host added on one side only is the failure this test exists to catch — the
same shape as tests/test_font_picker_options.py, and the same shape as the `verified`-with-no-producer bug
this whole feature is fixing.

The two groups are not interchangeable and are pinned separately on purpose:
  - UNVERIFIABLE_HOSTS cannot be fetched at all (login wall / JS shell).
  - SELF_EDITABLE_HOSTS can be fetched, but a positive result would be meaningless because anyone can edit
    them. Collapsing these into one list would lose the reason, and the reason is what stops someone
    "fixing" Wikipedia back into the checkable set later.
"""
import pathlib
import re
import unittest

from stripe_link.domain.social_links import (
    SAME_AS_HOSTS,
    SAME_AS_MAX,
    SELF_EDITABLE_HOSTS,
    UNVERIFIABLE_HOSTS,
)

SITES_VUE = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components" / "Sites.vue"


def _js_array(name: str) -> set[str]:
    source = SITES_VUE.read_text(encoding="utf-8")
    match = re.search(rf"const {name} = \[(.*?)\];", source, re.S)
    assert match, f"{name} not found in {SITES_VUE.name}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _js_number(name: str) -> int:
    source = SITES_VUE.read_text(encoding="utf-8")
    match = re.search(rf"const {name} = (\d+);", source)
    assert match, f"{name} not found in {SITES_VUE.name}"
    return int(match.group(1))


class SocialLinkPickerParityTests(unittest.TestCase):
    def test_the_form_offers_exactly_the_allowed_hosts(self):
        self.assertEqual(
            _js_array("SAME_AS_HOSTS"), set(SAME_AS_HOSTS),
            "Sites.vue and domain/social_links.py have drifted; a host in only one of them is either "
            "un-enterable or rejected by the server after the tenant has typed it",
        )

    def test_the_form_agrees_about_what_cannot_be_fetched(self):
        self.assertEqual(_js_array("UNVERIFIABLE_HOSTS"), set(UNVERIFIABLE_HOSTS))

    def test_the_form_agrees_about_what_anyone_can_edit(self):
        self.assertEqual(_js_array("SELF_EDITABLE_HOSTS"), set(SELF_EDITABLE_HOSTS))

    def test_the_form_enforces_the_same_cap(self):
        # A form that let a tenant add a 7th entry would fail validation only on save, after the typing.
        self.assertEqual(_js_number("SAME_AS_MAX"), SAME_AS_MAX)

    def test_unconfirmable_hosts_are_still_allowed_hosts(self):
        # They are listed and shown to visitors; they simply never enter the identity claim. If one ever
        # fell out of the allowlist it would stop being enterable, which is not the intent.
        for host in set(UNVERIFIABLE_HOSTS) | set(SELF_EDITABLE_HOSTS):
            self.assertIn(host, SAME_AS_HOSTS)

    def test_the_form_never_posts_verification_state(self):
        # sameAsForSave must send URLs only. If it ever spreads the row, a client would be POSTing a
        # verification object -- which the server discards, but the intent would be wrong at the source.
        source = SITES_VUE.read_text(encoding="utf-8")
        body = re.search(r"function sameAsForSave\(rows\) \{(.*?)\n\}", source, re.S)
        self.assertIsNotNone(body, "sameAsForSave not found")
        self.assertNotIn("verification", body.group(1))


if __name__ == "__main__":
    unittest.main()

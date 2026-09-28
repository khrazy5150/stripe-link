"""The AI settings screen: what it must never do, and what it must stay in step with.

Source-level checks, the pattern this repo already uses for dashboard invariants (see
test_refund_fee_disclosure.py). They catch the two failures that would actually hurt: leaking a key,
and drifting out of step with the server's closed model list.
"""

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = (ROOT / "dashboard" / "src" / "components" / "AiProvider.vue").read_text(encoding="utf-8")
STORE = (ROOT / "dashboard" / "src" / "stores" / "aiProvider.js").read_text(encoding="utf-8")
MENU = (ROOT / "dashboard" / "src" / "config" / "menu.js").read_text(encoding="utf-8")
APP = (ROOT / "dashboard" / "src" / "App.vue").read_text(encoding="utf-8")
BYOK_PY = (ROOT / "src" / "stripe_link" / "ai_byok.py").read_text(encoding="utf-8")


class KeyHandlingTests(unittest.TestCase):
    def _key_input(self):
        """The input under the "API key" label. Anchored on the label rather than an id, so moving to
        the app's own `offer-field` markup does not quietly drop these protections."""
        return SCREEN.split("<span>API key</span>", 1)[1].split("</label>", 1)[0]

    def test_the_key_field_is_a_password_input(self):
        self.assertIn('type="password"', self._key_input())

    def test_the_key_field_does_not_autocomplete(self):
        # A browser offering to remember an API key is a copy of it we did not ask for.
        self.assertIn('autocomplete="off"', self._key_input())

    def test_the_key_is_cleared_from_the_form_either_way(self):
        # A rejected key is not worth keeping in a field, and an accepted one is already saved.
        self.assertIn("form.apiKey = \"\";", SCREEN)

    def test_the_store_never_keeps_the_key_in_state(self):
        # Comments stripped first: the state block documents `has_api_key` as a field of the server's
        # REDACTED reply, which is the opposite of holding a key.
        state = STORE.split("state: () => ({", 1)[1].split("}),", 1)[0]
        code = "\n".join(re.sub(r"//.*$", "", line) for line in state.splitlines())
        for forbidden in ("apiKey", "api_key"):
            self.assertNotIn(forbidden, code)

    def test_the_screen_says_the_key_is_write_only(self):
        self.assertIn("never shown again", SCREEN)


class ContractTests(unittest.TestCase):
    def test_the_byok_model_lists_match_the_server_exactly(self):
        # The server refuses anything outside BYOK_MODELS, so a name here that is missing there shows
        # the tenant a puzzling "unknown model" for a model the UI offered them.
        server = {}
        block = BYOK_PY.split("BYOK_MODELS = {", 1)[1].split("\n}", 1)[0]
        for provider, body in re.findall(r'"(\w+)":\s*\{([^}]*)\}', block):
            server[provider] = set(re.findall(r'"([^"]+)":\s*"', body))
        ui = {}
        for provider, body in re.findall(r'key:\s*"(\w+)",[\s\S]*?models:\s*\[([\s\S]*?)\]', STORE):
            ui[provider] = set(re.findall(r'name:\s*"([^"]+)"', body))
        self.assertEqual(ui, server)

    def test_switching_provider_resets_the_model(self):
        # Their names, not ours -- an Anthropic id sent to OpenAI is refused server-side.
        self.assertIn("watch(() => form.provider", STORE + SCREEN)

    def test_the_screen_is_reachable_from_the_menu_and_the_app(self):
        self.assertIn('view: "ai"', MENU)
        self.assertIn('"ai"', MENU.split('items: [', 1)[1].split("]", 1)[0] + MENU)
        self.assertIn("activeView === 'ai'", APP)
        self.assertIn("AiProvider", APP)

    def test_the_menu_icon_exists(self):
        icon = re.search(r'key:\s*"ai",[\s\S]*?icon:\s*"(\w+)"', MENU).group(1)
        self.assertRegex(MENU, rf'\n\s*{icon}:\s*"M')


class HonestyTests(unittest.TestCase):
    def test_the_screen_warns_that_connecting_is_slow_and_why(self):
        # It really does run a generation before saving; an unexplained multi-second spinner reads as
        # a hang.
        self.assertIn("real generation", SCREEN)

    def test_it_says_who_is_billed(self):
        self.assertIn("billed to your own account", SCREEN)
        self.assertIn("included with your plan", SCREEN)

    def test_it_warns_that_a_chat_subscription_is_not_api_billing(self):
        # The trap both vendors share: a Pro/Max or ChatGPT subscription covers the chat apps, not the
        # API. Without this, every subscriber connects a key, is told by their provider to add
        # credits, and reports OUR feature as broken. Said before the button, not after a failure.
        self.assertIn("billingNote", SCREEN)
        for vendor in ("Claude Pro or Max", "ChatGPT"):
            self.assertIn(vendor, STORE)
        self.assertIn("billed separately", STORE)

    def test_it_uses_classes_the_stylesheet_actually_defines(self):
        # The first version invented a design system -- .screen, .card, .field-hint -- none of which
        # existed, so the page rendered with no padding or card chrome at all. Every class here must
        # be one the app really styles.
        import re
        css = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
        used = set()
        for attr in re.findall(r'\sclass="([^"]+)"', SCREEN):
            used.update(c for c in attr.split() if c and "{" not in c)
        for name in sorted(used):
            with self.subTest(name=name):
                self.assertRegex(css, rf"\.{re.escape(name)}\b",
                                 f".{name} is used by the screen but not defined in styles.css")

    def test_the_primary_button_stops_saying_turn_on_once_it_is_on(self):
        # Reported from the deployed screen: it still read "Turn on AI" after connecting, where the
        # same click then means switch model or re-check.
        self.assertIn("platformButtonLabel", SCREEN)
        for state in ("Turn on AI", "Switch model", "Re-check connection"):
            self.assertIn(state, SCREEN)

    def test_the_model_is_shown_by_its_label_not_its_registry_id(self):
        # "sonnet-4.6" is our internal name; "Claude Sonnet 4.6" is the one a tenant recognises.
        self.assertIn("modelLabel", SCREEN)

    def test_the_status_message_is_not_stranded_under_the_byok_section(self):
        # It was rendering at the foot of the template, so "Connected and verified." appeared to
        # belong to the bring-your-own-key card it had nothing to do with.
        banner = SCREEN.index("keys-status-banner")
        self.assertLess(banner, SCREEN.index("Use your own AI account"))

    def test_platform_paid_is_the_primary_path_and_byok_is_demoted(self):
        # Revised 2026-09-27: BYOK needs a separate vendor account funded with non-refundable,
        # one-year-expiry prepaid credits -- four steps before a tenant sees a page. Platform-paid
        # costs ~1.9c a generation and removes all of it, so it leads.
        self.assertLess(SCREEN.index("Junior Bay AI"), SCREEN.index("Use your own AI account"))
        self.assertIn("primary-action", SCREEN.split("Junior Bay AI", 1)[1].split("Use your own AI account", 1)[0])
        self.assertIn("showByok", SCREEN)   # kept behind a toggle, not promoted

    def test_byok_warns_that_credits_expire_and_do_not_refund(self):
        # The friction is the commitment, not the price: a tenant who buys $5 and generates three
        # pages has paid $1.67 each.
        self.assertIn("expire a year after purchase", SCREEN)
        self.assertIn("not refundable", SCREEN)


WIZARD = (ROOT / "dashboard" / "src" / "components" / "AiPageWizard.vue").read_text(encoding="utf-8")
PAGE_STORE = (ROOT / "dashboard" / "src" / "stores" / "aiPage.js").read_text(encoding="utf-8")


class WizardTests(unittest.TestCase):
    """The AI page wizard (plans/AI_PAGE_BRIEF.md)."""

    def test_it_uses_classes_the_stylesheet_defines(self):
        css = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
        used = set()
        for attr in re.findall(r'\sclass="([^"]+)"', WIZARD):
            used.update(c for c in attr.split() if c and "{" not in c)
        for name in sorted(used):
            with self.subTest(name=name):
                self.assertRegex(css, rf"\.{re.escape(name)}\b")

    def test_the_step_list_is_derived_from_the_kind(self):
        # The author's rule: smart steps, not fewer. One derived list feeds the rail, the labels and
        # the bounds -- LandingPages.vue's rail is the scar that says what happens otherwise.
        self.assertIn("export function stepsFor", PAGE_STORE)
        self.assertIn("KIND_STEP", PAGE_STORE)

    def test_a_download_is_never_asked_about_shipping(self):
        block = WIZARD.split("key === 'delivery'", 1)[1].split("</template>", 1)[0]
        self.assertNotIn("shipping", block.lower())

    def test_the_wizard_step_list_matches_the_server(self):
        # The server validates what the wizard collects; a step here with no field there is a dead
        # question, and a required field there with no step here is an unreachable wizard.
        from stripe_link.domain.page_brief import steps_for
        for kind in ("physical", "digital", "service"):
            with self.subTest(kind=kind):
                server = steps_for(kind)
                declared = re.search(r"const KIND_STEP = \{([^}]*)\}", PAGE_STORE).group(1)
                self.assertIn(f"{kind}:", declared)
                for step in server:
                    self.assertIn(f"{step}:", PAGE_STORE, f"{step} has no label in the store")

    def test_the_review_step_says_what_will_be_withheld_before_generating(self):
        review = WIZARD.split("key === 'review'", 1)[1].split("</template>", 1)[0]
        self.assertIn("What we won't be able to say", review)
        self.assertIn("store.withheld", review)

    def test_the_session_step_is_not_skippable(self):
        # A service page that cannot say how long it takes or whether it is remote is not worth
        # generating, so this is the one kind block that blocks.
        skippable = PAGE_STORE.split("export const SKIPPABLE", 1)[1].split("\n", 1)[0]
        self.assertNotIn("session", skippable)
        self.assertIn("delivery", skippable)

    def test_the_category_field_reuses_the_shared_component(self):
        # A free-text box beside a real taxonomy is a second source of truth, and the tenant cannot
        # see what categories exist. ProductCategoryField already does curated + promoted + their own.
        self.assertIn("ProductCategoryField", WIZARD)
        self.assertNotIn('placeholder="supplement"', WIZARD)

    def test_parcel_measurements_are_separate_numbers(self):
        # These ARE the packer's inputs -- fulfillment.dimensions and weight_lb, which label_readiness
        # gates on. One free-text "size or weight" box could only be parsed by guessing.
        block = WIZARD.split("key === 'shipping_use'", 1)[1].split("</template>", 1)[0]
        for field in ("length_in", "width_in", "height_in", "weight_lb"):
            with self.subTest(field=field):
                self.assertIn(f"b.physical.{field}", block)
                self.assertIn('type="number"', block)

    def test_the_shipping_question_does_not_presume_free(self):
        block = WIZARD.split("key === 'shipping_use'", 1)[1].split("</template>", 1)[0]
        self.assertIn("flat", block)             # a non-free example is offered
        self.assertIn("in your words", block)

    def test_measurements_are_marked_as_not_appearing_on_the_page(self):
        # They license no claim, and a tenant should not expect to see them in the copy.
        block = WIZARD.split("key === 'shipping_use'", 1)[1].split("</template>", 1)[0]
        self.assertIn("not written on the page", block)

    def test_the_result_never_claims_anything_is_live(self):
        done = WIZARD.split("Your draft page is ready", 1)[1]
        self.assertIn("draft", done.lower())
        self.assertIn("Nothing is live", done)

    def test_it_is_reachable_from_the_menu_and_the_app(self):
        self.assertIn('view: "aiPage"', MENU)
        self.assertIn("activeView === 'aiPage'", APP)
        self.assertIn("AiPageWizard", APP)

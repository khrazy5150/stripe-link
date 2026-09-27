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
    def test_the_key_field_is_a_password_input(self):
        self.assertRegex(SCREEN, r'id="ai-key"[\s\S]{0,200}?type="password"')

    def test_the_key_field_does_not_autocomplete(self):
        # A browser offering to remember an API key is a copy of it we did not ask for.
        self.assertRegex(SCREEN, r'id="ai-key"[\s\S]{0,200}?autocomplete="off"')

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

    def test_platform_paid_is_the_primary_path_and_byok_is_demoted(self):
        # Revised 2026-09-27: BYOK needs a separate vendor account funded with non-refundable,
        # one-year-expiry prepaid credits -- four steps before a tenant sees a page. Platform-paid
        # costs ~1.9c a generation and removes all of it, so it leads.
        self.assertLess(SCREEN.index("Junior Bay AI"), SCREEN.index("Use your own AI account"))
        self.assertIn('class="primary-action"', SCREEN.split("Junior Bay AI", 1)[1].split("<details", 1)[0])
        self.assertIn("<details", SCREEN)   # kept, not promoted

    def test_byok_warns_that_credits_expire_and_do_not_refund(self):
        # The friction is the commitment, not the price: a tenant who buys $5 and generates three
        # pages has paid $1.67 each.
        self.assertIn("expire a year after purchase", SCREEN)
        self.assertIn("not refundable", SCREEN)

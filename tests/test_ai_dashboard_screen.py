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


FORK = (ROOT / "dashboard" / "src" / "components" / "BuildWithAi.vue").read_text(encoding="utf-8")
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")
PAGE_STORE = (ROOT / "dashboard" / "src" / "stores" / "aiPage.js").read_text(encoding="utf-8")
MENU_SRC = (ROOT / "dashboard" / "src" / "config" / "menu.js").read_text(encoding="utf-8")


class ForkTests(unittest.TestCase):
    """Build with AI as a FORK off the product wizard (plans/AI_PAGE_BRIEF.md v2).

    The standalone nine-step wizard is gone. It duplicated the product wizard -- measured against
    Products.vue it re-asked kind, name, description, category and price -- so what remains asks only the
    two things nothing else can answer.
    """

    def test_it_uses_classes_the_stylesheet_defines(self):
        # The scar: a page was once built on invented classes (.screen, .card, .field-hint) and rendered
        # completely unstyled. Every class here has to exist.
        css = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
        used = set()
        for attr in re.findall(r'\sclass="([^"]+)"', FORK):
            used.update(c for c in attr.split() if c and "{" not in c)
        for name in sorted(used):
            with self.subTest(name=name):
                self.assertRegex(css, rf"\.{re.escape(name)}\b")

    def test_it_does_not_re_ask_what_the_product_already_knows(self):
        # The whole reason v1 was replaced. These are product-wizard questions and must not reappear here.
        for asked_elsewhere in ("Product Name", "Price", "Description", "Category"):
            with self.subTest(field=asked_elsewhere):
                self.assertNotIn(f">{asked_elsewhere}<", FORK)
        self.assertNotIn("unit_amount", FORK, "the browser never restates the price")

    def test_it_never_asks_for_the_refund_policy(self):
        # ai_floor already declared refund_policy a governed class -- it comes from the tenant's policy --
        # so asking for it here would contradict the floor and the floor was right.
        lowered = FORK.lower()
        for term in ("refund window", "guarantee\n", "cancellation policy"):
            with self.subTest(term=term):
                self.assertNotIn(term, lowered)

    def test_it_sends_a_product_id_and_never_a_brief(self):
        # The brief is PROJECTED server-side. A browser assembling one would be deciding what the AI is
        # licensed to assert.
        self.assertIn("product_id", PAGE_STORE)
        self.assertNotIn("brief:", FORK)

    def test_only_two_fields_are_required(self):
        self.assertEqual(FORK.count('<span class="required">*</span>'), 2)

    def test_every_optional_field_says_what_it_UNLOCKS(self):
        # "Add your guarantee and we can write about your guarantee" is a different sentence from "fill in
        # 12 fields" -- and the field floor makes it literally true.
        optional = FORK.split("Add more (optional)", 1)[1]
        for unlock in ("evidence", "trust badges", "category", "exactly as you write it"):
            with self.subTest(unlock=unlock):
                self.assertIn(unlock, optional.lower())

    def test_it_prefills_from_what_the_product_already_carries(self):
        # So a second page for the same product is not a retype. The point of Product.ai_context.
        self.assertIn("ai_context", FORK)
        self.assertIn("context.facts", FORK)

    def test_a_blank_answer_is_not_sent(self):
        # Blank means "unchanged", never "erase". The server applies the same rule; they have to agree or a
        # page is generated from different facts than the ones that get kept.
        generate = FORK.split("function generate()", 1)[1]
        self.assertIn("if (answers.value.audience.trim())", generate)

    def test_it_shows_what_the_page_could_NOT_say(self):
        # A tenant who understands a thin page is a different person from one who thinks the AI is bad.
        self.assertIn("withheld", FORK)
        self.assertIn("What we couldn't say", FORK)

    def test_it_is_reachable_from_a_new_product_AND_an_existing_one(self):
        # Both call sites, decided with the author: every product that exists today got there without ever
        # seeing this flow, so an existing-product entry point is not a nicety.
        self.assertIn("aiForProduct.value = saved", PRODUCTS)
        self.assertIn('@click="aiForProduct = product"', PRODUCTS)

    def test_services_and_lead_magnets_are_not_offered_it(self):
        # A service is its own document with a booking CTA; a lead magnet and a tip jar have no page of
        # this shape. v1 is products only.
        guard = PRODUCTS.split("function canBuildWithAi", 1)[1].split("\n}", 1)[0]
        for excluded in ("service", "lead_gen", "tip_jar"):
            with self.subTest(excluded=excluded):
                self.assertIn(excluded, guard)

    def test_the_standalone_wizard_is_gone_entirely(self):
        # Retired, not merely unlinked: a second way to create the same thing is the duplication this
        # rework exists to remove.
        self.assertFalse((ROOT / "dashboard" / "src" / "components" / "AiPageWizard.vue").exists())
        self.assertNotIn("AiPageWizard", APP)
        self.assertNotIn('"aiPage"', MENU_SRC)


class PollingTests(unittest.TestCase):
    """Queue-and-poll, which is not optional: a measured 35s generation against API Gateway's hard 29s
    ceiling meant the work succeeded while the browser reported "Failed to fetch"."""

    def test_the_fork_polls_the_job_rather_than_awaiting_the_response(self):
        self.assertIn("generateForProduct", PAGE_STORE)
        fork_action = PAGE_STORE.split("async generateForProduct", 1)[1]
        self.assertIn("awaitJob", fork_action)


BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


class BuilderRoundTripTests(unittest.TestCase):
    """Every section a generated page can contain must survive being opened and saved in the builder.

    The builder maps page sections to editable elements on load and writes back only what it mapped. A
    section type it does not know is dropped on load and GONE on the next save — so editing a generated page
    silently deleted its copy. Found by the author: "when I click edit, all those things disappear"
    (2026-09-30).

    `headline`, `subheadline` and `seo_title` were the casualties. The first two are legacy — the hero family
    absorbed them — and the third renders a visible paragraph the builder has no editor for. None of them
    should ever have been generatable, and this test is what says so from now on.
    """

    def _builder_loads(self):
        return set(re.findall(r'section\.type === "(\w+)"', BUILDER))

    def _mandatory(self):
        block = re.search(r"MANDATORY_SECTION_KEYS = new Set\(\[(.*?)\]\)", BUILDER, re.S)
        return set(re.findall(r'"(\w+)"', block.group(1))) if block else set()

    def test_every_generatable_section_survives_a_round_trip(self):
        from stripe_link.domain.ai_schema import SECTION_SHAPES

        loadable = self._builder_loads() | self._mandatory()
        for name in sorted(SECTION_SHAPES):
            with self.subTest(section=name):
                self.assertIn(name, loadable,
                              f"the AI can emit {name} but the builder cannot load it — "
                              "editing the page would delete it")

    def test_every_structural_section_the_composer_adds_survives_too(self):
        # The composer puts these on every generated page. One the builder cannot load would vanish on the
        # tenant's first save just as surely as an authored one.
        from stripe_link.domain.composition import baseline_order, default_visible, excluded_sections

        loadable = self._builder_loads() | self._mandatory()
        excluded = excluded_sections("single")
        for name in baseline_order(""):
            if name in excluded or not default_visible("single", name, ""):
                continue
            with self.subTest(section=name):
                self.assertIn(name, loadable, f"the composer adds {name} but the builder cannot load it")

    def test_the_parse_found_a_real_loader(self):
        """A regex that matched nothing would make both checks vacuously pass."""
        loads = self._builder_loads()
        self.assertGreater(len(loads), 10)
        self.assertIn("faq", loads)

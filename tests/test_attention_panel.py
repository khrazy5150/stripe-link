"""The Attention panel in the offer modal — the dashboard's only surface onto `../sam/attention`.

Asserted against the component SOURCE, the way this repo's other Vue guards are, because the properties
worth protecting are structural rather than visual:

1. **It is gated on the service being configured**, not assumed present. Attention is a separate stack and
   its base comes from `app_config`; an unconfigured environment must render nothing rather than fire at a
   guessed host. Prod is exactly that case today.
2. **No campaign logic lives in the component.** `ATTENTION_PRIMITIVE.md` §2 forbids a second derivation,
   and a component that started deciding which pillars an offer supports would be one.
3. **The 409 points at the button directly above it.** `semantic_model` is written by the enrich operation
   and by nothing else, so "no analysis yet" is the common FIRST answer here, not an edge case.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OFFERS = (ROOT / "dashboard" / "src" / "components" / "Offers.vue").read_text(encoding="utf-8")
ADAPTER = (ROOT / "dashboard" / "src" / "api" / "attention.js").read_text(encoding="utf-8")
CLIENT = (ROOT / "dashboard" / "src" / "api" / "client.js").read_text(encoding="utf-8")


class TheGateTests(unittest.TestCase):
    def test_the_panel_renders_only_when_the_service_is_CONFIGURED(self):
        self.assertIn('v-if="editingOfferId && attentionAvailable"', OFFERS)

    def test_availability_comes_from_the_CONFIG_not_a_constant(self):
        self.assertIn("const attentionAvailable = attentionConfigured();", OFFERS)
        self.assertIn("getEnvironmentConfig(channel).attention_api_base", CLIENT)

    def test_there_is_NO_hardcoded_attention_host(self):
        """The repo's own rule for every other base: config-driven per channel, no fallback. A fallback
        would point one environment's dashboard at another environment's service."""
        for source in (CLIENT, ADAPTER, OFFERS):
            self.assertNotIn("execute-api", source)

    def test_an_unconfigured_base_refuses_before_fetching(self):
        """Firing at `undefined/me/context` surfaces as an opaque network error rather than as
        "not configured here yet"."""
        self.assertIn('code = "not_configured"', ADAPTER)

    def test_the_panel_needs_a_SAVED_offer(self):
        """The service reads the stored document, so there is nothing to derive from until there is one."""
        self.assertIn("editingOfferId && attentionAvailable", OFFERS)


class NoSecondDerivationTests(unittest.TestCase):
    def test_the_component_does_not_name_a_PILLAR(self):
        """Which pillars exist, and which an offer supports, is the service's answer. A list of pillar
        keys in a component is the beginning of a second, disagreeing copy (§2)."""
        script = OFFERS.split("<script", 1)[1]
        for pillar in ("problem", "education", "mistakes", "transformation", "product_proof"):
            with self.subTest(pillar=pillar):
                self.assertNotIn(f'"{pillar}"', script)

    def test_the_ATTENTION_code_does_not_name_a_HOOK_or_a_FORMAT(self):
        """Scoped to the Attention code, not the whole component: "carousel" is also an offer
        PRESENTATION option elsewhere in this file, and a repo-wide word ban would be asserting that an
        unrelated feature cannot exist."""
        section = OFFERS.split("<h3>Attention</h3>", 1)[1].split("</section>", 1)[0]
        logic = OFFERS.split("// ATTENTION. A thin view over", 1)[1].split("function openOfferModal(", 1)[0]
        # COMMENTS STRIPPED. The ban is on a hardcoded format VALUE, and prose explaining why a carousel
        # has no duration is the opposite of the thing being banned -- asserting against it would be a
        # test that punishes the explanation.
        code = "\n".join(line.split("//", 1)[0] for line in logic.splitlines())
        for word in ("carousel", "short_video", "talking_head", "pattern_interrupt", "hook_style"):
            with self.subTest(word=word):
                self.assertNotIn(word, section)
                self.assertNotIn(word, code)

    def test_the_missing_pillars_come_from_the_SERVICE(self):
        """Computing them in the component would mean the component knowing the full pillar list."""
        self.assertIn("context.missing_pillars", OFFERS)

    def test_the_pillar_label_map_lives_in_the_ADAPTER(self):
        """A label map is presentation, so it is allowed -- but it belongs with the other service
        vocabulary, and an unknown key must show rather than vanish."""
        self.assertIn("PILLAR_LABELS", ADAPTER)
        self.assertIn('PILLAR_LABELS[key] || String(key || "")', ADAPTER)

    def test_the_channel_list_comes_from_the_adapter(self):
        self.assertIn("CHANNELS as ATTENTION_CHANNELS", OFFERS)
        self.assertIn("const attentionChannels = ATTENTION_CHANNELS;", OFFERS)


class TheRefusalsTests(unittest.TestCase):
    def test_the_missing_analysis_refusal_has_its_OWN_flag(self):
        """Not a substring match on the message: this refusal has an action attached, and matching on
        wording breaks the moment the service rewords it."""
        self.assertIn("attentionNeedsUnderstanding", OFFERS)
        self.assertIn("error.code === NO_SEMANTIC_MODEL", OFFERS)

    def test_it_points_at_the_button_directly_above(self):
        banner = OFFERS.split('v-if="attentionNeedsUnderstanding"', 1)[1][:500]
        self.assertIn("Enhance with AI", banner)
        self.assertIn("saving the offer does not produce it", banner)

    def test_the_banner_tracks_which_button_is_actually_showing(self):
        """The button says "Refresh understanding" once a model exists, and naming the other one would
        send the tenant looking for a control that is not there."""
        banner = OFFERS.split('v-if="attentionNeedsUnderstanding"', 1)[1][:500]
        self.assertIn("enrichedModel", banner)

    def test_the_services_own_message_is_shown_for_everything_else(self):
        """It is already written for a tenant to read; replacing it here would make it worse."""
        self.assertIn('attentionError.value = error.message', OFFERS)

    def test_the_code_survives_onto_the_error(self):
        self.assertIn("err.code = err.payload?.error", ADAPTER)


class TheRequestTests(unittest.TestCase):
    def test_the_sibling_base_is_an_ARGUMENT_to_the_shared_request_helper(self):
        """Not a second fetch wrapper. Everything around the fetch is what matters -- the id-token choice,
        the proactive renewal, the single 401 retry -- and a copy would be a second place for the
        2026-10 access-token bug to return."""
        self.assertIn("base: baseOverride", CLIENT)
        self.assertIn("const base = baseOverride || getApiBase();", CLIENT)
        self.assertIn("apiRequest(path, { base, params })", ADAPTER)

    def test_the_mode_is_not_sent_by_hand(self):
        """`apiRequest` already sends the dashboard's current Stripe mode, which is what the service
        requires -- it refuses a request that names none rather than defaulting to test."""
        self.assertNotIn("mode: getStripeMode()", ADAPTER)

    def test_changing_the_channel_does_not_fire_an_unasked_request(self):
        """Picking a platform before pressing the button must not fetch. Anchored on the early return
        rather than on a one-line `if`, which is what it was before copy generation was added."""
        handler = OFFERS.split("function onAttentionChannelChange()", 1)[1][:600]
        self.assertIn("if (!attentionBriefs.value.length) return;", handler)
        self.assertIn("loadAttention()", handler)

    def test_angles_are_cleared_when_another_offer_is_opened(self):
        """Carrying them over would show a tenant one offer's post plan for a different offer."""
        opener = OFFERS.split("function openOfferModal(", 1)[1][:900]
        self.assertIn("resetAttention()", opener)


class TheDeliverableTests(unittest.TestCase):
    def test_every_hook_is_individually_copyable(self):
        self.assertIn("copyAttentionHook(hook)", OFFERS)

    def test_the_whole_set_is_copyable_as_plain_text(self):
        """The entire deliverable until A5 can publish: a tenant pastes it into whatever they use."""
        self.assertIn("copyAttentionAll", OFFERS)
        exporter = OFFERS.split("function copyAttentionAll()", 1)[1][:700]
        for field in ("pillar", "anchor", "hooks"):
            with self.subTest(field=field):
                self.assertIn(field, exporter)

    def test_the_platform_shape_omits_what_does_not_apply(self):
        """A carousel has no duration and a video has no slide count; the service omits whichever does
        not apply, and the panel must not invent it."""
        shape = OFFERS.split("function attentionShape(brief)", 1)[1][:500]
        self.assertIn("brief.seconds?.length === 2", shape)
        self.assertIn("brief.slides?.length === 2", shape)

    def test_the_free_half_and_the_paid_half_are_labelled_SEPARATELY(self):
        """Deriving angles is deterministic and server-side, so claiming a cost for it would be a false
        statement about the tenant's allowance. WRITING a post is a real generation, so the button that
        does it says so. Two different claims, and neither may be applied to the other half."""
        section = OFFERS.split("<h3>Attention</h3>", 1)[1].split("</section>", 1)[0]
        derive = section.split("Show post angles", 1)[1].split("</div>", 1)[0] + section.split(
            "Show post angles", 1)[1].split("</div>", 2)[1]
        self.assertIn("no AI generation", derive)
        self.assertNotIn("Uses one AI generation", derive)
        write = section.split("writeAttentionPost(brief)", 1)[1][:400]
        self.assertIn("Uses one AI generation", write)


class TheConfigExampleTests(unittest.TestCase):
    def test_the_example_config_documents_the_key_for_both_channels(self):
        """`schemas/examples/app-config.json` is what a fresh environment is seeded from, so a key absent
        from it is a key the next deployment silently lacks."""
        import json

        example = json.loads((ROOT / "schemas" / "examples" / "app-config.json").read_text(encoding="utf-8"))
        for channel in ("dev", "prod"):
            with self.subTest(channel=channel):
                base = example["environments"][channel].get("attention_api_base") or ""
                self.assertTrue(re.match(r"^https://\S+$", base), base)


class WritingFinishedCopyTests(unittest.TestCase):
    """#2: the post itself, generated in stripe-link because the provider adapter, the BYOK config and the
    usage counter all live on that function (author decision 2026-11-02)."""

    def test_it_calls_the_shared_ai_route_not_the_attention_service(self):
        """A second service generating would mean a second service reaching the tenant's provider key."""
        writer = OFFERS.split("async function writeAttentionPost(", 1)[1][:900]
        self.assertIn('apiRequest("/ai/generate"', writer)
        self.assertIn('operation: "generate_copy"', writer)

    def test_the_brief_travels_as_DATA(self):
        """The service composes the prompt from fields it names, so nothing sent here is an instruction."""
        writer = OFFERS.split("async function writeAttentionPost(", 1)[1][:900]
        self.assertIn("brief,", writer)
        self.assertNotIn("prompt", writer)

    def test_it_is_PER_ANGLE_not_all_five(self):
        """Writing five posts a tenant wants one of spends five generations on four they discard."""
        self.assertIn("writeAttentionPost(brief)", OFFERS)
        self.assertIn("attentionWriting === brief.pillar", OFFERS)

    def test_the_cost_is_stated_BEFORE_the_click(self):
        """Discovering the price afterwards is the whole class of complaint this prevents -- the same
        sentence the Understanding button above already shows."""
        section = OFFERS.split("<h3>Attention</h3>", 1)[1].split("</section>", 1)[0]
        self.assertIn("Uses one AI generation{{ enrichRemaining }}", section)

    def test_the_button_is_disabled_when_they_cannot_SPEND(self):
        """Same gate as the Understanding button: no plan, or no generations left."""
        self.assertIn('attentionWriting === brief.pillar || !canEnrich', OFFERS)

    def test_a_refunded_generation_is_said_plainly(self):
        """"Nothing came back" and "you paid for nothing" are different things, and the server already
        released the slot."""
        writer = OFFERS.split("async function writeAttentionPost(", 1)[1][:1400]
        self.assertIn("your generation was not used", writer)

    def test_the_allowance_counter_is_refreshed_after_spending(self):
        """It is printed beside every button, so leaving it stale shows a number that is wrong."""
        writer = OFFERS.split("async function writeAttentionPost(", 1)[1][:1400]
        self.assertIn("aiProviderStore.load()", writer)

    def test_changing_the_platform_DISCARDS_copy_written_for_the_old_one(self):
        """A 7-second TikTok script under an Instagram carousel brief is wrong in a way that looks right."""
        handler = OFFERS.split("function onAttentionChannelChange()", 1)[1][:600]
        self.assertIn("attentionCopy.value = {}", handler)

    def test_paragraph_breaks_are_PRESERVED_in_the_markup(self):
        """A model writes in paragraphs; collapsing them is the defect the landing renderer shipped once."""
        self.assertIn('class="offer-attention-body"', OFFERS)
        css = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
        block = css.split(".offer-attention-body", 1)[1][:120]
        self.assertIn("pre-wrap", block)


if __name__ == "__main__":
    unittest.main()

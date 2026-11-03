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
        self.assertIn("attentionConfigured()", OFFERS)
        self.assertIn("getEnvironmentConfig(channel).attention_api_base", CLIENT)

    def test_the_gate_is_RE_CHECKED_when_the_modal_opens(self):
        """The bug that shipped this to dev invisible. App.vue loads app_config asynchronously on mount --
        deliberately in the background -- so a value read once at component setup is `false` on any load
        where localStorage did not already hold the base, and stays false for the whole page session."""
        self.assertIn("const attentionAvailable = ref(attentionConfigured());", OFFERS)
        opener = OFFERS.split("function openOfferModal(", 1)[1][:1200]
        self.assertIn("attentionAvailable.value = attentionConfigured()", opener)

    def test_the_gate_is_NOT_a_plain_computed(self):
        """A computed over localStorage is cached and never invalidated -- Vue has no dependency to
        invalidate on, so it would read `false` once and keep answering `false`."""
        self.assertNotIn("const attentionAvailable = computed(", OFFERS)

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


class ThePlanTests(unittest.TestCase):
    """A4: the angles become a dated plan the tenant can amend and take away."""

    def test_the_plan_is_labelled_FREE(self):
        """Deterministic and server-side, like deriving the angles. Writing the copy is the metered step,
        and claiming a cost here would be a false statement about the allowance."""
        plan = OFFERS.split('<h4>Plan a month of it</h4>', 1)[1].split("</div>", 2)[0]
        self.assertIn("No AI generation", plan)

    def test_the_calendar_is_read_BACK_after_planning(self):
        """The rows a tenant amends must be the STORED ones: due_at is part of the key, so a skip against
        a row from the create response would address a key that may not match."""
        planner = OFFERS.split("async function planCampaignForOffer()", 1)[1][:1200]
        self.assertIn("await loadCalendar()", planner)

    def test_both_amendments_send_the_posts_CURRENT_due_at(self):
        """It is part of the storage key; without it the service has no key to address."""
        self.assertIn("due_at: post.due_at", ADAPTER)
        self.assertEqual(ADAPTER.count("due_at: post.due_at"), 2)

    def test_a_move_RESORTS_the_rows(self):
        """The service returns due order; leaving a moved row in place makes the dates read as shuffled."""
        mover = OFFERS.split("async function movePost(", 1)[1][:900]
        self.assertIn("sort((a, b) => Number(a.due_at) - Number(b.due_at))", mover)

    def test_a_skipped_post_stays_VISIBLE(self):
        """Hiding it leaves an unexplained gap in the dates, and a tenant cannot restore what they cannot
        see."""
        self.assertIn("'is-skipped': post.status === 'skipped'", OFFERS)
        css = (ROOT / "dashboard" / "src" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("tr.is-skipped", css)

    def test_dates_are_rendered_in_the_VIEWERS_timezone(self):
        """`due_at` is a UTC epoch and stays one; a tenant reading "Tue 3 Nov" means their Tuesday."""
        formatter = OFFERS.split("function formatPostDate(", 1)[1][:500]
        self.assertIn("toLocaleString(undefined", formatter)

    def test_the_plan_is_EXPORTABLE_as_a_file_and_as_text(self):
        """A4's point while publishing is gated: a tenant takes the month into whatever they already use."""
        self.assertIn("function copyCalendar()", OFFERS)
        self.assertIn("function downloadCalendar()", OFFERS)

    def test_the_csv_quotes_its_fields(self):
        """An anchor is a sentence and will contain commas."""
        exporter = OFFERS.split("function downloadCalendar()", 1)[1][:900]
        self.assertIn('replace(/"/g, \'""\')', exporter)

    def test_the_csv_carries_a_BOM(self):
        """Excel mangles a UTF-8 CSV without one, and an anchor may well be accented."""
        exporter = OFFERS.split("function downloadCalendar()", 1)[1][:900]
        self.assertIn("ufeff", exporter)

    def test_an_OUTDATED_plan_is_reported_never_auto_rebuilt(self):
        """A scheduled post rewriting itself under the tenant is the surprise A3 refuses."""
        banner = OFFERS.split('v-if="planOutdated"', 1)[1][:400]
        self.assertIn("Re-plan", banner)

    def test_outdated_COMPARES_the_two_model_keys(self):
        """Not a flag someone has to remember to set: the plan records the model it was built from and the
        context reports the model the offer has now."""
        self.assertIn("planModelKey.value !== contextModelKey.value", OFFERS)
        self.assertIn('planModelKey.value = body.campaign?.model_key', OFFERS)
        self.assertIn('contextModelKey.value = context.context?.cache_key', OFFERS)

    def test_outdated_is_FALSE_until_both_keys_are_known(self):
        """An unknown key must not nag a tenant to rebuild a plan that was fine -- the same direction the
        service takes in `predates_the_offer`."""
        self.assertIn("Boolean(planModelKey.value && contextModelKey.value", OFFERS)

    def test_an_EXISTING_plan_is_surfaced_when_the_modal_opens(self):
        """Otherwise a plan built in an earlier session is invisible and the tenant presses Build again."""
        self.assertIn("async function loadExistingPlan()", OFFERS)
        self.assertIn("loadExistingPlan().catch(() => {})", OFFERS)

    def test_surfacing_it_cannot_break_the_ANGLES(self):
        """No plan is the common case, and it must not make the thing above it fail."""
        loader = OFFERS.split("loadExistingPlan().catch", 1)[1][:60]
        self.assertIn("{})", loader)

    def test_the_existing_plan_restores_its_own_settings(self):
        """The dropdowns should show what the plan was actually built with, not the defaults."""
        loader = OFFERS.split("async function loadExistingPlan()", 1)[1][:700]
        self.assertIn("planIntensity.value = mine.intensity", loader)
        self.assertIn("planDays.value = Number(mine.days)", loader)

    def test_the_plan_is_cleared_when_another_offer_is_opened(self):
        reset = OFFERS.split("function resetAttention()", 1)[1][:400]
        self.assertIn("resetPlan()", reset)

    def test_the_component_does_not_decide_the_SCHEDULE(self):
        """Which pillar lands on which day is the service's answer. A component computing it would be the
        second derivation §2 forbids."""
        logic = OFFERS.split("// A3/A4. The plan is the service's", 1)[1].split(
            "function copyAttentionPost(", 1)[0]
        code = "\n".join(line.split("//", 1)[0] for line in logic.splitlines())
        for word in ("slot", "per_week", "7 -", "% 7"):
            with self.subTest(word=word):
                self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()

"""The click-to-call page: inbound calls, and the things that page alone needs.

Author, 2026-09-16, working through the lead shapes one at a time. Two of these were bugs nobody had
reported because the page LOOKED plausible: the phone number rendered white on white, and the CTA left the
document flow. The rest is the page earning the call.
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.composition import excluded_sections
from stripe_link.runtime import html as html_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTS = (ROOT / "dashboard" / "src" / "components" / "Products.vue").read_text(encoding="utf-8")
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
CSS = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))


def _render(badges=None, phone="+12065654418", kicker="", orientation=None, tone=None):
    product = {
        "product_id": "p1", "tenant_id": "t1", "name": "Emergency Water Damage",
        "description": "For 24-hour service water damage", "product_intent": "lead_gen",
        "lead_capture": {"action": "call_number", "title": "T", "description": "D",
                         "target": {"type": "phone", "value": phone}},
        "prices": [{"price_id": "pr", "currency": "usd", "quantity": 1, "unit_amount": 0,
                    "pricing_model": "one_time", "context": "standard"}],
        "default_price_id": "pr",
    }
    offer = {
        "offer_id": "o1", "tenant_id": "t1", "status": "active", "stripe_mode": "test",
        "product_intent": "lead_gen", "lead_capture_action": "call_number",
        "items": [{"product_id": "p1", "price_id": "pr", "quantity": 1}],
        "presentation": {"headline": product["name"], "subheadline": product["description"],
                         "cta": {"type": "call", "label": "Call Now", "target": phone}},
    }
    sections = [{"id": "b", "type": "brand_label"}, {"id": "h", "type": "hero"}]
    if badges:
        badge_section = {"id": "tb", "type": "trust_badges", "enabled": True, "badges": badges}
        if orientation:
            badge_section["orientation"] = orientation
        sections.append(badge_section)
    sections += [{"id": "c", "type": "checkout_cta",
                  **({"call_kicker": kicker} if kicker else {}),
                  **({"tone": tone} if tone else {})},
                 {"id": "lf", "type": "legal_footer", "copyright": "(c)"}]
    page = {"page_id": "pg", "tenant_id": "t1", "offer_id": "o1", "name": "N", "status": "draft",
            "route": {"slug": "s"}, "theme": {"template": "universal_bundle", "preset": "clean-slate"},
            "sections": sections}
    return html_module.render_page(page, offer, {"p1": product})


class NumberLegibilityTests(unittest.TestCase):
    def test_the_number_is_not_painted_in_the_cta_text_colour(self):
        """It was `--sl-cta-text`, which is white BY DESIGN -- the colour of text sitting ON the CTA scrim.

        The moment the CTA rendered in the document flow, the number was white on white. It had been there
        the whole time; the page just looked sparse rather than broken.
        """
        rule = [line for line in CSS.splitlines() if ".sl-call-number{" in line][0]
        self.assertNotIn("var(--sl-cta-text)", rule)
        # It INHERITS the panel's ink, which is the only version that cannot go wrong when a theme changes
        # one and not the other. The ink itself now comes from the shared --sl-section-ink token.
        self.assertIn("color:inherit", rule)
        panel = [line for line in CSS.splitlines() if ".sl-call-panel{" in line][0]
        self.assertIn("color:var(--sl-section-ink", panel)

    def test_the_number_is_shown_and_dialable(self):
        markup = _render()
        self.assertIn("+12065654418", markup)
        self.assertIn('href="tel:+12065654418"', markup)


class CtaInFlowTests(unittest.TestCase):
    """Every LEAD cta is page CONTENT, not a buy bar riding over it."""

    def test_the_call_and_bridge_ctas_join_the_email_one_in_the_flow(self):
        rule = [line for line in CSS.splitlines()
                if ".sl-email-cta" in line and "position:static" in line][0]
        self.assertIn(".sl-call-cta", rule)
        self.assertIn(".sl-external-cta", rule)

    def test_the_footer_ends_the_page(self):
        body = _render().split("<body", 1)[1]
        self.assertLess(body.index('data-cta-type="call"'), body.index('class="sl-legal"'))

    def test_the_sales_bar_is_still_fixed(self):
        self.assertIn("position:fixed", [l for l in CSS.splitlines() if ".sl-checkout-cta{" in l][0])


class TrustBadgeTests(unittest.TestCase):
    """The one lead shape where the visitor is about to phone a stranger about something urgent.

    There is no price, no checkout and no cart to reassure them, so badges are the only slot for
    licensed / insured / 24-hour -- which is exactly what that decision turns on (author, 2026-09-16).
    """

    def test_call_and_bridge_pages_may_show_badges(self):
        for key in ("lead_call", "lead_bridge"):
            self.assertNotIn("trust_badges", excluded_sections(key), key)
            self.assertIn("trust_badges", RULES["offer_types"][key]["sections"], key)

    def test_the_other_lead_shapes_still_exclude_them(self):
        # A capture page has a form doing the persuading, and a link hub sells nothing at all.
        for key in ("lead_capture", "lead_social"):
            self.assertIn("trust_badges", excluded_sections(key), key)

    def test_they_render_above_the_call(self):
        markup = _render(badges=[{"enabled": True, "emoji": "🕒", "label": "24-hour response"},
                                 {"enabled": True, "emoji": "🛡️", "label": "Licensed & insured"}])
        body = markup.split("<body", 1)[1]
        self.assertIn("24-hour response", body)
        self.assertLess(body.index("24-hour response"), body.index('data-cta-type="call"'))

    def test_a_page_with_no_badges_renders_none(self):
        # Nothing is invented on the tenant's behalf: these are claims about THEIR business.
        self.assertNotIn('data-section-type="trust_badges"', _render())


class CtaLegendTests(unittest.TestCase):
    def test_the_legend_says_inbound(self):
        """"Click-to-call" reads as the OPPOSITE to anyone who has just configured a phone CAPTURE.

        One collects a number so the tenant rings the visitor; the other hands the visitor a number to ring.
        The author lost time to exactly that.
        """
        self.assertIn('call: "Call — inbound phone calls"', BUILDER)
        self.assertIn("the visitor calls YOU", BUILDER)


class OnePhoneControlTests(unittest.TestCase):
    """The number is asked for ONCE, with the same control the Profile screen uses."""

    def test_the_picker_no_longer_asks_for_a_destination(self):
        # It was asked in the picker AND on the step that follows -- two phone controls to build, and two
        # to keep agreeing.
        picker = PRODUCTS.split("Choose a lead capture action", 1)[1].split("</footer>", 1)[0]
        self.assertNotIn("draftLeadAction.target", picker)

    def test_the_step_uses_the_shared_e164_control(self):
        self.assertIn('import PhoneInput from "./PhoneInput.vue"', PRODUCTS)
        self.assertIn('<PhoneInput v-if="leadTargetIsPhone" v-model="form.lead_capture.target" />', PRODUCTS)

    def test_a_url_action_still_gets_a_plain_box(self):
        # PhoneInput is for phones; a bridge page's destination is a URL.
        self.assertIn('leadTargetPlaceholderFor(form.lead_capture.action)', PRODUCTS)
        self.assertIn('if (action === "external_url") return "https://example.com"', PRODUCTS)

    def test_confirming_the_same_action_keeps_what_was_typed(self):
        """Re-opening the picker must not wipe the number entered on the step.

        Switching to a DIFFERENT action does drop it, because a phone number is not a URL.
        """
        apply_block = PRODUCTS.split("function applyLeadAction", 1)[1].split("\n}", 1)[0]
        self.assertIn("const sameAction = form.value.lead_capture.action === draftLeadAction.value.action",
                      apply_block)
        self.assertIn("sameAction ? form.value.lead_capture.target : \"\"", apply_block)


class CallPanelTests(unittest.TestCase):
    """The number is the page's headline act, so it is the size of one (author's design, 2026-09-16).

    It was a line of small text above a short button on an otherwise empty page. The shape is borrowed from
    the page ribbon rather than invented -- the author reached for a ribbon to mock this up, which said the
    shape was already right and just not reachable from a CTA.
    """

    def test_the_number_is_formatted_the_way_it_is_read_aloud(self):
        self.assertEqual(html_module.dialable_number("+12065654418"), "(206) 565-4418")
        self.assertEqual(html_module.dialable_number("2065654418"), "(206) 565-4418")

    def test_a_non_nanp_number_keeps_its_e164_form(self):
        """NANP only, deliberately.

        Every other country's E.164 is correct and universally dialable; getting the rest right means
        libphonenumber, and a 220KB dependency in the PUBLISH path to prettify a label is not a trade worth
        making.
        """
        self.assertEqual(html_module.dialable_number("+4930901820"), "+4930901820")
        self.assertEqual(html_module.dialable_number("+442071838750"), "+442071838750")

    def test_the_href_always_uses_the_raw_digits(self):
        # Formatting is for the eye. A tel: built from "(206) 565-4418" is a gamble on the dialler.
        markup = _render()
        self.assertIn('href="tel:+12065654418"', markup)
        self.assertIn("(206) 565-4418", markup)

    def test_the_panel_carries_kicker_number_and_button(self):
        markup = _render(kicker="Available 24 hours per day")
        self.assertIn("sl-call-panel", markup)
        self.assertIn("Available 24 hours per day", markup)
        self.assertIn("sl-call-number", markup)
        self.assertIn("sl-call-button", markup)

    def test_the_kicker_is_the_tenants_line_and_never_ours(self):
        # It is a claim about their availability. Absent means absent.
        self.assertNotIn('<p class="sl-call-kicker">', _render())

    def test_the_panel_is_constrained_to_the_content_column(self):
        # .sl-checkout-cta is EXCLUDED from main's column rule, because that exclusion exists for the fixed
        # sales bar which must span the viewport. In flow the panel has to be put back, or it bleeds.
        rule = [line for line in CSS.splitlines() if ".sl-checkout-cta.sl-call-cta{width:" in line]
        self.assertTrue(rule, "the call panel is not constrained")
        self.assertIn("52rem", rule[0])

    def test_the_number_has_exactly_one_colour_rule(self):
        # The pre-rewrite rule survived once and, sitting later in the sheet, won -- blue on navy inside the
        # new dark panel. Two rules for one element is how that happens.
        self.assertEqual(len([line for line in CSS.splitlines() if ".sl-call-number{" in line]), 1)


class StickyCallTests(unittest.TestCase):
    """Restored on the author's instruction: "it pays to have that call button stick to the bottom".

    Someone scrolling a phone should never have to find their way back to the number. It is its OWN element
    rather than the panel being made sticky, so the panel can still be read in place.
    """

    def test_there_is_a_sticky_bar(self):
        self.assertIn('data-call-sticky', _render())

    def test_it_is_fixed_to_the_bottom(self):
        rule = [line for line in CSS.splitlines() if ".sl-call-sticky{" in line][0]
        self.assertIn("position:fixed", rule)
        self.assertIn("bottom:0", rule)
        # A phone's home indicator sits in that strip.
        self.assertIn("safe-area-inset-bottom", rule)

    def test_the_page_reserves_the_strip_it_covers(self):
        # The same bargain the sales bar makes. Without it the bar hides the end of the page.
        self.assertIn("body:has(.sl-call-sticky) main{padding-bottom:", CSS)

    def test_the_panel_is_not_the_sticky_one(self):
        # Two tap targets, and only one of them travels.
        panel = [line for line in CSS.splitlines() if ".sl-call-panel{" in line][0]
        self.assertNotIn("position:fixed", panel)


class BadgeOrientationTests(unittest.TestCase):
    def test_vertical_is_one_claim_per_line(self):
        """A pill row reads as decoration.

        On a page whose whole argument IS the claims -- licensed, answers at 3am, covers your county -- each
        one deserves its own line.
        """
        markup = _render(badges=[{"enabled": True, "emoji": "🛡️", "label": "Licensed"}], orientation="vertical")
        self.assertIn("sl-trust-badges is-vertical", markup)
        self.assertIn(".sl-trust-badges.is-vertical{flex-direction:column", CSS)

    def test_horizontal_is_still_the_default(self):
        markup = _render(badges=[{"enabled": True, "emoji": "🛡️", "label": "Licensed"}])
        self.assertIn("sl-trust-badges is-horizontal", markup)

    def test_the_validator_knows_both_and_nothing_else(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_page_document

        def page(orientation):
            return {"schema_version": "1", "document_type": "page", "tenant_id": "t", "page_id": "p1",
                    "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                    "sections": [{"id": "tb", "type": "trust_badges", "orientation": orientation,
                                  "badges": [{"label": "Licensed"}]}]}

        for good in ("horizontal", "vertical"):
            validate_page_document(page(good))
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page("diagonal"))

    def test_the_builder_offers_the_choice(self):
        self.assertIn('<option value="vertical">', BUILDER)
        self.assertIn("builder.trust_badges.orientation", BUILDER)



class PanelToneTests(unittest.TestCase):
    """The panel is part of the CALL TO ACTION section, and editable there.

    Author, 2026-09-16: they went looking for a "page ribbon" in Page Sections and did not find one. The
    ribbon's SHAPE was borrowed; the element was not. Whatever is adjustable about the panel therefore has to
    be adjustable from the CTA editor, or it is adjustable nowhere.
    """

    def test_dark_is_the_default(self):
        # An emergency number wants to be the loudest thing on the page.
        self.assertIn("sl-call-panel sl-tone-dark", _render())

    def test_the_tenant_can_change_it(self):
        self.assertIn("sl-call-panel sl-tone-accent", _render(tone="accent"))
        self.assertIn("sl-call-panel sl-tone-light", _render(tone="light"))

    def test_an_unknown_tone_falls_back_to_the_default(self):
        # Only reachable on a hand-edited document -- the validator refuses unknown tones. The class saying
        # what paints beats a silent reliance on a CSS fallback that happens to agree.
        self.assertIn("sl-call-panel sl-tone-dark", _render(tone="chartreuse"))

    def test_a_tone_paints_by_SETTING_the_shared_tokens(self):
        """The whole point of the refactor.

        A tone paints nothing itself -- it fills --sl-section-bg / -ink / -border, which six element
        families already read. So the scale lives once and every one of them gains it from a class.
        """
        for tone in ("dark", "accent", "light"):
            rule = [line for line in CSS.splitlines() if f".sl-tone-{tone}{{" in line][0]
            self.assertIn("--sl-section-bg:", rule)
            self.assertIn("--sl-section-ink:", rule)
            # Every value from the page theme: a literal here would be a colour that ignores the preset.
            self.assertNotRegex(rule, r"#[0-9a-fA-F]{3,6}")

    def test_the_panel_reads_those_tokens_rather_than_owning_colours(self):
        rule = [line for line in CSS.splitlines() if ".sl-call-panel{" in line][0]
        self.assertIn("var(--sl-section-bg", rule)
        self.assertIn("var(--sl-section-ink", rule)

    def test_the_button_inverts_on_any_toned_section_not_just_this_one(self):
        # Written against the TONE, so a ribbon with a button gets it too.
        self.assertIn(".sl-tone-dark .sl-cta,.sl-tone-accent .sl-cta{", CSS)

    def test_the_validator_knows_the_shared_three(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_page_document

        def page(tone):
            return {"schema_version": "1", "document_type": "page", "tenant_id": "t", "page_id": "p1",
                    "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                    "sections": [{"id": "c", "type": "checkout_cta", "tone": tone}]}

        for good in ("dark", "accent", "light"):
            validate_page_document(page(good))
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page("chartreuse"))


class EditorReachabilityTests(unittest.TestCase):
    """Every knob added here must be reachable from the dialog that owns it.

    The orientation picker shipped into a SECOND `v-else-if` for trust_badges, which the editor chain never
    reached because the first one matched -- so the control existed, passed its test, and could not be seen.
    """

    def test_there_is_exactly_one_editor_branch_per_section(self):
        for editor in ("trust_badges", "checkout_cta", "refund_policy"):
            self.assertEqual(BUILDER.count(f"sectionEditor.row.editor === '{editor}'"), 1, editor)

    def test_the_orientation_picker_is_inside_the_badge_editor(self):
        branch = BUILDER.split("sectionEditor.row.editor === 'trust_badges'", 1)[1].split("</template>", 1)[0]
        self.assertIn("builder.trust_badges.orientation", branch)

    def test_the_call_controls_are_inside_the_cta_editor(self):
        branch = BUILDER.split("sectionEditor.row.editor === 'checkout_cta'", 1)[1].split("\n            <template", 1)[0]
        self.assertIn("builder.cta_call_kicker", branch)
        self.assertIn("builder.cta_tone", branch)



class SharedToneTests(unittest.TestCase):
    """One tone scale, many consumers -- the author's point, and he was right.

    The call panel had shipped its own copy of "dark / accent / light" while a per-section colour mechanism
    (domain/section_theme.py) already existed and was already honoured by four elements. Two vocabularies for
    one idea is the duplication this codebase keeps producing -- slug rules, funnel roles, entry readers,
    chips -- and the module's own docstring says so.
    """

    def test_the_scale_is_defined_once_where_section_theming_lives(self):
        from stripe_link.domain.section_theme import SECTION_TONES, tone_class

        self.assertEqual(SECTION_TONES, ("dark", "accent", "light"))
        self.assertEqual(tone_class("accent"), "sl-tone-accent")
        self.assertEqual(tone_class("chartreuse"), "")
        self.assertEqual(tone_class(None, default="dark"), "sl-tone-dark")

    def test_the_renderer_holds_no_second_copy(self):
        runtime = (ROOT / "src" / "stripe_link" / "runtime" / "html.py").read_text(encoding="utf-8")
        self.assertNotIn("CALL_PANEL_TONES", runtime)
        self.assertIn("from stripe_link.domain.section_theme import", runtime)

    def test_the_page_ribbon_takes_the_same_tone(self):
        markup = html_module.render_page_ribbon(
            {"id": "r", "headline": "Call us", "presentation": "centered", "tone": "dark"})
        self.assertIn("sl-tone-dark", markup)

    def test_a_picked_colour_still_works_on_the_panel(self):
        # The call panel now honours section.theme like the four elements that already did -- which is the
        # reuse half of this. The tenant gets the picker AND the dropdown.
        markup = html_module.render_call_cta(
            {"type": "call", "label": "Call Now", "target": "+12065654418"}, {"theme": {"bg": "#1e1033"}})
        self.assertIn("--sl-section-bg:#1e1033", markup)
        # ...and its ink is DERIVED from that colour's luminance, never authored, so it cannot be unreadable.
        self.assertIn("--sl-section-ink:", markup)

    def test_a_picked_colour_beats_a_named_tone_by_the_cascade(self):
        """No precedence rule to maintain: `theme` is an inline style, `tone` is a class.

        Getting this for free is the reason the two mechanisms can coexist without a third thing arbitrating
        between them.
        """
        markup = html_module.render_call_cta(
            {"type": "call", "label": "Call Now", "target": "+12065654418"},
            {"tone": "accent", "theme": {"bg": "#1e1033"}})
        self.assertIn("sl-tone-accent", markup)
        self.assertIn('style="--sl-section-bg:#1e1033', markup)



class TrustBadgeCapacityTests(unittest.TestCase):
    """Raised 3 -> 7 (author, 2026-09-16).

    Three was right for a horizontal pill row. The VERTICAL orientation is a list, and a contractor's
    credentials -- licensed, bonded, insured, 24-hour, free estimates, insurance claims, years in business --
    run past three long before they run past seven.
    """

    def test_the_cap_is_seven_and_defined_once(self):
        from stripe_link.domain.documents import MAX_TRUST_BADGES

        self.assertEqual(MAX_TRUST_BADGES, 7)
        self.assertIn("const MAX_TRUST_BADGES = 7;", BUILDER)

    def test_seven_badges_validate(self):
        from stripe_link.domain.documents import DocumentValidationError, validate_page_document

        def page(count):
            return {"schema_version": "1", "document_type": "page", "tenant_id": "t", "page_id": "p1",
                    "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                    "sections": [{"id": "tb", "type": "trust_badges",
                                  "badges": [{"label": f"Claim {i}"} for i in range(count)]}]}

        validate_page_document(page(7))
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page(8))

    def test_all_seven_render(self):
        badges = [{"enabled": True, "emoji": "\u276f", "label": f"Claim {i}"} for i in range(7)]
        markup = _render(badges=badges, orientation="vertical")
        self.assertEqual(markup.count('class="sl-trust-badge"'), 7)

    def test_the_builder_can_add_and_remove_them(self):
        # The row list used to be a fixed three, so a seventh was unreachable from the dashboard even once
        # the validator allowed it.
        self.assertIn("function addTrustBadge()", BUILDER)
        self.assertIn("function removeTrustBadge(index)", BUILDER)
        self.assertIn("builder.trust_badges.badges.length < MAX_TRUST_BADGES", BUILDER)

    def test_removing_never_empties_the_list(self):
        # An empty row is what the tenant types into; no rows at all has no way back short of toggling the
        # whole section off and on.
        remove = BUILDER.split("function removeTrustBadge(index)", 1)[1].split("\n}", 1)[0]
        self.assertIn("length <= 1", remove)


class DirectionalIconTests(unittest.TestCase):
    """Chevrons in gold, an arrow in red (author, 2026-09-16)."""

    GOLD = ("\u276f", "\u2771", "\u00bb", "\u27a4")
    RED = "\u2794"

    def test_the_glyph_travels_as_an_attribute_so_css_can_colour_it(self):
        # Emoji bring their own colour; these are TEXT glyphs inheriting currentColor, so without this they
        # would be badge-text blue rather than gold and red.
        markup = _render(badges=[{"enabled": True, "emoji": self.GOLD[0], "label": "Fast"}])
        self.assertIn(f'data-icon="{self.GOLD[0]}"', markup)

    def test_every_new_glyph_is_coloured(self):
        gold_rule = [line for line in CSS.splitlines() if "icon-gold" in line][0]
        for glyph in self.GOLD:
            self.assertIn(f"{ord(glyph):X}", gold_rule.upper(), glyph)
        alert_rule = [line for line in CSS.splitlines() if "icon-alert" in line][0]
        self.assertIn(f"{ord(self.RED):X}", alert_rule.upper())

    def test_the_colours_are_tokens_with_defaults_not_bare_literals(self):
        # A theme can take them over later; until then the default is the gold and red asked for.
        gold = [line for line in CSS.splitlines() if "icon-gold" in line][0]
        self.assertIn("var(--sl-icon-gold,#d4a12a)", gold)
        alert = [line for line in CSS.splitlines() if "icon-alert" in line][0]
        self.assertIn("var(--sl-icon-alert,#dc2626)", alert)

    def test_the_picker_offers_them_in_the_same_colours(self):
        picker = (ROOT / "dashboard" / "src" / "icon-picker.js").read_text(encoding="utf-8")
        self.assertIn("ICON_PICKER_COLORS", picker)
        for glyph in self.GOLD + (self.RED,):
            # The file writes them as \uXXXX escapes, so compare hex without touching the escape's case.
            self.assertIn(f"{ord(glyph):04x}", picker.lower(), glyph)
        self.assertIn("#d4a12a", picker)
        self.assertIn("#dc2626", picker)

    def test_they_are_text_presentation_not_emoji_lookalikes(self):
        """The reason ▶️ and ➡️ are NOT the glyphs used.

        An emoji-presentation character carries its own colour and ignores CSS, so a "gold chevron" would
        render in whatever the vendor font decided. Every glyph here is a text-presentation ornament or
        dingbat, and none carries a variation selector.
        """
        picker = (ROOT / "dashboard" / "src" / "icon-picker.js").read_text(encoding="utf-8")
        directional = picker.split("Directional glyphs", 1)[1].split("];", 1)[0]
        self.assertNotIn("FE0F", directional.upper())   # VS16 forces emoji presentation



if __name__ == "__main__":
    unittest.main()

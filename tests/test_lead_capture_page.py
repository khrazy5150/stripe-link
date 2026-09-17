"""What a lead-capture PAGE actually looks like to a visitor.

The author's verdict on the rendered result, 2026-09-15: "an abomination". Six separate defects, none of
them in the composition (which had the section order right all along) and all of them somewhere else — the
stylesheet, the store, the page seeder and the consent copy. Kept together here because they only show up
together, on the page.
"""
import json
import pathlib
import re
import unittest

from stripe_link.runtime import html as html_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
PRODUCTS_STORE = (ROOT / "dashboard" / "src" / "stores" / "products.js").read_text(encoding="utf-8")
CSS = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)


def _offer():
    return {
        "offer_id": "off_1", "tenant_id": "t1", "status": "active", "stripe_mode": "test",
        "product_intent": "lead_gen", "lead_capture_action": "capture_email",
        "items": [{"product_id": "prod_lead", "price_id": "pr", "quantity": 1}],
        "presentation": {"headline": "2026 Guide to Junk Food Restaurants",
                         "subheadline": "My comprehensive list of fast food restaurants.",
                         "cta": {"type": "email", "label": "Get the guide"}},
    }


def _products():
    return {"prod_lead": {
        "product_id": "prod_lead", "tenant_id": "t1", "name": "2026 Guide to Junk Food Restaurants",
        "product_intent": "lead_gen",
        "lead_capture": {"action": "capture_email", "title": "Get the guide",
                         "description": "We'll email it to you.",
                         "fields": [{"name": "email", "type": "email", "required": True}]},
        # A lead product still carries the free price the store writes for it; the resolver needs one.
        "prices": [{"price_id": "pr", "currency": "usd", "quantity": 1, "unit_amount": 0,
                    "pricing_model": "one_time", "context": "standard"}],
        "default_price_id": "pr",
    }}


def _page():
    return {
        "page_id": "page_1", "tenant_id": "t1", "offer_id": "off_1", "name": "Guide", "status": "draft",
        "route": {"slug": "guide"}, "theme": {"template": "universal_bundle", "preset": "clean-slate"},
        "sections": [
            {"id": "brand", "type": "brand_label", "enabled": True},
            {"id": "hero", "type": "hero", "headline": "2026 Guide to Junk Food Restaurants",
             "subheadline": "My comprehensive list of fast food restaurants."},
            {"id": "checkout-cta", "type": "checkout_cta", "label": "Get the guide"},
            {"id": "legal-footer", "type": "legal_footer", "copyright": "© {{current_year}} All rights reserved."},
        ],
    }


def _render(site=None):
    return html_module.render_page(_page(), _offer(), _products(), site=site)


class FooterPositionTests(unittest.TestCase):
    """The footer rendered under the HERO with the form pinned to the bottom of the viewport.

    Not an ordering bug — the DOM order was right. `.sl-checkout-cta` is `position: fixed; bottom: 0`, which
    is correct for a sales page where the CTA is a sticky buy bar riding over the content. On a lead page the
    CTA *is* the form, so being fixed took the page's whole point out of the document flow and let the footer
    float up to meet the hero.
    """

    def test_the_lead_form_is_in_the_flow(self):
        rule = [line for line in CSS.splitlines()
                if ".sl-email-cta" in line and "position:static" in line]
        self.assertTrue(rule, "no rule returns the lead CTA to the flow")
        # Widened 2026-09-16: the call and bridge CTAs are page content for the same reason.
        self.assertIn(".sl-call-cta", rule[0])

    def test_the_sales_bar_is_still_fixed(self):
        # Narrowed to the lead variant, not removed: every other page still wants the sticky buy bar.
        rule = [line for line in CSS.splitlines() if ".sl-checkout-cta{" in line][0]
        self.assertIn("position:fixed", rule)

    def test_the_strip_reserved_for_a_fixed_bar_goes_with_it(self):
        # body/main carry bottom padding so the fixed bar never covers content. In flow it is just a screen
        # of trailing white space.
        # Narrowed 2026-09-16: the call/external/download panels reserve their OWN, taller strip for the
        # sticky bar, so only the email form's rule lives here now.
        self.assertIn("body:has(.sl-email-cta){padding-bottom:0}", CSS)
        self.assertIn("body:has(.sl-cta-sticky) main{padding-bottom:", CSS)

    def test_the_rendered_order_puts_the_footer_last(self):
        markup = _render()
        body = markup.split("<body", 1)[1]
        cta = body.index('data-section-type="checkout_cta"')
        footer = body.index('class="sl-legal"')
        self.assertLess(cta, footer, "the form must come before the footer")


class ConsentTests(unittest.TestCase):
    def test_the_tenant_list_is_named_after_the_business(self):
        # It read "Join capture email's mailing list" — the OFFER's name, which is not a thing anyone can
        # consent to. The business name is the same one the brand label at the top of the page shows.
        markup = _render(site={"organization": {"name": "Poliaxis Nutrition"}})
        self.assertIn("Join Poliaxis Nutrition&#x27;s mailing list.", markup)

    def test_it_falls_back_to_the_offer_brand_then_to_us(self):
        markup = _render()   # no Site, so no business name
        self.assertIn("mailing list.", markup)
        self.assertNotIn("Join &#x27;s mailing list.", markup)

    def test_neither_box_starts_ticked(self):
        """Consent needs an affirmative action, and this is the test that keeps it that way.

        GDPR recital 32 says in terms that "silence, pre-ticked boxes or inactivity" do not constitute
        consent; Art. 4(11) requires "a clear affirmative action"; CJEU Planet49 (C-673/17) settled it. The
        platform box is weaker still — third-party marketing is never covered by the ePrivacy soft opt-in
        that can otherwise excuse a tenant's own list.

        Briefly shipped pre-ticked on 2026-09-15 and reverted the same day. This test is the guard.
        """
        markup = _render()
        self.assertNotIn("checked", markup.split("sl-lead-form", 1)[1].split("</form>", 1)[0])

    def test_the_chosen_state_is_still_recorded(self):
        # Unticking the default must not quietly stop recording what the visitor actually chose.
        script = _render()
        self.assertIn("granted: box.checked", script)

    def test_the_two_opt_ins_stay_independent(self):
        # The tenant's list and Junior Bay's are separate decisions and separate records.
        markup = _render()
        self.assertIn('data-consent="tenant_marketing"', markup)
        self.assertIn('data-consent="platform_marketing"', markup)


class HeroCopyTests(unittest.TestCase):
    """The hero introduced the page as a FORM instead of as the thing on offer."""

    def test_the_seeder_never_uses_the_lead_actions_words(self):
        # "Collect the visitor's email address." describes the mechanism. It was the subheadline fallback,
        # so every capture page whose offer had no subheadline announced its own plumbing.
        self.assertNotIn("leadAction?.description", BUILDER)

    def test_a_new_page_stores_no_hero_copy_at_all(self):
        # The renderer derives it, so copying it in only freezes the page at what the offer said the day it
        # was made. That is how a lead page kept announcing "Capture Email" after its offer had a real one.
        block = BUILDER.split("function pageSections(", 1)[1][:1400]
        hero = block.split('type: "hero"', 1)[1].split("},", 1)[0]
        self.assertNotIn("headline:", hero)
        self.assertNotIn("subheadline:", hero)

    def test_the_builder_stores_only_what_the_tenant_changed(self):
        # Same rule the SEO fields already follow. A typed headline that matches the derived one is not an
        # edit, and storing it would silently opt the page out of every later correction to the offer.
        self.assertIn("function heroOverride(typed, derived)", BUILDER)
        build = BUILDER.split('if (sectionVisible("hero")) sections.push(', 1)[1][:1000]
        self.assertIn("heroOverride(", build)
        self.assertIn("offerHeadline(builderOffer.value)", build)
        self.assertIn("offerDescription(builderOffer.value)", build)

    def test_the_seo_description_is_not_the_headline_again(self):
        block = BUILDER.split("function buildPageDocument(", 1)[1][:1600]
        self.assertIn("description: offer.presentation?.subheadline || offerDescription(offer)", block)

    def test_the_rendered_hero_carries_the_products_words(self):
        markup = _render()
        self.assertIn("2026 Guide to Junk Food Restaurants", markup)
        self.assertIn("My comprehensive list of fast food restaurants.", markup)


class HeroImageTests(unittest.TestCase):
    def test_a_lead_product_keeps_its_images(self):
        """They were emptied because a lead magnet is "never sold".

        But the picture is what the squeeze page shows above the form, so the hero_media section had nothing
        to render and every lead page was text on white.
        """
        self.assertNotIn("images: isLeadGen ? [] : images", PRODUCTS_STORE)
        self.assertIn("\n    images,\n", PRODUCTS_STORE)

    def test_the_rest_of_the_lead_gen_stripping_is_untouched(self):
        # Prices, shipping and variants are genuinely meaningless on something never sold — only the IMAGES
        # were wrong to drop.
        self.assertIn("isLeadGen ? [freeLeadPrice(", PRODUCTS_STORE)
        self.assertIn("requires_shipping: isPhysical && !isLeadGen", PRODUCTS_STORE)


class HeroDerivationTests(unittest.TestCase):
    """A page that stores no hero copy DERIVES it, the way the picture already did.

    `hero_media_images` has always fallen back to the offer and then the product. The words had no such
    fallback, so whatever a page was seeded with was what it showed forever — the freezing problem this
    codebase keeps rediscovering, and the reason the brand label stopped storing its own text.
    """

    def _render_without(self, *fields):
        page = _page()
        for section in page["sections"]:
            if section["type"] == "hero":
                for field in fields:
                    section.pop(field, None)
        return html_module.render_page(page, _offer(), _products())

    def test_the_headline_falls_back_to_the_offer_then_the_product(self):
        markup = self._render_without("headline", "subheadline")
        self.assertIn("2026 Guide to Junk Food Restaurants", markup)
        self.assertIn("My comprehensive list of fast food restaurants.", markup)

    def test_the_page_still_wins_when_it_says_something(self):
        # A tenant who typed a headline meant it; derivation is only for silence.
        markup = html_module.render_page(_page(), _offer(), _products())
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", markup, re.S).group(1)
        self.assertIn("2026 Guide to Junk Food Restaurants", h1)

    def test_it_falls_all_the_way_to_the_product(self):
        # An offer written before `presentation` existed.
        offer = _offer()
        offer["presentation"] = {"cta": {"type": "email", "label": "Get the guide"}}
        page = _page()
        for section in page["sections"]:
            if section["type"] == "hero":
                section.pop("headline", None)
                section.pop("subheadline", None)
        markup = html_module.render_page(page, offer, _products())
        self.assertIn("2026 Guide to Junk Food Restaurants", markup)

    def test_the_forms_own_description_is_never_the_subheadline(self):
        # lead_capture.description describes the FORM. The product's words are what belong under the
        # headline; this is the same leak as the seeder's, one layer down.
        markup = self._render_without("headline", "subheadline")
        hero = markup.split('class="sl-hero"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("We&#x27;ll email it to you.", hero)

    def test_the_picture_derives_from_the_product_too(self):
        # Already true, and pinned here because the two halves are the same rule: an existing page shows the
        # image as soon as the product HAS one, with no edit to the page.
        products = _products()
        products["prod_lead"]["images"] = ["https://images.juniorbay.com/products/abc/medium.webp"]
        page = _page()
        page["sections"].insert(1, {"id": "hero-media", "type": "hero_media", "images": []})
        markup = html_module.render_page(page, _offer(), products)
        self.assertIn("products/abc", markup)



class HeroRoundTripTests(unittest.TestCase):
    """The load/save loop that wrote the page's FILENAME into its own headline.

    Storing nothing was right; the builder then loaded `page.name` in its place, and the next save wrote that
    back as though the tenant had typed it. So a hero that derived correctly on Monday read "2025 Guide to
    Junk Food Restaurants Landing Page" on Tuesday — the document title, plus two words nobody wrote. Every
    step of the round trip has to agree on what "nothing stored" means, or one of them fills the gap.
    """

    @staticmethod
    def _code(block):
        """The block with comment lines removed — these assertions are about what RUNS, and the comments
        here quote the very fallbacks they describe removing."""
        return "\n".join(line for line in block.splitlines() if not line.strip().startswith("//"))

    def test_loading_falls_back_to_the_derived_value_not_the_filename(self):
        load = self._code(BUILDER.split("const hero = sections.find(", 1)[1][:3000])
        self.assertIn("formatHeadline(offerHeadline(offer)", load)
        self.assertIn("offerDescription(offer)", load)
        self.assertNotIn("|| page.name", load)

    def test_saving_has_no_page_name_fallback_either(self):
        build = self._code(BUILDER.split('if (sectionVisible("hero")) sections.push(', 1)[1][:1400])
        self.assertIn('heroOverride(formatHeadline(builder.headline || "")', build)
        self.assertNotIn("builder.name", build)

    def test_the_round_trip_is_a_no_op(self):
        """Load then save must not turn a derived value into a stored one.

        The builder loads the derived text so the field shows what the page says; heroOverride then drops it
        because it equals the derived value. If either half changes, the page silently opts out of every
        later correction to the offer — which is the bug, one layer up.
        """
        self.assertIn("function heroOverride(typed, derived)", BUILDER)
        fn = BUILDER.split("function heroOverride(typed, derived)", 1)[1].split("\n}", 1)[0]
        self.assertIn("value === String(derived || \"\").trim()", fn)
        self.assertIn("return undefined", fn)

    def test_the_cta_label_loads_from_the_offers_contract(self):
        # The renderer reads offer_cta(offer), so loading a generic "Continue" would show the tenant a label
        # their page does not use — and then store it.
        load = BUILDER.split("cta_label: cta.label", 1)[1][:300]
        self.assertIn("offer?.presentation?.cta?.label", load)


class CtaSourceTests(unittest.TestCase):
    def test_the_lead_button_reads_the_offer_not_the_page(self):
        # Pinned because it decides where a wrong button label has to be FIXED: in the offer, not the page.
        markup = _render()
        self.assertIn("Get the guide", markup)

    def test_the_page_label_now_overrides_the_offer(self):
        """Reversed on 2026-09-16, deliberately.

        This used to pin "the offer always wins", which meant the builder's Button Label field was a no-op on
        every lead page -- the tenant typed a label, saved, and nothing changed. render_buy_cta had always
        read section.label; the lead CTAs had not. The offer is still the fallback.
        """
        page = _page()
        for section in page["sections"]:
            if section["type"] == "checkout_cta":
                section["label"] = "Call Me Back"
        markup = html_module.render_page(page, _offer(), _products())
        self.assertIn("Call Me Back", markup)



class PhoneCaptureTests(unittest.TestCase):
    """capture_phone and capture_email_phone, given the same pass as capture_email (author, 2026-09-16).

    They share ONE cta type (the inline collector) and one page composition, which is why they were carried
    along by the email fixes -- and also why the two places that must still differ went unnoticed.
    """

    def _render(self, action, fields, cta_label, prefs=None):
        product = _products()["prod_lead"]
        product = {**product, "name": "Free Roof Inspection",
                   "description": "A 20-minute check and a written report.",
                   "lead_capture": {"action": action, "title": "Where can we reach you?",
                                    "description": "Enter your number and we'll be in touch.",
                                    "fields": fields}}
        offer = _offer()
        offer["lead_capture_action"] = action
        offer["presentation"] = {**offer["presentation"],
                                 "headline": "Free Roof Inspection",
                                 "cta": {"type": "email", "label": cta_label}, "cta_label": cta_label}
        page = _page()
        for section in page["sections"]:
            if section["type"] == "hero":
                section.pop("headline", None)
                section.pop("subheadline", None)
        return html_module.render_page(page, offer, {"prod_lead": product}, preferences=prefs or {})

    def _phone(self, **kw):
        return self._render("capture_phone", [{"name": "phone", "type": "tel", "required": True}],
                            "Request a Callback", **kw)

    def test_the_button_does_not_promise_a_download(self):
        # One CTA type, three different promises. "Get Instant Access" on a form that only takes a phone
        # number promises a download that is never coming.
        offers = (ROOT / "dashboard" / "src" / "components" / "Offers.vue").read_text(encoding="utf-8")
        labels = offers.split("const CAPTURE_CTA_LABELS = {", 1)[1].split("};", 1)[0]
        self.assertIn('capture_email: "Get Instant Access"', labels)
        self.assertIn('capture_phone: "Request a Callback"', labels)
        self.assertIn('capture_email_phone: "Get in Touch"', labels)

    def test_the_phone_field_is_typed_and_autofillable(self):
        # This form is ONE field and the visitor is on a phone: without autocomplete there is no saved value
        # and without inputmode no numeric keypad. On a page whose entire conversion is "type the one thing
        # we asked for", that IS the funnel.
        markup = self._phone()
        field = [line for line in markup.splitlines() if "<input class=\"sl-lead-input\"" in line][0]
        self.assertIn('type="tel"', field)
        self.assertIn('autocomplete="tel"', field)
        self.assertIn('inputmode="tel"', field)

    def test_the_placeholder_shows_a_shape_not_the_label_again(self):
        self.assertIn("(555) 555-0100", self._phone())
        self.assertNotIn('placeholder="Phone"', self._phone())

    def test_both_fields_are_hinted_when_both_are_asked_for(self):
        markup = self._render("capture_email_phone",
                              [{"name": "email", "type": "email", "required": True},
                               {"name": "phone", "type": "tel", "required": True}], "Get in Touch")
        self.assertIn('autocomplete="email"', markup)
        self.assertIn('autocomplete="tel"', markup)

    def test_an_unhinted_field_still_renders(self):
        # A tenant-declared field we have no hints for falls back to the humanised name, as before.
        markup = self._render("capture_email_phone", [{"name": "company_size", "type": "text"}], "Get in Touch")
        self.assertIn('placeholder="Company Size"', markup)

    def _email(self, **kw):
        return self._render("capture_email", [{"name": "email", "type": "email", "required": True}],
                            "Get Instant Access", **kw)

    def test_the_consent_line_names_the_business_not_the_product(self):
        """The half left behind when the brand label was fixed.

        `offer_brand_fallback` ends at the offer's headline, which IS the product name -- so a page asked the
        visitor to join "Free Roof Inspection's mailing list", which is not a thing that has a mailing list.
        Checked on an EMAIL capture: a phone capture now shows no consent at all.
        """
        self.assertIn("Join Apex Roofing&#x27;s mailing list.",
                      self._email(prefs={"business_name": "Apex Roofing"}))

    def test_the_product_name_is_never_the_list_owner(self):
        markup = self._email(prefs={"display_name": "Dana Reeve"})
        self.assertIn("Join Dana Reeve&#x27;s mailing list.", markup)
        self.assertNotIn("Free Roof Inspection&#x27;s mailing list", markup)

    def test_the_hero_still_derives_from_the_product(self):
        # The rest of the email-page work applies unchanged, because the composition is shared.
        markup = self._phone()
        self.assertIn("Free Roof Inspection", markup)
        self.assertIn("A 20-minute check and a written report.", markup)

    def test_neither_consent_box_is_ticked_here_either(self):
        form = self._email().split("sl-lead-form", 1)[1].split("</form>", 1)[0]
        self.assertNotIn("checked", form)



class PhoneCaptureTenantControlTests(unittest.TestCase):
    """A phone capture page is for OUTBOUND CALLS -- contractors, insurance, real estate (author, 2026-09-16).

    Which means the seeded copy cannot be a fixture: a roofer's "Where can we reach you?" is not an insurance
    broker's. The defaults stay; what changes is that they are now a starting point.
    """

    def _render(self, section_extra=None, fields=None):
        product = {**_products()["prod_lead"],
                   "lead_capture": {"action": "capture_phone", "title": "Where can we reach you?",
                                    "description": "Enter your number and we'll be in touch.",
                                    "fields": fields or [{"name": "phone", "type": "tel", "required": True}]}}
        offer = _offer()
        offer["presentation"] = {**offer["presentation"], "cta": {"type": "email", "label": "Offer Snapshot"}}
        page = _page()
        for section in page["sections"]:
            if section["type"] == "checkout_cta":
                section.update(section_extra or {})
        return html_module.render_page(page, offer, {"prod_lead": product})

    def test_the_page_can_replace_the_form_heading_and_description(self):
        markup = self._render({"form_title": "Get a free roof quote",
                               "form_description": "We call back within one business day."})
        self.assertIn("Get a free roof quote", markup)
        self.assertIn("We call back within one business day.", markup)
        self.assertNotIn("Where can we reach you?", markup)

    def test_the_products_default_shows_when_the_page_says_nothing(self):
        markup = self._render()
        self.assertIn("Where can we reach you?", markup)

    def test_the_button_label_on_the_PAGE_finally_works(self):
        """render_buy_cta read section.label; the lead CTAs never did.

        So the builder's "Button Label" field was a no-op on exactly the pages whose whole job is that
        button -- the tenant typed a label, saved, and the offer's snapshot kept winning.
        """
        self.assertIn("Call Me Back Today", self._render({"label": "Call Me Back Today"}))

    def test_the_offer_still_supplies_it_when_the_page_does_not(self):
        self.assertIn("Offer Snapshot", self._render({"label": ""}))


class ConsentScopeTests(unittest.TestCase):
    """Mailing-list consent belongs on a page that collects a mailing address."""

    def _boxes(self, action, fields):
        product = {**_products()["prod_lead"],
                   "lead_capture": {"action": action, "title": "T", "description": "D", "fields": fields}}
        markup = html_module.render_page(_page(), _offer(), {"prod_lead": product})
        return re.findall(r'<label class="sl-lead-consent"><input type="checkbox" data-consent="(\w+)"', markup)

    def test_a_phone_capture_asks_for_no_email_consent(self):
        # There is no address to add to a list, so both boxes asked the visitor to agree to something that
        # cannot happen -- and a consent nothing can act on is worse than not asking.
        self.assertEqual(self._boxes("capture_phone", [{"name": "phone", "type": "tel", "required": True}]), [])

    def test_an_email_capture_still_asks(self):
        self.assertEqual(
            self._boxes("capture_email", [{"name": "email", "type": "email", "required": True}]),
            ["tenant_marketing", "platform_marketing"])

    def test_asking_for_both_keeps_the_consents(self):
        self.assertEqual(
            self._boxes("capture_email_phone", [{"name": "email", "type": "email", "required": True},
                                                {"name": "phone", "type": "tel", "required": True}]),
            ["tenant_marketing", "platform_marketing"])

    def test_the_possessive_does_not_produce_uss(self):
        # "Join us's mailing list." is what the last-resort brand did to the apostrophe.
        product = {**_products()["prod_lead"],
                   "lead_capture": {"action": "capture_email", "title": "T", "description": "D",
                                    "fields": [{"name": "email", "type": "email", "required": True}]}}
        offer = _offer()
        offer["presentation"] = {"cta": {"type": "email", "label": "Go"}}
        markup = html_module.render_page(_page(), offer, {"prod_lead": product})
        self.assertIn("Join our mailing list.", markup)
        self.assertNotIn("us&#x27;s", markup)


class CtaDialogTests(unittest.TestCase):
    def test_the_dialog_names_the_action_not_the_shared_type(self):
        # One cta type ("email") backs three lead actions, so a phone capture announced itself as
        # "Email — inline capture form" in the very dialog that edits it.
        labels = BUILDER.split("const LEAD_ACTION_CTA_LABELS = {", 1)[1].split("};", 1)[0]
        self.assertIn('capture_phone: "Phone — outbound calls"', labels)
        self.assertIn('capture_email_phone: "Email + phone', labels)

    def test_the_form_fields_are_offered_only_for_the_inline_collector(self):
        # Bounded by the BRANCH, not by a character count. It was `[:3200]`, and every control added to the
        # CTA editor since pushed these fields closer to the edge until a comment tipped them over it -- a
        # test that fails on the length of a comment is measuring the wrong thing.
        dialog = BUILDER.split("sectionEditor.row.editor === 'checkout_cta'", 1)[1]
        dialog = dialog.split("sectionEditor.row.editor === '", 1)[0]
        self.assertIn("builder.cta_form_title", dialog)
        self.assertIn("builder.cta_form_description", dialog)
        self.assertIn("builderCta.type === 'email'", dialog)

    def test_only_an_edit_is_stored(self):
        # The product's default is a PLACEHOLDER. Loading it as a value would store it back on the next
        # save, which is the loop that wrote a filename into the hero.
        load = BUILDER.split("cta_form_title: cta.form_title", 1)[1][:120]
        self.assertIn('|| ""', load)
        save = BUILDER.split('id: "checkout-cta"', 1)[1][:400]
        self.assertIn("form_title: builder.cta_form_title || undefined", save)



if __name__ == "__main__":
    unittest.main()

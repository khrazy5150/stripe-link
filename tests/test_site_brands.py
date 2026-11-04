"""Brands belong to the business that owns them, not to the tenant (plans/SITE_AS_BUSINESS_IDENTITY.md §P3b).

The author's words: *"brands still sit on the tenant's profile. That's NOT correct!"* A tenant running two
businesses had ONE brand list, so the Quill storefront could be headlined "Poliaxis Nutrition" — the same
shape as the review-invite bug this plan opened with, one surface further forward.

Two surfaces offer brands, and they know different amounts, so they behave differently ON PURPOSE:

- the PAGE BUILDER knows its Site (it has a Site step), so it scopes strictly to that business;
- the OFFERS screen cannot — an offer is authored before any page exists for it — so it offers the union
  and names the owner beside each brand, which keeps the choice honest instead of hiding the ambiguity.

Both read `Site.organization.brands`. The tenant profile's list survives as a fallback until §P4 deletes
it, so no tenant opens an empty dropdown mid-migration.
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_site_organization
from stripe_link.runtime import html

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITES_STORE = (ROOT / "dashboard/src/stores/sites.js").read_text(encoding="utf-8")
BUILDER = (ROOT / "dashboard/src/components/LandingPages.vue").read_text(encoding="utf-8")
OFFERS = (ROOT / "dashboard/src/components/Offers.vue").read_text(encoding="utf-8")
SITES_SCREEN = (ROOT / "dashboard/src/components/Sites.vue").read_text(encoding="utf-8")


class TheSiteCarriesTheBrandsTests(unittest.TestCase):
    def test_the_schema_declares_them_on_the_organization(self):
        schema = json.loads((ROOT / "schemas/Site.schema.json").read_text(encoding="utf-8"))
        org = schema["properties"]["organization"]["properties"]
        self.assertEqual(org["brands"]["type"], "array")
        self.assertEqual(org["brands"]["items"]["type"], "string")
        self.assertEqual(org["sources"]["type"], "object")

    def test_the_organization_still_refuses_additional_properties(self):
        """`additionalProperties: false` is why these had to be declared rather than just written."""
        schema = json.loads((ROOT / "schemas/Site.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["properties"]["organization"]["additionalProperties"])

    def test_a_list_of_strings_is_accepted(self):
        validate_site_organization({"name": "Quill", "brands": ["Luxe Wellness", "Quill Basics"]})

    def test_a_malformed_list_is_refused(self):
        for bad in ("Luxe", [1], [None], {"a": "b"}):
            with self.subTest(bad=bad):
                with self.assertRaises(DocumentValidationError):
                    validate_site_organization({"brands": bad})

    def test_NO_brands_is_valid(self):
        """Every Site that exists today has none."""
        validate_site_organization({"name": "Quill"})

    def test_the_list_is_UNCAPPED_and_UNTRIMMED_like_the_one_it_moves_from(self):
        """A stricter rule here would refuse a list the tenant could already save on their profile — a
        migration that fails on its own data. The dashboard trims and de-duplicates on the way out; the
        validator's job is only to let the migration through."""
        validate_site_organization({"brands": ["  padded  ", "dup", "dup"] + [f"b{i}" for i in range(50)]})

    def test_sources_is_a_map_of_field_to_provenance(self):
        validate_site_organization({"sources": {"name": "stripe", "address": "gbp"}})
        with self.assertRaises(DocumentValidationError):
            validate_site_organization({"sources": {"name": 1}})


class ThePagesOwnBrandDrivesTheTitleTests(unittest.TestCase):
    """One brand per page, used everywhere (author's choice, 2026-11-03).

    Before this the visible header read the PAGE's `brand_label` and the `<title>` suffix read the OFFER's
    `presentation.brand`, so one document could name two different businesses — a page headed "Luxe
    Wellness" titled "… | Quill". The chain is now: the page's own brand, then the offer's stored brand (a
    legacy carrier, so no published page changes until a brand is picked), then the Site's organization
    name, then the platform.
    """

    def setUp(self):
        self._org = dict(html._RENDER_ORG)
        html._RENDER_ORG.clear()
        html._RENDER_ORG.update({"name": "Quill"})

    def tearDown(self):
        html._RENDER_ORG.clear()
        html._RENDER_ORG.update(self._org)

    def _page(self, label=None, enabled=True):
        section = {"type": "brand_label", "id": "bl"}
        if label is not None:
            section["label"] = label
        if not enabled:
            section["enabled"] = False
        return {"sections": [{"type": "hero", "id": "h"}, section]}

    def test_the_pages_brand_WINS(self):
        self.assertEqual(
            html.resolved_brand_label({"brand": "Legacy Offer Brand"}, self._page("Luxe Wellness")),
            "Luxe Wellness")

    def test_the_offers_stored_brand_is_the_next_answer(self):
        """So a page that has never picked a brand keeps the title it has today."""
        self.assertEqual(html.resolved_brand_label({"brand": "Legacy Offer Brand"}, self._page("")),
                         "Legacy Offer Brand")

    def test_then_the_SITE(self):
        self.assertEqual(html.resolved_brand_label({}, self._page("")), "Quill")

    def test_a_page_with_no_brand_label_section_at_all_still_resolves(self):
        self.assertEqual(html.resolved_brand_label({}, {"sections": []}), "Quill")

    def test_a_caller_passing_NO_page_is_unchanged(self):
        """`resolved_brand_label` is called from two places and both pass the page; the default keeps any
        other caller, and every existing test, working."""
        self.assertEqual(html.resolved_brand_label({"brand": "Legacy Offer Brand"}), "Legacy Offer Brand")

    def test_a_HIDDEN_brand_header_is_not_a_brand_claim(self):
        """A tenant who switched the header off has not chosen a brand for the page — reading its leftover
        label would put a name in the title that appears nowhere on the page."""
        self.assertEqual(
            html.resolved_brand_label({}, self._page("Luxe Wellness", enabled=False)), "Quill")

    def test_the_platform_is_the_last_resort(self):
        html._RENDER_ORG.clear()
        self.assertEqual(html.resolved_brand_label({}, {"sections": []}), html.PLATFORM_BRAND)

    def test_both_call_sites_pass_the_page(self):
        """The title suffix and og:site_name. If either kept the old one-argument call they would disagree
        with the header again, which is the bug."""
        source = (ROOT / "src/stripe_link/runtime/html.py").read_text(encoding="utf-8")
        calls = [line.strip() for line in source.splitlines()
                 if "resolved_brand_label(" in line and "def " not in line]
        self.assertEqual(len(calls), 2, calls)
        for call in calls:
            with self.subTest(call=call):
                self.assertIn("page", call)


class TheBuilderScopesStrictlyTests(unittest.TestCase):
    """The surface where it matters: the brand chosen here becomes the headline on a page that belongs to
    exactly one business."""

    def test_it_asks_the_SELECTED_SITE_for_its_brands(self):
        block = BUILDER.split("const storeBrands = computed(", 1)[1][:400]
        self.assertIn("siteBrands(selectedSite.value)", block)

    def test_the_tenant_wide_list_is_GONE(self):
        """§P4 deleted it, 2026-11-04. It existed so a tenant mid-migration did not meet an empty dropdown;
        `audit_tenant_fallback.py` then measured ZERO profiles carrying a brand in dev AND prod, so it was
        reading a field nobody had. A brand now comes from the Site, or from the "+ New brand" control
        beside the picker, which writes it there."""
        block = BUILDER.split("const storeBrands = computed(", 1)[1][:300]
        self.assertNotIn("profileStore.brands", block)
        self.assertIn("siteBrands(selectedSite.value)", block)

    def test_the_PROFILE_SCREEN_no_longer_edits_brands(self):
        """Leaving the editor while nothing reads it is the worse half of a half-migration: a tenant types
        brands into a field that cannot affect any page."""
        profile_screen = (ROOT / "dashboard/src/components/Profile.vue").read_text(encoding="utf-8")
        self.assertNotIn("form.business.brands", profile_screen)
        self.assertNotIn("addBrand", profile_screen)
        store = (ROOT / "dashboard/src/stores/profile.js").read_text(encoding="utf-8")
        self.assertNotIn("business.brands", store)

    def test_the_control_is_a_PICKER_not_a_text_box(self):
        """Typing a name freehand is how a Quill page comes to be headed "Poliaxis Nutrition": a brand has
        to be one the Site's business actually owns."""
        block = BUILDER.split("sectionEditor.row.editor === 'brand_label'", 1)[1][:3000]
        self.assertIn('<select v-if="!brandCreateOpen" v-model="builder.brand_label_text">', block)
        self.assertIn('v-for="b in selectedSiteBrands"', block)

    def test_a_brand_can_be_CREATED_from_the_picker(self):
        """The author's "or optionally, allow the tenant to create a brand right from there" — it writes to
        the Site and selects it in one step, so the brand is still a fact about the business."""
        self.assertIn("addSiteBrandAndSelect", BUILDER)
        block = BUILDER.split("async function addSiteBrand(", 1)[1][:900]
        self.assertIn("sitesStore.addBrand(selectedSite.value.site_id", block)

    def test_the_site_step_offers_to_add_a_brand(self):
        """*"When a Site is selected (or created) the tenant should have the option to add a brand to go
        along with it."* """
        self.assertIn('v-if="selectedSite" class="offer-field wizard-site-brands"', BUILDER)
        self.assertIn("addSiteBrand", BUILDER)

    def test_a_brand_the_page_ALREADY_names_stays_selectable(self):
        """Opening an older page whose brand the Site no longer lists must not silently re-brand it on the
        next save."""
        block = BUILDER.split("sectionEditor.row.editor === 'brand_label'", 1)[1][:3000]
        self.assertIn("!selectedSiteBrands.includes(builder.brand_label_text)", block)



class TheOffersScreenHasNoBrandPickerTests(unittest.TestCase):
    """An offer cannot name a business, so it must not offer the choice (author, 2026-11-03).

    *"Offers are created before a page and before a site is assigned. In fact, the software is designed to
    allow tenants to create a brand new Site at page creation. This means that the only place in which
    brands can reasonably be picked is at the Landing Page Builder."*

    An earlier pass at P3b kept the control here and offered the union of every Site's brands, labelled by
    owner. That was the wrong answer to the right question: at this point in the flow there is no business
    to pick from, so any list shown is a list of other businesses' brands.
    """

    def test_the_control_is_GONE(self):
        self.assertNotIn("<span>Brand</span>", OFFERS)
        self.assertNotIn('v-model="form.brand"', OFFERS)

    def test_it_reads_no_brand_list_at_all(self):
        for dead in ("profileBrands", "brandOptions", "siteBrands"):
            with self.subTest(dead=dead):
                self.assertNotIn(dead, OFFERS)

    def test_a_loaded_offers_brand_is_still_CARRIED(self):
        """The author's call: leave the stored values readable. An offer saved before this keeps the brand
        it was saved with, so no published page changes until a brand is picked at the builder."""
        self.assertIn('form.brand = offer.presentation?.brand || ""', OFFERS)
        self.assertIn("brand: form.brand || undefined", OFFERS)

    def test_it_NO_LONGER_bakes_the_tenants_business_name_into_a_new_offer(self):
        """The sharp edge of removing the picker. `brand: form.brand || profileStore.businessName` stamped
        the tenant's ONE business name onto every new offer, and in the renderer's chain the offer's brand
        sits ABOVE the Site's organization name — so every page of every other business would have been
        titled after the first one. The review-invite bug arriving by a different road."""
        # Asserted on the CODE, not the surrounding block: the comment above it names the removed
        # expression on purpose, and a substring search over the block matches the explanation.
        self.assertNotIn("brand: form.brand || profileStore.businessName", OFFERS)
        self.assertIn("brand: form.brand || undefined,", OFFERS)

    def test_the_slug_preview_is_left_alone(self):
        """`smartOfferSlug` is a deliberate mirror of the server's `smart_offer_slug`. The brand's part in a
        SLUG is a different question from the brand's part in a TITLE, and changing one here would put the
        two implementations out of parity."""
        self.assertIn("slugTokens(form.brand || profileStore.businessName", OFFERS)


class TheStoreIsTheOneSourceTests(unittest.TestCase):
    def test_siteBrands_reads_the_organization(self):
        block = SITES_STORE.split("export function siteBrands(", 1)[1][:300]
        self.assertIn("organization?.brands", block)

    def test_the_UNION_helper_is_gone(self):
        """It existed only for the Offers picker. With that control removed, a function that mixes two
        businesses' brands into one list has no caller and no reason to exist — and leaving it would invite
        the next screen to reach for it."""
        self.assertNotIn("brandOptions", SITES_STORE)

    def test_ONE_writer_adds_a_brand(self):
        """The wizard's Site step and the builder's brand picker both add brands. Two code paths would be
        two chances for one of them to write somewhere else."""
        block = SITES_STORE.split("async addBrand(", 1)[1][:800]
        self.assertIn("organization: { ...(site.organization || {}), brands:", block)
        self.assertIn("toLowerCase()", block)   # adding a brand the Site already owns is a no-op

    def test_a_derived_default_site_INHERITS_the_brands_it_came_from(self):
        """A tenant's first Site is built from their profile. Without this they would open the brand picker
        on their own Site and find it empty."""
        block = SITES_STORE.split("export function organizationFromBusiness(", 1)[1][:900]
        self.assertIn("business.brands", block)
        self.assertIn("business.sources", block)


class TheSitesScreenManagesThemTests(unittest.TestCase):
    def test_the_editor_has_a_brand_list(self):
        self.assertIn('v-for="(brand, index) in form.org.brands"', SITES_SCREEN)
        self.assertIn("addOrgBrand", SITES_SCREEN)
        self.assertIn("removeOrgBrand", SITES_SCREEN)

    def test_it_loads_the_stored_brands_into_the_form(self):
        block = SITES_SCREEN.split("function openEdit(", 1)[1][:1600]
        self.assertIn("brands: Array.isArray(org.brands) ? [...org.brands] : []", block)

    def test_saving_TRIMS_and_DEDUPLICATES(self):
        block = SITES_SCREEN.split("async function saveEdit(", 1)[1][:900]
        self.assertIn("new Set(", block)
        self.assertIn(".trim()", block)

    def test_clearing_every_brand_REMOVES_the_key(self):
        """Rather than storing an empty array on a Site nobody has given brands. `undefined` is dropped by
        the same filter that drops every other unset organization field."""
        block = SITES_SCREEN.split("async function saveEdit(", 1)[1][:900]
        self.assertIn("brands.length ? brands : undefined", block)


class TheOperationalFieldsMovedSEPARATELYTests(unittest.TestCase):
    """P3b left `timezone` and `shipping_cutoff_hour` on the account ON PURPOSE — *"Not identity.
    Operational... it should not ride along silently."* They have since moved, under their own plan
    (`plans/SHIPPING_PER_SITE.md` §S1) and with their own resolution rule, which is exactly what "not
    silently" asked for.

    This test flipped rather than being deleted: the point it was making was never "these fields must
    never move", it was "they must not move as a side effect of the identity work". Both halves of the
    account/Site split are now asserted, so neither can quietly disappear.
    """

    def test_they_ARE_on_the_site_organization_now(self):
        schema = json.loads((ROOT / "schemas/Site.schema.json").read_text(encoding="utf-8"))
        org = schema["properties"]["organization"]["properties"]
        self.assertEqual(org["timezone"]["type"], ["string", "null"])
        self.assertEqual(org["shipping_cutoff_hour"]["maximum"], 23)

    def test_they_are_STILL_on_the_tenant_profile_as_the_fallback(self):
        """A Site that states neither inherits the account's, so the account-level fields are not dead —
        and `business.address` is still what the timezone is guessed from."""
        validator = (ROOT / "src/stripe_link/domain/documents.py").read_text(encoding="utf-8")
        self.assertIn('optional_string(business, "timezone"', validator)
        self.assertIn('"shipping_cutoff_hour"', validator)

    def test_the_SHIP_FROM_ADDRESS_did_not_move_with_them(self):
        """It was never on the profile to begin with — it lives on ShippingConfig, which is §S3/§S4's
        work, not §S1's. Recorded because the plan's own first finding was that this assumption was
        wrong."""
        schema = json.loads((ROOT / "schemas/Site.schema.json").read_text(encoding="utf-8"))
        org = schema["properties"]["organization"]["properties"]
        self.assertNotIn("ship_from_address", org)
        self.assertNotIn("return_address", org)


if __name__ == "__main__":
    unittest.main()

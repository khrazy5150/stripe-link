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


class TheBuilderScopesStrictlyTests(unittest.TestCase):
    """The surface where it matters: the brand chosen here becomes the headline on a page that belongs to
    exactly one business."""

    def test_it_asks_the_SELECTED_SITE_for_its_brands(self):
        block = BUILDER.split("const storeBrands = computed(", 1)[1][:400]
        self.assertIn("siteBrands(selectedSite.value)", block)

    def test_it_no_longer_reads_the_tenant_wide_list_FIRST(self):
        block = BUILDER.split("const storeBrands = computed(", 1)[1][:400]
        self.assertLess(block.index("siteBrands(selectedSite.value)"), block.index("profileStore.brands"),
                        "the Site must be consulted before the tenant-wide fallback")

    def test_the_tenant_list_survives_as_a_FALLBACK(self):
        """Until §P4 deletes it. Without this a tenant mid-migration opens an empty dropdown and loses the
        brands they have always had."""
        block = BUILDER.split("const storeBrands = computed(", 1)[1][:400]
        self.assertIn("profileStore.brands", block)


class TheOffersScreenNamesTheOwnerTests(unittest.TestCase):
    def test_it_no_longer_reads_the_profile_brands_directly(self):
        self.assertNotIn("profileStore.brands)", OFFERS.replace("sitesStore.brandOptions(profileStore.brands)", ""))
        self.assertNotIn("profileBrands", OFFERS)

    def test_it_offers_the_union_through_the_store(self):
        self.assertIn("sitesStore.brandOptions(profileStore.brands)", OFFERS)

    def test_the_owner_is_shown_only_when_there_is_MORE_THAN_ONE_site(self):
        """With a single Site every brand belongs to it, and the suffix would be noise on every row."""
        self.assertIn("sitesStore.sites.length > 1", OFFERS)

    def test_a_brand_the_tenant_already_chose_stays_selectable(self):
        """An offer saved before this change may name a brand no Site declares. Dropping it from the
        options would silently reset the offer's brand the next time it was saved."""
        self.assertIn('v-if="form.brand && !brandOptions.some((o) => o.brand === form.brand)"', OFFERS)

    def test_the_help_text_points_at_the_new_home(self):
        self.assertIn("Sites → Edit → Business", OFFERS)
        self.assertNotIn("Manage your brands in Profile", OFFERS)


class TheStoreIsTheOneSourceTests(unittest.TestCase):
    def test_siteBrands_reads_the_organization(self):
        block = SITES_STORE.split("export function siteBrands(", 1)[1][:300]
        self.assertIn("organization?.brands", block)

    def test_brandOptions_tags_each_brand_with_its_owner(self):
        block = SITES_STORE.split("brandOptions(", 1)[1][:900]
        self.assertIn("siteBrands(site)", block)
        self.assertIn("organization?.name", block)
        self.assertIn("{ brand, owner }", block)

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


class TheOperationalFieldsDidNotRideAlongTests(unittest.TestCase):
    """The plan calls these out by name: *"Not identity. Operational... it should not ride along silently."*
    `timezone` is already duplicated by TenantAvailability/booking, and `shipping_cutoff_hour` answers a
    shipping question. Both stay on the tenant profile until they get their own decision."""

    def test_neither_appeared_on_the_site_organization(self):
        schema = json.loads((ROOT / "schemas/Site.schema.json").read_text(encoding="utf-8"))
        org = schema["properties"]["organization"]["properties"]
        self.assertNotIn("timezone", org)
        self.assertNotIn("shipping_cutoff_hour", org)

    def test_they_are_STILL_on_the_tenant_profile(self):
        validator = (ROOT / "src/stripe_link/domain/documents.py").read_text(encoding="utf-8")
        self.assertIn('optional_string(business, "timezone"', validator)
        self.assertIn('"shipping_cutoff_hour"', validator)


if __name__ == "__main__":
    unittest.main()

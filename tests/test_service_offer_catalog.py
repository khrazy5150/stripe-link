"""The Organization's hasOfferCatalog, and the Service.serviceType that is the point of it.

A local trade with no schema.org type of its own — a massage therapist — cannot say what it does in
`@type`, because schema.org is a closed vocabulary (plans/BUSINESS_TYPE_VOCABULARY.md). `Service.serviceType`
is free Text, so the catalog is where that claim becomes sayable AND accurate. These tests pin the shape,
and the exclusions that keep it honest.

Every test here asserts a BASELINE before the behaviour it is about: this file would otherwise pass
vacuously if the catalog silently stopped being emitted at all.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_service
from stripe_link.runtime import html

ROOT = pathlib.Path(__file__).resolve().parents[1]

ORG = {
    "name": "Luxe Wellness Spa",
    "entity_type": "HealthAndBeautyBusiness",
    "address": {"street": "123 Main St", "locality": "St. George", "region": "UT"},
}
ORIGIN = "https://luxe.example.com"


def catalog_for(services, *, org=None, category_pages=None):
    """The hasOfferCatalog the renderer produces for `services`, via the real render-scoped globals."""
    html._RENDER_SERVICE_CATALOG.clear()
    html._RENDER_CATEGORY_PAGES.clear()
    try:
        html._RENDER_SERVICE_CATALOG.extend(
            s for s in services if isinstance(s, dict) and s.get("active") is not False
        )
        html._RENDER_CATEGORY_PAGES.update(category_pages or {})
        return html.organization_node(org or ORG, ORIGIN).get("hasOfferCatalog")
    finally:
        html._RENDER_SERVICE_CATALOG.clear()
        html._RENDER_CATEGORY_PAGES.clear()


class ServiceCatalogShape(unittest.TestCase):
    def test_no_services_and_no_category_pages_emit_no_catalog(self):
        """The baseline the rest of the file depends on: absence really is absence."""
        self.assertIsNone(catalog_for([]))

    def test_service_category_becomes_a_group_and_the_servicetype(self):
        catalog = catalog_for([
            {"name": "90-Minute Deep Tissue", "product_category": "massage_therapy",
             "description": "Deep tissue work."},
        ])
        self.assertIsNotNone(catalog)
        self.assertEqual("OfferCatalog", catalog["@type"])
        group = catalog["itemListElement"][0]
        self.assertEqual({"@type": "OfferCatalog", "name": "Massage Therapy"},
                         {k: group[k] for k in ("@type", "name")})
        offer = group["itemListElement"][0]
        self.assertEqual("Offer", offer["@type"])
        self.assertEqual(
            {"@type": "Service", "name": "90-Minute Deep Tissue",
             "serviceType": "Massage Therapy", "description": "Deep tissue work."},
            offer["itemOffered"],
        )

    def test_the_whole_point_massage_therapy_is_sayable_where_type_cannot_say_it(self):
        """`@type` stays the broad bucket; serviceType carries the trade. Both, in one node."""
        html._RENDER_SERVICE_CATALOG.clear()
        html._RENDER_SERVICE_CATALOG.append({"name": "Swedish Massage", "product_category": "massage_therapy"})
        try:
            node = html.organization_node(ORG, ORIGIN)
        finally:
            html._RENDER_SERVICE_CATALOG.clear()
        self.assertEqual("HealthAndBeautyBusiness", node["@type"])  # no MassageTherapist type exists
        blob = json.dumps(node)
        self.assertIn("Massage Therapy", blob)
        self.assertNotIn("MassageTherapist", blob)  # never invent a type

    def test_several_categories_each_get_their_own_group(self):
        catalog = catalog_for([
            {"name": "Signature Facial", "product_category": "skin_care"},
            {"name": "Swedish Massage", "product_category": "massage_therapy"},
        ])
        self.assertEqual(["Massage Therapy", "Skin Care"],
                         [i["name"] for i in catalog["itemListElement"]])

    def test_an_uncategorised_service_is_listed_but_claims_no_type(self):
        """Not dropped (the catalog would be incomplete) and not guessed (the claim would be false)."""
        catalog = catalog_for([{"name": "Infrared Sauna Session"}])
        offer = catalog["itemListElement"][0]
        self.assertEqual("Offer", offer["@type"])  # a bare Offer, not an OfferCatalog group
        self.assertEqual({"@type": "Service", "name": "Infrared Sauna Session"}, offer["itemOffered"])
        self.assertNotIn("serviceType", offer["itemOffered"])

    def test_an_archived_service_is_not_advertised(self):
        active = {"name": "Swedish Massage", "product_category": "massage_therapy"}
        self.assertIsNotNone(catalog_for([active]))  # baseline: it WOULD be listed if active
        self.assertIsNone(catalog_for([{**active, "active": False}]))

    def test_a_nameless_service_is_skipped_rather_than_emitting_an_empty_node(self):
        catalog = catalog_for([
            {"name": "Swedish Massage", "product_category": "massage_therapy"},
            {"name": "   ", "product_category": "massage_therapy"},
        ])
        names = [o["itemOffered"]["name"] for o in catalog["itemListElement"][0]["itemListElement"]]
        self.assertEqual(["Swedish Massage"], names)

    def test_no_price_is_claimed(self):
        """A service's price depends on the render's price context, so a single number here could
        contradict the page it sits on."""
        catalog = catalog_for([
            {"name": "Swedish Massage", "product_category": "massage_therapy",
             "price": {"currency": "usd", "unit_amount": 9000}},
        ])
        self.assertNotIn("price", json.dumps(catalog))

    def test_output_is_stable_so_republishing_is_a_no_op(self):
        services = [
            {"name": "Swedish Massage", "product_category": "massage_therapy"},
            {"name": "Deep Tissue", "product_category": "massage_therapy"},
            {"name": "Signature Facial", "product_category": "skin_care"},
        ]
        first = catalog_for(services)
        self.assertEqual(first, catalog_for(list(reversed(services))))

    def test_category_pages_still_emit_and_services_are_added_alongside(self):
        pages = {"supplements": {"slug": "supplements", "label": "Supplements"}}
        products_only = catalog_for([], category_pages=pages)
        self.assertEqual([{"@type": "OfferCatalog", "name": "Supplements"}],
                         products_only["itemListElement"])
        both = catalog_for([{"name": "Swedish Massage", "product_category": "massage_therapy"}],
                           category_pages=pages)
        self.assertEqual(["Supplements", "Massage Therapy"],
                         [i["name"] for i in both["itemListElement"]])

    def test_the_catalog_does_not_leak_between_renders(self):
        """_RENDER_SERVICE_CATALOG is render-scoped; one tenant's services must not reach another's page
        on a warm container."""
        catalog_for([{"name": "Swedish Massage", "product_category": "massage_therapy"}])
        self.assertEqual([], html._RENDER_SERVICE_CATALOG)
        self.assertIsNone(html.organization_node(ORG, ORIGIN).get("hasOfferCatalog"))


class CatalogReachesARealPage(unittest.TestCase):
    """End to end through `render_page`, not by poking the render globals.

    Every other test in this file sets `_RENDER_SERVICE_CATALOG` itself, so all of them would still pass if
    the `service_catalog=` parameter were never wired to that global — which is the one thing the publisher
    actually depends on.
    """

    SITE = {
        "organization": {
            "name": "Luxe Wellness Spa",
            "entity_type": "HealthAndBeautyBusiness",
            "address": {"street": "123 Main St", "locality": "St. George", "region": "UT"},
        },
        "hosting": {"type": "custom", "custom_domain": "luxe.example.com",
                    "verification": {"verified": True}},
    }

    def _render(self, service_catalog=None):
        from tests.test_structured_data import load_fixture

        page = load_fixture("page-creatine-standard.json")
        page["sections"].append({"id": "structured-data", "type": "structured_data"})
        page["goal"] = "search_seo"
        offer = load_fixture("offer-creatine-standard.json")
        product = load_fixture("product-creatine-gummies.json")
        return html.render_page(
            page, offer, {product["product_id"]: product},
            canonical_url="https://luxe.example.com/", robots="index,follow",
            site=self.SITE, page_type="landing", service_catalog=service_catalog,
        )

    @staticmethod
    def _org_node(markup):
        for block in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', markup, re.S):
            raw = block.group(1).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
            payload = json.loads(raw)
            if str(payload.get("@id", "")).endswith("#organization"):
                return payload
        return None

    def test_a_page_rendered_without_a_catalog_has_none(self):
        node = self._org_node(self._render())
        self.assertIsNotNone(node, "the Organization node is the baseline for this test")
        self.assertNotIn("hasOfferCatalog", node)

    def test_passing_the_catalog_puts_servicetype_on_the_page(self):
        markup = self._render([{"name": "Swedish Massage", "product_category": "massage_therapy"}])
        node = self._org_node(markup)
        offer = node["hasOfferCatalog"]["itemListElement"][0]["itemListElement"][0]
        self.assertEqual("Massage Therapy", offer["itemOffered"]["serviceType"])

    def test_render_page_filters_archived_services_itself(self):
        """The filter lives in the render context, so the publisher can hand over the raw list."""
        markup = self._render([
            {"name": "Swedish Massage", "product_category": "massage_therapy", "active": True},
            {"name": "Retired Hot Stone", "product_category": "massage_therapy", "active": False},
        ])
        names = [o["itemOffered"]["name"]
                 for o in self._org_node(markup)["hasOfferCatalog"]["itemListElement"][0]["itemListElement"]]
        self.assertEqual(["Swedish Massage"], names)


class ServiceCategoryIsStored(unittest.TestCase):
    """The field has to survive the round trip, or the catalog has nothing to group by."""

    BASE = {
        "schema_version": "2026-05-29", "document_type": "service", "tenant_id": "t1",
        "service_id": "svc_1", "name": "Swedish Massage", "duration_minutes": 60,
        "price": {"currency": "usd", "unit_amount": 9000},
    }

    def test_validator_accepts_a_category_and_a_service_without_one(self):
        validate_service(dict(self.BASE))  # optional: every existing service predates the field
        validate_service({**self.BASE, "product_category": "massage_therapy"})

    def test_validator_rejects_a_non_string_category(self):
        with self.assertRaises(DocumentValidationError):
            validate_service({**self.BASE, "product_category": ["massage_therapy"]})

    def test_schema_documents_the_field(self):
        schema = json.loads((ROOT / "schemas" / "Service.schema.json").read_text())
        self.assertFalse(schema["additionalProperties"])  # baseline: an undocumented field is a real gap
        self.assertEqual("string", schema["properties"]["product_category"]["type"])
        self.assertNotIn("product_category", schema["required"])

    def test_the_dashboard_sends_and_reloads_the_category(self):
        """Source-level, because there is no JS suite. The wizard asked for this field since 2026-09-15
        while the document builder dropped it, so the field existed and stored nothing."""
        store = (ROOT / "dashboard" / "src" / "stores" / "services.js").read_text()
        builder = store[store.index("export async function buildServiceDocument"):]
        builder = builder[:builder.index("\n}\n")]
        self.assertIn("product_category:", strip_js_comments(builder))

        edit = (ROOT / "dashboard" / "src" / "components" / "Services.vue").read_text()
        self.assertIn("product_category: service.product_category", strip_js_comments(edit))

    def test_both_service_forms_render_the_picker_scoped_to_services(self):
        for relative in ("components/Services.vue", "components/services/ServiceWizard.vue"):
            source = strip_js_comments((ROOT / "dashboard" / "src" / relative).read_text())
            with self.subTest(relative):
                self.assertRegex(
                    source,
                    r'<ProductCategoryField[^>]*v-model="form\.product_category"[^>]*product-type="service"',
                )


def strip_js_comments(source: str) -> str:
    """Drop // and /* */ comments so a comment that MENTIONS a field cannot satisfy an assertion about
    the code — these guards read shipped source, where the two are easy to confuse."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in source.splitlines())


class TheListCanShowWhatItDisplays(unittest.TestCase):
    """The Details pane reads a list ROW, not the document.

    Only the editor refetches the whole service (`openEditModal` -> `fetchFullService`), so a field the
    list DISPLAYS has to survive the slim projection. It did not, and the pane read "Not set" for every
    service — including one whose category was stored and already being emitted into the page's JSON-LD.
    """

    def test_the_projection_carries_the_category(self):
        from stripe_link.domain.service_index import service_index_entry

        row = service_index_entry({
            "service_id": "svc_1", "name": "60-Minute Massage",
            "product_category": "massage_therapy",
            "price": {"currency": "usd", "unit_amount": 7800},
        })
        self.assertEqual("massage_therapy", row.get("product_category"))

    def test_a_service_with_no_category_simply_omits_it(self):
        from stripe_link.domain.service_index import service_index_entry

        row = service_index_entry({"service_id": "svc_1", "name": "Sauna", "product_category": ""})
        self.assertNotIn("product_category", row)

    def test_the_details_pane_reads_the_field_the_projection_now_carries(self):
        pane = strip_js_comments((ROOT / "dashboard" / "src" / "components" / "Services.vue").read_text())
        self.assertIn("humanizeCategory(selectedService.product_category)", pane)

if __name__ == "__main__":
    unittest.main()

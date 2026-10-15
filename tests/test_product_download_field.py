"""The download file is asked for while the product is being CREATED, not only after it exists.

Reported 2026-10-14: the edit form has a "Download File" picker, the create wizard does not. So a tenant
making their first digital product walks the whole wizard, saves, and has a product that charges money and
delivers nothing -- the file can only be attached by finding the product again and reopening it, which the
wizard never mentions.

One component now serves both bodies, because the gap was exactly what two copies of a field produce: the
edit form grew one and the wizard never did.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "dashboard" / "src"
PRODUCTS = (SRC / "components" / "Products.vue").read_text(encoding="utf-8")
FIELD = (SRC / "components" / "products" / "ProductDownloadField.vue").read_text(encoding="utf-8")
STORE = (SRC / "stores" / "products.js").read_text(encoding="utf-8")

TEMPLATE, SCRIPT = PRODUCTS.split("<script setup>", 1)


def details_step() -> str:
    """ONLY the wizard's 'Product details' panel.

    Anchored between the two step guards rather than searched for in the whole template: the edit form has
    its own copy of nearly every field here, so a file-wide `assertIn` passes on the edit form's markup and
    proves nothing about the wizard. That is the mistake this suite exists to catch.
    """
    body = TEMPLATE.split("""wizardStepKey === 'details'""", 1)[1]
    return body.split("""wizardStepKey === 'pricing'""", 1)[0]


def edit_body() -> str:
    return TEMPLATE.split("""<form v-else class="product-create-body\"""", 1)[1]


class WizardTests(unittest.TestCase):
    def test_the_details_step_offers_the_download_field(self):
        self.assertIn("<ProductDownloadField", details_step())

    def test_only_for_a_digital_product(self):
        """A physical product has a box; a service has a calendar. Neither delivers a file, and offering
        one would be the same noise the wizard was built to remove."""
        block = details_step().split("<ProductDownloadField", 1)[1][:200]
        self.assertIn("form.product_type === 'digital'", block)

    def test_it_sits_in_the_transaction_branch(self):
        """A lead magnet's file is delivered by its lead_capture action, not by a purchase receipt, so the
        picker must not appear on a lead-gen or tip-jar wizard."""
        step = details_step()
        transaction = step.split("""wizardIntent === 'transaction'""", 1)[1]
        transaction = transaction.split("""wizardIntent === 'lead_gen'""", 1)[0]
        self.assertIn("<ProductDownloadField", transaction)

    def test_advancing_is_blocked_while_a_file_uploads(self):
        """Details is not the last step, but Continue during an upload still abandons the file: the form
        moves on and the promise lands on a step nobody is looking at."""
        advance = SCRIPT.split("const wizardCanAdvance = computed", 1)[1].split("});", 1)[0]
        self.assertIn("if (uploadingAsset.value) return false;", advance)


class SharedFieldTests(unittest.TestCase):
    def test_both_bodies_use_the_same_component(self):
        self.assertIn("<ProductDownloadField", details_step())
        self.assertIn("<ProductDownloadField", edit_body())
        self.assertIn('import ProductDownloadField from "./products/ProductDownloadField.vue";', SCRIPT)

    def test_no_inline_copy_survives(self):
        """The edit form's hand-rolled picker is GONE, not merely joined by a component. Leaving it is how
        the two drift again -- and drift is the whole bug."""
        self.assertNotIn("digital-asset-picker", TEMPLATE)
        self.assertNotIn("onDigitalFileChange", PRODUCTS)
        self.assertIn("digital-asset-picker", FIELD)

    def test_the_edit_form_keeps_its_guards(self):
        block = edit_body().split("<ProductDownloadField", 1)[1][:260]
        self.assertIn("form.product_type === 'digital'", block)
        self.assertIn("form.product_intent === 'transaction'", block)

    def test_saving_is_blocked_while_a_file_uploads(self):
        footer = edit_body().split("product-modal-footer", 1)[1][:600]
        self.assertIn('store.savingStatus || uploadingAsset', footer)

    def test_failures_reach_the_banner(self):
        """Both bodies render `formError`, so a failed upload has to be told to it -- the component cannot
        show it itself, and an upload that fails silently reads as one that worked."""
        for body in (details_step(), edit_body()):
            block = body.split("<ProductDownloadField", 1)[1][:300]
            self.assertIn('@error="formError = $event"', block)


class ProductIdTests(unittest.TestCase):
    """The file is uploaded BEFORE the product is saved, under the product's own id. If the id the upload
    used is not the id the product is saved with, the object exists and nothing points at it."""

    def test_the_id_is_minted_in_one_place(self):
        self.assertIn("export function ensureProductId(form)", STORE)
        # Products.vue had its own copy, with its own alphabet and Math.random.
        self.assertNotIn("function ensureProductId()", SCRIPT)
        imported = next(line for line in SCRIPT.splitlines() if 'from "../stores/products"' in line)
        self.assertIn("ensureProductId", imported)

    def test_the_field_settles_the_id_before_uploading(self):
        upload = FIELD.split("async function onFileChange", 1)[1]
        self.assertIn("store.uploadDigitalAsset(ensureProductId(props.form), file)", upload)

    def test_the_saved_product_keeps_that_id(self):
        build = STORE.split("export async function buildProductDocument", 1)[1][:400]
        self.assertIn('const productId = form.product_id || localId("local");', build)

    def test_the_asset_is_carried_into_the_payload(self):
        self.assertIn("product.digital_asset = form.digital_asset;", STORE)


if __name__ == "__main__":
    unittest.main()

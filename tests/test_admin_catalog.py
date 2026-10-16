"""The admin catalog: what a tenant actually delivers, not what their page says.

plans/ADMIN_SITE.md §1c. The landing page is marketing; a wholesome page can ship anything as the file,
and an upsell is where a product a reviewer never saw usually lives.
"""
import os
import unittest

from handlers import offers as offers_handler


def setUpModule():
    """Without a media bucket there is no link to sign, and `_asset_link` correctly returns nothing --
    which is right in production and useless in a test about links."""
    os.environ.setdefault("MEDIA_BUCKET", "jb-media-test")


def product(pid="prod_1", name="Course", context="standard", asset=True, **extra):
    doc = {
        "product_id": pid, "name": name, "description": "Ten lessons.", "product_type": "digital",
        "prices": [{"price_id": f"price_{pid}", "context": context, "unit_amount": 1000,
                    "currency": "usd"}],
        "images": ["https://img.test/a.png"],
    }
    if asset:
        doc["digital_asset"] = {"bucket_key": f"downloads/t1/{pid}/file.pdf", "filename": "file.pdf"}
    doc.update(extra)
    return doc


def offer(*product_ids):
    return {"offer_id": "offer_1", "name": "Berries Health Guide",
            "items": [{"product_id": p} for p in product_ids]}


class FakeRepo:
    def __init__(self, docs):
        self.docs = docs

    def list_for_tenant(self, tenant_id):
        return [dict(d) for d in self.docs]


class FakeS3:
    def __init__(self, explode=False):
        self.explode, self.calls = explode, []

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        self.calls.append((Params["Key"], ExpiresIn, Params.get("ResponseContentDisposition")))
        if self.explode:
            raise RuntimeError("NoSuchKey")
        return f"https://media.test/{Params['Key']}?signed=1"


def catalog(products, offers, s3=None, tenant="t1"):
    return offers_handler._tenant_catalog(
        {"tenant_id": tenant}, FakeRepo(offers), FakeRepo(products), s3 or FakeS3())


class TheDeliverableTests(unittest.TestCase):
    def test_the_file_a_buyer_receives_is_linked(self):
        """The whole point: "a course" is whatever the file says it is, and the page cannot tell you."""
        out = catalog([product()], [offer("prod_1")])
        asset = out["offers"][0]["products"][0]["asset"]
        self.assertEqual(asset["filename"], "file.pdf")
        self.assertIn("signed=1", asset["url"])

    def test_the_link_is_short_lived(self):
        s3 = FakeS3()
        catalog([product()], [offer("prod_1")], s3)
        self.assertLessEqual(s3.calls[0][1], 900)

    def test_it_opens_rather_than_downloads(self):
        """A forced download turns every review into a file sitting on someone's laptop."""
        s3 = FakeS3()
        catalog([product()], [offer("prod_1")], s3)
        self.assertIn("inline", s3.calls[0][2])

    def test_a_product_with_no_file_says_so(self):
        out = catalog([product(asset=False)], [offer("prod_1")])
        self.assertEqual(out["offers"][0]["products"][0]["asset"], {})

    def test_an_unlinkable_file_does_not_break_the_catalog(self):
        """One broken asset must not hide the other nine products from review."""
        out = catalog([product()], [offer("prod_1")], FakeS3(explode=True))
        asset = out["offers"][0]["products"][0]["asset"]
        self.assertEqual(asset["filename"], "file.pdf")
        self.assertIn("NoSuchKey", asset["error"])
        self.assertNotIn("url", asset)


class TheFunnelTests(unittest.TestCase):
    def test_an_upsell_is_shown_with_its_role(self):
        """The product a reviewer never sees on the landing page."""
        out = catalog([product("prod_1"), product("prod_2", name="Advanced", context="upsell")],
                      [offer("prod_1", "prod_2")])
        roles = {p["name"]: p["roles"] for p in out["offers"][0]["products"]}
        self.assertEqual(roles["Course"], ["Sold on the landing page"])
        self.assertIn("Upsell", roles["Advanced"][0])

    def test_order_bumps_and_downsells_are_named_too(self):
        out = catalog(
            [product("prod_1"), product("prod_2", context="order_bump"),
             product("prod_3", context="downsell")],
            [offer("prod_1", "prod_2", "prod_3")])
        labels = " ".join(r for p in out["offers"][0]["products"] for r in p["roles"])
        self.assertIn("Order bump", labels)
        self.assertIn("Downsell", labels)

    def test_the_role_is_DERIVED_from_pricing(self):
        """Not read from a stored placement -- so the admin sees the role a buyer actually meets, which is
        the same rule the renderer follows (plans/OFFER_MODEL_REDESIGN.md §6)."""
        stored_wrong = {**offer("prod_1"), "items": [{"product_id": "prod_1", "placement": "upsell"}]}
        out = catalog([product("prod_1", context="standard")], [stored_wrong])
        self.assertEqual(out["offers"][0]["products"][0]["roles"], ["Sold on the landing page"])

    def test_a_missing_product_is_reported_not_skipped(self):
        """A gap in the catalog is itself worth seeing."""
        out = catalog([], [offer("prod_gone")])
        self.assertEqual(out["offers"][0]["products"][0]["name"], "(missing product)")


class WhatIsReturnedTests(unittest.TestCase):
    def test_the_description_comes_through_whole(self):
        """What the tenant TELLS a buyer they are getting; a mismatch with the file is the clearest signal
        there is, so it is not truncated."""
        long = "x" * 900
        out = catalog([product(description=long)], [offer("prod_1")])
        self.assertEqual(out["offers"][0]["products"][0]["description"], long)

    def test_images_are_included(self):
        out = catalog([product()], [offer("prod_1")])
        self.assertEqual(out["offers"][0]["products"][0]["images"], ["https://img.test/a.png"])

    def test_a_tenant_is_required(self):
        self.assertFalse(offers_handler._tenant_catalog({})["ok"])

    def test_it_covers_both_stripe_modes(self):
        """A test-mode offer sells through a real checkout; sweeping only live would review half the
        account."""
        out = catalog([product()], [offer("prod_1")])
        self.assertEqual({o["stripe_mode"] for o in out["offers"]}, {"live", "test"})


if __name__ == "__main__":
    unittest.main()

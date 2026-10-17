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


class TheAttackThisExistsToCatchTests(unittest.TestCase):
    """A legitimate physical product on the landing page, something illegal on the bump.

    The buyer's card statement shows ONE charge, because an order bump rides the same Checkout Session as
    the primary item. So the money trail does not separate them either, and the only place the second
    product is visible is here (author, 2026-10-16).
    """

    def setUp(self):
        self.offer = {
            "offer_id": "offer_1", "name": "Protein Powder",
            # The real shape: the bump lives on offer.funnel.order_bumps, NOT in items[]. A catalog that
            # read only items[] would show the wholesome product and nothing else -- which is precisely
            # the hole the attack walks through.
            "items": [{"product_id": "prod_clean"}],
            "funnel": {"order_bumps": [{"product_id": "prod_hidden"}],
                       "upsells": [{"product_id": "prod_upsell"}]},
        }
        self.products = [
            product("prod_clean", name="Protein Powder", product_type="physical", asset=False),
            product("prod_hidden", name="Bonus Guide", context="order_bump"),
            product("prod_upsell", name="Masterclass", context="upsell"),
        ]

    def test_the_bump_product_is_in_the_catalog(self):
        names = [p["name"] for p in catalog(self.products, [self.offer])["offers"][0]["products"]]
        self.assertIn("Bonus Guide", names)

    def test_the_upsell_product_is_too(self):
        names = [p["name"] for p in catalog(self.products, [self.offer])["offers"][0]["products"]]
        self.assertIn("Masterclass", names)

    def test_each_hidden_product_is_LABELLED_as_what_it_is(self):
        """Seeing it is half the job; knowing a buyer meets it at checkout rather than on the page is the
        other half."""
        by_name = {p["name"]: p for p in catalog(self.products, [self.offer])["offers"][0]["products"]}
        self.assertIn("Order bump", " ".join(by_name["Bonus Guide"]["roles"]))
        self.assertIn("Upsell", " ".join(by_name["Masterclass"]["roles"]))

    def test_the_hidden_products_FILE_is_linked(self):
        """The physical product has nothing to inspect; the digital bump is the one carrying the payload."""
        by_name = {p["name"]: p for p in catalog(self.products, [self.offer])["offers"][0]["products"]}
        self.assertEqual(by_name["Protein Powder"]["asset"], {})
        self.assertIn("signed=1", by_name["Bonus Guide"]["asset"]["url"])


class NothingIsSilentlyDroppedTests(unittest.TestCase):
    """The catalog's job is "see every sale opportunity", so it must fail loudly, never quietly."""

    def test_a_service_backed_opportunity_still_appears(self):
        """`offer_product_ids` collects product_id only, so building the list from it dropped a
        service-backed bump in silence -- a sale opportunity the screen would not show and nobody would
        know was missing. Services are not Offer inputs yet; this is here so the day they are, a
        service-backed bump is visible rather than invisible until someone notices."""
        o = {"offer_id": "offer_1", "name": "Clinic",
             "items": [{"product_id": "prod_1"}],
             "funnel": {"order_bumps": [{"service_id": "svc_1"}]}}
        out = catalog([product("prod_1")], [o])
        rows = out["offers"][0]["products"]
        self.assertEqual(len(rows), 2)
        self.assertIn("Order bump", " ".join(rows[1]["roles"]))

    def test_an_opportunity_for_a_deleted_product_is_shown_as_missing(self):
        o = {"offer_id": "offer_1", "items": [{"product_id": "gone"}]}
        rows = catalog([], [o])["offers"][0]["products"]
        self.assertEqual(rows[0]["name"], "(missing product)")
        self.assertIn("landing page", rows[0]["roles"][0])

    def test_a_missing_opportunity_still_says_WHERE_a_buyer_meets_it(self):
        """Knowing an unresolvable row is an upsell is most of what makes it worth chasing."""
        o = {"offer_id": "offer_1", "items": [{"product_id": "prod_1"}],
             "funnel": {"upsells": [{"product_id": "gone"}]}}
        rows = catalog([product("prod_1")], [o])["offers"][0]["products"]
        self.assertIn("Upsell", rows[1]["roles"][0])

    def test_every_funnel_position_produces_exactly_one_row(self):
        o = {"offer_id": "offer_1", "items": [{"product_id": "p1"}],
             "funnel": {"order_bumps": [{"product_id": "p2"}], "upsells": [{"product_id": "p3"}],
                        "downsells": [{"product_id": "p4"}]}}
        products = [product(f"p{i}") for i in range(1, 5)]
        rows = catalog(products, [o])["offers"][0]["products"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r["product_id"] for r in rows}), 4)


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


class PageOwnedFilesTests(unittest.TestCase):
    """A file attached to a PAGE, not to any product — the "free guide" a visitor gets for an email.

    No purchase sits behind it, so the offer catalog would never show it, and it is as capable of
    carrying something illegal as anything someone pays for.
    """

    def sign(self, keys, tenant="t1", s3=None):
        return offers_handler._sign_tenant_assets(
            {"tenant_id": tenant, "keys": keys}, s3 or FakeS3())

    def test_a_page_asset_is_signed(self):
        out = self.sign(["downloads/t1/page/page_1/asset_1/guide.pdf"])
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["assets"]), 1)

    def test_a_key_outside_the_tenants_own_prefix_is_REFUSED(self):
        """The keys come from the caller, so they are constrained rather than trusted. Without this,
        anything that reached this function could have had any object in the media bucket signed by
        naming it — a far larger power than looking at the account under review."""
        out = self.sign(["downloads/someone_else/page/p/a/secret.pdf"])
        self.assertEqual(out["assets"], {})
        self.assertEqual(len(out["refused"]), 1)

    def test_traversal_out_of_the_prefix_is_refused(self):
        out = self.sign(["../downloads/t2/x.pdf", "downloads/t11/x.pdf"])
        self.assertEqual(out["assets"], {})

    def test_a_mixed_batch_signs_only_what_it_may(self):
        out = self.sign(["downloads/t1/ok.pdf", "downloads/t2/no.pdf"])
        self.assertEqual(list(out["assets"]), ["downloads/t1/ok.pdf"])
        self.assertEqual(out["refused"], ["downloads/t2/no.pdf"])

    def test_a_batch_is_bounded(self):
        out = self.sign([f"downloads/t1/{i}.pdf" for i in range(80)])
        self.assertLessEqual(len(out["assets"]), 50)

    def test_no_tenant_signs_nothing(self):
        self.assertFalse(offers_handler._sign_tenant_assets({"keys": ["downloads/t1/x.pdf"]})["ok"])

"""The short order reference: unique, searchable, and the only id a tenant is shown.

The author accepted the substring approach on two conditions -- "as long as collisions can't happen and
it's searchable". Neither was true when they said it: the reference was computed per-order in the browser
(so nothing could see a collision), and the search box matched only customer name and email.
"""
import json
import unittest

from handlers.orders import handler as orders_handler
from stripe_link.domain.order_reference import (
    MAX_LENGTH,
    MIN_LENGTH,
    matches_reference,
    short_ref,
    short_refs,
)

SESSION = "order_cs_test_b13b4Un3fLskfKQnlC26ksYEkPw7PjUaxalKrgY7qzcZsg6cf6JbOjrzRJ"


class ShapeTests(unittest.TestCase):
    def test_it_is_a_SUBSTRING_of_the_real_id(self):
        """This is the whole reason it is not a hash: a quoted reference can be pasted into search."""
        self.assertIn(short_ref(SESSION), SESSION)

    def test_it_strips_our_prefix_and_stripes(self):
        self.assertEqual(short_ref(SESSION), "b13b4Un3")
        self.assertEqual(short_ref("order_in_1UJRhD21lLbLd4Y5fht1Zu5J"), "1UJRhD21")
        self.assertEqual(short_ref("order_cs_live_a1gXWA49OA8dEg"), "a1gXWA49")

    def test_an_upsell_keeps_its_sequence(self):
        self.assertEqual(short_ref(f"{SESSION}_upsell_2"), "b13b4Un3-U2")

    def test_an_id_shaped_like_nothing_we_know_still_shortens(self):
        self.assertTrue(short_ref("order_something_else"))
        self.assertEqual(short_ref(""), "")


class CollisionTests(unittest.TestCase):
    """The author was promised collisions CANNOT happen, not that they are unlikely.

    Stripe's ids are not uniformly random at the front: across 45 real sessions, 42 began `a1` and 3
    began `b1`. An 8-character prefix therefore carries closer to 6 characters of entropy.
    """

    def test_two_orders_that_would_share_a_prefix_both_get_a_longer_one(self):
        ids = ["order_cs_test_a1AAAAAAxxxx", "order_cs_test_a1AAAAAAyyyy"]
        refs = short_refs(ids)
        self.assertEqual(len(set(refs.values())), 2)
        self.assertTrue(all(len(v) > MIN_LENGTH for v in refs.values()))

    def test_it_keeps_lengthening_until_they_separate(self):
        ids = [f"order_cs_test_a1AAAAAAAAAAAAAA{tail}" for tail in ("x", "y", "z")]
        refs = short_refs(ids)
        self.assertEqual(len(set(refs.values())), 3)

    def test_an_upsell_does_not_collide_with_the_purchase_it_followed(self):
        """A post-purchase order carries its PARENT's session id, so without the suffix all three would
        answer to one reference."""
        refs = short_refs([SESSION, f"{SESSION}_upsell_1", f"{SESSION}_upsell_2"])
        self.assertEqual(len(set(refs.values())), 3)
        self.assertEqual(refs[SESSION], "b13b4Un3")

    def test_unrelated_orders_keep_the_short_form(self):
        # Lengthening is the exception; a normal set stays at eight.
        refs = short_refs([SESSION, "order_cs_test_zzTopHatxxxx"])
        self.assertTrue(all(len(v) == MIN_LENGTH for v in refs.values()))

    def test_ids_that_stay_identical_past_the_limit_fall_back_rather_than_lie(self):
        """Two DIFFERENT ids sharing their first 24 characters. Synthetic -- real Stripe ids diverge long
        before that -- but an ambiguous reference is worse than a long one, so the branch exists and is
        worth pinning. (The same id twice cannot happen: order_id is a primary key.)"""
        shared = "order_cs_test_" + ("a" * MAX_LENGTH)
        ids = [f"{shared}x", f"{shared}y"]

        refs = short_refs(ids)

        self.assertEqual(set(refs.values()), set(ids), "an unresolvable clash must hand back the full id")

    def test_an_empty_set_is_not_a_crash(self):
        self.assertEqual(short_refs([]), {})


class SearchTests(unittest.TestCase):
    ORDER = {"order_id": SESSION, "short_ref": "b13b4Un3",
             "session_id": "cs_test_b13b4Un3fLskfKQnlC26ksYEkPw7PjUaxalKrgY7qzcZsg6cf6JbOjrzRJ"}

    def test_the_reference_the_tenant_can_see_is_the_one_that_finds_it(self):
        self.assertTrue(matches_reference(self.ORDER, "b13b4Un3"))

    def test_case_and_a_leading_hash_do_not_matter(self):
        for typed in ("B13B4UN3", "#b13b4Un3", "  b13b4un3  "):
            self.assertTrue(matches_reference(self.ORDER, typed), typed)

    def test_the_full_id_and_the_stripe_session_id_still_work(self):
        """A tenant pastes whichever of the three they happen to be holding."""
        self.assertTrue(matches_reference(self.ORDER, SESSION))
        self.assertTrue(matches_reference(self.ORDER, "cs_test_b13b4Un3"))

    def test_a_quoted_upsell_reference_finds_the_upsell(self):
        upsell = {"order_id": f"{SESSION}_upsell_2", "short_ref": "b13b4Un3-U2"}
        self.assertTrue(matches_reference(upsell, "b13b4Un3-U2"))

    def test_something_else_entirely_does_not_match(self):
        self.assertFalse(matches_reference(self.ORDER, "nope"))
        self.assertFalse(matches_reference(self.ORDER, ""))


class Repo:
    def __init__(self, rows):
        self.rows = list(rows)

    def get(self, tenant_id, doc_id=None):
        return next((r for r in self.rows if r.get("order_id") == doc_id), None)

    def list_for_tenant(self, tenant_id):
        return list(self.rows)

    def put(self, document):
        return document


def _list(params=None):
    orders = [{"order_id": SESSION, "tenant_id": "t1", "created_at": "100",
               "customer": {"name": "Ada", "email": "ada@example.com"}},
              {"order_id": f"{SESSION}_upsell_1", "tenant_id": "t1", "created_at": "101",
               "customer": {"name": "Ada", "email": "ada@example.com"}}]
    result = orders_handler(
        {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", **(params or {})}}, None,
        repository=Repo(orders), products_repo=Repo([]), shipments_repo=Repo([]),
        shipping_config_repo=Repo([]))
    return json.loads(result["body"])


class EndpointTests(unittest.TestCase):
    def test_every_order_arrives_with_its_reference(self):
        body = _list()
        self.assertEqual({o["short_ref"] for o in body["orders"]}, {"b13b4Un3", "b13b4Un3-U1"})

    def test_searching_the_reference_finds_exactly_that_order(self):
        body = _list({"customer": "b13b4Un3-U1"})
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["orders"][0]["short_ref"], "b13b4Un3-U1")

    def test_searching_a_customer_still_works(self):
        self.assertEqual(_list({"customer": "ada@example.com"})["count"], 2)

    def test_the_reference_is_computed_before_filtering_so_a_search_does_not_change_it(self):
        """Computed over the filtered set, a search for one order could hand it a shorter reference than
        the full list showed -- the same order answering to two numbers."""
        full = {o["order_id"]: o["short_ref"] for o in _list()["orders"]}
        found = _list({"customer": "b13b4Un3-U1"})["orders"][0]
        self.assertEqual(found["short_ref"], full[found["order_id"]])


if __name__ == "__main__":
    unittest.main()

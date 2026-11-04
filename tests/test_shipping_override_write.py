"""Writing ONE Site's shipping override (plans/SHIPPING_PER_SITE.md §S4).

The overrides live in a map on a document the whole ACCOUNT shares. That makes the WRITE the dangerous
part, not the read: a read-modify-write from one Site's screen restores every other Site's override as it
looked a moment earlier, so two shipping screens open at once and one business silently loses its
warehouse (`feedback_shared_document_read_modify_write`). The artifact looks right afterwards, because it
was built from the in-memory copy.

So the rule this file holds is: **read to VALIDATE, write TARGETED.**
"""
import json
import pathlib
import unittest

from handlers.shipping import save_shipping_config, save_site_override
from stripe_link.repositories.documents import SimpleKeyRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]
HQ = {"name": "HQ", "street1": "1 A St", "city": "Seattle", "state": "WA",
      "postal_code": "98101", "country": "US"}
AUSTIN = {"name": "Quill", "street1": "2 B St", "city": "Austin", "state": "TX",
          "postal_code": "73301", "country": "US"}
# A zone the REAL validator accepts. `{"id": "z1"}` does not, and my first draft of this file used it —
# so the test that meant to check the resolved view was quietly asserting against a 400.
ZONE = {"destinations": [{"country": "US"}], "rule": {"type": "live"}}


class FakeTable:
    """Records the UpdateExpressions, which is the only way to tell a targeted write from a put."""

    def __init__(self, item=None):
        self.item = dict(item) if item else None
        self.updates = []
        self.puts = []
        self.missing = False

    def get_item(self, Key):  # noqa: N803 - boto3's own casing
        return {"Item": dict(self.item)} if self.item else {}

    def put_item(self, Item):  # noqa: N803
        self.puts.append(Item)
        self.item = dict(Item)

    def update_item(self, **kwargs):
        if self.missing:
            raise RuntimeError("ConditionalCheckFailedException")
        self.updates.append(kwargs)


def config(**over):
    doc = {"schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
           "provider": {"name": "shippo", "api_key_ref": "ref"}, "ship_from_address": dict(HQ),
           "boxes": [], "zones": []}
    doc.update(over)
    return doc


_DEFAULT = object()   # so a test can ask for NO stored document and mean it, rather than the default one


def repo(doc=_DEFAULT):
    table = FakeTable(config() if doc is _DEFAULT else doc)
    return SimpleKeyRepository("jb-shipping-config-dev", key_field="tenant_id", table=table), table


def event(body):
    return {"httpMethod": "PUT", "queryStringParameters": {"tenant_id": "t1"}, "body": json.dumps(body)}


class TheWriteIsTARGETEDTests(unittest.TestCase):
    def test_it_updates_ONE_MEMBER_and_never_puts(self):
        repository, table = repo()
        response = save_site_override(
            event({"site_id": "site_qui", "site_override": {"ship_from_address": AUSTIN}}), repository)
        self.assertEqual(response["statusCode"], 201, response.get("body"))
        self.assertEqual(table.puts, [], "a put would restore every other site's override")
        self.assertEqual(len(table.updates), 1)
        update = table.updates[0]
        self.assertIn("#c.#m = :v", update["UpdateExpression"])
        self.assertEqual(update["ExpressionAttributeNames"], {"#c": "sites", "#m": "site_qui"})

    def test_the_FIRST_override_creates_the_map(self):
        """A bare `SET #c.#m` on a document with no `sites` attribute fails the whole update with
        ValidationException — which is how a tenant's first override would have 500'd."""
        repository, table = repo()
        save_site_override(event({"site_id": "site_qui", "site_override": {"ship_from_address": AUSTIN}}),
                           repository)
        self.assertIn("if_not_exists(#c, :empty)", table.updates[0]["UpdateExpression"])

    def test_it_is_CONDITIONAL_on_the_document_existing(self):
        repository, table = repo()
        save_site_override(event({"site_id": "site_qui", "site_override": {"ship_from_address": AUSTIN}}),
                           repository)
        self.assertIn("attribute_exists(tenant_id)", table.updates[0]["ConditionExpression"])

    def test_an_EMPTY_override_REMOVES_the_member(self):
        """"Go back to inheriting". Removing beats storing an empty map, or "states nothing" has two
        stored shapes that every reader then has to collapse."""
        repository, table = repo(config(sites={"site_qui": {"ship_from_address": AUSTIN}}))
        response = save_site_override(event({"site_id": "site_qui", "site_override": {}}), repository)
        self.assertEqual(response["statusCode"], 201, response.get("body"))
        self.assertEqual(table.updates[0]["UpdateExpression"], "REMOVE #c.#m")

    def test_a_vanished_document_is_a_404_not_a_crash(self):
        repository, table = repo()
        table.missing = True
        response = save_site_override(
            event({"site_id": "site_qui", "site_override": {"ship_from_address": AUSTIN}}), repository)
        self.assertEqual(response["statusCode"], 404)


class ItRidesTheExistingRouteTests(unittest.TestCase):
    """This handler's own note: adding a route took the transformed stack over CloudFormation's
    1,000,000-byte limit once already, so "new endpoints have to ride existing routes"."""

    def test_the_account_save_DELEGATES_when_a_site_is_named(self):
        repository, table = repo()
        response = save_shipping_config(
            event({"tenant_id": "t1", "site_id": "site_qui",
                   "site_override": {"ship_from_address": AUSTIN}}), repository, secret_cipher=None)
        self.assertEqual(response["statusCode"], 201, response.get("body"))
        self.assertEqual(table.puts, [], "the account document must not be rewritten")
        self.assertEqual(len(table.updates), 1)

    def test_a_body_with_NO_site_id_still_saves_the_account(self):
        """The split is on the body, so the ordinary save has to be completely unaffected."""
        source = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")
        block = source.split("def save_shipping_config(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('if str(parse_json_body(event).get("site_id") or "").strip():', block)
        self.assertIn("return save_site_override(", block)


class TheOverrideCannotBeTheSOFTERPathTests(unittest.TestCase):
    def test_a_PARTIAL_address_is_refused(self):
        repository, table = repo()
        response = save_site_override(
            event({"site_id": "site_qui", "site_override": {"ship_from_address": {"city": "Austin"}}}),
            repository)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(table.updates, [], "nothing may be written when validation refused it")

    def test_a_NON_OVERRIDABLE_field_is_dropped_not_stored(self):
        """The payload is filtered to `SITE_OVERRIDABLE` before validation, so a client sending a provider
        gets it ignored rather than an error it cannot act on — and nothing of it is stored."""
        repository, _table = repo()
        response = save_site_override(
            event({"site_id": "site_qui",
                   "site_override": {"ship_from_address": AUSTIN, "provider": {"name": "easypost"}}}),
            repository)
        self.assertEqual(response["statusCode"], 201, response.get("body"))
        self.assertNotIn("provider", json.loads(response["body"])["site_override"])

    def test_a_malformed_site_id_is_refused(self):
        repository, _ = repo()
        self.assertEqual(save_site_override(event({"site_id": "quill"}), repository)["statusCode"], 400)

    def test_an_account_with_NO_shipping_config_is_told_to_set_one_up(self):
        """Overriding nothing is not a thing, and the message says what to do instead of 404-ing blankly."""
        repository, _ = repo(doc=None)
        response = save_site_override(
            event({"site_id": "site_qui", "site_override": {"ship_from_address": AUSTIN}}), repository)
        self.assertEqual(response["statusCode"], 404)
        self.assertIn("before overriding", json.loads(response["body"])["message"])


class TheResponseTellsTheScreenWhatIsINHERITEDTests(unittest.TestCase):
    def test_it_returns_the_resolved_view_and_the_inherited_list(self):
        """So the screen shows what this site will actually ship with, rather than re-deriving inheritance
        in JavaScript and disagreeing with the server about it."""
        repository, _ = repo(config(zones=[ZONE]))
        body = json.loads(save_site_override(
            event({"site_id": "site_qui", "site_override": {"ship_from_address": AUSTIN}}),
            repository)["body"])
        self.assertEqual(body["resolved"]["ship_from_address"]["city"], "Austin")
        self.assertEqual(body["resolved"]["zones"], [ZONE])
        self.assertEqual(body["inherited"], ["return_address", "zones"])

    def test_the_resolved_view_is_REDACTED(self):
        """It carries the provider block, and a key reference has been treated as a secret since this
        module was written. The FIELD stays — the dashboard needs to know a key exists — so what must be
        absent is the reference ITSELF, which is what this now asserts."""
        repository, _ = repo()
        body = json.loads(save_site_override(
            event({"site_id": "site_qui", "site_override": {"ship_from_address": AUSTIN}}),
            repository)["body"])
        self.assertNotIn("ref", json.dumps(body["resolved"]["provider"]["api_key_ref"]))
        self.assertEqual(body["resolved"]["provider"]["api_key_ref"], "********")


class TheScreenNamesTheScopeTests(unittest.TestCase):
    SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    def test_the_selector_only_appears_with_MORE_THAN_ONE_site(self):
        """With one site every address on the screen is unambiguously its, and a selector offering a
        single choice is a question with no answer."""
        self.assertIn('v-if="sitesStore.sites.length > 1"', self.SCREEN)

    def test_it_says_which_sites_have_their_OWN_address(self):
        self.assertIn("overriddenSiteIds", self.SCREEN)
        self.assertIn("own address", self.SCREEN)
        self.assertIn("inherits", self.SCREEN)

    def test_editing_the_ACCOUNT_default_says_so_outright(self):
        """A tenant editing the account default while believing they are editing one shop would change
        every shop."""
        self.assertIn("Every site without its own address ships from here", self.SCREEN)

    def test_a_site_scoped_save_takes_the_SEPARATE_route(self):
        block = self.SCREEN.split("async function save()", 1)[1][:400]
        self.assertIn("if (shipFromScope.value) return saveSiteOverride();", block)

    def test_going_back_to_inheriting_is_OFFERED(self):
        self.assertIn("clearSiteOverride", self.SCREEN)
        self.assertIn("Go back to inheriting", self.SCREEN)

    def test_switching_scope_seeds_the_form_from_the_ACCOUNT_for_an_inheriting_site(self):
        """So "fill it in and save" starts from something rather than an empty form to retype."""
        block = self.SCREEN.split("watch(shipFromScope", 1)[1][:500]
        self.assertIn("own || rawDoc.value?.ship_from_address", block)


if __name__ == "__main__":
    unittest.main()

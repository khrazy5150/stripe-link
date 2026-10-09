"""Every captured payload goes through the real handler, not past it.

`test_real_payload_shapes.py` checks the PARSERS against Stripe's actual output. This drives the whole
`stripe_webhook.handler` with the same payloads — signature, silo routing, tenant resolution, persistence
— because a parser that reads a field correctly inside a handler that never reaches it is worth nothing,
and that is exactly how the funnel and order-write defects survived a green suite.

These are the paths that had never executed against live Stripe as of 2026-10-08:
`invoice.paid` (subscription renewal), `charge.refunded`, `payment_intent.succeeded`,
`payment_intent.payment_failed`, `customer.subscription.updated`. Each is now exercised here with the
payload Stripe really sent, in both Stripe modes.
"""
import hashlib
import hmac
import json
import os
import pathlib
import unittest
from unittest.mock import patch

from handlers.stripe_webhook import handler as stripe_webhook_handler

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "stripe_events"
SECRET = "whsec_preview_test"
TIMESTAMP = 1781230000


class RecordingRepo:
    """Accepts writes and remembers them, and refuses an item with no tenant — the way the real one does."""

    def __init__(self, id_field="id"):
        self.id_field = id_field
        self.documents = {}
        self.writes = []

    def put(self, document):
        if not document.get("tenant_id"):
            raise AssertionError("Document tenant_id is required.")
        self.writes.append(document)
        self.documents[document.get(self.id_field)] = document
        return document

    def append(self, document):
        return self.put(document)

    def get(self, *_args, **_kwargs):
        return None

    def scan_type(self):
        return list(self.documents.values())

    def find_by_payment_intent(self, _pi):
        return None

    def find_by_stripe_refund(self, _rid):
        return None


class KeysRepo:
    """Resolves the fixture's connected account to a tenant, as the real lookup does."""

    def find_by_connect_account_id(self, account_id, _mode=None):
        return {"tenant_id": "t_fixture", "connect_account_id": account_id} if account_id else None

    def get(self, *_a, **_k):
        return {}


class OrdersTable:
    """A boto3-shaped table that enforces the key schema, like `jb-orders-*` does."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item, **_kwargs):
        for required in ("PK", "SK"):
            if required not in Item:
                raise AssertionError(f"Missing the key {required} in the item")
        self.items[(Item["PK"], Item["SK"])] = Item


def deliver(payload, *, environment="dev", repos=None):
    """Run the real handler over a real payload, signed the way Stripe signs it."""
    body = json.dumps(payload, separators=(",", ":"))
    signature = hmac.new(SECRET.encode(), f"{TIMESTAMP}.{body}".encode(), hashlib.sha256).hexdigest()
    repos = repos if repos is not None else {}
    with patch.dict(os.environ, {"ENVIRONMENT": environment}, clear=False):
        return stripe_webhook_handler(
            {"httpMethod": "POST", "path": "/webhook/stripe-preview",
             "headers": {"Stripe-Signature": f"t={TIMESTAMP},v1={signature}"},
             "body": body},
            None,
            repository=KeysRepo(),
            webhook_secret_loader=lambda kind, mode, refresh=False: SECRET,
            now_fn=lambda: TIMESTAMP,
            **repos,
        )


def fixtures():
    return sorted(FIXTURES.glob("*.json"))


class EveryCapturedPayloadIsAccepted(unittest.TestCase):
    """Not 'processed' — accepted. A foreign silo is declined with a 200 by design, and that is a correct
    outcome. What must never happen is a 4xx or 5xx, because Stripe retries those and eventually disables
    the endpoint: nine days of that is how this whole sequence started."""

    def test_none_of_them_error(self):
        failures = []
        for path in fixtures():
            payload = json.loads(path.read_text())
            try:
                response = deliver(payload)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.name}: raised {type(exc).__name__}: {exc}")
                continue
            if response["statusCode"] >= 300:
                failures.append(f"{path.name}: HTTP {response['statusCode']} {response.get('body','')[:120]}")
        self.assertEqual(failures, [], "a non-2xx makes Stripe retry and eventually disable us:\n  " +
                         "\n  ".join(failures))

    def test_none_of_them_are_refused_before_the_signature_check(self):
        """A rejection is logged as `webhook_rejected`. A real payload must never produce one."""
        import contextlib
        import io

        for path in fixtures():
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                deliver(json.loads(path.read_text()))
            for line in buffer.getvalue().splitlines():
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                self.assertNotIn("webhook_rejected", parsed,
                                 f"{path.name} was refused: {parsed.get('webhook_rejected')}")


class TheSiloIsResolvedForEveryPayload(unittest.TestCase):
    def test_each_one_logs_a_routing_decision(self):
        import contextlib
        import io

        undecided = []
        for path in fixtures():
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                deliver(json.loads(path.read_text()))
            lines = [json.loads(l) for l in buffer.getvalue().splitlines() if l.startswith("{")]
            if not any("silo_routing" in l for l in lines):
                undecided.append(path.name)
        self.assertEqual(undecided, [], "an event with no routing decision is one nobody owns")


class BothModesBehaveTheSame(unittest.TestCase):
    """The mode-parity rule applied to real payloads: a deployment must not accept an event in one mode
    and refuse it in the other."""

    def test_sandbox_and_production_both_accept_every_payload(self):
        for path in fixtures():
            payload = json.loads(path.read_text())
            sandbox = deliver(payload, environment="dev")
            production = deliver(payload, environment="prod")
            self.assertLess(sandbox["statusCode"], 300, path.name)
            self.assertLess(production["statusCode"], 300, path.name)


class TheRefundPayloadStillNeedsItsRefundsFetched(unittest.TestCase):
    """The end-to-end proof of the `charge.refunds` defect: the handler must not conclude there are no
    refunds just because the payload carries none."""

    def test_the_handler_does_not_treat_an_absent_list_as_empty(self):
        from handlers.stripe_webhook import _refunds_for_charge
        charge = json.loads((FIXTURES / "charge_refunded.json").read_text())["data"]["object"]
        self.assertNotIn("refunds", charge)
        asked = []
        _refunds_for_charge(charge, "t_1", fetcher=lambda cid: asked.append(cid) or [])
        self.assertEqual(len(asked), 1, "it must go and ask Stripe rather than iterate nothing")


class TheOrderIsActuallyWritten(unittest.TestCase):
    """The difference between "the handler did not crash" and "the handler did the work".

    The order write goes STRAIGHT to the boto3 table so it can use a conditional put, which is how it
    escaped the mode retrofit and wrote an item with no `PK` for a live sale. The table here refuses that
    item the way DynamoDB did.
    """

    def _checkout_payload(self):
        return json.loads((FIXTURES / "checkout_session_completed.json").read_text())

    def test_a_real_checkout_session_produces_a_keyed_order(self):
        payload = self._checkout_payload()
        silo = ((payload.get("data") or {}).get("object") or {}).get("metadata", {}).get("silo", "")
        environment = "prod" if silo == "production" else "dev"
        table = OrdersTable()
        response = deliver(payload, environment=environment,
                           repos={"orders_table": table, "ledger_repo": RecordingRepo("entry_id"),
                                  "customers_repo": RecordingRepo("customer_id")})
        self.assertLess(response["statusCode"], 300, response.get("body"))
        self.assertTrue(table.items, "the silo that owns this event wrote no order for it")
        (pk, sk), item = next(iter(table.items.items()))
        self.assertTrue(pk.startswith("TENANT#"), f"order written under {pk!r}")
        self.assertIn("#", pk.split("TENANT#", 1)[1], "the partition must carry the Stripe mode")
        self.assertEqual(item.get("stripe_mode"), "live" if payload.get("livemode") else "test")
        self.assertTrue(sk, "the sort key is the order id")

    def test_the_foreign_silo_writes_nothing(self):
        """The other deployment receives the same event and must decline it without writing."""
        payload = self._checkout_payload()
        silo = ((payload.get("data") or {}).get("object") or {}).get("metadata", {}).get("silo", "")
        foreign = "dev" if silo == "production" else "prod"
        table = OrdersTable()
        response = deliver(payload, environment=foreign, repos={"orders_table": table})
        self.assertLess(response["statusCode"], 300, "a foreign event is declined with a 200, not an error")
        self.assertEqual(table.items, {}, "the silo that does not own this event must not record it")

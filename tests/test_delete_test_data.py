"""The delete-all-test-data admin handler.

Two things are asserted here, and the second is the one that matters:

  1. It clears the caller's TEST documents.
  2. It cannot reach their LIVE ones -- because the mode is in the KEY, not in a predicate. The fake table
     below therefore honors real key conditions (PK equality, SK begins_with) instead of a tag, so a test
     that passes proves the query was actually scoped rather than that the fixture cooperated.
"""
import json
import os
import unittest
from unittest.mock import patch

from handlers.admin_delete_test_data import handler
from stripe_link.repositories import documents


def _condition_strings(condition):
    """The literal string operands of a boto3 KeyConditionExpression tree."""
    values = []
    get_expression = getattr(condition, "get_expression", None)
    if not get_expression:
        return [condition] if isinstance(condition, str) else []
    for operand in get_expression().get("values", ()):
        if isinstance(operand, str):
            values.append(operand)
        elif getattr(operand, "get_expression", None):
            values.extend(_condition_strings(operand))
    return values


class FakeTable:
    """A table that answers key conditions the way DynamoDB does.

    It deliberately does NOT understand "which rows the test meant" -- only PK equality and SK prefix. That
    is the whole point: if the handler queried the wrong key space, these tests fail.
    """

    def __init__(self, name, key_attrs, items):
        self.name = name
        self.key_schema = [{"AttributeName": key_attrs[0], "KeyType": "HASH"}]
        if len(key_attrs) > 1:
            self.key_schema.append({"AttributeName": key_attrs[1], "KeyType": "RANGE"})
        self.items = items
        self.deleted = []

    def query(self, **kwargs):
        strings = _condition_strings(kwargs.get("KeyConditionExpression"))
        pk = next((s for s in strings if s.startswith("TENANT#")), None)
        prefixes = [s for s in strings if s != pk]
        items = self.items
        if pk is not None:
            items = [i for i in items if i.get("PK") == pk]
        if prefixes:
            items = [i for i in items if any(str(i.get("SK") or "").startswith(p) for p in prefixes)]
        return {"Items": items}

    def scan(self, **kwargs):
        return {"Items": list(self.items)}

    def batch_writer(self):
        table = self

        class _Batch:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def delete_item(self_inner, Key):
                table.deleted.append(Key)

        return _Batch()


class FakeDynamo:
    def __init__(self, tables):
        self.tables = tables

    def Table(self, name):
        if name not in self.tables:
            self.tables[name] = FakeTable(name, ["PK", "SK"], [])
        return self.tables[name]


def _product(mode="test", pid="p1"):
    """A mode-scoped document as the repository writes it: the mode is in the SK AND on the row."""
    return {"PK": "TENANT#t1", "SK": f"PRODUCT#{mode}#{pid}", "stripe_mode": mode}


def _unmoded(sk="REVIEW#r1", **extra):
    """A document from a type that is NOT mode-scoped. Nothing on it says which books it belongs to."""
    return {"PK": "TENANT#t1", "SK": sk, **extra}


class NoKeyStripeRepo:
    def get(self, tenant_id, mode="test"):
        return {}


class Cipher:
    def decrypt(self, *a, **k):
        return ""


ALL_TABLE_ENVS = [
    "PRODUCTS_TABLE", "OFFERS_TABLE", "COUPONS_TABLE", "COUPON_GRANTS_TABLE",
    "COUPON_REDEMPTIONS_TABLE", "PAGES_TABLE", "COLLECTIONS_TABLE", "EXPERIMENTS_TABLE",
    "LEADS_TABLE", "REVIEWS_TABLE", "CARTS_TABLE", "SHIPMENTS_TABLE", "INVOICES_TABLE",
    "NOTIFICATIONS_TABLE", "BOOKING_CREDITS_TABLE", "CUSTOMERS_TABLE", "ORDERS_TABLE",
    "REFUNDS_TABLE", "LEDGER_TABLE", "CHECKOUT_SESSIONS_TABLE", "SERVICES_TABLE",
]


def _table_name(env_name):
    """What the deployed stack calls it. The repository layer refuses any resource not named `jb-...`,
    so the fixtures have to look real."""
    return "jb-" + env_name.lower().replace("_table", "")


def _env_for(tables):
    env = {"ENVIRONMENT": "dev", "JOBS_TABLE": "jb-jobs"}
    for name in ALL_TABLE_ENVS:
        env[name] = _table_name(name)
        tables.setdefault(_table_name(name), FakeTable(name, ["PK", "SK"], []))
    return env


def _event(method="POST", mode=None):
    body = {"tenant_id": "t1"}
    if mode:
        body["mode"] = mode
    return {"httpMethod": method, "requestContext": {}, "headers": {"X-Tenant-Id": "t1"},
            "body": json.dumps(body)}


class FakeJobs:
    """The shared jobs table, in memory."""

    def __init__(self):
        self.rows = {}

    def put(self, job):
        self.rows[(job["tenant_id"], job["job_id"])] = dict(job)
        return job

    def get(self, tenant_id, job_id):
        return self.rows.get((str(tenant_id), str(job_id)))


def _run(tables, *, mode=None, defer=False):
    """POST, then run the worker the way Lambda would, then read the job row.

    Exercises the real path end to end: the request only queues, and everything the old synchronous
    response carried now lands on the job row. `defer=True` leaves the worker unrun, so a test can see
    what the tenant sees before the work starts.
    """
    env = _env_for(tables)
    jobs = FakeJobs()
    ran = []

    def invoker(job):
        if defer:
            return
        ran.append(handler({"internal_job": True, "tenant_id": job["tenant_id"],
                            "job_id": job["job_id"], "mode": job["mode"]},
                           _Context(), dynamodb=FakeDynamo(tables), stripe_repo=NoKeyStripeRepo(),
                           secret_cipher=Cipher(), jobs_repo=jobs))

    with patch.dict(os.environ, env, clear=False):
        resp = handler(_event(mode=mode), None, dynamodb=FakeDynamo(tables),
                       stripe_repo=NoKeyStripeRepo(), secret_cipher=Cipher(),
                       jobs_repo=jobs, invoker=invoker)
    accepted = json.loads(resp["body"])
    if resp["statusCode"] >= 400 or defer:
        return resp, accepted, jobs
    job = jobs.get("t1", accepted["job"]["job_id"])
    # The job row is the response now; hand back its result so the assertions read as before.
    return resp, {**(job.get("result") or {}), "status": job["status"], "mode": job["mode"]}, jobs


class _Context:
    """Enough of a Lambda context for the worker's deadline maths."""

    @staticmethod
    def get_remaining_time_in_millis():
        return 900_000


class TheGateTests(unittest.TestCase):
    def test_options_ok(self):
        self.assertEqual(handler(_event("OPTIONS"), None)["statusCode"], 200)

    def test_requires_tenant(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}):
            resp = handler({"httpMethod": "POST", "requestContext": {}, "headers": {}, "body": "{}"}, None)
        self.assertEqual(resp["statusCode"], 400)

    def test_prod_is_NOT_a_gate_because_the_gate_is_the_mode(self):
        """The old guard refused whenever ENVIRONMENT was prod. That protected nothing -- dev and prod hold
        the same tenant's live Stripe credentials -- while denying the action to every tenant whose sandbox
        lives on the production backend. Mode is the gate now, in every deployment."""
        tables = {"jb-products": FakeTable("PRODUCTS_TABLE", ["PK", "SK"], [_product(pid="p1")])}
        env = _env_for(tables)
        env["ENVIRONMENT"] = "prod"
        with patch.dict(os.environ, env, clear=False):
            resp = handler(_event(), None, dynamodb=FakeDynamo(tables),
                           stripe_repo=NoKeyStripeRepo(), secret_cipher=Cipher(),
                           jobs_repo=FakeJobs(), invoker=lambda job: None)
        body = json.loads(resp["body"])
        self.assertEqual(resp["statusCode"], 202)
        self.assertEqual(body["job"]["status"], "queued")

    def test_live_mode_is_refused_outright(self):
        """Not scoped down to test behind the caller's back -- refused, so the mistake is visible."""
        tables = {"jb-products": FakeTable("PRODUCTS_TABLE", ["PK", "SK"], [_product()])}
        resp, body, _jobs = _run(tables, mode="live")
        self.assertEqual(resp["statusCode"], 400)
        self.assertEqual(body["error"], "live_mode")
        self.assertEqual(tables["jb-products"].deleted, [])

    def test_the_response_names_the_mode_it_acted_on(self):
        _, body, _jobs = _run({})
        self.assertEqual(body["mode"], "test")


class LiveDataSurvivesTests(unittest.TestCase):
    """What this action must NEVER do, now that a tenant's sandbox shares a deployment with their live
    books. The protection is the key, not a predicate."""

    def test_a_live_document_is_not_merely_filtered_out_it_is_UNREACHABLE(self):
        """THE regression this guards. Both modes share PK=TENANT#{id}; only the sort key separates them.
        The query asks for `PRODUCT#test#`, so the live row is never even returned."""
        table = FakeTable("PRODUCTS_TABLE", ["PK", "SK"], [_product(mode="live", pid="real")])
        _, body, _jobs = _run({"jb-products": table})
        self.assertEqual(table.deleted, [])
        self.assertEqual(body["deleted"]["products"], 0)

    def test_test_and_live_side_by_side(self):
        table = FakeTable("PRODUCTS_TABLE", ["PK", "SK"],
                          [_product(mode="test", pid="t"), _product(mode="live", pid="l")])
        _, body, _jobs = _run({"jb-products": table})
        self.assertEqual(body["deleted"]["products"], 1)
        self.assertEqual([k["SK"] for k in table.deleted], ["PRODUCT#test#t"])

    def test_another_tenants_partition_is_untouched(self):
        table = FakeTable("PRODUCTS_TABLE", ["PK", "SK"],
                          [_product(), {"PK": "TENANT#other", "SK": "PRODUCT#test#x"}])
        _, body, _jobs = _run({"jb-products": table})
        self.assertEqual([k["PK"] for k in table.deleted], ["TENANT#t1"])

    def test_the_repository_refuses_a_bulk_delete_with_no_mode(self):
        """The one way this could still reach both sets of books: `TYPE#` is a prefix of BOTH `TYPE#test#`
        and `TYPE#live#`. Refused at the repository, not just at the handler."""
        with patch.dict(os.environ, {"PRODUCTS_TABLE": "jb-products"}, clear=False):
            repo = documents.products_repository(FakeTable("P", ["PK", "SK"], []), mode="test")
        repo.mode = None  # the state a careless caller would produce
        with self.assertRaises(documents.RepositoryError):
            documents.delete_all_for_tenant(repo, "t1")


class ModeAgnosticDocumentsTests(unittest.TestCase):
    """Reviews, leads, notifications and refund requests carry no mode in their key. These are the only
    documents a predicate still decides, and it errs toward keeping."""

    def test_a_record_named_after_a_test_session_is_deleted(self):
        table = FakeTable("REVIEWS_TABLE", ["PK", "SK"], [_unmoded(order_id="order_cs_test_abc")])
        _, body, _jobs = _run({"jb-reviews": table})
        self.assertEqual(body["deleted"]["reviews"], 1)

    def test_and_one_named_after_a_LIVE_session_is_not(self):
        table = FakeTable("REVIEWS_TABLE", ["PK", "SK"], [_unmoded(order_id="order_cs_live_abc")])
        _, body, _jobs = _run({"jb-reviews": table})
        self.assertEqual(table.deleted, [])

    def test_a_document_that_proves_nothing_is_KEPT_and_counted(self):
        """Left alone -- and said out loud rather than silently skipped."""
        table = FakeTable("REVIEWS_TABLE", ["PK", "SK"], [_unmoded()])
        _, body, _jobs = _run({"jb-reviews": table})
        self.assertEqual(table.deleted, [])
        self.assertEqual(body["kept_not_mode_scoped"]["reviews"], 1)

    def test_the_stripe_mode_stamp_is_proof_enough(self):
        table = FakeTable("REVIEWS_TABLE", ["PK", "SK"], [_unmoded(stripe_mode="test")])
        _, body, _jobs = _run({"jb-reviews": table})
        self.assertEqual(body["deleted"]["reviews"], 1)


class WhatItClearsTests(unittest.TestCase):
    def test_clears_every_shape_and_skips_stripe_without_a_key(self):
        tables = {
            "jb-products": FakeTable("PRODUCTS_TABLE", ["PK", "SK"],
                                        [_product(pid="p1"), _product(pid="p2"), _product(mode="live", pid="p3")]),
            # Money documents live in a partition of their own per mode.
            "jb-orders": FakeTable("ORDERS_TABLE", ["PK", "SK"],
                                      [{"PK": "TENANT#t1#test", "SK": "order_cs_test_1"},
                                       {"PK": "TENANT#t1#live", "SK": "order_cs_live_9"}]),
            # Session ids carry their own books.
            "jb-checkout_sessions": FakeTable("CHECKOUT_SESSIONS_TABLE", ["session_id", "tenant_id"],
                                                 [{"session_id": "cs_test_1", "tenant_id": "t1"},
                                                  {"session_id": "cs_live_2", "tenant_id": "t1"}]),
            # A shared table: appointment is mode-scoped DATA, service is SETUP and stays.
            "jb-services": FakeTable("SERVICES_TABLE", ["PK", "SK"], [
                {"PK": "TENANT#t1", "SK": "APPOINTMENT#test#a1", "stripe_mode": "test"},
                {"PK": "TENANT#t1", "SK": "SLOTLOCK#test#f#2026", "stripe_mode": "test"},
                {"PK": "TENANT#t1", "SK": "SERVICE#test#s1", "stripe_mode": "test"},
            ]),
        }
        resp, body, _jobs = _run(tables)
        self.assertEqual(resp["statusCode"], 202)
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["errors"], {})
        self.assertEqual(body["deleted"]["products"], 2)
        self.assertEqual(body["deleted"]["orders"], 1)         # the live partition is a different key
        self.assertEqual(body["deleted"]["checkout_sessions"], 1)
        self.assertEqual(body["deleted"]["offers"], 0)
        self.assertEqual(body["deleted"]["appointments"], 1)
        self.assertEqual(body["deleted"]["slot_locks"], 1)
        # Booking SETUP in the same table is never addressed.
        self.assertTrue(all(k["SK"] != "SERVICE#test#s1" for k in tables["jb-services"].deleted))
        self.assertEqual(len(tables["jb-services"].deleted), 2)
        self.assertEqual(body["stripe"], {"skipped": "no_test_key"})

    def test_it_clears_the_tables_the_old_hand_kept_list_forgot(self):
        """Shipments, coupon grants and redemptions, booking credits, collections and A/B tests were all
        mode-scoped and none of them were cleared -- a sandbox reset left redemptions that still counted
        against a coupon's usage limit."""
        forgotten = {
            "shipments": ("jb-shipments", "SHIPMENT"),
            "coupon_grants": ("jb-coupon_grants", "COUPON_GRANT"),
            "coupon_redemptions": ("jb-coupon_redemptions", "COUPON_REDEMPTION"),
            # The table is BOOKING_CREDITS; the documents in it are service entitlements.
            "booking_credits": ("jb-booking_credits", "SERVICE_ENTITLEMENT"),
            "collections": ("jb-collections", "COLLECTION"),
            "experiments": ("jb-experiments", "EXPERIMENT"),
        }
        tables = {tbl: FakeTable(tbl, ["PK", "SK"],
                                 [{"PK": "TENANT#t1", "SK": f"{prefix}#test#x", "stripe_mode": "test"}])
                  for tbl, prefix in forgotten.values()}
        _, body, _jobs = _run(tables)
        for label in forgotten:
            with self.subTest(label=label):
                self.assertEqual(body["deleted"][label], 1)

    def test_a_table_that_refuses_is_reported_not_counted_as_empty(self):
        """A DynamoDB refusal once read as '0 deleted', which is indistinguishable from 'nothing there'."""
        class Exploding(FakeTable):
            def query(self, **kwargs):
                raise RuntimeError("AccessDeniedException")

        tables = {"jb-products": Exploding("PRODUCTS_TABLE", ["PK", "SK"], [])}
        resp, body, _jobs = _run(tables)
        self.assertEqual(body["status"], "failed")
        self.assertIn("products", body["errors"])
        self.assertIn("AccessDenied", body["errors"]["products"])


class TheResponseWindowTests(unittest.TestCase):
    """API Gateway hangs up at 29s whatever the Lambda timeout says. On the first real run the database
    half finished, the Stripe half ran on, the function hit its own 120s timeout, and the browser showed
    "Failed to fetch" -- no status, no body, no way to tell a disaster from a success."""

    def _stripe_run(self, *, deadline_offset):
        """Drive the Stripe cleanup with a deadline already in the past or far in the future."""
        import handlers.admin_delete_test_data as mod

        calls = []

        def opener(*a, **k):  # never reached if the budget stops us first
            raise AssertionError("made a Stripe call after the deadline")

        def fake_request(method, path, **kw):
            calls.append((method, path))
            if method == "GET":
                return {"data": [{"id": f"obj_{n}"} for n in range(3)], "has_more": False}
            return {}

        class Repo:
            def get(self, tenant_id, mode="test"):
                return {}

        with patch.object(mod, "stripe_request", fake_request), \
             patch.object(mod, "checkout_credentials", lambda *a, **k: ("sk_test_x", "acct_1")):
            return mod._delete_stripe_test_data(
                "t1", Repo(), None, opener,
                deadline=__import__("time").monotonic() + deadline_offset), calls

    def test_an_expired_budget_stops_before_mutating_anything(self):
        results, calls = self._stripe_run(deadline_offset=-1)
        self.assertTrue(results["incomplete"])
        self.assertEqual(results["prices_archived"], 0)
        self.assertEqual([m for m, _ in calls], [], "listed or mutated after the deadline")

    def test_with_budget_it_does_the_work_and_is_not_marked_incomplete(self):
        results, calls = self._stripe_run(deadline_offset=60)
        self.assertNotIn("incomplete", results)
        self.assertEqual(results["prices_archived"], 3)
        self.assertEqual(results["customers_deleted"], 3)
        self.assertTrue(any(m == "DELETE" for m, _ in calls))

    def test_a_non_test_key_is_refused_before_any_call(self):
        """The safety check that keeps this off live objects."""
        import handlers.admin_delete_test_data as mod

        class Repo:
            def get(self, tenant_id, mode="test"):
                return {}

        with patch.object(mod, "checkout_credentials", lambda *a, **k: ("sk_live_x", "acct_1")):
            self.assertEqual(
                mod._delete_stripe_test_data("t1", Repo(), None, None, deadline=None),
                {"skipped": "not_a_test_key"})


class TheRequestOnlyQueuesTests(unittest.TestCase):
    """The work outgrew the request path, so the request path stopped doing it.

    A wipe costs one sequential Stripe round-trip per object and is unbounded in the tenant's object
    count. API Gateway hangs up at 29s, and on a DESTRUCTIVE action that is the worst error available:
    no status, no body, nothing to distinguish a disaster from a success.
    """

    def test_the_post_answers_202_without_deleting_anything_yet(self):
        table = FakeTable("PRODUCTS_TABLE", ["PK", "SK"], [_product()])
        resp, accepted, jobs = _run({"jb-products": table}, defer=True)
        self.assertEqual(resp["statusCode"], 202)
        self.assertEqual(accepted["job"]["status"], "queued")
        self.assertEqual(table.deleted, [], "deleted on the request path")

    def test_the_job_carries_its_own_type_so_another_reaper_leaves_it_alone(self):
        _, accepted, jobs = _run({}, defer=True)
        self.assertEqual(accepted["job"]["document_type"], "delete_test_data_job")

    def test_a_queued_job_expires_so_the_table_does_not_grow_forever(self):
        _, accepted, _ = _run({}, defer=True)
        job = accepted["job"]
        self.assertGreater(job["expires_at"], job["created_at"])

    def test_polling_returns_the_finished_job_with_its_counts(self):
        table = FakeTable("PRODUCTS_TABLE", ["PK", "SK"], [_product()])
        _, _, jobs = _run({"jb-products": table})
        job_id = next(iter(jobs.rows))[1]
        event = {"httpMethod": "GET", "requestContext": {}, "headers": {"X-Tenant-Id": "t1"},
                 "queryStringParameters": {"job_id": job_id}, "body": ""}
        with patch.dict(os.environ, {"JOBS_TABLE": "jb-jobs"}, clear=False):
            resp = handler(event, None, jobs_repo=jobs)
        body = json.loads(resp["body"])
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(body["job"]["status"], "done")
        self.assertEqual(body["job"]["result"]["deleted"]["products"], 1)

    def test_polling_an_unknown_job_is_a_404_not_an_empty_success(self):
        event = {"httpMethod": "GET", "requestContext": {}, "headers": {"X-Tenant-Id": "t1"},
                 "queryStringParameters": {"job_id": "job_nope"}, "body": ""}
        resp = handler(event, None, jobs_repo=FakeJobs())
        self.assertEqual(resp["statusCode"], 404)

    def test_a_retried_invoke_does_not_report_the_work_twice(self):
        """Lambda retries an async invoke. Doing the deletion twice is harmless -- it is idempotent --
        but overwriting a finished job's counts with a second empty run is not."""
        table = FakeTable("PRODUCTS_TABLE", ["PK", "SK"], [_product()])
        _, body, jobs = _run({"jb-products": table})
        (tenant_id, job_id), = list(jobs.rows)
        again = handler({"internal_job": True, "tenant_id": tenant_id, "job_id": job_id, "mode": "test"},
                        _Context(), dynamodb=FakeDynamo({}), stripe_repo=NoKeyStripeRepo(),
                        secret_cipher=Cipher(), jobs_repo=jobs)
        self.assertEqual(again, {"ok": True, "skipped": "not_queued"})
        self.assertEqual(jobs.get(tenant_id, job_id)["result"]["deleted"]["products"], 1)


if __name__ == "__main__":
    unittest.main()

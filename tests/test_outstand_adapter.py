"""The Outstand adapter, against a stated transport.

No network. Every test says exactly what the vendor replied and asserts what we made of it — which is the
only way to pin a contract we do not control.

The response shapes here are taken from the published docs (outstand.so/docs, read 2026-11-06), not
invented. Where the docs are silent the test says so rather than guessing.
"""
import json
import unittest

from stripe_link.domain import outstand
from stripe_link.domain.outstand import (FAILED, PENDING, PUBLISHED, OutstandError, account_result,
                                         is_settled, list_accounts, publish, publish_result, upload_media)

#: A create-post response in the documented shape, before the vendor has processed it.
FRESH = {
    "success": True,
    "post": {
        "id": "post_abc", "orgId": "org_1", "publishedAt": None, "scheduledAt": None,
        "isDraft": False, "createdAt": "2026-11-06T10:00:00Z",
        "socialAccounts": [
            {"id": "acc_ig", "nickname": "Blue Whale", "network": "instagram", "username": "bluewhalegoodies"},
            {"id": "acc_li", "nickname": "BW", "network": "linkedin", "username": "blue-whale"},
        ],
        "containers": [{"id": "c1", "content": "hello", "media": []}],
    },
}

#: The same post once processed: one destination published, one failed. The half-success the original
#: single-id contract could not represent.
HALF = {
    "post": {
        "id": "post_abc", "scheduledAt": None, "publishedAt": "2026-11-06T10:00:09Z",
        "socialAccounts": [
            {"id": "acc_ig", "network": "instagram", "username": "bluewhalegoodies",
             "status": "published", "platformPostId": "178000", "publishedAt": "2026-11-06T10:00:09Z"},
            {"id": "acc_li", "network": "linkedin", "username": "blue-whale",
             "status": "failed", "error": "token expired"},
        ],
    },
}


def transport(status=200, payload=None, record=None):
    def send(method, url, headers, body):
        if record is not None:
            record.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None})
        return status, json.dumps(payload if payload is not None else {})
    return send


class TheFanOutIsTheContractTests(unittest.TestCase):
    """§6.1's original shape had room for ONE result. One call reaches many accounts."""

    def test_one_publish_returns_one_result_per_destination(self):
        result = publish({"accounts": ["acc_ig", "acc_li"], "content": "hello"},
                         token="k", transport=transport(payload=FRESH))
        self.assertEqual(result["post_id"], "post_abc")
        self.assertEqual([r["account_id"] for r in result["results"]], ["acc_ig", "acc_li"])

    def test_a_HALF_SUCCESS_is_representable(self):
        """THE ONE THAT MATTERS. Published to Instagram, failed on LinkedIn, in one call. A contract
        returning a single id would have lost one of these in the retry path."""
        result = publish_result(HALF)
        by_id = {r["account_id"]: r for r in result["results"]}
        self.assertEqual(by_id["acc_ig"]["status"], PUBLISHED)
        self.assertEqual(by_id["acc_ig"]["external_post_id"], "178000")
        self.assertEqual(by_id["acc_li"]["status"], FAILED)
        self.assertEqual(by_id["acc_li"]["error"], "token expired")

    def test_no_live_url_is_promised_anywhere(self):
        """The vendor returns no permalink. The contract must not invent a field it cannot fill."""
        result = publish_result(HALF)
        self.assertNotIn("live_url", result)
        for row in result["results"]:
            self.assertNotIn("live_url", row)


class TheStatusIsAStateNotAVerdictTests(unittest.TestCase):
    def test_a_fresh_publish_is_PENDING_not_published(self):
        result = publish({"accounts": ["acc_ig"], "content": "x"}, token="k",
                         transport=transport(payload=FRESH))
        self.assertEqual(result["results"][0]["status"], PENDING)

    def test_a_MISSING_status_reads_as_pending_not_failed(self):
        """The vendor omits `status` until the post is processed. Reading absent as failed would retry a
        post that is merely on its way."""
        self.assertEqual(account_result({"id": "a", "network": "x"})["status"], PENDING)

    def test_an_unknown_status_reads_as_pending(self):
        self.assertEqual(account_result({"id": "a", "status": "quantum"})["status"], PENDING)

    def test_is_settled_only_when_every_destination_is_terminal(self):
        self.assertTrue(is_settled(publish_result(HALF)))
        self.assertFalse(is_settled(publish_result(FRESH)))

    def test_a_post_with_NO_destinations_is_not_settled(self):
        """A malformed response is not a finished job. Treating it as settled would silently abandon it."""
        self.assertFalse(is_settled({"results": []}))
        self.assertFalse(is_settled({}))


class TheRequestShapeTests(unittest.TestCase):
    def test_our_schema_is_mapped_to_containers_here_and_nowhere_else(self):
        calls = []
        publish({"accounts": ["acc_ig"], "content": "hello", "media": ["https://cdn/x.jpg"]},
                token="k", transport=transport(payload=FRESH, record=calls))
        body = calls[0]["body"]
        self.assertEqual(body["accounts"], ["acc_ig"])
        self.assertEqual(body["containers"][0]["content"], "hello")
        self.assertEqual(body["containers"][0]["media"], ["https://cdn/x.jpg"])

    def test_the_key_travels_as_a_bearer_token(self):
        calls = []
        publish({"accounts": ["a"], "content": "x"}, token="secret-key",
                transport=transport(payload=FRESH, record=calls))
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer secret-key")

    def test_scheduling_is_passed_through_when_present(self):
        calls = []
        publish({"accounts": ["a"], "content": "x", "scheduled_at": "2026-11-20T18:00:00Z"},
                token="k", transport=transport(payload=FRESH, record=calls))
        self.assertEqual(calls[0]["body"]["scheduledAt"], "2026-11-20T18:00:00Z")

    def test_no_scheduledAt_key_at_all_when_publishing_now(self):
        """A null or past `scheduledAt` publishes immediately per the docs, but sending the key with an
        empty value is a different statement from not scheduling."""
        calls = []
        publish({"accounts": ["a"], "content": "x"}, token="k",
                transport=transport(payload=FRESH, record=calls))
        self.assertNotIn("scheduledAt", calls[0]["body"])

    def test_empty_media_is_omitted_rather_than_sent_empty(self):
        calls = []
        publish({"accounts": ["a"], "content": "x", "media": []}, token="k",
                transport=transport(payload=FRESH, record=calls))
        self.assertNotIn("media", calls[0]["body"]["containers"][0])

    def test_a_post_with_no_destination_is_refused_before_the_call(self):
        calls = []
        with self.assertRaises(OutstandError):
            publish({"accounts": [], "content": "x"}, token="k",
                    transport=transport(payload=FRESH, record=calls))
        self.assertEqual(calls, [])


class TheAccountListTests(unittest.TestCase):
    PAYLOAD = {"socialAccounts": [
        {"id": "acc_ig", "network": "Instagram", "username": "bluewhalegoodies", "nickname": "BW"},
        {"id": "", "network": "x", "username": "nope"},
    ]}

    def test_it_returns_ids_networks_and_handles(self):
        accounts = list_accounts(token="k", transport=transport(payload=self.PAYLOAD))
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["account_id"], "acc_ig")
        self.assertEqual(accounts[0]["network"], "instagram")
        self.assertEqual(accounts[0]["username"], "bluewhalegoodies")

    def test_an_entry_with_no_id_is_dropped(self):
        """The id is the only durable key; a row without one cannot be addressed later."""
        self.assertEqual(len(list_accounts(token="k", transport=transport(payload=self.PAYLOAD))), 1)


class TheErrorsTests(unittest.TestCase):
    def test_an_auth_failure_is_distinguishable(self):
        """A tenant can do nothing about a bad platform key, and retrying it only burns quota."""
        try:
            list_accounts(token="k", transport=transport(status=401, payload={"error": "nope"}))
            self.fail("expected OutstandError")
        except OutstandError as exc:
            self.assertTrue(exc.is_auth_failure)
            self.assertFalse(exc.is_retryable)

    def test_a_5xx_is_retryable_and_a_4xx_is_not(self):
        for status, retryable in ((500, True), (503, True), (429, True), (400, False), (404, False)):
            with self.subTest(status=status):
                try:
                    list_accounts(token="k", transport=transport(status=status, payload={}))
                    self.fail("expected OutstandError")
                except OutstandError as exc:
                    self.assertEqual(exc.is_retryable, retryable)

    def test_the_vendors_own_message_is_kept(self):
        """"HTTP 400" is not actionable; the body names what was wrong."""
        try:
            publish({"accounts": ["a"], "content": "x"}, token="k",
                    transport=transport(status=400, payload={"message": "account not connected"}))
            self.fail("expected OutstandError")
        except OutstandError as exc:
            self.assertIn("account not connected", exc.body)

    def test_a_missing_key_is_a_CONFIGURATION_fault_not_a_401(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(OutstandError) as caught:
                list_accounts(transport=transport(payload={}))
        self.assertIn("No Outstand API key", str(caught.exception))

    def test_nonsense_instead_of_json_is_an_error_not_an_empty_post(self):
        def send(method, url, headers, body):
            return 200, "<html>502</html>"

        with self.assertRaises(OutstandError):
            publish({"accounts": ["a"], "content": "x"}, token="k", transport=send)


class TheMediaUploadTests(unittest.TestCase):
    def test_the_three_steps_happen_in_order(self):
        calls, puts = [], []

        def send(method, url, headers, body):
            calls.append(url)
            if url.endswith("/v1/media/upload"):
                return 200, json.dumps({"id": "m1", "upload_url": "https://s3/put", "expires_in": 3600})
            return 200, json.dumps({"url": "https://cdn/m1.jpg"})

        result = upload_media("a.jpg", "image/jpeg", b"bytes", token="k", transport=send,
                              put=lambda u, c, d: puts.append((u, c, d)))
        self.assertTrue(calls[0].endswith("/v1/media/upload"))
        self.assertTrue(calls[1].endswith("/v1/media/m1/confirm"))
        self.assertEqual(puts, [("https://s3/put", "image/jpeg", b"bytes")])
        self.assertEqual(result, {"media_id": "m1", "url": "https://cdn/m1.jpg"})

    def test_the_confirm_reports_the_real_byte_count(self):
        sizes = []

        def send(method, url, headers, body):
            if url.endswith("/confirm"):
                sizes.append(json.loads(body)["size"])
                return 200, json.dumps({"url": "u"})
            return 200, json.dumps({"id": "m1", "upload_url": "https://s3/put"})

        upload_media("a.jpg", "image/jpeg", b"1234567890", token="k", transport=send, put=lambda *a: None)
        self.assertEqual(sizes, [10])

    def test_a_presign_without_an_upload_url_fails_before_any_PUT(self):
        puts = []
        with self.assertRaises(OutstandError):
            upload_media("a.jpg", "image/jpeg", b"x", token="k",
                         transport=transport(payload={"id": "m1"}),
                         put=lambda *a: puts.append(a))
        self.assertEqual(puts, [])

    def test_the_bearer_token_is_NOT_sent_to_the_storage_origin(self):
        """The presigned signature IS the credential there. Sending ours would leak it outside the API."""
        import inspect

        # The DOCSTRING says "Authorization" in order to explain its absence, so assert against the code
        # with the prose removed -- otherwise the comment explaining the rule breaks the test enforcing it.
        source = inspect.getsource(outstand._put_bytes)
        code = source.split('"""')[2]   # everything after the docstring
        self.assertNotIn("Authorization", code)
        self.assertIn("Content-Type", code)


class TheFeatureSwitchTests(unittest.TestCase):
    def test_no_key_configured_means_not_configured(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(outstand.configured())
        with mock.patch.dict(os.environ, {"OUTSTAND_API_KEY": "k"}, clear=True):
            self.assertTrue(outstand.configured())


class NothingReachesTheNetworkAtImportTests(unittest.TestCase):
    def test_no_module_level_call(self):
        import inspect

        source = inspect.getsource(outstand)
        top_level = [l for l in source.splitlines()
                     if l and not l[0].isspace() and not l.startswith(("def ", "class ", "#", '"', "'"))]
        for line in top_level:
            self.assertNotIn("urlopen", line)
            self.assertNotIn("boto3", line)


if __name__ == "__main__":
    unittest.main()

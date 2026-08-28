import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from handlers import support_contact
from stripe_link.mailer import EmailError


def _post(body, ip="1.2.3.4"):
    return {"httpMethod": "POST", "body": json.dumps(body),
            "requestContext": {"identity": {"sourceIp": ip}}, "headers": {"User-Agent": "UA/1"}}


GOOD = {"name": "Ada Lovelace", "email": "ada@example.com", "role": "buyer",
        "reference": "ord_123", "message": "My download link never arrived after paying."}


class SupportContactTests(unittest.TestCase):
    def test_sends_email_with_reply_to_submitter(self):
        sent = []
        resp = support_contact.handler(_post(GOOD), None, send=lambda **kw: sent.append(kw) or {}, now_fn=lambda: 1_790_000_000)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(json.loads(resp["body"])["status"], "sent")
        self.assertEqual(len(sent), 1)
        kw = sent[0]
        self.assertEqual(kw["reply_to"], "ada@example.com")
        self.assertEqual(kw["from_name"], "Ada Lovelace (via Junior Bay Support)")
        self.assertIn("Buyer: Ada Lovelace", kw["subject"])
        self.assertIn("ref ord_123", kw["subject"])
        self.assertIn("My download link never arrived", kw["text"])
        self.assertIn("1.2.3.4", kw["text"])
        self.assertIn("&lt;ada@example.com&gt;", kw["html"])  # escaped, not injected

    def test_honeypot_is_silently_accepted_and_not_sent(self):
        sent = []
        resp = support_contact.handler(_post({**GOOD, "website": "http://spam"}), None, send=lambda **kw: sent.append(kw))
        self.assertEqual(resp["statusCode"], 202)
        self.assertEqual(sent, [])

    def test_validation_errors(self):
        for bad, needle in [
            ({**GOOD, "email": "not-an-email"}, "valid email"),
            ({**GOOD, "message": "short"}, "describe"),
            ({**GOOD, "name": ""}, "name"),
        ]:
            resp = support_contact.handler(_post(bad), None, send=lambda **kw: None)
            self.assertEqual(resp["statusCode"], 400, bad)
            self.assertIn(needle, json.loads(resp["body"])["message"].lower())

    def test_unknown_role_falls_back_to_other_and_caps_lengths(self):
        sent = []
        support_contact.handler(_post({**GOOD, "role": "hacker", "message": "x" * 5000}), None, send=lambda **kw: sent.append(kw))
        self.assertIn("Other:", sent[0]["subject"])
        self.assertLessEqual(len(sent[0]["text"]), 4400)

    def test_send_failure_is_a_502(self):
        def boom(**kw):
            raise EmailError("SES down")
        resp = support_contact.handler(_post(GOOD), None, send=boom)
        self.assertEqual(resp["statusCode"], 502)

    def test_html_is_escaped(self):
        sent = []
        support_contact.handler(_post({**GOOD, "message": "<script>alert(1)</script> please help me"}), None, send=lambda **kw: sent.append(kw))
        self.assertNotIn("<script>", sent[0]["html"])
        self.assertIn("&lt;script&gt;", sent[0]["html"])

    def test_options_and_wrong_method(self):
        self.assertEqual(support_contact.handler({"httpMethod": "OPTIONS"}, None)["statusCode"], 200)
        self.assertEqual(support_contact.handler({"httpMethod": "GET"}, None)["statusCode"], 405)


class DisplayNameTests(unittest.TestCase):
    def test_header_injection_is_stripped(self):
        sent = []
        support_contact.handler(
            _post({**GOOD, "name": 'Evil"\r\nBcc: victim@example.com <x>'}), None,
            send=lambda **kw: sent.append(kw))
        fn = sent[0]["from_name"]
        for bad in ('"', "\r", "\n", "<", ">"):
            self.assertNotIn(bad, fn)
        self.assertTrue(fn.endswith("(via Junior Bay Support)"))

    def test_blank_name_falls_back(self):
        # a name of only stripped characters still yields a usable display name
        sent = []
        support_contact.handler(_post({**GOOD, "name": '"<>"'}), None, send=lambda **kw: sent.append(kw))
        self.assertEqual(sent[0]["from_name"], "Junior Bay Support Form")


if __name__ == "__main__":
    unittest.main()

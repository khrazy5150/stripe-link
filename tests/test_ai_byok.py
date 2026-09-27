"""Bring-your-own-key: the tenant's own provider account, billed to them (§A.1).

The two vendors reach structured output by genuinely different routes -- OpenAI has a strict
json_schema mode that guarantees conformance, Anthropic has forced tool-use where the tool's schema IS
the contract -- so these tests pin the wire format of each, and that both normalize to one shape the
callers above cannot tell apart.
"""

import json
import unittest

from stripe_link.ai_byok import ANTHROPIC_URL, OPENAI_URL, ByokError, _strict, generate
from stripe_link.ai_client import AiError, generate_structured

SCHEMA = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}


class Recorder:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []

    def __call__(self, url, headers, payload):
        self.sent.append({"url": url, "headers": headers, "payload": payload})
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        return reply


def anthropic_reply(value, *, tokens=(40, 12)):
    return {"content": [{"type": "tool_use", "name": "result", "input": value}],
            "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
            "stop_reason": "tool_use"}


def openai_reply(value, *, tokens=(40, 12), cached=0):
    return {"choices": [{"message": {"content": json.dumps(value)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1],
                      "prompt_tokens_details": {"cached_tokens": cached}}}


class StrictSchemaTests(unittest.TestCase):
    def test_every_nested_object_is_closed_and_fully_required(self):
        # OpenAI strict mode rejects the whole request otherwise, so this is normalization, not polish.
        out = _strict({"type": "object", "properties": {
            "a": {"type": "string"},
            "b": {"type": "object", "properties": {"c": {"type": "integer"}}}}, "required": ["a"]})
        self.assertFalse(out["additionalProperties"])
        self.assertEqual(out["required"], ["a", "b"])
        self.assertFalse(out["properties"]["b"]["additionalProperties"])
        self.assertEqual(out["properties"]["b"]["required"], ["c"])

    def test_it_reaches_inside_arrays_and_unions(self):
        out = _strict({"type": "object", "properties": {
            "xs": {"type": "array", "items": {"type": "object", "properties": {"n": {"type": "integer"}}}},
            "y": {"anyOf": [{"type": "object", "properties": {"m": {"type": "string"}}}]}}})
        self.assertFalse(out["properties"]["xs"]["items"]["additionalProperties"])
        self.assertFalse(out["properties"]["y"]["anyOf"][0]["additionalProperties"])


class AnthropicTests(unittest.TestCase):
    def test_it_forces_a_single_tool_so_prose_is_not_an_option(self):
        send = Recorder(anthropic_reply({"ok": True}))
        out = generate("anthropic", api_key="sk-ant", model="claude-sonnet-4-6", prompt="p",
                       json_schema=SCHEMA, schema_name="result", poster=send)
        payload = send.sent[0]["payload"]
        self.assertEqual(len(payload["tools"]), 1)
        self.assertEqual(payload["tool_choice"], {"type": "tool", "name": "result"})
        self.assertEqual(payload["tools"][0]["input_schema"], SCHEMA)
        self.assertEqual(json.loads(out["text"]), {"ok": True})

    def test_it_authenticates_with_the_vendors_own_header(self):
        send = Recorder(anthropic_reply({"ok": True}))
        generate("anthropic", api_key="sk-ant", model="claude-sonnet-4-6", prompt="p",
                 json_schema=SCHEMA, poster=send)
        self.assertEqual(send.sent[0]["url"], ANTHROPIC_URL)
        self.assertEqual(send.sent[0]["headers"]["x-api-key"], "sk-ant")
        self.assertIn("anthropic-version", send.sent[0]["headers"])

    def test_usage_is_normalized(self):
        send = Recorder(anthropic_reply({"ok": True}, tokens=(100, 25)))
        out = generate("anthropic", api_key="k", model="claude-sonnet-4-6", prompt="p",
                       json_schema=SCHEMA, poster=send)
        self.assertEqual(out["usage"], {"input": 100, "output": 25, "cache_read": 0})

    def test_an_answer_without_the_tool_is_unusable_rather_than_silently_empty(self):
        send = Recorder({"content": [{"type": "text", "text": "I'd rather chat"}], "usage": {}})
        with self.assertRaises(ByokError) as caught:
            generate("anthropic", api_key="k", model="claude-sonnet-4-6", prompt="p",
                     json_schema=SCHEMA, poster=send)
        self.assertEqual(caught.exception.kind, "unusable_output")


class OpenAiTests(unittest.TestCase):
    def test_it_asks_for_strict_json_schema(self):
        send = Recorder(openai_reply({"ok": True}))
        generate("openai", api_key="sk-oa", model="gpt-5.6", prompt="p", json_schema=SCHEMA,
                 schema_name="result", poster=send)
        fmt = send.sent[0]["payload"]["response_format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertTrue(fmt["json_schema"]["strict"])
        self.assertFalse(fmt["json_schema"]["schema"]["additionalProperties"])
        self.assertEqual(send.sent[0]["headers"]["Authorization"], "Bearer sk-oa")
        self.assertEqual(send.sent[0]["url"], OPENAI_URL)

    def test_a_system_prompt_becomes_a_system_message(self):
        send = Recorder(openai_reply({"ok": True}))
        generate("openai", api_key="k", model="gpt-5.6", prompt="p", json_schema=SCHEMA,
                 system="be terse", poster=send)
        self.assertEqual(send.sent[0]["payload"]["messages"][0], {"role": "system", "content": "be terse"})

    def test_cached_prompt_tokens_are_carried(self):
        send = Recorder(openai_reply({"ok": True}, tokens=(500, 20), cached=400))
        out = generate("openai", api_key="k", model="gpt-5.6", prompt="p", json_schema=SCHEMA, poster=send)
        self.assertEqual(out["usage"], {"input": 500, "output": 20, "cache_read": 400})


class GuardTests(unittest.TestCase):
    def test_an_unknown_model_never_reaches_the_vendor(self):
        # A closed list, not a passthrough: a typo would otherwise be a confusing vendor error and a
        # wrong id a surprise charge.
        send = Recorder(openai_reply({"ok": True}))
        with self.assertRaises(ByokError):
            generate("openai", api_key="k", model="gpt-nonexistent", prompt="p",
                     json_schema=SCHEMA, poster=send)
        self.assertEqual(send.sent, [])

    def test_an_unknown_provider_is_refused(self):
        with self.assertRaises(ByokError):
            generate("skynet", api_key="k", model="gpt-5.6", prompt="p", json_schema=SCHEMA,
                     poster=Recorder())

    def test_a_missing_key_is_refused_before_the_request(self):
        send = Recorder()
        with self.assertRaises(ByokError) as caught:
            generate("anthropic", api_key="", model="claude-sonnet-4-6", prompt="p",
                     json_schema=SCHEMA, poster=send)
        self.assertEqual(caught.exception.kind, "bad_credentials")
        self.assertEqual(send.sent, [])


class _NeverCallMe:
    """A Bedrock client that fails loudly if the BYOK path ever touches it."""

    def converse(self, **kwargs):
        raise AssertionError("BYOK must not reach Bedrock")


class DispatchTests(unittest.TestCase):
    """generate_structured must route by provider and return ONE shape regardless of who answered."""

    def test_a_byok_provider_bypasses_bedrock_entirely(self):
        send = Recorder(anthropic_reply({"ok": True}))
        exploding_bedrock = _NeverCallMe()
        out = generate_structured(prompt="p", json_schema=SCHEMA, model="claude-sonnet-4-6",
                                  provider="anthropic", api_key="k", schema_name="r",
                                  client=exploding_bedrock,
                                  byok_sender=lambda provider, **kw: generate(provider, poster=send, **kw))
        self.assertEqual(out["value"], {"ok": True})
        self.assertEqual(out["provider"], "anthropic")
        self.assertEqual(out["usage"], {"input": 40, "output": 12, "cache_read": 0})
        self.assertEqual(out["repairs"], 0)

    def test_the_repair_loop_works_on_the_byok_path_too(self):
        calls = []
        def sender(provider, **kwargs):
            calls.append(kwargs["prompt"])
            value = {"nope": 1} if len(calls) == 1 else {"ok": True}
            return {"text": json.dumps(value), "usage": {"input": 10, "output": 5, "cache_read": 0},
                    "stop_reason": "stop"}
        def validator(value):
            if "ok" not in value:
                raise ValueError("missing ok")
        from stripe_link.ai_client import _byok_loop
        out = _byok_loop(provider="anthropic", api_key="k", model="claude-sonnet-4-6", prompt="p",
                         json_schema=SCHEMA, system="", schema_name="r", validate=validator,
                         max_tokens=64, temperature=1.0, sender=sender)
        self.assertEqual(out["repairs"], 1)
        self.assertEqual(out["usage"]["input"], 20)          # both attempts billed
        self.assertIn("missing ok", calls[1])                # told what was wrong

    def test_vendor_errors_normalize_to_the_shared_error_kinds(self):
        from stripe_link.ai_client import _byok_loop
        for kind in ("bad_credentials", "throttled", "invalid_request"):
            with self.subTest(kind=kind):
                def sender(provider, **kwargs):
                    raise ByokError("boom", kind=kind, status=401)
                with self.assertRaises(AiError) as caught:
                    _byok_loop(provider="anthropic", api_key="k", model="claude-sonnet-4-6",
                               prompt="p", json_schema=SCHEMA, system="", schema_name="r",
                               validate=None, max_tokens=64, temperature=1.0, sender=sender)
                self.assertEqual(caught.exception.kind, kind)

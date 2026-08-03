import unittest
from unittest.mock import patch

from handlers import coupons as coupons_handler
from handlers import offers as offers_handler
from handlers import pages as pages_handler
from handlers import products as products_handler
from handlers import collections as collections_handler


class ModeRecordingRepo:
    """Captures the mode a handler resolved + threaded into its repository factory."""

    def __init__(self, mode=None):
        self.mode = mode

    def list_for_tenant(self, tenant_id):
        return []


def _list_event(mode):
    params = {"tenant_id": "t1"}
    if mode is not None:
        params["mode"] = mode
    return {"httpMethod": "GET", "queryStringParameters": params}


class HandlerModeThreadingTests(unittest.TestCase):
    """Each dashboard CRUD handler must build its repo scoped to the request's ?mode= (default test)."""

    CASES = [
        (products_handler, "products_repository"),
        (offers_handler, "offers_repository"),
        (coupons_handler, "coupons_repository"),
        (pages_handler, "pages_repository"),
        (collections_handler, "collections_repository"),
    ]

    def _resolved_mode(self, module, factory_name, event):
        captured = {}

        def fake_factory(*args, mode=None, **kwargs):
            captured["mode"] = mode
            return ModeRecordingRepo(mode)

        with patch.object(module, factory_name, side_effect=fake_factory):
            module.handler(event, None)
        return captured.get("mode")

    def test_live_mode_threads_through(self):
        for module, factory in self.CASES:
            with self.subTest(handler=factory):
                self.assertEqual(self._resolved_mode(module, factory, _list_event("live")), "live")

    def test_absent_mode_defaults_to_test(self):
        for module, factory in self.CASES:
            with self.subTest(handler=factory):
                self.assertEqual(self._resolved_mode(module, factory, _list_event(None)), "test")


if __name__ == "__main__":
    unittest.main()

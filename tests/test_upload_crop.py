"""Baking a tenant's crop into a derivative.

ASSET images -- product, service, landing hero -- differ from decorative ones in a way that decides the
mechanism: the same photo appears on several surfaces AND in `og:image` and Product JSON-LD, which are URLs
in meta tags. CSS cannot reach a meta tag, so a CSS-cropped product would still send the uncropped image to
Facebook and Google. For these the crop has to live in the file (plans/IMAGE_CROPPER.md).
"""

import json
import unittest

from handlers.upload import CROP_MAX_EDGE, CROP_MIN_EDGE, create_crop


class FakeUpstream:
    def __init__(self, payload=None, status=200):
        self.payload = payload if payload is not None else {"urls": {"webp": "https://cdn/x/custom.webp"}}
        self.status = status
        self.requests = []

    def __call__(self, req, *args, **kwargs):
        self.requests.append(req.full_url)
        upstream = self

        class Response:
            status = upstream.status

            def read(self):
                return json.dumps(upstream.payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Response()


def call(payload, upstream=None):
    upstream = upstream or FakeUpstream()
    event = {"httpMethod": "POST", "path": "/upload/crop", "body": json.dumps(payload)}
    return create_crop(event, opener=upstream), upstream


GOOD = {"image_id": "img_123", "width": 1600, "height": 900,
        "crop": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.25}}


class RequestShapeTests(unittest.TestCase):
    def test_it_asks_the_service_for_exactly_the_tenants_rect(self):
        response, upstream = call(GOOD)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("/resize/img_123/1600x900", upstream.requests[0])
        self.assertIn("crop=0.1,0.2,0.5,0.25", upstream.requests[0])

    def test_it_asks_for_cover_so_the_box_is_filled(self):
        # The rect already decides what is kept; `inside` would letterbox it and reintroduce dead space.
        _, upstream = call(GOOD)
        self.assertIn("fit=cover", upstream.requests[0])

    def test_the_image_id_is_escaped_into_the_path(self):
        # It is client-supplied, so it must not be able to reshape the upstream URL.
        _, upstream = call({**GOOD, "image_id": "../../admin"})
        self.assertNotIn("/resize/../../admin", upstream.requests[0])

    def test_it_returns_what_the_service_returned(self):
        response, _ = call(GOOD)
        self.assertIn("custom.webp", response["body"])


class ValidationTests(unittest.TestCase):
    """Everything here reaches the service as a URL, so a bad value becomes a 500 from a system that had
    no way to know better. Refuse it at the edge instead."""

    def _refused(self, payload):
        response, upstream = call(payload)
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(upstream.requests, [], "a refused request must not reach the service")

    def test_an_image_id_is_required(self):
        self._refused({k: v for k, v in GOOD.items() if k != "image_id"})

    def test_a_crop_needs_all_four_numbers(self):
        for missing in ("x", "y", "w", "h"):
            with self.subTest(missing=missing):
                crop = {k: v for k, v in GOOD["crop"].items() if k != missing}
                self._refused({**GOOD, "crop": crop})

    def test_a_zero_area_crop_is_refused(self):
        for crop in ({"x": 0, "y": 0, "w": 0, "h": 1}, {"x": 0, "y": 0, "w": 1, "h": 0}):
            with self.subTest(crop=crop):
                self._refused({**GOOD, "crop": crop})

    def test_the_output_box_is_bounded(self):
        # Unbounded, a tenant could ask the service to render something enormous on the platform's dime.
        for size in (CROP_MIN_EDGE - 1, CROP_MAX_EDGE + 1, 0, -100):
            with self.subTest(size=size):
                self._refused({**GOOD, "width": size})
                self._refused({**GOOD, "height": size})

    def test_non_numeric_values_are_refused(self):
        self._refused({**GOOD, "width": "big"})
        self._refused({**GOOD, "crop": {"x": "a", "y": 0, "w": 1, "h": 1}})

    def test_a_malformed_body_is_refused(self):
        event = {"httpMethod": "POST", "path": "/upload/crop", "body": "not json"}
        self.assertEqual(create_crop(event, opener=FakeUpstream())["statusCode"], 400)


class RoutingTests(unittest.TestCase):
    def test_the_route_exists_in_the_template(self):
        import pathlib
        import re

        tmpl = (pathlib.Path(__file__).resolve().parents[1] / "template.yaml").read_text()
        block = re.search(r"^  UploadFunction:\n((?:    .*\n|\n)*)", tmpl, re.M)
        self.assertIsNotNone(block)
        self.assertIn("/upload/crop", block.group(1),
                      "the handler answers /upload/crop but nothing routes to it")

    def test_the_handler_dispatches_crop_separately_from_upload(self):
        from handlers import upload

        event = {"httpMethod": "POST", "path": "/upload/crop", "body": json.dumps(GOOD)}
        upstream = FakeUpstream()
        response = upload.handler(event, None, opener=upstream)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("/resize/", upstream.requests[0], "a crop must not be sent to /upload/multiple")


if __name__ == "__main__":
    unittest.main()

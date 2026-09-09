"""Importing a tenant's own font (plans/FONT_SERVICE.md §10).

The licence gate is the point of most of this. A font licensed for DESKTOP use does not necessarily carry
web-embedding rights, and importing one publishes it from our CDN — so the affirmation is required, and when
it was made is recorded rather than merely that it was.
"""
import base64
import json
import unittest

from handlers import font_import


def _event(**body):
    payload = {"licence_affirmed": True, "family": "Acme Display", "filename": "Acme.ttf",
               "data": base64.b64encode(b"fake-ttf-bytes").decode(), **body}
    return {"httpMethod": "POST", "body": json.dumps(payload),
            "requestContext": {"authorizer": {"claims": {"custom:tenant_id": "t1"}}},
            "queryStringParameters": {"tenant_id": "t1"}}


class _Repo:
    def __init__(self, profile=None):
        self.profile = profile if profile is not None else {"tenant_id": "t1", "fonts": {}}
        self.saved = None

    def get(self, tenant_id, document_id):
        return self.profile

    def put(self, document):
        self.saved = document
        return document


class _S3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def _converter(variable=False, axes=None, weight_class=None, family="", style=""):
    def convert(raw, filename):
        return b"WOFF2-BYTES", {"variable": variable, "axes": axes or [],
                                "weight_class": weight_class, "family": family, "style": style}
    return convert


def _body(response):
    return json.loads(response["body"])


class LicenceGateTests(unittest.TestCase):
    def test_an_upload_without_the_affirmation_is_refused(self):
        r = font_import.handler(_event(licence_affirmed=False), None,
                                repository=_Repo(), s3_client=_S3(), converter=_converter())
        self.assertEqual(r["statusCode"], 400)
        self.assertEqual(_body(r)["error"], "licence_not_affirmed")

    def test_a_missing_affirmation_is_not_treated_as_consent(self):
        # Absent must not read as false-y-but-fine; only an explicit True passes.
        for value in (None, "yes", 1, "true"):
            with self.subTest(value=value):
                r = font_import.handler(_event(licence_affirmed=value), None,
                                        repository=_Repo(), s3_client=_S3(), converter=_converter())
                self.assertEqual(r["statusCode"], 400)

    def test_the_moment_of_affirmation_is_recorded(self):
        repo = _Repo()
        font_import.handler(_event(), None, repository=repo, s3_client=_S3(), converter=_converter())
        self.assertGreater(repo.saved["fonts"]["imported"][0]["licence_affirmed_at"], 0)


class ConversionTests(unittest.TestCase):
    def test_a_variable_font_records_the_range_the_FONT_reports(self):
        # Not what the form said: the tenant cannot know it, and guessing wrong makes the browser
        # synthesise weights the file already contains.
        repo = _Repo()
        conv = _converter(variable=True, axes=[{"tag": "wght", "min": 200, "max": 900}])
        font_import.handler(_event(weight="400"), None, repository=repo, s3_client=_S3(), converter=conv)
        record = repo.saved["fonts"]["imported"][0]
        self.assertEqual(record["weight"], "200 900")
        self.assertTrue(record["variable"])

    def test_a_static_fonts_own_weight_class_beats_the_form(self):
        # The tenant is looking at a file, not at its OS/2 table, so the form is a guess. Declaring a Bold
        # as 400 would make the browser synthesise bold ON TOP of a bold face.
        repo = _Repo()
        font_import.handler(_event(weight="400"), None, repository=repo, s3_client=_S3(),
                            converter=_converter(weight_class=700))
        self.assertEqual(repo.saved["fonts"]["imported"][0]["weight"], "700")

    def test_the_form_is_used_only_when_the_font_states_nothing(self):
        repo = _Repo()
        font_import.handler(_event(weight="600"), None, repository=repo, s3_client=_S3(),
                            converter=_converter(weight_class=None))
        self.assertEqual(repo.saved["fonts"]["imported"][0]["weight"], "600")

    def test_a_nonsense_weight_falls_back_rather_than_being_stored(self):
        repo = _Repo()
        font_import.handler(_event(weight="enormous"), None, repository=repo, s3_client=_S3(),
                            converter=_converter(weight_class=None))
        self.assertEqual(repo.saved["fonts"]["imported"][0]["weight"], "400")

    def test_what_the_font_called_itself_is_recorded(self):
        repo = _Repo()
        font_import.handler(_event(), None, repository=repo, s3_client=_S3(),
                            converter=_converter(weight_class=400, family="Lato", style="Regular"))
        record = repo.saved["fonts"]["imported"][0]
        self.assertEqual((record["detected_family"], record["detected_style"]), ("Lato", "Regular"))


class StorageTests(unittest.TestCase):
    def test_it_writes_under_the_tenant_prefix_only(self):
        # The catalogue's own files live under /fonts/<Family>/ and must never be writable from here; the
        # IAM policy scopes to fonts/tenant/*, so a key outside it would fail in production, not in tests.
        s3 = _S3()
        font_import.handler(_event(), None, repository=_Repo(), s3_client=s3, converter=_converter())
        self.assertTrue(s3.calls[0]["Key"].startswith("fonts/tenant/t1/"))
        self.assertEqual(s3.calls[0]["ContentType"], "font/woff2")

    def test_it_is_not_cached_immutable(self):
        # The key is family+weight+style, so re-uploading the SAME face overwrites it. `immutable` would
        # strand the old bytes at every edge for a year — the trap that cost hours on 2026-09-08.
        s3 = _S3()
        font_import.handler(_event(), None, repository=_Repo(), s3_client=s3, converter=_converter())
        self.assertNotIn("immutable", s3.calls[0]["CacheControl"])

    def test_reuploading_a_face_replaces_it(self):
        repo = _Repo()
        for _ in range(3):
            font_import.handler(_event(weight="400"), None, repository=repo, s3_client=_S3(), converter=_converter())
        self.assertEqual(len(repo.saved["fonts"]["imported"]), 1)

    def test_a_different_weight_is_a_different_face(self):
        repo = _Repo()
        for weight in ("400", "700"):
            font_import.handler(_event(weight=weight), None, repository=repo, s3_client=_S3(), converter=_converter())
        self.assertEqual(len(repo.saved["fonts"]["imported"]), 2)


class RejectionTests(unittest.TestCase):
    def test_only_font_files_are_accepted(self):
        r = font_import.handler(_event(filename="notafont.zip"), None,
                                repository=_Repo(), s3_client=_S3(), converter=_converter())
        self.assertEqual(_body(r)["error"], "unsupported_format")

    def test_nothing_is_stored_when_conversion_fails(self):
        def boom(raw, filename):
            raise font_import.FontConversionError("That font could not be converted.")
        s3, repo = _S3(), _Repo()
        r = font_import.handler(_event(), None, repository=repo, s3_client=s3, converter=boom)
        self.assertEqual(r["statusCode"], 400)
        self.assertEqual(s3.calls, [])
        self.assertIsNone(repo.saved)

    def test_the_import_is_capped(self):
        repo = _Repo({"tenant_id": "t1", "fonts": {"imported": [
            {"family": f"F{i}", "url": "u", "weight": "400"} for i in range(font_import.MAX_IMPORTED_FONTS)]}})
        r = font_import.handler(_event(), None, repository=repo, s3_client=_S3(), converter=_converter())
        self.assertEqual(_body(r)["error"], "too_many_fonts")


if __name__ == "__main__":
    unittest.main()


class RemoveTests(unittest.TestCase):
    def _profile(self):
        return {"tenant_id": "t1", "fonts": {"imported": [
            {"family": "Acme", "weight": "400", "style": "normal",
             "url": "https://juniorbay.com/fonts/tenant/t1/acme-400-normal.woff2"},
            {"family": "Acme", "weight": "700", "style": "normal",
             "url": "https://juniorbay.com/fonts/tenant/t1/acme-700-normal.woff2"},
        ]}}

    def _delete(self, repo, s3, **body):
        event = {"httpMethod": "DELETE", "body": json.dumps(body),
                 "queryStringParameters": {"tenant_id": "t1"},
                 "requestContext": {"authorizer": {"claims": {"custom:tenant_id": "t1"}}}}
        return font_import.handler(event, None, repository=repo, s3_client=s3)

    def test_one_weight_goes_and_the_other_stays(self):
        repo, s3 = _Repo(self._profile()), _S3()
        r = self._delete(repo, s3, family="Acme", weight="400", style="normal")
        self.assertEqual(r["statusCode"], 200)
        remaining = repo.saved["fonts"]["imported"]
        self.assertEqual([f["weight"] for f in remaining], ["700"])

    def test_the_object_is_removed_from_the_bucket_too(self):
        repo, s3 = _Repo(self._profile()), _S3()
        s3.deleted = []
        s3.delete_object = lambda **kw: s3.deleted.append(kw)
        self._delete(repo, s3, family="Acme", weight="400", style="normal")
        self.assertEqual(s3.deleted[0]["Key"], "fonts/tenant/t1/acme-400-normal.woff2")

    def test_a_failed_cleanup_still_removes_the_record(self):
        # The record is the source of truth; a stranded object is waste, not a reason to refuse the delete.
        repo, s3 = _Repo(self._profile()), _S3()
        def boom(**kw):
            raise RuntimeError("s3 down")
        s3.delete_object = boom
        r = self._delete(repo, s3, family="Acme", weight="400", style="normal")
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(len(repo.saved["fonts"]["imported"]), 1)

    def test_deleting_something_absent_says_so(self):
        r = self._delete(_Repo(self._profile()), _S3(), family="Nope", weight="400")
        self.assertEqual(r["statusCode"], 404)


class ListTests(unittest.TestCase):
    def _get(self, repo):
        return font_import.handler(
            {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1"},
             "requestContext": {"authorizer": {"claims": {"custom:tenant_id": "t1"}}}},
            None, repository=repo)

    def test_it_returns_what_was_imported(self):
        # Without this the list is only ever filled by an import response, so a refresh shows nothing and
        # the tenant reasonably concludes their upload was lost.
        repo = _Repo({"tenant_id": "t1", "fonts": {"imported": [
            {"family": "Acme", "weight": "400", "url": "u"}]}})
        self.assertEqual(len(_body(self._get(repo))["fonts"]), 1)

    def test_a_store_with_no_fonts_returns_an_empty_list_not_an_error(self):
        self.assertEqual(_body(self._get(_Repo({"tenant_id": "t1"})))["fonts"], [])
        self.assertEqual(_body(self._get(_Repo({})))["fonts"], [])


class ConvertedBytesTests(unittest.TestCase):
    """What reaches S3 must be a real WOFF2.

    font-converter answers with isBase64Encoded, and API Gateway only decodes that for a client negotiating
    a binary media type — urllib does not. Writing the base64 TEXT to S3 produces a file no browser can
    parse, and nothing reports it: the @font-face is emitted, the file serves 200, and the font just never
    renders. Verified by the bytes, not by a header.
    """

    def test_base64_from_the_converter_is_decoded(self):
        real = b"wOF2" + b"\x00" * 40
        encoded = base64.b64encode(real)

        class _Resp:
            headers = {"X-Font-Variable": "false", "X-Font-Axes": "[]", "X-Font-Weight-Class": "700"}
            def read(self): return encoded
            def __enter__(self): return self
            def __exit__(self, *a): return False

        import urllib.request
        original, font_import.CONVERTER_URL = urllib.request.urlopen, "https://example.test/convert"
        urllib.request.urlopen = lambda *a, **k: _Resp()
        try:
            woff2, meta = font_import.convert_font(b"ttf", "x.ttf")
        finally:
            urllib.request.urlopen = original
        self.assertEqual(woff2[:4], b"wOF2")
        self.assertEqual(meta["weight_class"], 700)

    def test_something_that_is_not_a_font_either_way_is_refused(self):
        class _Resp:
            headers = {}
            def read(self): return b"definitely not a font"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        import urllib.request
        original, font_import.CONVERTER_URL = urllib.request.urlopen, "https://example.test/convert"
        urllib.request.urlopen = lambda *a, **k: _Resp()
        try:
            with self.assertRaises(font_import.FontConversionError):
                font_import.convert_font(b"ttf", "x.ttf")
        finally:
            urllib.request.urlopen = original

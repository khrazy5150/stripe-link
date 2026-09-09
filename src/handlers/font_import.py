"""Import a tenant's own font: convert it, store it, record it on their store profile.

The font service cannot serve these. Its catalogue is a hardcoded dict shared by every tenant, so a
tenant's own face is emitted as an @font-face by the RENDERER instead (runtime/html.py). This handler is
the part that turns an upload into something the renderer can point at.

Conversion is delegated to ../sam/font-converter, which already does it and reports the font's real
variation axes. Nothing about fonts is parsed here: fontTools would have to be added to src/requirements.txt,
which is deliberately empty because every function shares CodeUri: src/ -- one dependency there bundles into
all 49 of them, and boto3 alone once cost ~6.5s of cold start.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.repositories.documents import RepositoryError, tenant_profiles_repository

CONVERTER_URL = os.environ.get("FONT_CONVERTER_URL", "")
FONTS_BUCKET = os.environ.get("FONTS_BUCKET", "")
FONTS_PUBLIC_BASE = os.environ.get("FONTS_PUBLIC_BASE", "https://juniorbay.com/fonts")

# A tenant's whole catalogue, not one file: enough for a family with several weights, small enough that a
# runaway upload cannot fill the bucket.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMPORTED_FONTS = 12
ALLOWED_EXTENSIONS = (".ttf", ".otf")


def handler(event, context, repository=None, s3_client=None, converter=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method == "GET":
        return list_fonts(event, repository=repository)
    if method == "DELETE":
        return remove_font(event, repository=repository, s3_client=s3_client)
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")

    # LICENCE. A font licensed for desktop use does not necessarily carry web-embedding rights, and this
    # would serve it publicly from our CDN. The tenant must say they hold those rights; we record when.
    if body.get("licence_affirmed") is not True:
        return error_response(
            "Confirm you hold a licence permitting web embedding of this font before uploading it.",
            code="licence_not_affirmed",
        )

    family = str(body.get("family") or "").strip()

    filename = str(body.get("filename") or "").strip()
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        return error_response(
            f"Upload a {' or '.join(e.upper().lstrip('.') for e in ALLOWED_EXTENSIONS)} file.",
            code="unsupported_format",
        )

    try:
        raw = base64.b64decode(str(body.get("data") or ""), validate=True)
    except Exception:
        return error_response("The uploaded file could not be read.", code="invalid_upload")
    if not raw:
        return error_response("The uploaded file is empty.", code="invalid_upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        return error_response(
            f"Font files must be under {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.", code="upload_too_large"
        )

    try:
        woff2, meta = (converter or convert_font)(raw, filename)
    except FontConversionError as exc:
        return error_response(str(exc), code="conversion_failed")

    repository = repository or tenant_profiles_repository()
    try:
        profile = repository.get(tenant_id, tenant_id) or {}
    except RepositoryError as exc:
        return error_response(str(exc), code="profile_unavailable")
    if not profile:
        return error_response("No store profile to attach this font to.", status_code=404, code="not_found")

    existing = list(((profile.get("fonts") or {}).get("imported")) or [])
    if len(existing) >= MAX_IMPORTED_FONTS:
        return error_response(
            f"You can import up to {MAX_IMPORTED_FONTS} fonts. Remove one first.", code="too_many_fonts"
        )

    # The FONT decides its weight, not the form. A tenant is looking at a file, not at its OS/2 table, so
    # "is this 400 or 600?" is a question they cannot answer -- and getting it wrong is not cosmetic: the
    # weight becomes the @font-face descriptor, so a Bold declared 400 makes the browser synthesise bold on
    # top of a bold face. The submitted value is only a fallback for a font that states nothing.
    # Named by the font when the tenant did not name it: they should not have to invent a label for
    # something that already has one.
    family = family or str(meta.get("family") or "").strip()
    if not family:
        return error_response(
            "This font does not name itself — give it a family name.", code="missing_family"
        )

    weight = normalize_weight(body.get("weight"), meta)
    style = "italic" if str(body.get("style") or "").strip().lower() == "italic" else "normal"
    key = f"tenant/{tenant_id}/{slugify(family)}-{slugify(weight)}-{style}.woff2"
    try:
        put_font(s3_client, key, woff2)
    except Exception:
        return error_response("The font could not be stored. Try again.", code="storage_failed")

    record = {
        "family": family,
        "url": f"{FONTS_PUBLIC_BASE.rstrip('/')}/{key}",
        "weight": weight,
        "style": style,
        "variable": bool(meta.get("variable")),
        "axes": meta.get("axes") or [],
        # What the font called itself, kept so a tenant can see we read it rather than guessed.
        "detected_family": meta.get("family") or "",
        "detected_style": meta.get("style") or "",
        "bytes": len(woff2),
        "original_filename": filename,
        # WHEN they affirmed it, not merely that they did: the claim is about a licence held at a point in
        # time, and "they ticked a box once" is not much of a record without it.
        "licence_affirmed_at": int(time.time()),
    }
    # One face per family+weight+style. Re-uploading replaces rather than accumulating near-duplicates that
    # differ only by which one the browser happens to pick.
    kept = [
        f for f in existing
        if not (str(f.get("family")) == family and str(f.get("weight")) == weight
                and str(f.get("style", "normal")) == style)
    ]
    profile.setdefault("fonts", {})["imported"] = kept + [record]
    try:
        repository.put(profile)
    except RepositoryError as exc:
        return error_response(str(exc), code="profile_save_failed")

    return json_response({"font": record, "fonts": profile["fonts"]["imported"]}, status_code=201)


def list_fonts(event, repository=None):
    """The store's imported faces. Without this the list is only ever populated by an import response, so a
    refresh shows nothing and a tenant reasonably concludes their upload was lost."""
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    repository = repository or tenant_profiles_repository()
    try:
        profile = repository.get(tenant_id, tenant_id) or {}
    except RepositoryError as exc:
        return error_response(str(exc), code="profile_unavailable")
    return json_response({"fonts": ((profile.get("fonts") or {}).get("imported")) or []})


def remove_font(event, repository=None, s3_client=None):
    """Drop one imported face from the store profile, and its object from the bucket.

    Identified by family + weight + style, the same triple the import keys on -- not by URL, which would
    break the moment the public base changed.

    A page still naming this family does NOT break: nothing emits its @font-face any more, so the family
    simply falls through to the fallback stack in the CSS. That is the same degradation as a font that
    fails to load, and better than refusing the delete because a page might reference it.
    """
    tenant_id = tenant_id_from_event(event)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return error_response(str(exc), code="invalid_body")

    family = str(body.get("family") or "").strip()
    if not family:
        return error_response("Which font?", code="missing_family")
    weight = str(body.get("weight") or "").strip()
    style = str(body.get("style") or "normal").strip().lower()

    repository = repository or tenant_profiles_repository()
    try:
        profile = repository.get(tenant_id, tenant_id) or {}
    except RepositoryError as exc:
        return error_response(str(exc), code="profile_unavailable")
    existing = list(((profile.get("fonts") or {}).get("imported")) or [])

    def matches(face):
        return (str(face.get("family")) == family
                and (not weight or str(face.get("weight")) == weight)
                and str(face.get("style", "normal")).lower() == style)

    removed = [f for f in existing if matches(f)]
    if not removed:
        return error_response("That font is not imported.", status_code=404, code="not_found")

    profile.setdefault("fonts", {})["imported"] = [f for f in existing if not matches(f)]
    try:
        repository.put(profile)
    except RepositoryError as exc:
        return error_response(str(exc), code="profile_save_failed")

    # Best effort. The record is the source of truth, so a bucket object that outlives it is waste, not a
    # bug -- and failing the delete because cleanup failed would leave the tenant unable to remove a font.
    for face in removed:
        try:
            delete_font_object(s3_client, str(face.get("url") or ""))
        except Exception:
            pass

    return json_response({"fonts": profile["fonts"]["imported"]})


def delete_font_object(s3_client, url: str) -> None:
    prefix = f"{FONTS_PUBLIC_BASE.rstrip('/')}/"
    if not url.startswith(prefix):
        return
    key = f"fonts/{url[len(prefix):]}"
    if not key.startswith("fonts/tenant/"):
        return   # never reach outside the tenant prefix, whatever a stored URL claims
    import boto3

    (s3_client or boto3.client("s3")).delete_object(Bucket=FONTS_BUCKET, Key=key)


class FontConversionError(Exception):
    pass


def convert_font(raw: bytes, filename: str):
    """(woff2 bytes, metadata) from font-converter, which reads the font rather than its filename.

    It answers the only question that matters to the tenant: whether one upload covers every weight, or
    whether they must upload each weight separately. A static TTF cannot become a variable WOFF2 -- WOFF2 is
    a compression container and adds no axes that were never in the outlines.
    """
    if not CONVERTER_URL:
        raise FontConversionError("Font conversion is not configured.")
    request = urllib.request.Request(
        CONVERTER_URL, data=raw, method="POST",
        headers={"Content-Type": "application/octet-stream", "X-Filename": filename},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            converted = response.read()
            headers = response.headers
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get("error", "")
        except Exception:
            pass
        raise FontConversionError(f"That font could not be converted. {detail}".strip())
    except Exception:
        raise FontConversionError("The font service did not respond. Try again.")
    if not converted:
        raise FontConversionError("That font could not be converted.")
    # The converter answers with `isBase64Encoded: true`, and API Gateway only decodes that for a client
    # negotiating a binary media type. urllib does not, so what arrives here is usually the base64 TEXT --
    # and writing that to S3 produces a file the browser cannot parse, with no error anywhere: the font
    # simply never renders. Decide by looking at the bytes rather than trusting a header.
    if converted[:4] != b"wOF2":
        try:
            decoded = base64.b64decode(converted, validate=True)
        except Exception:
            decoded = b""
        if decoded[:4] == b"wOF2":
            converted = decoded
    if converted[:4] != b"wOF2":
        raise FontConversionError("The converted font was not readable. Try a different file.")
    try:
        axes = json.loads(headers.get("X-Font-Axes") or "[]")
    except ValueError:
        axes = []
    weight_class = str(headers.get("X-Font-Weight-Class") or "").strip()
    return converted, {
        "variable": (headers.get("X-Font-Variable") or "").lower() == "true",
        "axes": axes if isinstance(axes, list) else [],
        "weight_class": int(weight_class) if weight_class.isdigit() else None,
        "family": (headers.get("X-Font-Family") or "").strip(),
        "style": (headers.get("X-Font-Style") or "").strip(),
    }


def normalize_weight(requested, meta) -> str:
    """The weight the font declares: an fvar range if variable, else its OS/2 weight class.

    Falls back to the submitted value only when the file states nothing, which is rare and usually means an
    unusual font. Everything here comes from the file precisely so the tenant is not asked to guess.
    """
    meta = meta or {}
    if meta.get("variable"):
        for axis in meta.get("axes") or []:
            if isinstance(axis, dict) and axis.get("tag") == "wght":
                return f"{int(float(axis.get('min', 400)))} {int(float(axis.get('max', 700)))}"
    declared = meta.get("weight_class")
    if isinstance(declared, int) and 1 <= declared <= 1000:
        return str(declared)
    weight = str(requested or "400").strip()
    return weight if weight.isdigit() and 1 <= int(weight) <= 1000 else "400"


def slugify(value: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in str(value or "")).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "font"


def put_font(s3_client, key: str, data: bytes) -> None:
    import boto3

    client = s3_client or boto3.client("s3")
    client.put_object(
        Bucket=FONTS_BUCKET, Key=f"fonts/{key}", Body=data,
        ContentType="font/woff2",
        # Same contract as the catalogue fonts: the key carries family+weight+style, so a re-upload of the
        # SAME face overwrites and would be stranded at the edge by `immutable`. Kept short for that reason.
        CacheControl="public, max-age=86400",
    )

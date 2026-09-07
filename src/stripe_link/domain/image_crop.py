"""The stored crop rect, and the CSS that applies it.

A crop is NORMALIZED fractions of the source ({x, y, w, h} in 0..1), never pixels. The image service emits
thumb/small/medium/large/full and mints more renditions on demand, so a pixel rect is correct against
exactly one of them and silently wrong against every other (plans/IMAGE_CROPPER.md).

The same arithmetic runs in two places -- here for the published page, and in ImageUploadField.vue for the
builder's thumbnail -- so the percentages come from ONE set of formulas checked against a shared fixture,
`schemas/image_crop_cases.json`. Two implementations of a formula with nothing forcing them to agree is how
a preview ends up lying about the page.
"""

import json
from pathlib import Path
from typing import Any

# object-position cannot express a zoom, so the crop is applied by scaling the image inside a clipped box:
# the image is enlarged by 1/w and 1/h, then offset by -x/w and -y/h, which puts exactly the chosen region
# in view. Percentages (not pixels) so it holds at any rendered size.
CROP_KEYS = ("x", "y", "w", "h")

# Ratios are DATA, shared with the builder, not a constant restated per language. The cropper must frame
# exactly what the renderer crops to; a comment saying "must match" is not a mechanism.
_RATIOS_PATH = Path(__file__).resolve().parent.parent / "image_ratios.json"
_RATIOS_FILE: dict[str, Any] = json.loads(_RATIOS_PATH.read_text())

# Two mechanisms, one table. PLACEMENT crops are clipped in CSS at render time; ASSET crops are baked into
# a derivative, so the stored URL is already cropped and the renderer must apply nothing. Keeping them in
# one file with the mechanism in the structure means a surface cannot be wired one way and rendered the
# other -- which would either double-crop the image or ignore the crop entirely.
PLACEMENT_SURFACES: dict[str, Any] = _RATIOS_FILE.get("placement") or {}
ASSET_SURFACES: dict[str, Any] = _RATIOS_FILE.get("asset") or {}
_RATIOS: dict[str, Any] = {**PLACEMENT_SURFACES, **ASSET_SURFACES}

# A surface that accepts any shape. "original" means the source image's own ratio -- a reframe that zooms
# and pans without changing the shape, which is what a shape-agnostic surface usually wants.
FREEFORM = "original"


def surface_ratios(surface: str) -> list[Any]:
    """Every ratio a surface offers, in order. One entry means locked; empty means anything goes."""
    value = _RATIOS.get(str(surface or ""), None)
    if value is None:
        return [FREEFORM]
    if isinstance(value, list):
        return [v for v in value if v == FREEFORM or (isinstance(v, (int, float)) and v > 0)]
    return [value] if isinstance(value, (int, float)) and value > 0 else [FREEFORM]


def surface_ratio(surface: str, default: float = 1.0) -> float:
    """The single ratio a LOCKED surface renders at.

    Only meaningful where the layout demands one shape. A surface offering choices has no single answer,
    so the crop itself carries the shape it was made at -- see crop_aspect.
    """
    options = surface_ratios(surface)
    if len(options) == 1 and options[0] != FREEFORM:
        return float(options[0])
    return default


def crop_aspect(crop: Any, surface: str = "", default: float = 1.0) -> float:
    """The shape a crop actually renders at.

    The rect is fractions of the SOURCE, so its own numbers cannot reveal the output shape without the
    source dimensions. Rather than depend on the image_dims sidecar being present, the cropper records the
    ratio it framed at; a locked surface can still answer from the table for crops made before it did.
    """
    if isinstance(crop, dict):
        try:
            stored = float(crop.get("ar"))
            if stored > 0:
                return stored
        except (TypeError, ValueError):
            pass
    return surface_ratio(surface, default)


def normalized_crop(value: Any) -> dict[str, float] | None:
    """A usable crop, or None. A full-frame crop is None: it changes nothing and should not add markup."""
    if not isinstance(value, dict):
        return None
    try:
        rect = {key: float(value.get(key)) for key in CROP_KEYS}
    except (TypeError, ValueError):
        return None
    if not (rect["w"] > 0 and rect["h"] > 0):
        return None
    if any(rect[key] < 0 for key in CROP_KEYS):
        return None
    # A hair over 1 is browser rounding, not a bad value; clamp rather than discard the tenant's framing.
    rect["w"] = min(rect["w"], 1.0)
    rect["h"] = min(rect["h"], 1.0)
    rect["x"] = min(rect["x"], 1.0 - rect["w"])
    rect["y"] = min(rect["y"], 1.0 - rect["h"])
    rect["x"] = max(rect["x"], 0.0)
    rect["y"] = max(rect["y"], 0.0)
    if rect["w"] >= 1.0 and rect["h"] >= 1.0:
        return None
    return rect


def _pct(value: float) -> str:
    """Trim trailing zeros so the emitted CSS is stable and diffable rather than full of float noise.

    `value + 0.0` collapses negative zero: an un-offset crop otherwise emits `-0%`, which is valid CSS but
    noise in every published page and a diff that appears whenever a tenant re-crops to the same place.
    """
    text = f"{value + 0.0:.4f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return f"{text}%"


def crop_style_vars(crop: Any, surface: str = "") -> str:
    """The inline custom properties the `.sl-cropped` rule reads, or "" when there is nothing to apply."""
    rect = normalized_crop(crop)
    if not rect:
        return ""
    aspect = crop_aspect(crop, surface)
    return ";".join([
        f"--sl-crop-ar:{aspect:g}",
        f"--sl-crop-w:{_pct(100.0 / rect['w'])}",
        f"--sl-crop-h:{_pct(100.0 / rect['h'])}",
        f"--sl-crop-x:{_pct(-rect['x'] / rect['w'] * 100.0)}",
        f"--sl-crop-y:{_pct(-rect['y'] / rect['h'] * 100.0)}",
    ])

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
_RATIOS: dict[str, float] = {
    key: float(value) for key, value in json.loads(_RATIOS_PATH.read_text())["ratios"].items()
}


def surface_ratio(surface: str, default: float = 1.0) -> float:
    """The width/height a surface renders at. Unknown surfaces are square rather than an error."""
    return _RATIOS.get(str(surface or ""), default)


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


def crop_style_vars(crop: Any, ratio: Any = None) -> str:
    """The inline custom properties the `.sl-cropped` rule reads, or "" when there is nothing to apply."""
    rect = normalized_crop(crop)
    if not rect:
        return ""
    parts = [
        f"--sl-crop-w:{_pct(100.0 / rect['w'])}",
        f"--sl-crop-h:{_pct(100.0 / rect['h'])}",
        f"--sl-crop-x:{_pct(-rect['x'] / rect['w'] * 100.0)}",
        f"--sl-crop-y:{_pct(-rect['y'] / rect['h'] * 100.0)}",
    ]
    try:
        if ratio and float(ratio) > 0:
            parts.insert(0, f"--sl-crop-ar:{float(ratio):g}")
    except (TypeError, ValueError):
        pass
    return ";".join(parts)

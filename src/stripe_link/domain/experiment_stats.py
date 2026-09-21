"""Reading an A/B result honestly: is the gap bigger than the noise, and how much longer at this rate.

Pure, stdlib only. Two rules shape everything here (plans/AB_TESTING.md A3):

* **Nothing gates and nothing auto-pauses.** "Enough evidence" is the tenant's judgement, not a threshold
  the software enforces. These functions describe; the tenant decides.
* **Never imply precision that isn't there.** A verdict is words, an estimate is labelled as an estimate at
  the CURRENT rate, and anything we cannot honestly compute returns None rather than a comforting number.
"""
from typing import Any

import math

# Two-sided z thresholds. Named, because a bare 1.96 in a branch is unreadable six months later.
_Z_LIKELY = 1.96   # ~95%
_Z_CLEAR = 2.58    # ~99%

# Rule-of-thumb sample size per arm for 80% power at 95% two-sided: n ≈ 16·p̄(1−p̄)/δ².
# Deliberately the rule of thumb and not an exact power calculation -- the inputs (a conversion rate
# measured on a few hundred views) carry far more uncertainty than the constant does, so precision here
# would be decoration.
_POWER_CONSTANT = 16


def _rate(conversions: int, views: int) -> float:
    return (conversions / views) if views else 0.0


def z_score(control: dict[str, Any], variant: dict[str, Any]) -> float | None:
    """Two-proportion z for variant vs control, or None when it cannot be computed.

    None rather than 0.0 on purpose: "no evidence either way" and "measured no difference" are different
    statements, and a caller that cannot tell them apart will report the first as the second.
    """
    n1, n2 = int(control.get("views") or 0), int(variant.get("views") or 0)
    if n1 <= 0 or n2 <= 0:
        return None
    c1, c2 = int(control.get("conversions") or 0), int(variant.get("conversions") or 0)
    pooled = (c1 + c2) / (n1 + n2)
    if pooled <= 0 or pooled >= 1:
        return None  # nobody has converted, or everybody has: the test says nothing yet
    standard_error = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if standard_error <= 0:
        return None
    return (_rate(c2, n2) - _rate(c1, n1)) / standard_error


def verdict(z: float | None) -> str:
    """The result in words. `insufficient` is a real answer, not a failure."""
    if z is None:
        return "insufficient"
    magnitude = abs(z)
    if magnitude >= _Z_CLEAR:
        return "clear"
    if magnitude >= _Z_LIKELY:
        return "likely"
    return "too_close"


def views_needed_per_arm(control: dict[str, Any], variant: dict[str, Any]) -> int | None:
    """Roughly how many views EACH arm needs to call a difference this size, or None.

    None when there is no difference to detect yet: with δ = 0 the required sample is infinite, and
    rendering that as a number would tell a tenant their test is nearly done when it has learned nothing.
    """
    n1, n2 = int(control.get("views") or 0), int(variant.get("views") or 0)
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = _rate(int(control.get("conversions") or 0), n1), _rate(int(variant.get("conversions") or 0), n2)
    delta = abs(p2 - p1)
    if delta <= 0:
        return None
    mean = (p1 + p2) / 2
    if mean <= 0 or mean >= 1:
        return None
    return int(math.ceil(_POWER_CONSTANT * mean * (1 - mean) / (delta * delta)))


def days_remaining(views_so_far: int, needed_per_arm: int | None, days_elapsed: float) -> float | None:
    """How much longer AT THE CURRENT RATE, or None when that cannot be said honestly.

    The name is the caveat: this is arithmetic on the rate observed so far, not a forecast. A tenant who
    doubles their traffic tomorrow makes it wrong, and so does one whose campaign ends.
    """
    if needed_per_arm is None or days_elapsed <= 0 or views_so_far <= 0:
        return None
    remaining = needed_per_arm - views_so_far
    if remaining <= 0:
        return 0.0
    per_day = views_so_far / days_elapsed
    if per_day <= 0:
        return None
    return remaining / per_day


def summarize(results: list[dict[str, Any]], control_page_id: str, days_elapsed: float = 0.0):
    """Each non-control arm against the control. Returns a list, one entry per variant.

    Revenue is carried through but never given a verdict: these are proportion tests, and revenue per view
    has a different (much wider) distribution. Claiming significance on it with this machinery would be
    making something up.
    """
    control = next(
        (row for row in results or [] if str(row.get("page_id") or "") == str(control_page_id or "")),
        None,
    )
    if control is None:
        return []
    comparisons = []
    for row in results or []:
        page_id = str(row.get("page_id") or "")
        if not page_id or page_id == str(control_page_id or ""):
            continue
        z = z_score(control, row)
        needed = views_needed_per_arm(control, row)
        control_rate = _rate(int(control.get("conversions") or 0), int(control.get("views") or 0))
        variant_rate = _rate(int(row.get("conversions") or 0), int(row.get("views") or 0))
        comparisons.append({
            "page_id": page_id,
            "verdict": verdict(z),
            "z": z,
            # Relative lift is what a tenant reads; None when the control has no rate to lift FROM, because
            # "infinite improvement over zero" is not a useful thing to show anyone.
            "lift": ((variant_rate - control_rate) / control_rate) if control_rate > 0 else None,
            "views_needed_per_arm": needed,
            "days_remaining": days_remaining(int(row.get("views") or 0), needed, days_elapsed),
        })
    return comparisons

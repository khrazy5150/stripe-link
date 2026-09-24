"""Which SILO this deployment is — the axis that was never modeled (plans/SILO_MODEL.md).

A **silo** is a complete, independent SaaS: its own tables, its own tenants, its own money, differing
from the others only in who uses it. Sandbox is for developers, production for everyone, staging one day
for a few real tenants ahead of a general release.

**It is not `ENVIRONMENT` and it is not `stripe_mode`,** and the confusion between those three words is
the reason this module exists. `ENVIRONMENT` (`dev`/`prod`) is the deployment name AWS knows; `stripe_mode`
(`test`/`live`) is Stripe's own axis and rides on every record already. The silo is what neither of them
says: *which independent copy of Junior Bay does this belong to?* The decoupling split mode from
environment in the data and never gave the silo a name, so every reader has had to infer it from whatever
tables it happened to be pointed at — which is unverifiable, and is the shape of every mode-isolation bug
found on 2026-09-23.
"""

from __future__ import annotations

import os

SANDBOX = "sandbox"
PRODUCTION = "production"

# One definition. Adding a silo is an edit HERE plus its own deployment — never a new webhook endpoint,
# which is the whole point of keeping the Stripe axis as data (plans/SILO_MODEL.md).
KNOWN_SILOS = (SANDBOX, PRODUCTION)

# The deployment names AWS uses, mapped to what they ARE. `dev` is a deployment; `sandbox` is a silo.
_SILO_FOR_ENVIRONMENT = {"dev": SANDBOX, "prod": PRODUCTION}


def normalize_silo(value) -> str:
    """A known silo name, or `""` for anything else.

    Deliberately NOT fail-safe-to-a-default. Both directions of guess are wrong: calling production
    "sandbox" makes a silo foreign to itself, and calling sandbox "production" pollutes real data. An
    unknown value is unknown, and callers omit the stamp rather than invent one — the documented read rule
    (unstamped means sandbox, never production) then applies exactly once, where it is written down.
    """
    name = str(value or "").strip().lower()
    return name if name in KNOWN_SILOS else ""


def current_silo() -> str:
    """This deployment's silo, or `""` when it cannot be established.

    `SILO` is set by the template. The `ENVIRONMENT` fallback exists for the window in which a function is
    running code that knows about silos on a stack deployed before they did — during that window the
    answer is still correct, because today the mapping is exact.
    """
    explicit = normalize_silo(os.environ.get("SILO"))
    if explicit:
        return explicit
    return _SILO_FOR_ENVIRONMENT.get(str(os.environ.get("ENVIRONMENT") or "").strip().lower(), "")

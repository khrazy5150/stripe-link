"""Run ONE page generation per candidate model and compare what came back.

Why this exists: the model registry is two generations behind what the account offers, and the reason is
that choosing a model has always cost a hand-run evaluation (§A.7, 2026-09-27) plus a human reading the
output. So nobody ran it again. This makes "try Sonnet 5.5", "try Nova", "try the cheapest thing" a
command instead of a project.

It measures what §A.7 found actually matters, which is NOT prose quality:

  * `repairs`         -- how many times the schema had to be re-prompted. 0 is the bar; 4 models hit it.
  * `violations`      -- claims the brief did not license, and facts put in the wrong element. This is
                         the one that barred haiku-4.5: cheapest of four, and the only one that invented
                         dosing and an efficacy claim from a brief containing neither.
  * `classification`  -- the model's OWN account of where it put each fact. A price routed to
                         bragging_points shows up here as data rather than as a complaint about a page.
  * cost              -- from the registry's hand-maintained rates, with their confidence attached.

The brief is the §A.7 one on purpose: a supplement, with measurements and a guarantee. It is the shape
that produced every measured failure, so a model that is clean on it has cleared the known traps rather
than an easy case.

NOTHING IS PUBLISHED. This generates, validates and scores in memory. That is the point -- a model can be
tried without a tenant's storefront being the experiment.

    python scripts/compare_models.py                  # dry run: shows what it WOULD call, spends nothing
    python scripts/compare_models.py --run            # the registry's page-capable models
    python scripts/compare_models.py --run sonnet-5-5 nova-pro
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from stripe_link.domain.ai_models import estimate_cost, model as model_entry, profile_id  # noqa: E402

# The §A.7 brief. Measurements a model can over-read into a dose, and a guarantee it can over-read into
# cancellation terms -- both real failures, from real models, on this exact input.
BRIEF = {
    "kind": "physical", "name": "Poliaxis Creatine Gummies",
    "what_it_is": "Creatine monohydrate in a chewable gummy.",
    "audience": "Lifters who dislike powder.",
    "facts": ["5g creatine monohydrate per serving", "60 gummies per tub"],
    "category": "supplement",
    "price": {"unit_amount": 3291, "currency": "usd",
              "pricing_model": "recurring", "recurring_interval": "month"},
    "guarantee": "30-day money-back guarantee",
}


def candidates() -> list[str]:
    """Every registry model NOT barred from page generation. A barred one is barred for a measured
    reason; re-running it is a deliberate act, so name it on the command line."""
    from stripe_link.domain.ai_models import model_names

    return [n for n in model_names()
            if (model_entry(n) or {}).get("page_generation", True) is not False]


def run_one(name: str) -> dict:
    from handlers.ai_generate import _generate

    entry = model_entry(name) or {}
    if not entry:
        return {"model": name, "error": "not in the registry — add it to src/stripe_link/ai_models.json"}
    started = time.time()
    try:
        out = _generate(BRIEF, model=profile_id(name) or name,
                        provider=str(entry.get("provider") or "bedrock"))
    except Exception as exc:  # noqa: BLE001 - a model that cannot answer IS the result
        return {"model": name, "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - started, 1)}

    usage = out.get("usage") or {}
    cost = estimate_cost(name, int(usage.get("input") or 0), int(usage.get("output") or 0))
    residual = out.get("residual_violations") or []
    return {
        "model": name,
        "seconds": round(time.time() - started, 1),
        "repairs": out.get("repairs", 0),
        "sections": len(out.get("sections") or []),
        "violations": len(residual),
        "violation_detail": [f"{v.get('element') or v.get('section')}: {v.get('reason','')[:90]}"
                             for v in residual],
        # Where the model says it put each fact. The price-in-the-wrong-element failure is visible here.
        "routing": [f"{str(c.get('source_fact',''))[:38]} -> {c.get('element','?')}"
                    for c in (out.get("classification") or [])],
        "tokens": f"{usage.get('input', 0)}/{usage.get('output', 0)}",
        "usd": cost.get("usd"),
        "cost_confidence": cost.get("confidence"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="*", help="registry names; default is every page-capable model")
    parser.add_argument("--run", action="store_true", help="actually call Bedrock (spends money)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    names = args.models or candidates()
    if not args.run:
        print("DRY RUN — nothing called, nothing spent.\n")
        print("Would generate one page each for:")
        for n in names:
            entry = model_entry(n) or {}
            print(f"  {n:16} {entry.get('label') or '(NOT IN REGISTRY)':34} "
                  f"profile={profile_id(n) or '—'}")
        print("\nEach call is one page generation — cents, not dollars. Re-run with --run to spend it.")
        print("A model missing from the registry needs an entry in src/stripe_link/ai_models.json first;")
        print("the rates there are hand-maintained because AWS publishes none.")
        return 0

    results = [run_one(n) for n in names]
    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print(f"{'model':16} {'ok':4} {'rep':>4} {'sec':>5} {'viol':>5} {'tokens':>13} {'usd':>8}")
    print("-" * 62)
    for r in results:
        if r.get("error"):
            print(f"{r['model']:16} {'ERR':4} {r.get('error','')[:60]}")
            continue
        usd = r.get("usd")
        print(f"{r['model']:16} {'yes':4} {r['repairs']:>4} {r['seconds']:>5} {r['violations']:>5} "
              f"{r['tokens']:>13} {('$%.4f' % usd) if usd is not None else '—':>8}")

    for r in results:
        if r.get("error") or not (r.get("violation_detail") or r.get("routing")):
            continue
        print(f"\n--- {r['model']}")
        for v in r.get("violation_detail") or []:
            print(f"  VIOLATION  {v}")
        for route in r.get("routing") or []:
            print(f"  routed     {route}")

    worst = [r for r in results if not r.get("error") and r.get("violations")]
    if worst:
        print(f"\n{len(worst)} model(s) left violations after the repair loop. That is the signal that "
              "barred haiku-4.5 — not prose quality.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

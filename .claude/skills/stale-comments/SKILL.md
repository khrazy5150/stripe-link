---
name: stale-comments
description: Audit the codebase for comments that describe an architecture we no longer have, and update them. Use when terminology has been abolished or a subsystem reworked, after a decoupling or rename, or when a comment's reasoning has just misled someone.
---

# Stale comment audit

This codebase records decisions and their reasons in comments, deliberately and at length. That is why it
is navigable — and it is exactly why a comment describing an architecture we no longer have is expensive.
It does not just fail to help; it **argues for the old design**, convincingly, to whoever reads it next.

Two of those cost real time on 2026-10-23: a comment justifying a refusal with "custom-domain serving is
handled by the single production edge Worker" (a per-environment Worker script had existed for months),
and a docstring saying a page is indexable "in production" when it had come to mean live Stripe mode.

## The one rule that matters

**Never rewrite a comment from the code alone when that comment justifies a gate, a refusal, or a
default.**

The "single production edge Worker" comment was factually wrong and its *conclusion was still right* — the
deployed stacks shared one Cloudflare zone, so a dev Site genuinely could not serve a custom domain. The
code did not contain that fact; the CloudFormation parameters did. Reading the setup script, concluding
the comment was stale and deleting the guard produced a live 404 on a real domain.

So, for any load-bearing comment:

1. Check the **deployed** truth, not the repo's capability:
   `aws cloudformation describe-stacks --stack-name jb-stripe-link-stack-{dev,prod} --query "Stacks[0].Parameters"`
   and `aws lambda get-function-configuration --function-name <fn> --query Environment.Variables`.
2. Check `git log -S'<the claim>'` for when and why the line was written.
3. If code and deployment disagree, **the deployment is the current architecture.** See
   `feedback-deployed-config-outranks-code` in memory.

A comment that merely describes mechanics ("this returns X when Y") can be corrected from the code.

## Running the audit

Report first. Never bulk-rewrite.

### Detector 1 — concept drift (the high-yield one)

Finds comments that reason about one axis using another axis's vocabulary. The current live example is
`environment` (dev/prod — which stack) versus `mode` (test/live — Stripe mode); they moved together before
`plans/STRIPE_MODE_DECOUPLING.md` and are independent now.

```bash
python3 - <<'PY'
import re, pathlib
root = pathlib.Path(".")
files = (list(root.glob("src/**/*.py")) + list(root.glob("dashboard/src/**/*.vue"))
         + list(root.glob("dashboard/src/**/*.js")))
# LEFT: the vocabulary suspected of being used as a stand-in. RIGHT: the concern it is standing in for.
LEFT  = re.compile(r"\b(prod|production|dev|sandbox|non-prod|nonprod)\b", re.I)
RIGHT = re.compile(r"\b(live|test[- ]?mode|index|indexed|indexable|noindex|crawl|search engines?|"
                   r"custom domain|real (money|business|tenant|shop|store))\b", re.I)
for src in files:
    for i, line in enumerate(src.read_text(errors="ignore").splitlines(), 1):
        s = line.strip()
        if not (s.startswith(("#", "//", "*", '"""'))):
            continue
        if LEFT.search(s) and RIGHT.search(s):
            print(f"{src}:{i}\n    {s[:150]}")
PY
```

Expect roughly 35–40 hits and expect most to be **correct**: plenty of comments discuss deployment
ownership of modes, which is a genuine deployment concern (`stripe_webhook.py` silo routing, for
instance). Read each one and ask: *is this sentence about which stack runs the code, or about whether the
money is real?* Only the second kind is stale.

Swap LEFT/RIGHT for whatever pair has just been decoupled or renamed.

### Detector 2 — identifiers cited in comments that no longer exist

Precise, low yield, worth running after a refactor. A comment pointing at a function that was renamed
sends the next reader somewhere that does not exist.

```bash
python3 - <<'PY'
import re, pathlib, collections
root = pathlib.Path(".")
files = (list(root.glob("src/**/*.py")) + list(root.glob("dashboard/src/**/*.vue"))
         + list(root.glob("dashboard/src/**/*.js")))
corpus = "\n".join(p.read_text(errors="ignore") for p in files)
cited = collections.defaultdict(list)
for src in files:
    for i, line in enumerate(src.read_text(errors="ignore").splitlines(), 1):
        s = line.strip()
        if not s.startswith(("#", "//", "*")):
            continue
        for name in re.findall(r"`([a-z_][a-z0-9_]{4,})\(?\)?`", s) + re.findall(r"\b([a-z_][a-z0-9_]{6,})\(\)", s):
            cited[name].append(f"{src}:{i}")
for name, where in sorted(cited.items()):
    if re.search(rf"\b(def|function|const|let|var)\s+{re.escape(name)}\b", corpus):
        continue
    if corpus.count(name) > len(where):
        continue
    print(f"{name:34s} {', '.join(where[:3])}")
PY
```

Many hits are document field names or deliberate prose, not code references. Confirm before touching.

### Detector 3 — shipped work still described as future

Weak on its own (few `plans/*.md` carry a parseable `**Status:**` line) but worth a pass after a plan
completes. Grep the plan's own name across `src/` and `dashboard/src/` and read every comment citing it:

```bash
grep -rn "plans/<PLAN>.md" src/ dashboard/src/
```

Then look for "later", "not yet", "Phase N", "once X lands", "deferred", "for now" in those comments and
check each against what now exists.

## Rewriting, once a finding is confirmed

- **Keep the why, correct the fact.** These comments exist to carry reasoning. Replace the stale claim,
  preserve the argument, and keep any dated attribution (`author, 2026-09-13`) — it is provenance.
- **Narrow rather than delete.** If a claim is now true only in a smaller case, say the smaller case. A
  deleted comment loses the reason along with the error.
- **Say what changed when the change is surprising.** The convention here is a parenthetical:
  `(author, 2026-10-23)` or a short "this used to read X, which was the pre-decoupling world" line. Future
  readers need to know a reversal was deliberate.
- **A comment pinned by a test is a contract.** `grep` the claim in `tests/` first — several tests assert
  on comment text or on the code the comment describes (`test_offer_intent_derivation`,
  `test_breadcrumb_chrome`, `test_offerless_composition_parity`). Update both together.
- Run the suite afterwards: `python3 -m pytest tests/ -q`.

## Scope

A whole-codebase pass is expensive and mostly returns correct comments. Prefer:

- the subsystem that just changed (`git diff --name-only <since>`), or
- one detector across `src/` only, or
- the files touched by the rename that prompted this.

Report findings as a ranked list with file:line and the evidence for each, then apply only what the
author approves.

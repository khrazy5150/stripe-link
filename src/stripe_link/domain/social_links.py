"""Social profile links (`Site.organization.same_as`) and their verification state.

Two rules hold this together, and both exist because a social link asserted on our markup is an
impersonation vector:

1. **`verification` is SERVER-owned.** A client may send URLs; it may never send verification state.
   `preserve_verification` is the boundary that enforces it -- see the docstring there for why this is a
   merge and not a validation rule.
2. **A URL change invalidates the proof.** Verification says "we fetched THIS url and found our page on
   it". Point the entry somewhere else and the finding no longer applies, so the state resets rather
   than following the entry.

Verification method is a URL-presence check, not `rel="me"`: measured 2026-09-09, `rel="me"` is emitted
by ZERO of these hosts. See plans/SOCIAL_MEDIA_PAGES.md §7a-i.
"""
from typing import Any


# sameAs destinations are whitelisted to major social/authority hosts (TENANT_PROFILE_REQUIREMENTS §4.4):
# an arbitrary URL asserted as the tenant's identity on our domain's markup is an impersonation/abuse vector.
SAME_AS_HOSTS = frozenset({
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com",
    "tiktok.com", "pinterest.com", "threads.net", "github.com", "crunchbase.com", "bbb.org",
    "wikidata.org", "wikipedia.org", "yelp.com", "trustpilot.com",
})

# The cap is on the IDENTITY claim, not on what a page may display. A link-in-bio page shows more links
# than this; only these six can enter sameAs.
SAME_AS_MAX = 6

UNVERIFIED = "unverified"
PENDING = "pending"
VERIFIED = "verified"
FAILED = "failed"
UNVERIFIABLE = "unverifiable"
VERIFICATION_STATES = frozenset({UNVERIFIED, PENDING, VERIFIED, FAILED, UNVERIFIABLE})

# Measured from a Lambda on 2026-09-09: both serve a login wall / JS shell to any unauthenticated
# fetch, so no amount of parsing recovers the profile's links. They are not "failures" -- there is
# nothing to try -- and the UI must say so rather than leaving them pending forever. Proof for these
# arrives later via OAuth (an aggregator first), where authenticating with the account IS the proof.
UNVERIFIABLE_HOSTS = frozenset({"instagram.com", "tiktok.com"})

# Anyone can edit these, so finding our URL there proves nothing about who controls the subject -- it is
# the impersonation vector itself. A tenant could add their own URL to a brand's article and claim
# sameAs with that brand. Never auto-verify them.
SELF_EDITABLE_HOSTS = frozenset({"wikipedia.org", "wikidata.org"})

# We identify ourselves rather than impersonating a browser. This is not only the honest choice, it is
# the one that WORKS: measured 2026-09-09, Facebook returned 400 to a Chrome UA and 200 to this one,
# and Threads returned an empty shell to Chrome and the real page to this one.
VERIFIER_USER_AGENT = "JuniorBayLinkVerifier/1.0 (+https://juniorbay.com/verify)"


def same_as_host(url: Any) -> str:
    """The registrable-ish host of a profile URL, lowercased and stripped of scheme/www/port/path."""
    text = str(url or "").strip().lower()
    for scheme in ("https://", "http://"):
        if text.startswith(scheme):
            text = text[len(scheme):]
            break
    host = text.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_allowed_host(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in SAME_AS_HOSTS)


def host_matches(host: str, group: frozenset) -> bool:
    return any(host == h or host.endswith("." + h) for h in group)


def is_checkable(url: Any) -> bool:
    """Can a fetch decide this entry at all?

    False for the two hosts that serve nothing to an unauthenticated fetch, and for the hosts anyone
    can edit -- where a positive result would be meaningless rather than merely unavailable.
    """
    host = same_as_host(url)
    if not is_allowed_host(host):
        return False
    return not host_matches(host, UNVERIFIABLE_HOSTS) and not host_matches(host, SELF_EDITABLE_HOSTS)


def url_key(url: Any) -> str:
    """Identity of an entry for merge purposes: scheme and www ignored, trailing slash ignored.

    Deliberately NOT lowercased past the host -- `github.com/Foo` and `github.com/foo` may be different
    people on some hosts, and treating them as one would carry a proof across a URL it was never
    granted for.
    """
    text = str(url or "").strip()
    lowered = text.lower()
    for scheme in ("https://", "http://"):
        if lowered.startswith(scheme):
            text = text[len(scheme):]
            break
    if text[:4].lower() == "www.":
        text = text[4:]
    host, _, rest = text.partition("/")
    return f"{host.lower()}/{rest}".rstrip("/")


def is_verified(entry: Any) -> bool:
    """The ONE place that decides whether a same_as entry is verified.

    Both the JSON-LD builder and the seller-profile renderer previously spelled this out inline as
    `entry.get("verified") is True`, in two places that had to agree with nothing forcing them to.
    """
    if not isinstance(entry, dict):
        return False
    verification = entry.get("verification")
    return isinstance(verification, dict) and verification.get("state") == VERIFIED


def verified_urls(organization: Any) -> list[str]:
    """Verified profile URLs, capped -- what may enter sameAs."""
    if not isinstance(organization, dict):
        return []
    return [str(e.get("url")).strip() for e in (organization.get("same_as") or [])
            if is_verified(e) and str(e.get("url") or "").strip()][:SAME_AS_MAX]


def display_entries(organization: Any) -> list[dict]:
    """Every well-formed entry, verified or not -- what may be DISPLAYED.

    Display is not gated on verification. Verification gates sameAs only, which is why the two
    platforms that dominate link-in-bio traffic are unaffected by being unverifiable. Unverified links
    still render, with rel="nofollow ugc noopener".
    """
    if not isinstance(organization, dict):
        return []
    return [e for e in (organization.get("same_as") or [])
            if isinstance(e, dict) and str(e.get("url") or "").strip()]


def initial_verification(url: Any) -> dict:
    """The state a newly-entered link starts in."""
    if not is_checkable(url):
        return {"state": UNVERIFIABLE, "method": None, "checked_at": None}
    return {"state": UNVERIFIED, "method": None, "checked_at": None}


def preserve_verification(incoming_org: Any, existing_org: Any) -> list[dict]:
    """Strip client-supplied verification state and restore what the SERVER stored.

    This is a merge at the write boundary rather than a validation rule, and deliberately so. The
    document is re-validated on the way OUT as well (publish re-runs validate_site over the stored
    doc), so a validator that rejected the `verification` key would reject our own writes. The same
    reasoning produced `restore_redacted_fields` for credentials; this is that pattern applied to a
    field whose forgery costs identity rather than money.

    Entries are matched by `url_key`, so re-pointing a link drops its proof: the check said "we found
    our page ON THIS URL", and that finding does not travel.
    """
    stored: dict[str, Any] = {}
    for entry in (existing_org or {}).get("same_as") or []:
        if isinstance(entry, dict) and str(entry.get("url") or "").strip():
            stored[url_key(entry["url"])] = entry.get("verification")

    merged: list[dict] = []
    for entry in (incoming_org or {}).get("same_as") or []:
        if not isinstance(entry, dict):
            merged.append(entry)     # malformed -- leave it for validation to reject with a real message
            continue
        # `verified` is the pre-2026-09-09 boolean. Nothing ever set it, so there is no data to migrate;
        # it is dropped here so it cannot be reintroduced by a client that still sends it.
        clean = {k: v for k, v in entry.items() if k not in ("verification", "verified")}
        url = str(entry.get("url") or "").strip()
        prior = stored.get(url_key(url)) if url else None
        clean["verification"] = dict(prior) if isinstance(prior, dict) else initial_verification(url)
        merged.append(clean)
    return merged

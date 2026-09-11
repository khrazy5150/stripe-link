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

from stripe_link.domain.network_icons import NETWORK_ICON_PATHS as _GENERATED_ICON_PATHS
from stripe_link.domain.network_icons_manual import MANUAL_ICON_PATHS

# The generated set, with hand-drawn marks layered over it. Manual wins: it exists precisely for the networks
# upstream cannot supply, and a later regeneration must not be able to take one away.
NETWORK_ICON_PATHS = {**_GENERATED_ICON_PATHS, **MANUAL_ICON_PATHS}


# sameAs destinations are whitelisted to major social/authority hosts (TENANT_PROFILE_REQUIREMENTS §4.4):
# an arbitrary URL asserted as the tenant's identity on our domain's markup is an impersonation/abuse vector.
SAME_AS_HOSTS = frozenset({
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com",
    "tiktok.com", "pinterest.com", "threads.net", "github.com", "crunchbase.com", "bbb.org",
    "wikidata.org", "wikipedia.org", "yelp.com", "trustpilot.com",
})

# Reddit is deliberately ABSENT, and the omission is load-bearing rather than an oversight. sameAs asserts
# "this entity IS that profile"; a subreddit is a community the business does not own, so the claim would be
# false, and a /user/ account is a person. Its actual value is citation, not identity, which belongs with the
# attention/campaign work. See plans/TODO.md, "Reddit is its own study". Do not add it here as a step
# toward that.

# Display names for every allowlisted host. Complete by construction -- a host without a label used to
# fall back to its bare domain, so a Better Business Bureau link rendered as "bbb.org". The parity test
# asserts every host has one, on both sides.
NETWORK_LABELS = {
    "bbb.org": "Better Business Bureau",
    "crunchbase.com": "Crunchbase",
    "facebook.com": "Facebook",
    "github.com": "GitHub",
    "instagram.com": "Instagram",
    "linkedin.com": "LinkedIn",
    "pinterest.com": "Pinterest",
    "threads.net": "Threads",
    "tiktok.com": "TikTok",
    "trustpilot.com": "Trustpilot",
    "twitter.com": "Twitter",
    "wikidata.org": "Wikidata",
    "wikipedia.org": "Wikipedia",
    "x.com": "X",
    "yelp.com": "Yelp",
    "youtube.com": "YouTube",
}

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


def _network_lookup(url: Any, table: dict[str, Any]) -> Any:
    """Match a profile URL's host against a network table, subdomains included.

    Shared by the label and the icon so the two can never disagree about which network a URL belongs to --
    a link showing the Facebook mark labelled "Instagram" would be worse than either alone.
    """
    host = same_as_host(url)
    for domain, value in table.items():
        if host == domain or host.endswith("." + domain):
            return value
    return None


def network_label(url: Any) -> str:
    """The human name of the network a profile URL belongs to."""
    return _network_lookup(url, NETWORK_LABELS) or same_as_host(url) or "Profile"


def network_icon_path(url: Any) -> str:
    """The 24x24 brand-glyph path for this network, or "" when there is none.

    Empty is a normal answer, not a failure: LinkedIn and Twitter were removed from the upstream icon set at
    their owners' request, the BBB was never in it, and a tenant may paste any host at all. The renderer
    falls back to the worded label, which stays readable and stays honest.
    """
    return _network_lookup(url, NETWORK_ICON_PATHS) or ""


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


def section_own_links(section: Any) -> list[dict]:
    """The profile links typed into a social_links SECTION, as opposed to inherited from the Site.

    Deliberately NOT filtered through SAME_AS_HOSTS. The allowlist exists to protect `sameAs`, which is a
    machine-readable claim about who the tenant IS and therefore an impersonation vector. These links make no
    such claim -- they are things a visitor can tap -- so a creator's Substack, Patreon or OnlyFans belongs
    here even though none of them could ever be a sameAs. That is the whole point of the split: the page-local
    list is FREER precisely because it asserts nothing.

    (What may be LINKED from a page served on shared platform infrastructure is a different question again,
    answered by linkable_on_platform_host at render time. That one is about the URL bar, not identity.)
    """
    if not isinstance(section, dict):
        return []
    return [{"url": str((item or {}).get("url") or "").strip()}
            for item in (section.get("items") or [])
            if isinstance(item, dict) and str((item or {}).get("url") or "").strip()]


def section_link_entries(section: Any, organization: Any) -> list[dict]:
    """Which profiles a social_links section renders: its OWN if it has any, else the Site's.

    The same override-or-inherit rule the page avatar already uses, and for the same reason -- a business
    fills its profiles in once on the Business Profile and every page picks them up, while a single page can
    still say something different without that becoming the Site's identity.

    Overriding is an explicit act: the section starts with no items, so a tenant who never touches it
    inherits, which is the behaviour every page had before this existed. Attachment is deliberately NOT part
    of the rule -- making it so would mean a page silently changing what it displays when it joins a Site,
    which is exactly the kind of invisible dependency that made this element confusing in the first place.
    """
    own = section_own_links(section)
    return own if own else display_entries(organization)


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

# ---------------------------------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------------------------------

MAX_FETCH_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15


class ProfileFetchError(Exception):
    """The profile could not be read. Distinct from 'read it, no backlink' -- see verify_entry."""


def site_backlink_host(site: Any) -> str:
    """The host a tenant is asked to link back to.

    The custom domain once it is verified, otherwise the platform hostname -- mirroring siteStoreUrl in
    Sites.vue, because the tenant will paste whatever the dashboard shows them.
    """
    hosting = (site or {}).get("hosting") or {}
    custom = str(hosting.get("custom_domain") or "").strip()
    verified = bool((hosting.get("verification") or {}).get("verified"))
    if custom and verified:
        return custom.lower()
    return str(hosting.get("platform_hostname") or "").strip().lower()


def backlink_present(html: str, host: str) -> bool:
    """Is `host` linked from this page?

    Checked raw AND percent-decoded, because platforms route outbound links through redirectors that
    encode the destination -- YouTube's /redirect?q=, Facebook's l.php?u=. A raw-only match would report
    "link back not found" for a link that is plainly on the page.
    """
    if not host:
        return False
    needle = host.lower()
    body = (html or "").lower()
    if needle in body:
        return True
    try:
        from urllib.parse import unquote
        return needle in unquote(body)
    except Exception:
        return False


def fetch_profile(url: str) -> str:
    """GET a profile page as ourselves.

    We identify honestly rather than impersonating a browser. Measured 2026-09-09, that is also the
    choice that WORKS: Facebook returned 400 to a Chrome UA and 200 to this one.

    Redirects are re-checked against the allowlist. Starting from an allowlisted host is not enough on
    its own -- a redirect is an attacker-influenced hop, and following one anywhere would turn this into
    a fetch-anything proxy running inside our account.
    """
    import urllib.error
    import urllib.request

    class _AllowlistedRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not is_allowed_host(same_as_host(newurl)):
                raise ProfileFetchError(f"redirect to a host we do not fetch: {same_as_host(newurl)}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    if not is_checkable(url):
        raise ProfileFetchError("this profile cannot be checked automatically")
    opener = urllib.request.build_opener(_AllowlistedRedirects)
    request = urllib.request.Request(url, headers={
        "User-Agent": VERIFIER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            return response.read(MAX_FETCH_BYTES).decode("utf-8", "replace")
    except ProfileFetchError:
        raise
    except urllib.error.HTTPError as exc:
        # A 404 is a real answer -- the profile is not there -- so let the caller record `failed`
        # rather than an error the tenant can do nothing about.
        if exc.code == 404:
            return ""
        raise ProfileFetchError(f"the profile returned HTTP {exc.code}") from exc
    except Exception as exc:
        raise ProfileFetchError(str(exc) or type(exc).__name__) from exc


def verify_entry(entry: dict, backlink_host: str, now: int, fetcher=fetch_profile) -> dict:
    """The verification state for one entry, after actually looking.

    `fetcher` is injected so the decision logic can be tested without the network -- the logic is what
    carries the security weight, and it should not be the part that only runs against live Instagram.
    """
    url = str((entry or {}).get("url") or "").strip()
    if not is_checkable(url):
        return {"state": UNVERIFIABLE, "method": None, "checked_at": now}
    try:
        html = fetcher(url)
    except ProfileFetchError as exc:
        # Could not read it. NOT `failed`: failed means "we looked and the link is not there", which is
        # a statement about the tenant's profile. Conflating the two would tell a tenant to fix
        # something that is already correct.
        return {"state": UNVERIFIED, "method": "url_presence", "checked_at": now,
                "detail": str(exc)[:200]}
    if backlink_present(html, backlink_host):
        return {"state": VERIFIED, "method": "url_presence", "checked_at": now}
    return {"state": FAILED, "method": "url_presence", "checked_at": now}

# ---------------------------------------------------------------------------------------------------
# link_cards — arbitrary EXTERNAL destinations (plans/SOCIAL_MEDIA_PAGES.md §8a)
# ---------------------------------------------------------------------------------------------------

# Which hosts may be LINKED from a page served on platform infrastructure.
#
# The reason is the URL bar, not SEO. `noindex` protects our search reputation; it does nothing about a
# human tapping a phishing link on scammer.jbay.uk, which is a browser-blocklist and registrar-abuse
# problem for OUR domain and every tenant sharing it. On the tenant's own custom domain the reputation at
# stake is theirs, so any destination is allowed there.
#
# Deliberately conservative to start: the same identity hosts, nothing more. A creator page wants Amazon,
# Etsy, Substack, Patreon and a hundred others, so this list is NOT the long-term answer -- but the safe
# direction to be wrong in is "too few links work on the free host", not "we shipped an open redirect
# surface on a shared domain". Widening it is a P3 decision that should come with an abuse story.
PLATFORM_LINKABLE_HOSTS = SAME_AS_HOSTS


def linkable_on_platform_host(url: Any) -> bool:
    return host_matches(same_as_host(url), PLATFORM_LINKABLE_HOSTS)

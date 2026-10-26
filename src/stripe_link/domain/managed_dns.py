"""Taking over a tenant's DNS zone without taking down their email (plans/MANAGED_DNS.md).

A tenant on Route 53 or GoDaddy cannot point a root domain at us at all, and the workaround — connect
`www`, then build a certificate, a distribution, a function and an alias record to redirect the root — is
a lot to ask. Moving the zone to Cloudflare removes the limit outright: the apex becomes a proxied record
in a zone we control, flattening is automatic, and Universal SSL covers it.

The price is that we become authoritative for everything else the domain does, and the part of
"everything else" that matters is MAIL. A zone that goes live missing an MX record stops a business
receiving email, and nobody will connect that to a button they clicked on the Sites screen.

**Cloudflare's import scan is best-effort and says so** — their docs name email records and non-default
DKIM selectors as the usual misses, because those cannot be enumerated without a zone transfer. So this
module does not display the scan and ask for a nod. It resolves the domain's mail records independently
and COMPARES, and a discrepancy blocks the nameserver change. Same rule the domain health sweep is built
on: stored state and served reality are allowed to drift, so something has to compare them.

Pure decisions only. The caller does the DNS lookups and the Cloudflare calls; everything here is a
function of what it read, so the rules are testable without either.
"""

from __future__ import annotations

from typing import Any, Iterable

SCHEMA_VERSION = "2026-05-29"

# What a record is FOR, which is what decides how loudly its absence is reported. The categories are
# deliberately coarse: a tenant reviewing this screen cannot evaluate an MX hostname, but they can
# answer "do you send email from this domain".
MAIL = "mail"
SERVING = "serving"
VERIFICATION = "verification"
OTHER = "other"

# Mail hosts we can name. Recognising the provider is the difference between a review screen that works
# and one that gets clicked through: "we found your Google Workspace mail" is a sentence a tenant can
# check, and five rows of `aspmx.l.google.com` is not.
_MAIL_PROVIDERS = (
    ("Google Workspace", ("aspmx.l.google.com", "googlemail.com", "smtp.google.com")),
    ("Microsoft 365", ("mail.protection.outlook.com", "outlook.com")),
    ("Zoho Mail", ("zoho.com", "zoho.eu")),
    ("Proton Mail", ("protonmail.ch", "proton.me")),
    ("Fastmail", ("messagingengine.com",)),
    ("iCloud Mail", ("mail.icloud.com",)),
    ("Namecheap Private Email", ("privateemail.com",)),
    ("Amazon WorkMail", ("awsapps.com",)),
    ("Zoho/Other", ()),
)


def _host(value: str) -> str:
    """An MX value is `<priority> <host>`; a bare host is accepted too."""
    parts = str(value or "").strip().rstrip(".").split()
    return (parts[-1] if parts else "").lower()


def mail_provider(mx_values: Iterable[str]) -> str:
    """Whose mail this is, named, or "" when we do not recognise it.

    Not recognising it is not a problem — the tenant still sees the records and is asked the same
    question. It only means we cannot phrase it in their words.
    """
    hosts = [_host(v) for v in mx_values or [] if _host(v)]
    for name, markers in _MAIL_PROVIDERS:
        if markers and any(marker in host for host in hosts for marker in markers):
            return name
    return ""


def classify_record(record: dict[str, Any]) -> str:
    """What this record is for. Mail is the category that gates; the rest are informational."""
    record_type = str(record.get("type") or "").strip().upper()
    name = str(record.get("name") or "").strip().lower()
    content = str(record.get("content") or record.get("value") or "")
    if record_type == "MX":
        return MAIL
    if record_type == "TXT":
        lowered = content.lower()
        if "v=spf1" in lowered or name.startswith("_dmarc") or "._domainkey" in name:
            return MAIL
        # Ownership proofs for Google, Microsoft, Facebook and friends. Harmless to lose, annoying to
        # re-earn, and worth naming separately so they are not mistaken for mail delivery.
        if any(marker in lowered for marker in ("site-verification", "verify", "verification")):
            return VERIFICATION
        return OTHER
    if record_type in ("CNAME", "A", "AAAA") and ("._domainkey" in name or name.startswith("autodiscover")
                                                  or name.startswith("mail.")):
        return MAIL
    if record_type in ("A", "AAAA", "CNAME", "ALIAS"):
        return SERVING
    return OTHER


def _mail_shape(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The mail facts, reduced to what a comparison can be made on."""
    mx, spf, dmarc, dkim = [], False, False, set()
    for record in records or []:
        record_type = str(record.get("type") or "").upper()
        name = str(record.get("name") or "").lower()
        content = str(record.get("content") or record.get("value") or "")
        if record_type == "MX":
            mx.append(_host(content))
        elif record_type == "TXT":
            if "v=spf1" in content.lower():
                spf = True
            if name.startswith("_dmarc"):
                dmarc = True
        if "._domainkey" in name:
            dkim.add(name.split("._domainkey")[0].lstrip("."))
    return {"mx": sorted(h for h in mx if h), "spf": spf, "dmarc": dmarc, "dkim": sorted(dkim)}


def mail_discrepancies(imported: Iterable[dict[str, Any]],
                       observed: Iterable[dict[str, Any]]) -> list[str]:
    """What live DNS has that the import did not pick up.

    `observed` is what the caller resolved directly from the domain's current nameservers; `imported` is
    what Cloudflare's scan produced. ONLY the direction that loses mail is reported: a record the scan
    found and the live lookup missed is a transient resolver failure or a record mid-change, and blocking
    on it would stop tenants for no reason. A record that is live and NOT imported is the one that goes
    dark at cutover.
    """
    was, now = _mail_shape(imported), _mail_shape(observed)
    missing: list[str] = []
    for host in now["mx"]:
        if host not in was["mx"]:
            missing.append(f"MX {host}")
    if now["spf"] and not was["spf"]:
        missing.append("SPF record")
    if now["dmarc"] and not was["dmarc"]:
        missing.append("DMARC record")
    for selector in now["dkim"]:
        if selector not in was["dkim"]:
            missing.append(f"DKIM key {selector}")
    return missing


def review(imported: Iterable[dict[str, Any]], observed: Iterable[dict[str, Any]], *,
           observed_complete: bool) -> dict[str, Any]:
    """The gate. Returns what to show, and whether the nameserver change may be offered at all.

    `blocked` is not advisory. A missing mail record found BEFORE the switch is a non-event — add it and
    carry on. Found after, it is the tenant's business email, and the repair takes as long as DNS takes
    to propagate twice.

    **`observed_complete` has no default, on purpose.** An empty `observed` means one of two opposite
    things — we asked and this domain genuinely has no mail, or we could not ask — and only the caller
    knows which. Inferring "no mail" from silence is how our own failed lookup becomes a tenant's outage,
    and it is the same mistake the health sweep refuses to make when Cloudflare is unreachable. Requiring
    the flag means the safe-looking answer cannot be reached by forgetting something.
    """
    imported = list(imported or [])
    observed = list(observed or [])
    missing = mail_discrepancies(imported, observed) if observed_complete else []
    shape = _mail_shape(imported)
    live = _mail_shape(observed)
    buckets: dict[str, list[dict[str, Any]]] = {MAIL: [], SERVING: [], VERIFICATION: [], OTHER: []}
    for record in imported:
        buckets[classify_record(record)].append(record)

    # Reasons to stop that are not "a specific record is missing". Each is a case where the comparison
    # itself cannot be trusted, which is worse than a known gap: a known gap can be shown and fixed.
    contradictions: list[str] = []
    if not observed_complete:
        contradictions.append(
            "We could not read this domain's live mail records just now, so there is nothing to check "
            "the import against. Try again in a moment."
        )
    elif live["spf"] and not live["mx"]:
        # A domain publishing SPF is a domain that sends mail. Finding one with no MX anywhere is not a
        # mail-less domain, it is an incomplete answer -- and it is exactly the shape a partial lookup
        # takes, because SPF is one TXT at the apex while MX enumeration is what fails.
        contradictions.append(
            "This domain publishes an SPF record but no MX was found. Mail is almost certainly set up "
            "here and the record list is incomplete."
        )

    has_mail = bool(live["mx"]) or bool(shape["mx"])
    provider = mail_provider(live["mx"] or shape["mx"])
    if contradictions:
        prompt = contradictions[0]
    elif provider:
        prompt = (f"We found {len(imported)} DNS records. Mail is handled by {provider}. "
                  "Anything missing from this list will stop working when you change nameservers.")
    elif has_mail:
        prompt = (f"We found {len(imported)} DNS records, including mail. "
                  "Anything missing from this list will stop working when you change nameservers.")
    else:
        # Not an error, and not a warning dressed as one: plenty of domains are web-only, or keep mail on
        # a different name entirely. It is a question only the tenant can answer, so ask it plainly once.
        prompt = (f"We found {len(imported)} DNS records and no mail records at all. That is normal for "
                  "a domain that does not receive email — but if yours does, stop here and tell us, "
                  "because moving the nameservers would take it offline.")
    return {
        "records": buckets,
        "mail": {
            "present": has_mail,
            "provider": provider,
            "mx_count": len(shape["mx"]),
            "spf": shape["spf"],
            "dmarc": shape["dmarc"],
            "dkim": shape["dkim"],
        },
        "missing": missing,
        "contradictions": contradictions,
        "blocked": bool(missing) or bool(contradictions),
        "confirm_prompt": prompt,
    }


def serving_records(domain: str, placeholder_ip: str = "192.0.2.1") -> list[dict[str, Any]]:
    """The records WE add once the zone is ours: the apex and www, both proxied.

    The address is a placeholder on purpose. Requests never reach it — the Worker route on this zone
    answers first and reverse-proxies to the resolved artifact — but Cloudflare requires a record to
    proxy, and 192.0.2.1 is RFC 5737 TEST-NET-1, reserved for documentation and guaranteed to route
    nowhere. A real origin here would be a second place the serving path is configured, and the one that
    silently takes over if the Worker route is ever missing.
    """
    apex = str(domain or "").strip().lower().rstrip(".")
    if not apex or "." not in apex:
        return []
    return [
        {"type": "A", "name": apex, "content": placeholder_ip, "proxied": True},
        {"type": "A", "name": f"www.{apex}", "content": placeholder_ip, "proxied": True},
    ]


def managed_zone_record(tenant_id: str, domain: str, zone: dict[str, Any], now: int) -> dict[str, Any]:
    """The stored record, which lives beside the custom-domain index and NOT on the Site.

    A Site's `domain_provisioning` describes its claim on a hostname and is discarded when the tenant
    disconnects. A zone is not that: it stays authoritative for the whole domain, mail included, until
    the tenant moves their nameservers away. If it lived on the Site, disconnecting would orphan a zone
    that is still answering for someone's business, with nothing in our data pointing at it.
    """
    name = str(domain or "").strip().lower().rstrip(".")
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "managed_zone",
        "tenant_id": str(tenant_id or ""),
        "domain": name,
        "zone_id": str(zone.get("id") or ""),
        "name_servers": [str(ns).lower() for ns in (zone.get("name_servers") or [])],
        "original_name_servers": [str(ns).lower() for ns in (zone.get("original_name_servers") or [])],
        "status": zone_state(zone),
        "created_at": int(now),
    }


def zone_state(zone: dict[str, Any]) -> str:
    """Cloudflare's word for where the zone is: `pending` until the nameservers are changed, `active`
    once it sees them, `moved` / `deactivated` if it stops. Passed through rather than reinterpreted —
    the same reason the health sweep asks Cloudflare instead of re-deriving."""
    return str((zone or {}).get("status") or "unknown").strip().lower()


def provision(*, tenant_id: str, domain: str, now: int, create_zone_fn, list_records_fn,
              observe_fn, repository) -> dict[str, Any]:
    """Create the zone, read what the import found, compare it with live DNS, and record the zone.

    **The zone is created before the review can run, and that is safe.** Cloudflare's import scan only
    happens as part of zone creation, so there is no way to see what it found first. A created zone
    changes nothing on the internet: the tenant's nameservers still point at their old provider and will
    until they act. What the review gates is the INSTRUCTIONS -- a blocked review simply never shows the
    nameservers, so the switch that would matter cannot happen.

    **The record is written even when the review blocks.** The zone exists on our account from this
    moment, and a zone nobody is tracking is the thing we are trying never to have. Writing it is also
    what makes the next step possible in either direction: retry the comparison, or abandon and delete.

    `observe_fn(domain)` returns `(records, complete)` -- the caller's independent lookup and whether it
    actually succeeded. The flag is passed straight through to `review`, which requires it, because
    "found no mail" and "could not ask" are opposite answers that both arrive as an empty list.
    """
    zone = create_zone_fn(domain)
    zone_id = str(zone.get("id") or "")
    imported = list(list_records_fn(zone_id) or [])
    observed, observed_complete = observe_fn(domain)
    summary = review(imported, observed, observed_complete=bool(observed_complete))
    record = managed_zone_record(tenant_id, domain, zone, now)
    record["review"] = {"blocked": summary["blocked"], "missing": summary["missing"],
                        "checked_at": int(now)}
    repository.put(record)
    return {
        "zone": record,
        "review": summary,
        # Withheld until the comparison is clean. These four lines are the only irreversible thing in the
        # flow -- once they are followed, the domain answers from here and the old provider stops.
        "name_servers": [] if summary["blocked"] else record["name_servers"],
    }


def zone_export(records: Iterable[dict[str, Any]], domain: str) -> str:
    """Every record as a zone file the tenant can hand to any other provider.

    Ships WITH onboarding, not after it. A tenant who wants to leave must be able to take their DNS with
    them, and an exit built last is an exit that exists in a plan and not in the product.
    """
    lines = [f"; {domain} — exported from Junior Bay managed DNS", "; one record per line, BIND format"]
    for record in records or []:
        name = str(record.get("name") or "").rstrip(".")
        record_type = str(record.get("type") or "").upper()
        content = str(record.get("content") or record.get("value") or "")
        ttl = int(record.get("ttl") or 300) or 300
        if not name or not record_type or not content:
            continue
        value = content
        if record_type == "MX":
            # Cloudflare returns MX as content=host with priority alongside; a zone file carries both in
            # one field. Both shapes reach this function, and emitting "1 1 aspmx..." for the second is
            # the kind of corruption that delivers mail to whichever host happens to sort first. `_host`
            # already tolerates both, so the exporter uses it rather than keeping a second opinion.
            priority = record.get("priority")
            head = str(content).strip().split()
            if priority is None and len(head) > 1 and head[0].isdigit():
                priority = int(head[0])
            value = f"{priority if priority is not None else 10} {_host(content)}"
        lines.append(f"{name}.\t{ttl}\tIN\t{record_type}\t{value}")
    return "\n".join(lines) + "\n"

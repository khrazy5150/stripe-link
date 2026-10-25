/**
 * Turning the DNS records the server computed into instructions a tenant can actually follow at THEIR
 * provider (plans/SITE_OBJECT.md 2.6b).
 *
 * The server emits one row per record, each named by its fully-qualified hostname -- which is correct, and
 * is not what any provider's form asks for. Two differences cost a real tenant a failed connect on
 * 2026-10-23, the first day apex domains were live:
 *
 *   1. ROUTE 53 HAS NO `@`. Every other provider here uses `@` to mean the zone apex; Route 53 wants the
 *      Name field LEFT BLANK, and typing `@` creates a record literally called `@.example.com` -- which
 *      resolves, looks created, and serves nothing. That is exactly what happened.
 *   2. TWO A ROWS ARE ONE RECORD. An apex gets two addresses, and DNS holds them as one record set with
 *      two values. Listing them as two steps invites "create record", then "create record" again, which
 *      Route 53 rejects with "a record with the specified name already exists" -- a correct refusal that
 *      reads like a broken instruction.
 *
 * Extracted from Sites.vue so both rules are testable without mounting a component, and because deciding
 * what a provider's form needs is not presentation.
 */

export const DNS_PROVIDERS = [
  // `apexName` is what this provider's Name field wants for the zone apex. Empty string means LEAVE BLANK
  // and is deliberately distinct from undefined, which means "this provider takes full names".
  { id: "route53", label: "AWS Route 53", fqdn: false, apexName: "" },
  { id: "cloudflare", label: "Cloudflare", fqdn: false, apexName: "@" },
  { id: "godaddy", label: "GoDaddy", fqdn: false, apexName: "@" },
  { id: "namecheap", label: "Namecheap", fqdn: false, apexName: "@" },
  { id: "cpanel", label: "cPanel", fqdn: true },
  { id: "other", label: "Other / full name", fqdn: true },
];

/**
 * Whose nameservers a domain is on, read from the domain itself.
 *
 * The provider picker is a manual `<select>` that defaults to Route 53, so a tenant who never touches it
 * reads Route 53 advice whatever their DNS actually is -- and now that the advice DIFFERS in kind
 * ("add an ALIAS" vs "you cannot do this at all"), a wrong default is worse than no advice. The
 * nameservers say the answer outright, so ask them.
 *
 * Patterns are matched against the NS hostnames. Only providers whose advice we actually carry are
 * listed; anything else falls through to `other`, which gives the generic apex instruction.
 */
const NS_PATTERNS = [
  ["route53", /(^|\.)awsdns-\d+\.(com|net|org|co\.uk)\.?$/i],
  ["cloudflare", /(^|\.)ns\.cloudflare\.com\.?$/i],
  ["godaddy", /(^|\.)domaincontrol\.com\.?$/i],
  ["namecheap", /(^|\.)registrar-servers\.com\.?$/i],
];

/** Providers that CANNOT point a root domain at an external host, verified against their documentation
 *  on 2026-10-25 rather than guessed: Route 53's ALIAS targets only AWS resources, and GoDaddy has no
 *  ALIAS or ANAME at all. Everything else is treated as capable, which is true of Cloudflare
 *  (flattening), Namecheap (ALIAS on BasicDNS/FreeDNS/PremiumDNS), DNSimple, DNS Made Easy, NS1 and
 *  Porkbun — and a wrong guess in that direction costs a tenant nothing, while the reverse told one to
 *  abandon their root domain. */
const APEX_INCAPABLE = new Set(["route53", "godaddy"]);

export function detectProvider(nameservers) {
  for (const ns of nameservers || []) {
    const host = String(ns || "").trim().toLowerCase();
    for (const [id, pattern] of NS_PATTERNS) {
      if (pattern.test(host)) return id;
    }
  }
  return "";
}

/** The domain's NS records, over DNS-over-HTTPS. Guidance only: a failure leaves the manual picker
 *  exactly as it was, so the connect flow never depends on this answering. */
export async function lookupNameservers(domain, { fetchFn = fetch } = {}) {
  const name = String(domain || "").trim().replace(/\.$/, "");
  if (!name || !name.includes(".")) return [];
  try {
    const response = await fetchFn(
      `https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(name)}&type=NS`,
      { headers: { Accept: "application/dns-json" } },
    );
    if (!response.ok) return [];
    const body = await response.json();
    return (body.Answer || []).filter((a) => a.type === 2).map((a) => String(a.data || ""));
  } catch {
    return [];                       // offline, blocked, CORS -- all mean "we do not know"
  }
}

/**
 * What to tell someone about to connect `domain`, before they connect it.
 *
 * The expensive moment is AFTER connecting: a Cloudflare hostname is minted, DNS records are published,
 * and the tenant works through records that cannot ever verify (coderbay.net, 2026-10-23). Saying it
 * first costs one DNS lookup.
 */
export function apexAdvice(domain, providerId) {
  const name = String(domain || "").trim().toLowerCase().replace(/^\.+|\.+$/g, "");
  const labels = name.split(".").filter(Boolean);
  const isApex = labels.length > 0 && labels.length <= 2;      // deliberately simple; the server decides
  if (!name || !isApex || !APEX_INCAPABLE.has(providerId)) return null;
  const provider = dnsProvider(providerId);
  return {
    suggestion: `www.${name}`,
    reason: providerId === "route53"
      ? `${provider.label} can't point a root domain at an external host — its ALIAS records only target AWS resources, so ${name} has no way to reach us.`
      : `${provider.label} has no ALIAS or ANAME record, so a root domain can't be pointed at an external host like ours.`,
    // The redirect is the tenant's to set up, and what it takes differs sharply: GoDaddy has forwarding
    // built in (and it now carries HTTPS automatically), while Route 53 has no redirect of its own --
    // the usual S3 website bucket is HTTP-only, so an HTTPS redirect needs CloudFront and a certificate.
    fix: providerId === "godaddy"
      ? `Connect www.${name} instead — it works today — then add Domain Forwarding from ${name} to it in GoDaddy. Forwarding includes HTTPS automatically.`
      : `Connect www.${name} instead — it works today. To send ${name} there as well, Route 53 needs something to redirect from: an S3 website bucket handles it over HTTP, and HTTPS needs CloudFront with a certificate.`,
  };
}

export function dnsProvider(id) {
  return DNS_PROVIDERS.find((p) => p.id === id) || DNS_PROVIDERS[DNS_PROVIDERS.length - 1];
}

export function rootDomain(domain) {
  const parts = String(domain || "").split(".");
  return parts.length > 2 ? parts.slice(-2).join(".") : domain;
}

/** The Name field's value at `providerId`: the full hostname, the apex token, or the sub-label. */
export function hostPrefix(fullName, domain, providerId) {
  const provider = dnsProvider(providerId);
  const root = rootDomain(domain);
  if (provider.fqdn) return fullName;
  if (fullName === root) return provider.apexName ?? "@";
  return fullName.endsWith("." + root) ? fullName.slice(0, -(root.length + 1)) : fullName;
}

function apexNameNote(providerId) {
  return dnsProvider(providerId).apexName === ""
    ? "Leave the Name field blank — Route 53 fills in your root domain. Typing @ there creates a record " +
      "literally called “@”, which looks created and serves nothing."
    : "";
}

function multiValueNote(count) {
  return count > 1
    ? `All ${count} addresses belong to ONE record, not ${count}. Enter them as ${count} lines in the same ` +
      "Value box — creating a second record with the same name is refused."
    : "";
}

/** Route 53 rejects an unquoted TXT value outright ("Invalid Resource Record"), which reads as a bad
 *  instruction rather than a formatting rule. Only claimed for the provider it was confirmed on. */
function txtQuotingNote(type, providerId) {
  return String(type).toUpperCase() === "TXT" && providerId === "route53"
    ? "Route 53 wants a TXT value in double quotes — paste it as \"…\" or it refuses the record."
    : "";
}

/**
 * Group the server's records into the steps a tenant performs. Rows sharing a type AND a name are one
 * record set with several values, which is what DNS actually stores and what every provider's form expects.
 */
export function dnsRecordSteps(records, { domain = "", providerId = "other" } = {}) {
  const steps = [];
  const byKey = new Map();
  for (const record of records || []) {
    const key = `${record.type}\n${record.name}`;
    const existing = byKey.get(key);
    if (existing) {
      if (!existing.values.includes(record.value)) existing.values.push(record.value);
      if (record.note && !existing.note) existing.note = record.note;
      continue;
    }
    const isApex = record.name === rootDomain(domain);
    const step = {
      type: record.type,
      recordName: record.name,
      displayName: hostPrefix(record.name, domain, providerId),
      values: [record.value],
      note: record.note || "",
      isApex,
      isSsl: String(record.name || "").startsWith("_acme-challenge"),
      // An apex proves ownership with this TXT instead of a routing CNAME it cannot have. It is neither
      // "point your domain" nor a certificate record, and labelling it as either hides what it is for.
      isOwnership: String(record.name || "").startsWith("_cf-custom-hostname"),
    };
    byKey.set(key, step);
    steps.push(step);
  }
  for (const step of steps) {
    // Computed last, because the multi-value note depends on the grouping being finished.
    step.nameNote = step.isApex ? apexNameNote(providerId) : "";
    step.valueNote = [multiValueNote(step.values.length), txtQuotingNote(step.type, providerId)]
      .filter(Boolean).join(" ");
    step.nameIsBlank = step.displayName === "";
  }
  return steps;
}

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
  { id: "azure", label: "Azure DNS", fqdn: false, apexName: "@" },
  { id: "cloudflare", label: "Cloudflare", fqdn: false, apexName: "@" },
  { id: "googlecloud", label: "Google Cloud DNS", fqdn: true },
  { id: "godaddy", label: "GoDaddy", fqdn: false, apexName: "@" },
  { id: "namecheap", label: "Namecheap", fqdn: false, apexName: "@" },
  { id: "digitalocean", label: "DigitalOcean", fqdn: false, apexName: "@" },
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
  ["azure", /(^|\.)azure-dns\.(com|net|org|info)\.?$/i],
  ["cloudflare", /(^|\.)ns\.cloudflare\.com\.?$/i],
  ["googlecloud", /(^|\.)googledomains\.com\.?$/i],
  ["godaddy", /(^|\.)domaincontrol\.com\.?$/i],
  ["namecheap", /(^|\.)registrar-servers\.com\.?$/i],
  ["digitalocean", /(^|\.)digitalocean\.com\.?$/i],
  // A cPanel host usually runs its own vanity nameservers (ns1.somehost.com), so the NS name says
  // nothing. These are the names cPanel itself publishes, and they are the only hint available from DNS
  // alone -- the service ports (2082/2083, 2086/2087) are not reachable from a browser.
  ["cpanel", /(^|\.)(cpanel|whm|webmail)\./i],
];

/** Providers that CANNOT point a root domain at an external host. Verified against their own docs,
 *  because a wrong entry here tells someone to abandon their root domain:
 *    - Route 53  ALIAS targets only AWS resources.
 *    - Azure DNS alias record sets reference Azure resources (Traffic Manager, CDN, Front Door, public
 *                IPs), not arbitrary external hostnames.
 *    - GoDaddy   no ALIAS or ANAME at all.
 *  Everything else is treated as capable and shown the generic ALIAS instruction. That is right for
 *  Cloudflare (flattening), Namecheap (ALIAS on Basic/Free/Premium DNS), DNSimple, DNS Made Easy, NS1 and
 *  Porkbun, and it fails in the harmless direction for anything unclassified: the tenant looks for an
 *  ALIAS option and does not find one, rather than being told to give up a domain that would have worked.
 *  DigitalOcean and cPanel sit in that unclassified group deliberately -- not verified either way. */
const APEX_INCAPABLE = new Set(["route53", "azure", "godaddy"]);

export function detectProvider(nameservers) {
  for (const ns of nameservers || []) {
    const host = String(ns || "").trim().toLowerCase();
    for (const [id, pattern] of NS_PATTERNS) {
      if (pattern.test(host)) return id;
    }
  }
  return "";
}

/** The registrable root of a hostname, so a lookup for `shop.example.co.uk` asks about `example.co.uk`. */
export function rootDomain(domain) {
  const parts = String(domain || "").toLowerCase().replace(/\.$/, "").split(".");
  if (parts.length <= 2) return parts.join(".");
  const lastTwo = parts.slice(-2).join(".");
  return MULTIPART_TLDS.has(lastTwo) ? parts.slice(-3).join(".") : lastTwo;
}

// Mirrors the server's list in domain/custom_domains.py so both sides agree on what an apex is.
const MULTIPART_TLDS = new Set([
  "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "net.uk", "ltd.uk", "plc.uk", "sch.uk",
  "com.au", "net.au", "org.au", "edu.au", "gov.au", "co.nz", "net.nz", "org.nz",
  "co.za", "org.za", "co.jp", "or.jp", "ne.jp", "com.br", "com.mx", "co.in", "com.sg", "com.hk", "com.tr",
]);

async function doh(name, type, fetchFn) {
  const response = await fetchFn(
    `https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(name)}&type=${type}`,
    { headers: { Accept: "application/dns-json" } },
  );
  if (!response.ok) return {};
  return await response.json();
}

/**
 * Who runs this domain's DNS, read from the domain itself.
 *
 * Asks on the REGISTRABLE ROOT, and falls back from NS to SOA. Both matter: an NS query for
 * `shop.example.com` returns nothing, because the delegation lives at `example.com`; and where NS is
 * filtered or empty, the SOA's primary nameserver still names the provider. The SOA usually arrives in
 * the AUTHORITY section rather than the answer, so both are read.
 *
 * Guidance only. Every failure path returns "" and leaves the manual picker exactly as it was.
 */
export async function lookupNameservers(domain, { fetchFn = fetch } = {}) {
  const root = rootDomain(domain);
  if (!root || !root.includes(".")) return [];
  try {
    const ns = await doh(root, "NS", fetchFn);
    const fromNs = (ns.Answer || []).filter((a) => a.type === 2).map((a) => String(a.data || ""));
    if (fromNs.length) return fromNs;
    const soa = await doh(root, "SOA", fetchFn);
    return [...(soa.Answer || []), ...(soa.Authority || [])]
      .filter((a) => a.type === 6)
      .map((a) => String(a.data || "").split(/\s+/)[0]);   // MNAME: the primary nameserver
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
  if (!name || !name.includes(".") || name !== rootDomain(name)) return null;
  if (!APEX_INCAPABLE.has(providerId)) return null;
  const provider = dnsProvider(providerId);
  return {
    suggestion: `www.${name}`,
    reason: `The apex domain (${name}) can't be pointed at an external host from ${provider.label}. `
          + `Use www.${name} instead.`,
    // What it then takes to send the root there as well differs sharply by provider, so do not flatten
    // it into "set up a redirect". GoDaddy has forwarding built in and it now carries HTTPS; Route 53
    // has no redirect of its own, and the usual S3 website bucket is HTTP-only.
    fix: providerId === "godaddy"
      ? `To send ${name} there too, add Domain Forwarding to www.${name} in GoDaddy — forwarding includes HTTPS automatically.`
      : providerId === "azure"
      ? `To send ${name} there too, you need something to redirect from — Azure Front Door or a small redirect app; Azure DNS cannot do it on its own.`
      : `To send ${name} there too, Route 53 needs something to redirect from: an S3 website bucket handles it over HTTP, and HTTPS needs CloudFront with a certificate.`,
  };
}

export function dnsProvider(id) {
  return DNS_PROVIDERS.find((p) => p.id === id) || DNS_PROVIDERS[DNS_PROVIDERS.length - 1];
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

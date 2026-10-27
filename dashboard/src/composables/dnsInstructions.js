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

/** Providers we have VERIFIED can point a root domain at an external host, and so say nothing about.
 *
 *  Separating this from "everything not in APEX_INCAPABLE" is the whole point. Those two sets used to be
 *  complements, which quietly equated "we know this works" with "we have no idea" -- and the second group
 *  is much the larger one. A tenant on Bluehost, DreamHost, a cPanel reseller or any vanity-nameserver
 *  host got silence, which reads as "nothing to worry about" and left them with no apex guidance at all.
 *
 *  Anything in NEITHER set is now unknown, and unknown gets told how to find out. That is a real answer:
 *  we cannot inspect their DNS editor, but they can, and ALIAS/ANAME is a one-look question. cPanel is
 *  the case that proves the category is needed -- its apex support depends on whether the host runs
 *  PowerDNS with `expand-alias` enabled, so it has no answer that is true of every cPanel host.
 *
 *  Google Cloud DNS is in here on an earlier verification -- it has an apex ALIAS, reachable via
 *  gcloud/API -- and stays on it. "We can't tell" would be a false statement about a provider somebody
 *  already checked. */
const APEX_CAPABLE = new Set(["cloudflare", "namecheap", "googlecloud"]);

/** The provider's name for prose. `dnsProvider` falls back to the picker's catch-all entry, whose label
 *  ("Other / full name") is a form hint and reads as nonsense in a sentence. */
function providerProse(providerId) {
  const provider = DNS_PROVIDERS.find((p) => p.id === providerId);
  return provider && provider.id !== "other" ? provider.label : "your DNS provider";
}

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
  if (APEX_CAPABLE.has(providerId)) return null;        // flattening or ALIAS, confirmed: nothing to say
  if (!APEX_INCAPABLE.has(providerId)) {
    // UNKNOWN, said out loud. Not a warning -- it is a question with a one-look answer, and the tenant
    // is the only one who can look. `tone` keeps it out of the orange banner that means "you cannot".
    return {
      tone: "info",
      suggestion: `www.${name}`,
      reason: `We can't tell whether ${providerProse(providerId)} can point a root domain at an `
            + `external host. That needs an ALIAS, ANAME or CNAME-flattening record, and not every `
            + `provider has one.`,
      fix: `Look for an ALIAS or ANAME option in your DNS editor. If it is there, use it to point `
         + `${name} at us. If it is not, use www.${name} instead — that always works.`,
    };
  }
  const provider = dnsProvider(providerId);
  return {
    tone: "warning",
    suggestion: `www.${name}`,
    reason: `The apex domain (${name}) can't be pointed at an external host from ${provider.label}. `
          + `Use www.${name} instead.`,
    // What it then takes to send the root there as well differs sharply by provider, so do not flatten
    // it into "set up a redirect". GoDaddy has forwarding built in and it now carries HTTPS; Route 53
    // has no redirect of its own and needs a CloudFront distribution with a certificate. The
    // S3-website-bucket version that every guide suggests is deliberately not offered anywhere: those
    // endpoints cannot serve HTTPS, and no business page is served over plain HTTP in 2026, so it is a
    // dead end dressed up as the simple option.
    fix: providerId === "godaddy"
      ? `To send ${name} there too, add Domain Forwarding to www.${name} in GoDaddy — forwarding includes HTTPS automatically.`
      : providerId === "azure"
      ? `To send ${name} there too, you need something to redirect from — Azure Front Door or a small redirect app; Azure DNS cannot do it on its own.`
      : `To send ${name} there too, Route 53 needs something that answers HTTP for it — a CloudFront distribution with a certificate and a redirect function. The domain panel walks you through it once www.${name} is connected.`,
  };
}

/**
 * The optional last step: make the apex land on the www hostname the tenant connected.
 *
 * Only offered when the connected domain IS `www.<root>`, which is the case where the root is left
 * orphaned — a visitor who types `example.com` gets NXDOMAIN and concludes the business is gone. The
 * site works without it, so this is never a failure state and never blocks verification.
 *
 * DNS CANNOT DO THIS, and the instructions have to say so or a tenant will go looking for a record type
 * that does not exist. A redirect is an HTTP 301; it needs something that speaks HTTP and holds a
 * certificate for the apex. What that something is differs completely by provider, which is why this is
 * nine paragraphs rather than one.
 *
 * For providers that CAN point an apex at an external host, the better answer is offered first: serve
 * the root directly instead of bouncing it. A redirect costs a round trip and splits the address.
 */
/**
 * Split a line on `**bold**` into segments the template renders as text or <strong>.
 *
 * A walkthrough has two or three details that decide whether it works at all -- the console REGION, the
 * record type, which event the function runs on -- and in a wall of grey paragraph text they are
 * invisible. Done as segments rather than v-html: these strings are ours today, and the moment one of
 * them interpolates a tenant's domain into markup that gets parsed, it is not a styling choice any more.
 */
export function emphasise(line) {
  return String(line || "").split(/\*\*/).map((text, i) => ({ text, bold: i % 2 === 1 }))
    .filter((seg) => seg.text !== "");
}

export function apexRedirectStep(domain, providerId, dnsTarget) {
  const www = String(domain || "").trim().toLowerCase().replace(/\.$/, "");
  if (!www.startsWith("www.")) return null;
  const apex = www.slice(4);
  if (!apex.includes(".")) return null;
  const target = dnsTarget || "the target above";
  // The console rejects spaces and dots here, and an empty required field is where people stop.
  const fnName = `redirect-${apex.replace(/\./g, "-")}-to-www`;

  const byProvider = {
    route53: [
      `Route 53 has no redirect of its own, so the certificate, distribution and function below are what actually do the redirecting. Six steps, and the AWS console moves you between three services.`,
      `**1. Certificate.** In AWS Certificate Manager, first switch the console region (top right) to **us-east-1 / N. Virginia** — CloudFront accepts certificates from that region and no other. Request a public certificate for ${apex}. If one already exists for this domain, skip to step 2. Choose DNS validation; Route 53 can create the validation record for you in one click. Wait for Status to read **Issued** before going on.`,
      `**2. Switch the region back** to the one you normally work in. CloudFront and Route 53 are global and do not care, but the console remembers us-east-1, and every other resource you own will look like it has vanished.`,
      `**3. Distribution.** CloudFront → Create distribution. **Any Origin will do** — the function answers before CloudFront ever reaches it, so the origin is never contacted. Set Alternate domain name to **${apex}**, attach the certificate from step 1, and set Viewer protocol policy to **Redirect HTTP to HTTPS**.`,
      `**4. Function.** CloudFront → Functions → Create function. The name field is required and rejects spaces — **${fnName}** works. Description: **301 redirect ${apex} to ${www}**. Runtime: **cloudfront-js-2.0**. Paste the code below, Save changes, then Publish.`,
      `**5. Associate it.** On the published function's Associations (or the distribution's Behaviors → Default → Edit), add your distribution with Event type **Viewer request**. A function that is published but not associated does nothing, and nothing warns you.`,
      `**6. Route 53.** First, on the distribution's General tab, copy **Domain name (standard)** — it looks like d1p1tvfq21mu6z.cloudfront.net; there is a copy icon beside it. Then Route 53 → Hosted zones → ${apex} → Create record. Leave **Record name blank**, Record type **A**, turn **Alias** on, choose **Alias to CloudFront distribution**, and paste that domain name. Repeat with type **AAAA** if you want IPv6.`,
      `The function carries the path and query string across, so an ad landing on ${apex}/offer?utm_source=… keeps its tracking instead of arriving bare.`,
    ],
    azure: [
      `Azure DNS has no redirect of its own.`,
      `Use Azure Front Door with a redirect rule to https://${www}, or any small service that answers HTTP and holds a certificate for ${apex}, then point ${apex} at it.`,
    ],
    godaddy: [
      `1. GoDaddy → Domain Portfolio → your domain → DNS → Forwarding → Add Forwarding.`,
      `2. Forward the root domain to https://${www} as a Permanent (301) redirect.`,
      `GoDaddy applies HTTPS to forwarding automatically, so https://${apex} works too.`,
    ],
    namecheap: [
      `Namecheap can serve the root DIRECTLY, which is better than redirecting: Advanced DNS → Add New Record → ALIAS Record, host @, value ${target}. Then connect ${apex} here instead of ${www}.`,
      `If you would rather keep ${www} as your address: Advanced DNS → Add New Record → URL Redirect Record, host @, value https://${www}, type Permanent (301).`,
    ],
    cloudflare: [
      `Cloudflare can serve the root DIRECTLY, which is better than redirecting: add a proxied CNAME at @ pointing to ${target} — Cloudflare flattens it at the apex. Then connect ${apex} here instead of ${www}.`,
      `If you would rather keep ${www} as your address: Rules → Redirect Rules → Create rule, matching hostname ${apex}, redirecting to https://${www} with "Preserve path" on and status 301.`,
    ],
    googlecloud: [
      `Cloud DNS can serve the root DIRECTLY, which is better than redirecting: create an ALIAS record at the apex pointing to ${target} — through gcloud or the API, as the Cloud console does not expose ALIAS. Then connect ${apex} here instead of ${www}.`,
      `If you would rather keep ${www} as your address, you need something that answers HTTP for ${apex} — a load balancer with a redirect rule, or any redirect service — since DNS alone cannot redirect.`,
    ],
  };
  const generic = [
    `Most providers call this URL forwarding, a redirect rule, or a URL Redirect Record: send ${apex} to https://${www} as a permanent (301) redirect.`,
    `If yours has no such feature, nothing in DNS will do it — a redirect is an HTTP response, so it needs something that answers HTTP and holds a certificate for ${apex}.`,
  ];

  // The one part nobody can guess, so hand it over rather than describe it. Shape taken from AWS's own
  // CloudFront Functions redirect example -- {statusCode, statusDescription, headers:{location:{value}}}
  // -- and written ES5-plain so it runs on either runtime version.
  const code = providerId === "route53" ? `async function handler(event) {
  var qs = event.request.querystring;
  var parts = [];
  for (var k in qs) { parts.push(qs[k].value ? k + '=' + qs[k].value : k); }
  var search = parts.length ? '?' + parts.join('&') : '';
  return {
    statusCode: 301,
    statusDescription: 'Moved Permanently',
    headers: { location: { value: 'https://${www}' + event.request.uri + search } }
  };
}` : "";

  return {
    optional: true,
    code,
    stepLabel: `Send ${apex} here too`,
    instructions: byProvider[providerId] || generic,
    note: `Optional. ${www} works without this. Add it so someone who types ${apex} lands on your site `
        + `instead of an error.`,
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

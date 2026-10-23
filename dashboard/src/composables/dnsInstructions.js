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
    };
    byKey.set(key, step);
    steps.push(step);
  }
  for (const step of steps) {
    // Computed last, because the multi-value note depends on the grouping being finished.
    step.nameNote = step.isApex ? apexNameNote(providerId) : "";
    step.valueNote = multiValueNote(step.values.length);
    step.nameIsBlank = step.displayName === "";
  }
  return steps;
}

import { rootDomain } from "./dnsInstructions.js";

/**
 * The managed-DNS flow's shape, kept out of the component (plans/MANAGED_DNS.md P4).
 *
 * Four states, and which one you are in is decided by the server, never inferred from what the UI last
 * did. That matters because the interesting failures here are all "the server knows something the screen
 * does not": a mail record the import missed, a delegation half the internet can see.
 *
 *   choose     -> nothing started; offer managed DNS or keeping their own DNS
 *   blocked    -> the zone exists, and the mail comparison refuses to hand over the nameservers
 *   delegate   -> nameservers issued; waiting for the tenant to change them, then for resolvers
 *   live       -> Cloudflare sees the delegation; the apex serves
 */

export const CHOOSE = "choose";
export const BLOCKED = "blocked";
export const REVIEW = "review";
export const DELEGATE = "delegate";
export const LIVE = "live";

export function managedDnsState(zone, review) {
  if (!zone || !zone.zone_id) return CHOOSE;
  if (zone.status === "active") return LIVE;
  // `blocked` is the server's verdict, and it is re-read on every poll rather than remembered: a tenant
  // who adds the missing MX and retries must be able to move on without starting over.
  if (review && review.blocked) return BLOCKED;
  // READ BEFORE DELEGATE. A clean review used to go straight to the nameservers, so the summary of what
  // we had imported was computed and then shown to nobody -- the one screen that tells a tenant what we
  // are about to take responsibility for. Confirmation lives on the ZONE, so it survives a reload.
  if (!zone.review || !zone.review.confirmed_at) return REVIEW;
  return DELEGATE;
}

/** What we read, in a sentence a tenant can check against their own DNS. */
export function importSummary(zone) {
  const r = (zone && zone.review) || {};
  const records = r.records || 0;
  const mail = r.mail_count || 0;
  const parts = [`${records} record${records === 1 ? "" : "s"} imported`];
  parts.push(mail ? `${mail} of them mail` : "none of them mail");
  if (r.provider) parts.push(r.provider);
  return parts.join(" · ");
}

/**
 * How to change nameservers, in the words of the place they have to do it.
 *
 * Reuses the provider detection already built for DNS records, so a Route 53 tenant is told about
 * Registered domains rather than about their hosted zone -- a distinction that costs an hour if you get
 * it wrong, because the hosted zone has an NS record that looks like the thing to edit and is not.
 */
export function nameserverInstructions(providerId, typed) {
  // The REGISTRABLE ROOT, never what was typed. Nameservers belong to the registered domain, and there
  // is no registered domain called `www.example.com` -- sending someone to look for one in Route 53's
  // Registered domains list is sending them to find nothing.
  const domain = rootDomain(typed);
  const byProvider = {
    route53: [
      `Route 53 → **Registered domains** → ${domain} → **Actions → Edit name servers**.`,
      `Not the hosted zone. The NS record inside the hosted zone looks like the setting to change and is not — the registrar is what the rest of the internet asks.`,
      `Replace all four entries with the two below.`,
    ],
    godaddy: [
      `GoDaddy → **Domain Portfolio** → ${domain} → **Nameservers → Change**.`,
      `Choose **I'll use my own nameservers**, then replace what is there with the two below.`,
    ],
    namecheap: [
      `Namecheap → **Domain List** → Manage → **Nameservers**.`,
      `Switch from Namecheap BasicDNS to **Custom DNS**, then enter the two below.`,
    ],
    cloudflare: [
      `This domain is already on Cloudflare, so there are no nameservers to change — connect it as a custom domain instead; the root will work as it is.`,
    ],
  };
  return byProvider[providerId] || [
    `At your registrar — the company you bought ${domain} from, which may not be where its DNS is edited — find the nameserver setting and replace what is there with the two below.`,
    `It is usually called "nameservers", "custom DNS" or "DNS servers". Replace every entry, not just the first.`,
  ];
}

/**
 * What to say while waiting, which is mostly "this is normal".
 *
 * Measured on the first live run: Cloudflare saw the delegation 3.5 minutes after the change, and the
 * certificate issued ~2 minutes later -- but resolvers disagreed for far longer. Google and Quad9 had
 * the new nameservers while Cloudflare's own 1.1.1.1 still served the old ones. A tenant refreshing in
 * that window is watching DNS behave exactly as designed, and must not be told something is wrong.
 */
export function waitingMessage(elapsedSeconds) {
  if (elapsedSeconds < 300) {
    return "Waiting for your registrar. This usually takes a few minutes once you have saved the change.";
  }
  if (elapsedSeconds < 3600) {
    return "Still waiting. Nameserver changes can take up to an hour to reach us, and longer to reach "
         + "everyone — that is normal and nothing is wrong. You can close this and come back.";
  }
  return "This is taking longer than usual. Check that the nameservers were saved at your REGISTRAR "
       + "rather than in a DNS zone editor, and that you replaced every entry rather than adding to them.";
}

/** Mail, phrased so a tenant can actually check it rather than audit a record list. */
export function mailSummary(review) {
  const mail = (review && review.mail) || {};
  if (!mail.present) return "No mail records found. If this domain receives email, stop and tell us.";
  const parts = [];
  if (mail.provider) parts.push(`Mail is handled by ${mail.provider}`);
  else parts.push(`${mail.mx_count} mail server${mail.mx_count === 1 ? "" : "s"} found`);
  if (mail.spf) parts.push("SPF");
  if (mail.dmarc) parts.push("DMARC");
  if ((mail.dkim || []).length) parts.push(`${mail.dkim.length} DKIM key${mail.dkim.length === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

// Cloudflare Worker for the jbay.uk, jbay.be AND jbay.page zones. Handles three things on the platform edge:
//
//  (Was four. The go.jbay.uk short-URL host was removed 2026-10-23: A/B testing had already moved off it --
//   "an experiment runs on the page's OWN url now", ABTesting.vue -- and nothing else produced one, so a
//   valid short code 404'd there while the SAME code served fine through the test viewer. The short CODES
//   are untouched and very much alive: publish writes one on every page and the shareable test link
//   {stage}-test.juniorbay.com/published/{code} is built from it.)
//
//  1. Tenant custom domains: resolve the hostname to a published page and reverse-proxy it
//     verbatim, so the visitor's browser only ever sees their own custom domain.
//  2. Free platform-host stores ({label}.jbay.uk in prod, {label}.jbay.be in test): the SAME
//     resolve + reverse-proxy path as a custom domain (the resolve endpoint distinguishes them
//     by the domain-index record), except the resolver flags the route `noindex: true`, so we
//     stamp `X-Robots-Tag: noindex, nofollow` on the response. A platform host is a navigable
//     but NEVER-indexed store surface — the reputation-isolation floor
//     (plans/PLATFORM_HOSTNAME_SERVING.md).
//  3. Link-in-bio pages on the creator apex (jbay.page/{username}): the same resolve + proxy path again.
//     The difference is WHERE the tenant is named — every creator shares one hostname, so the resolver
//     keys off host + first path segment instead of host alone. That split lives server-side; this script
//     already forwards both, so the only edge work is the apex guard below. Also noindex-stamped: a shared
//     UGC apex must never couple one creator's reputation to another's.
//     Deploy this one script to every zone with the zone-wide `*/*` route
//     (see deploy/setup-cloudflare-custom-domain-worker.sh).

const API_BASE = "https://REPLACE_WITH_PUBLIC_API_BASE_URL";
const CUSTOM_DOMAIN_RESOLVE = `${API_BASE}/custom-domains/resolve`;

// Infrastructure hostnames on the jbay.uk / jbay.be zones that must pass straight through to
// their normal origin rather than being resolved as a Site store. Add any leftover stripe-cart
// subdomains on jbay.be here so they don't collide with the `*.jbay.be` store route.
//
// `domains.jbay.be` was MISSING while `domains.jbay.uk` was present (fixed 2026-10-23). The asymmetry
// encoded the pre-decoupling assumption that jbay.uk was "production, authorized to serve published pages"
// and jbay.be was "sandbox, not authorized" (author). That is the deployment axis, and it is not the one
// that decides anything here: a sandbox stack serves live-mode Sites, and whether a page may be INDEXED is
// decided per-Site by Stripe mode and the eligibility gate, server-side -- see page_robots_directive and
// stripe_link/silo.py. Both zones are ordinary platform edges and their fallback origins are infrastructure
// in exactly the same way.
//
// `go.jbay.be` is listed defensively. It is DNS-only today, so this Worker never sees it, and it belongs to
// the legacy stripe-cart app (Lambda@Edge rewrites /{code} into its own bucket). Reserving it means someone
// turning that cloud orange gets a pass-through rather than a 404 from a resolver that has never heard of
// it. Costs a line; removes a footgun that exists only while the old app does.
// The creator apex. NOT in RESERVED_HOSTS, and it must never be added there: that set is keyed on hostname
// alone, and every creator URL shares this one hostname — reserving it would pass every creator page through
// to the origin instead of resolving it. The bare apex (no username) is guarded in handleSiteHost instead.
const CREATOR_HOST = "REPLACE_WITH_CREATOR_HOST";
const RESERVED_HOSTS = new Set([
  "domains.jbay.uk",
  "domains.jbay.be",
  "go.jbay.be",
  "jbay.uk",
  "www.jbay.uk",
  "jbay.be",
  "www.jbay.be",
  "www.jbay.page",
]);

async function resolveJson(cacheNamespace, cacheValue, url) {
  const cache = caches.default;
  const cacheKey = new Request(`https://stripe-link-${cacheNamespace}.local/${cacheValue}`);
  const cached = await cache.match(cacheKey);
  if (cached) {
    return cached.json();
  }

  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    return null;
  }

  const bodyText = await response.text();
  const cacheResponse = new Response(bodyText, {
    headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
  });
  await cache.put(cacheKey, cacheResponse.clone());
  return JSON.parse(bodyText);
}

// What a visitor sees when an address does not resolve: a renamed creator handle, an archived Site, a slug
// that was never published. Ported from stripe-cart's `_error_page` (src/test_page_serve.py) at the author's
// request, so the platform's error surface looks the same either side of the migration.
//
// Deliberately ONE page for every cause, and deliberately vague. "This store is suspended" or "this creator
// renamed" tells a stranger something about the tenant; a bare Cloudflare 404 tells the visitor the whole
// domain is broken. Single-theme dark by design, like the original -- it is a standalone page with no host
// theme to inherit, so it commits rather than guessing.
//
// Parameterised (status, message) because this is the platform's error page, not the 404: the same surface
// should answer a 500 or a suspension when those need one.
function errorPage(status, message) {
  const body = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${status}</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);color:#f1f5f9;
min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.container{text-align:center;max-width:500px}
h1{font-size:4rem;line-height:1;margin-bottom:1rem;font-weight:800;letter-spacing:-.03em;
background:linear-gradient(135deg,#f59e0b,#ef4444);-webkit-background-clip:text;background-clip:text;
-webkit-text-fill-color:transparent;color:#f59e0b}
p{font-size:1.25rem;color:#94a3b8;margin-bottom:2rem;text-wrap:balance}
.badge{display:inline-block;background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3);
color:#f59e0b;padding:.5rem 1rem;border-radius:9999px;font-size:.875rem}
</style></head><body><div class="container">
<h1>${status}</h1><p>${message}</p>
<span class="badge">Junior Bay</span>
</div></body></html>`;
  return new Response(body, { status, headers: { "content-type": "text/html; charset=utf-8" } });
}

function notFound() {
  return errorPage(404, "Oops! This page doesn't exist. The link may be out of date, or the page may have moved.");
}

// Serve a Site host — a tenant custom domain OR a free platform host. The resolve endpoint keys off the
// incoming hostname and returns the same shape for both; a platform host additionally carries
// `route.noindex`, which we translate into an X-Robots-Tag header on the proxied response.
async function handleSiteHost(request, hostname, waitUntil) {
  // Resolution is path-dependent — the Site homepage at "/", funnel/collection pages at their slugs, and
  // well-known crawl files (robots.txt/sitemap.xml/{key}.txt) — so forward the path and key the cache by it.
  const path = new URL(request.url).pathname;
  // The bare creator apex belongs to the platform, not to whoever claims it first. Without this, `jbay.page/`
  // resolves as a Site host and answers a page-not-found on the domain's own front door.
  if (hostname === CREATOR_HOST && path.replace(/\/+$/, "") === "") {
    return Response.redirect("https://juniorbay.com/", 302);
  }
  // A reserved funnel slug resolves to a DIFFERENT artifact per request: `funnel_step` picks which upsell
  // in the sequence, and `funnel_page` says whose funnel it is (one `/upsell` slug serves every page on the
  // Site, so a funnel no longer has to belong to the page at "/"). The resolver has read `funnel_step` since
  // reserved slugs shipped and this Worker never sent it, so a sequence past step 1 could not resolve at the
  // edge at all; `funnel_page` is new with the same journey (2026-10-02).
  //
  // They are part of the CACHE KEY, not just the query. Caching `/upsell` by host+path alone would pin the
  // first buyer's step and serve it to everyone after -- upsell 2 answering with upsell 1, or one page's
  // funnel answering for another's.
  const funnelParams = new URL(request.url).searchParams;
  const funnelStep = funnelParams.get("funnel_step") || "";
  const funnelPage = funnelParams.get("funnel_page") || "";
  const funnelQuery = (funnelStep ? `&funnel_step=${encodeURIComponent(funnelStep)}` : "")
    + (funnelPage ? `&funnel_page=${encodeURIComponent(funnelPage)}` : "");
  const resolveUrl = `${CUSTOM_DOMAIN_RESOLVE}?host=${encodeURIComponent(hostname)}&path=${encodeURIComponent(path)}${funnelQuery}`;
  const resolved = await resolveJson(
    "custom-domain-router", `${hostname}${path}${funnelQuery}`, resolveUrl);
  const route = resolved && resolved.route;
  // Two kinds of 301, and they differ in whether the path comes along. A HOST-level move (www→apex) carries
  // it, so /a/b lands on /a/b at the new host. A per-path target names its exact destination, and appending
  // to that invents a URL nobody asked for -- `/link-bio` → `jbay.page/maria` must not become
  // `jbay.page/maria/link-bio`. Everything used to preserve the path, which silently broke the second case.
  if (route && route.type === "redirect" && route.location) {
    const url = new URL(request.url);
    const target = route.preserve_path
      ? route.location.replace(/\/$/, "") + url.pathname + url.search
      : route.location + url.search;
    return Response.redirect(target, 301);
  }
  if (!route || route.type !== "origin_url" || !route.origin_url) {
    return notFound();
  }

  // A/B: the resolver says WHAT the experiment is; the edge decides WHO gets which. Assignment cannot live
  // in the resolve response because that response is cached for 60s -- every visitor in the window would
  // get the same variant, a time-bucketed split rather than a random one. `route.origin_url` is always the
  // CONTROL, so an experiment that cannot be read here degrades to serving the control.
  const assignment = assignVariant(route.experiment, request);
  const originUrl = assignment.origin_url || route.origin_url;

  const proxied = new Request(originUrl, request);
  proxied.headers.set("X-Junior-Bay-Custom-Host", hostname);
  const response = await fetch(proxied);
  countView(route.experiment, assignment, waitUntil);
  // Free platform host: force noindex at the edge so the same artifact that says index,follow on a verified
  // custom domain is never indexed here (more-restrictive wins). Re-wrap so the header is mutable.
  if (route.noindex || assignment.page_id) {
    const stamped = new Response(response.body, response);
    if (route.noindex) {
      stamped.headers.set("X-Robots-Tag", "noindex, nofollow");
    }
    if (assignment.page_id) {
      // Pin the visitor so a refresh does not reroll them into the other variant, which would make one
      // person look like two and smear their behaviour across both arms.
      stamped.headers.append(
        "Set-Cookie",
        `${assignment.cookie_name}=${assignment.page_id}; Path=/; Max-Age=2592000; Secure; SameSite=Lax`,
      );
      // A variant response must never be shared between visitors by any cache in front of us.
      stamped.headers.set("Cache-Control", "private, no-store");
    }
    return stamped;
  }
  return response;
}

// --- A/B assignment -------------------------------------------------------------------------------------

function readCookie(request, name) {
  const raw = request.headers.get("Cookie") || "";
  for (const part of raw.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return "";
}

// Returns {} when there is nothing to assign, so every caller can treat "no experiment" as the normal case.
function assignVariant(experiment, request) {
  const variants = (experiment && experiment.variants) || [];
  if (!variants.length) return {};
  const cookieName = experiment.cookie_name || `jb_ab_${experiment.experiment_id}`;

  // An existing pin wins, but only if it still names a variant of THIS experiment -- a variant removed
  // mid-flight would otherwise strand those visitors on a page that is no longer being tested.
  const pinned = readCookie(request, cookieName);
  const held = variants.find((variant) => variant.page_id === pinned);
  if (held) {
    return { page_id: held.page_id, origin_url: held.origin_url, cookie_name: cookieName, counted: false };
  }

  const total = variants.reduce((sum, variant) => sum + Math.max(0, variant.weight || 0), 0);
  if (total <= 0) return {};
  let roll = Math.floor(Math.random() * total);
  for (const variant of variants) {
    roll -= Math.max(0, variant.weight || 0);
    if (roll < 0) {
      return { page_id: variant.page_id, origin_url: variant.origin_url, cookie_name: cookieName, counted: true };
    }
  }
  const last = variants[variants.length - 1];
  return { page_id: last.page_id, origin_url: last.origin_url, cookie_name: cookieName, counted: true };
}

// Fire-and-forget: a view is counted only on a NEW assignment, never on a refresh by an already-pinned
// visitor, or one person reloading would look like many.
function countView(experiment, assignment, waitUntil) {
  if (!assignment.counted || !experiment || !experiment.view_url || !waitUntil) return;
  waitUntil(
    fetch(experiment.view_url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_id: assignment.page_id }),
    }).catch(() => {}),
  );
}

async function handleRequest(request, waitUntil) {
  const sourceUrl = new URL(request.url);
  const hostname = sourceUrl.hostname.toLowerCase();

  if (RESERVED_HOSTS.has(hostname)) {
    return fetch(request);
  }
  return handleSiteHost(request, hostname, waitUntil);
}

addEventListener("fetch", (event) => {
  // waitUntil is threaded through so an A/B view can be counted AFTER the visitor's response is sent --
  // a metric must never be in the critical path of serving a page.
  event.respondWith(handleRequest(event.request, (promise) => event.waitUntil(promise)));
});

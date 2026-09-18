// Cloudflare Worker for the jbay.uk, jbay.be AND jbay.page zones. Handles four things on the platform edge:
//
//  1. Short URLs on the short-URL host (go.jbay.uk/{code}): resolve the code to a
//     destination via the routes resolve endpoint and 302-redirect the visitor. For A/B
//     experiment codes the destination is the experiment resolver, which itself redirects
//     to a weighted variant.
//  2. Tenant custom domains: resolve the hostname to a published page and reverse-proxy it
//     verbatim, so the visitor's browser only ever sees their own custom domain.
//  3. Free platform-host stores ({label}.jbay.uk in prod, {label}.jbay.be in test): the SAME
//     resolve + reverse-proxy path as a custom domain (the resolve endpoint distinguishes them
//     by the domain-index record), except the resolver flags the route `noindex: true`, so we
//     stamp `X-Robots-Tag: noindex, nofollow` on the response. A platform host is a navigable
//     but NEVER-indexed store surface — the reputation-isolation floor
//     (plans/PLATFORM_HOSTNAME_SERVING.md).
//  4. Link-in-bio pages on the creator apex (jbay.page/{username}): the same resolve + proxy path again.
//     The difference is WHERE the tenant is named — every creator shares one hostname, so the resolver
//     keys off host + first path segment instead of host alone. That split lives server-side; this script
//     already forwards both, so the only edge work is the apex guard below. Also noindex-stamped: a shared
//     UGC apex must never couple one creator's reputation to another's.
//     Deploy this one script to every zone with the zone-wide `*/*` route
//     (see deploy/setup-cloudflare-custom-domain-worker.sh).

const API_BASE = "https://REPLACE_WITH_PUBLIC_API_BASE_URL";
const CUSTOM_DOMAIN_RESOLVE = `${API_BASE}/custom-domains/resolve`;
const ROUTES_RESOLVE = `${API_BASE}/routes/resolve`;

const SHORT_URL_HOST = "go.jbay.uk";
// Infrastructure hostnames on the jbay.uk / jbay.be zones that must pass straight through to
// their normal origin rather than being resolved as a Site store. Add any leftover stripe-cart
// subdomains on jbay.be here so they don't collide with the `*.jbay.be` store route.
// The creator apex. NOT in RESERVED_HOSTS, and it must never be added there: that set is keyed on hostname
// alone, and every creator URL shares this one hostname — reserving it would pass every creator page through
// to the origin instead of resolving it. The bare apex (no username) is guarded in handleSiteHost instead.
const CREATOR_HOST = "REPLACE_WITH_CREATOR_HOST";
const RESERVED_HOSTS = new Set([
  "domains.jbay.uk",
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

async function handleShortUrl(sourceUrl) {
  const code = sourceUrl.pathname.replace(/^\/+/, "").split("/")[0];
  if (!code) {
    return new Response("Short link not found.", { status: 404 });
  }
  const resolved = await resolveJson("short-url-router", code, `${ROUTES_RESOLVE}?code=${encodeURIComponent(code)}`);
  const route = resolved && resolved.route;
  if (!route || route.type !== "redirect" || !route.destination_url) {
    return new Response("Short link not found.", { status: 404 });
  }
  return Response.redirect(route.destination_url, 302);
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
async function handleSiteHost(request, hostname) {
  // Resolution is path-dependent — the Site homepage at "/", funnel/collection pages at their slugs, and
  // well-known crawl files (robots.txt/sitemap.xml/{key}.txt) — so forward the path and key the cache by it.
  const path = new URL(request.url).pathname;
  // The bare creator apex belongs to the platform, not to whoever claims it first. Without this, `jbay.page/`
  // resolves as a Site host and answers a page-not-found on the domain's own front door.
  if (hostname === CREATOR_HOST && path.replace(/\/+$/, "") === "") {
    return Response.redirect("https://juniorbay.com/", 302);
  }
  const resolveUrl = `${CUSTOM_DOMAIN_RESOLVE}?host=${encodeURIComponent(hostname)}&path=${encodeURIComponent(path)}`;
  const resolved = await resolveJson("custom-domain-router", `${hostname}${path}`, resolveUrl);
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
  const proxied = new Request(route.origin_url, request);
  proxied.headers.set("X-Junior-Bay-Custom-Host", hostname);
  const response = await fetch(proxied);
  // Free platform host: force noindex at the edge so the same artifact that says index,follow on a verified
  // custom domain is never indexed here (more-restrictive wins). Re-wrap so the header is mutable.
  if (route.noindex) {
    const stamped = new Response(response.body, response);
    stamped.headers.set("X-Robots-Tag", "noindex, nofollow");
    return stamped;
  }
  return response;
}

async function handleRequest(request) {
  const sourceUrl = new URL(request.url);
  const hostname = sourceUrl.hostname.toLowerCase();

  if (hostname === SHORT_URL_HOST) {
    return handleShortUrl(sourceUrl);
  }
  if (RESERVED_HOSTS.has(hostname)) {
    return fetch(request);
  }
  return handleSiteHost(request, hostname);
}

addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

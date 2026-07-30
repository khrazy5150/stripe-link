// Cloudflare Worker for the jbay.uk AND jbay.be zones. Handles three things on the platform edge:
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
//     (plans/PLATFORM_HOSTNAME_SERVING.md). Deploy this one script to both zones with the
//     zone-wide `*/*` route (see deploy/setup-cloudflare-custom-domain-worker.sh).

const API_BASE = "https://REPLACE_WITH_PUBLIC_API_BASE_URL";
const CUSTOM_DOMAIN_RESOLVE = `${API_BASE}/custom-domains/resolve`;
const ROUTES_RESOLVE = `${API_BASE}/routes/resolve`;

const SHORT_URL_HOST = "go.jbay.uk";
// Infrastructure hostnames on the jbay.uk / jbay.be zones that must pass straight through to
// their normal origin rather than being resolved as a Site store. Add any leftover stripe-cart
// subdomains on jbay.be here so they don't collide with the `*.jbay.be` store route.
const RESERVED_HOSTS = new Set([
  "domains.jbay.uk",
  "jbay.uk",
  "www.jbay.uk",
  "jbay.be",
  "www.jbay.be",
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

// Serve a Site host — a tenant custom domain OR a free platform host. The resolve endpoint keys off the
// incoming hostname and returns the same shape for both; a platform host additionally carries
// `route.noindex`, which we translate into an X-Robots-Tag header on the proxied response.
async function handleSiteHost(request, hostname) {
  // Resolution is path-dependent — the Site homepage at "/", funnel/collection pages at their slugs, and
  // well-known crawl files (robots.txt/sitemap.xml/{key}.txt) — so forward the path and key the cache by it.
  const path = new URL(request.url).pathname;
  const resolveUrl = `${CUSTOM_DOMAIN_RESOLVE}?host=${encodeURIComponent(hostname)}&path=${encodeURIComponent(path)}`;
  const resolved = await resolveJson("custom-domain-router", `${hostname}${path}`, resolveUrl);
  const route = resolved && resolved.route;
  // A www→apex redirect: 301 to the canonical apex, carrying the path + query through.
  if (route && route.type === "redirect" && route.location) {
    const url = new URL(request.url);
    return Response.redirect(route.location.replace(/\/$/, "") + url.pathname + url.search, 301);
  }
  if (!route || route.type !== "origin_url" || !route.origin_url) {
    return new Response("This store is not active.", { status: 404 });
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

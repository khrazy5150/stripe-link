// Cloudflare Worker for the jbay.uk zone (+ the test.juniorbay.com hostname). Handles the platform edge:
//
//  1. Short URLs on the short-URL host (go.jbay.uk/{code}): resolve the code to a
//     destination via the routes resolve endpoint and 302-redirect the visitor. For A/B
//     experiment codes the destination is the experiment resolver, which itself redirects
//     to a weighted variant.
//  2. Tenant custom domains: resolve the hostname to a published page and reverse-proxy it
//     verbatim, so the visitor's browser only ever sees their own custom domain.
//  3. Test-environment shareable links (test.juniorbay.com/published/{code}[/sale|/flash-sale]):
//     resolve the page short_code + view to its published artifact and reverse-proxy it, so a
//     tenant can QA and share the /sale //flash-sale views without a custom domain.

const API_BASE = "https://REPLACE_WITH_PUBLIC_API_BASE_URL";
const CUSTOM_DOMAIN_RESOLVE = `${API_BASE}/custom-domains/resolve`;
const ROUTES_RESOLVE = `${API_BASE}/routes/resolve`;
const PAGES_RESOLVE = `${API_BASE}/pages/resolve`;

const SHORT_URL_HOST = "go.jbay.uk";
const TEST_PAGES_HOST = "test.juniorbay.com";
const TEST_VIEWS = new Set(["", "sale", "flash-sale"]);
const PLATFORM_HOSTS = new Set([
  "domains.jbay.uk",
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

async function handleTestPage(request, sourceUrl) {
  // /published/{code}            -> standard view
  // /published/{code}/sale       -> sale view
  // /published/{code}/flash-sale -> flash-sale view
  const parts = sourceUrl.pathname.replace(/^\/+/, "").split("/").filter(Boolean);
  if (parts[0] !== "published" || !parts[1]) {
    return new Response("Test page not found.", { status: 404 });
  }
  const code = parts[1];
  const view = parts[2] || "";
  if (!TEST_VIEWS.has(view)) {
    return new Response("Test page not found.", { status: 404 });
  }
  const resolveUrl = `${PAGES_RESOLVE}?code=${encodeURIComponent(code)}&view=${encodeURIComponent(view)}`;
  const resolved = await resolveJson("test-page-router", `${code}/${view}`, resolveUrl);
  const route = resolved && resolved.route;
  if (!route || route.type !== "origin_url" || !route.origin_url) {
    return new Response("Test page not found.", { status: 404 });
  }
  const proxied = new Request(route.origin_url, request);
  proxied.headers.set("X-Junior-Bay-Test-Host", TEST_PAGES_HOST);
  return fetch(proxied);
}

async function handleCustomDomain(request, hostname) {
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
    return new Response("Custom domain is not active.", { status: 404 });
  }
  const proxied = new Request(route.origin_url, request);
  proxied.headers.set("X-Junior-Bay-Custom-Host", hostname);
  return fetch(proxied);
}

async function handleRequest(request) {
  const sourceUrl = new URL(request.url);
  const hostname = sourceUrl.hostname.toLowerCase();

  if (hostname === SHORT_URL_HOST) {
    return handleShortUrl(sourceUrl);
  }
  if (hostname === TEST_PAGES_HOST) {
    return handleTestPage(request, sourceUrl);
  }
  if (PLATFORM_HOSTS.has(hostname)) {
    return fetch(request);
  }
  return handleCustomDomain(request, hostname);
}

addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

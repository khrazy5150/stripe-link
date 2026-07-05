// Cloudflare Worker for the jbay.uk zone. Handles two things on the platform edge:
//
//  1. Short URLs on the short-URL host (go.jbay.uk/{code}): resolve the code to a
//     destination via the routes resolve endpoint and 302-redirect the visitor. For A/B
//     experiment codes the destination is the experiment resolver, which itself redirects
//     to a weighted variant.
//  2. Tenant custom domains: resolve the hostname to a published page and reverse-proxy it
//     verbatim, so the visitor's browser only ever sees their own custom domain.

const API_BASE = "https://REPLACE_WITH_PUBLIC_API_BASE_URL";
const CUSTOM_DOMAIN_RESOLVE = `${API_BASE}/custom-domains/resolve`;
const ROUTES_RESOLVE = `${API_BASE}/routes/resolve`;

const SHORT_URL_HOST = "go.jbay.uk";
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

async function handleCustomDomain(request, hostname) {
  const resolved = await resolveJson("custom-domain-router", hostname, `${CUSTOM_DOMAIN_RESOLVE}?host=${encodeURIComponent(hostname)}`);
  const route = resolved && resolved.route;
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
  if (PLATFORM_HOSTS.has(hostname)) {
    return fetch(request);
  }
  return handleCustomDomain(request, hostname);
}

addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

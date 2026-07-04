// Reverse-proxies requests for tenant custom domains to their published stripe-link page.
//
// Unlike legacy stripe-cart's worker (which redirected through a short_code path), a
// stripe-link custom domain maps directly to one published page's own URL -- the resolve
// endpoint hands back that URL and this worker fetches it verbatim, so the visitor's
// browser never sees anything but the custom domain the whole time.

const PLATFORM_HOSTS = new Set([
  "domains.jbay.uk",
]);

const RESOLVE_ENDPOINT = "https://REPLACE_WITH_PUBLIC_API_BASE_URL/custom-domains/resolve";

async function resolveCustomHost(hostname) {
  const cache = caches.default;
  const cacheKey = new Request(`https://stripe-link-custom-domain-router.local/${hostname}`);
  const cached = await cache.match(cacheKey);
  if (cached) {
    return cached.json();
  }

  const response = await fetch(`${RESOLVE_ENDPOINT}?host=${encodeURIComponent(hostname)}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    return null;
  }

  const bodyText = await response.text();
  const cacheResponse = new Response(bodyText, {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=60",
    },
  });
  await cache.put(cacheKey, cacheResponse.clone());
  return JSON.parse(bodyText);
}

async function handleRequest(request) {
  const sourceUrl = new URL(request.url);
  const hostname = sourceUrl.hostname.toLowerCase();

  if (PLATFORM_HOSTS.has(hostname)) {
    return fetch(request);
  }

  const resolved = await resolveCustomHost(hostname);
  const route = resolved && resolved.route;
  if (!route || route.type !== "origin_url" || !route.origin_url) {
    return new Response("Custom domain is not active.", { status: 404 });
  }

  const proxied = new Request(route.origin_url, request);
  proxied.headers.set("X-Junior-Bay-Custom-Host", hostname);
  return fetch(proxied);
}

addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event.request));
});

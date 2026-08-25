/**
 * Service worker for site use.
 *
 * Scope is deliberately narrow. The application shell and static assets are cached so
 * the app opens without a connection; API responses are NOT cached here — the client
 * keeps its own read-through cache with the timestamp attached, so the operator always
 * sees how old the data is. A silently cached API response would look current.
 */
const SHELL_CACHE = "oneai-twin-shell-v1";
const SHELL_ASSETS = ["/", "/compare", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(cache => cache.addAll(SHELL_ASSETS).catch(() => undefined)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== SHELL_CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  // Never intercept the API or the websocket: freshness there is the client's business.
  if (url.pathname.startsWith("/api/") || url.protocol === "ws:" || url.protocol === "wss:") return;
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.ok && (request.mode === "navigate" || url.pathname.startsWith("/_next/static"))) {
          const copy = response.clone();
          caches.open(SHELL_CACHE).then(cache => cache.put(request, copy));
        }
        return response;
      })
      .catch(async () => (await caches.match(request)) || (await caches.match("/")) || Response.error())
  );
});

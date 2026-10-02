/* Arena service worker: makes the app installable and opens the last-seen pages when offline.
   Pages are always fetched fresh when there is a network (the game changes every few seconds);
   the API is never cached. */
const CACHE = "arena-v1";
const SHELL = ["/", "/play.html", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/") || u.pathname.startsWith("/live/")) return;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(u.pathname === "/play.html" ? "/play.html" : e.request, copy)); }
    return r;
  }).catch(() => caches.match(u.pathname === "/play.html" ? "/play.html" : e.request)));
});

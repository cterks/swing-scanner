// Cache the shell so the app opens offline. Data is always fetched fresh -
// a stale scan shown as today's would be worse than no scan at all.
const SHELL = "swing-shell-v1";
const FILES = ["./", "./index.html", "./manifest.json",
               "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Never serve cached scan data.
  if (url.pathname.endsWith("data.json") || url.pathname.endsWith("record.json")) {
    e.respondWith(fetch(e.request).catch(() =>
      new Response("null", {headers: {"Content-Type": "application/json"}})));
    return;
  }
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});

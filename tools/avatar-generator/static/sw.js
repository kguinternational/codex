const CACHE_NAME = "kgu-twin-cache-v1";
const ASSETS = [
  "/static/index.html",
  "/static/style.css",
  "/static/app.js",
  "/static/images/joann.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
});

self.addEventListener("fetch", (e) => {
  e.respondWith(
    caches.match(e.request).then((cachedResponse) => {
      return cachedResponse || fetch(e.request);
    })
  );
});

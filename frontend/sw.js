// Cache dell'interfaccia per un'apertura rapida; i dati (/api) arrivano sempre dalla rete.
const CACHE = "paperfolio-v13";
const SHELL = [
  "./", "index.html", "manifest.json", "css/style.css", "js/app.js", "js/api.js", "js/format.js",
  "js/screens/portfolio.js", "js/screens/detail.js", "js/screens/order-sheet.js", "js/screens/search.js",
  "js/screens/orders.js", "js/screens/fiscal.js", "js/screens/settings.js",
  "js/screens/auto.js", "js/screens/auto-detail.js", "js/screens/backtest.js", "icons/icon-192.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" }))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  // Rete prima, cache come riserva: dopo un deploy si vede subito la versione nuova
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

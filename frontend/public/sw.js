/* NextPanel service worker: PWA installability, app-shell caching, web push. */

// Bump a name when its caching rules change; activate deletes the old one.
const SHELL_CACHE = "nextpanel-shell-v1";
const ASSET_CACHE = "nextpanel-assets-v1";
// Same-origin pages that are not the app: API responses, FastAPI's docs and
// Cloudflare Access's login/logout endpoints always go straight through.
const NOT_APP_PAGES = ["/api/", "/cdn-cgi/", "/docs", "/redoc", "/openapi.json"];

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const current = new Set([SHELL_CACHE, ASSET_CACHE]);
      for (const name of await caches.keys()) {
        if (name.startsWith("nextpanel-") && !current.has(name)) await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  );
});

// Vite puts a content hash in every /assets file name, so a cached copy can
// never be out of date.
async function fingerprintedAsset(request) {
  const cache = await caches.open(ASSET_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

// Drop assets from previous releases once a newer page no longer uses them.
async function pruneAssets(page) {
  const html = await page.text();
  const used = new Set(html.match(/\/assets\/[^"'\s>]+/g) || []);
  const cache = await caches.open(ASSET_CACHE);
  for (const request of await cache.keys()) {
    if (!used.has(new URL(request.url).pathname)) await cache.delete(request);
  }
}

// Pages always come from the network, so a new release shows up on the next
// load. Every app route is the same index.html; the last good copy is kept
// so the installed app still opens (and explains itself) while offline.
async function appPage(event) {
  try {
    const response = await fetch(event.request);
    const isHtml = (response.headers.get("content-type") || "").includes("text/html");
    if (response.ok && response.type === "basic" && isHtml) {
      const copy = response.clone();
      event.waitUntil(
        (async () => {
          const cache = await caches.open(SHELL_CACHE);
          await cache.put("/", copy.clone());
          await pruneAssets(copy);
        })(),
      );
    }
    return response;
  } catch (error) {
    const shell = await caches.match("/", { cacheName: SHELL_CACHE });
    if (shell) return shell;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(fingerprintedAsset(request));
  } else if (
    request.mode === "navigate" &&
    !NOT_APP_PAGES.some((prefix) => url.pathname.startsWith(prefix))
  ) {
    event.respondWith(appPage(event));
  }
  // API calls, icons and cross-origin covers are left to the browser.
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data && event.data.text() };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "NextPanel", {
      body: data.body || "",
      icon: "/nextpanel-icon-192.png",
      badge: "/nextpanel-icon-192.png",
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  const targetUrl = new URL(url, self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (windows) => {
      for (const client of windows) {
        if ("focus" in client) {
          const navigated = "navigate" in client ? await client.navigate(targetUrl) : null;
          return (navigated || client).focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    }),
  );
});

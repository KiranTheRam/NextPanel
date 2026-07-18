/* NextPanel service worker: PWA installability + web push. */

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// Pass-through fetch handler (kept minimal on purpose: the app is useless
// offline anyway — everything is live request data).
self.addEventListener("fetch", () => {});

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

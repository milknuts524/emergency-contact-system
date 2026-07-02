const SW_VERSION = "2026-07-02-push-production-2";
const CACHE_NAME = "emergency-contact-v9";
const DEBUG_PUSH = false;
const MAINTENANCE_URL = "/static/maintenance.html";
const APP_SHELL = [
  "/",
  "/static/manifest.json",
  MAINTENANCE_URL,
  "/static/icons/icon.svg",
  "/static/icons/maskable-icon.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(async () => {
        return await caches.match(MAINTENANCE_URL) || caches.match("/");
      })
    );
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

self.addEventListener("push", (event) => {
  const fallback = {
    title: "院内緊急連絡",
    body: "通知を受信しました",
    url: "/"
  };

  const showPushNotification = async () => {
    let rawText = "";
    let data = {};

    try {
      if (event.data) {
        rawText = await event.data.text();
      }
    } catch (error) {
      rawText = "";
    }

    try {
      if (rawText) {
        data = JSON.parse(rawText);
      }
    } catch (error) {
      data = {};
    }

    if (!data || typeof data !== "object") {
      data = {};
    }

    const title = DEBUG_PUSH
      ? "DEBUG Push Received"
      : String(data.title || "").trim() || fallback.title;
    const body = DEBUG_PUSH
      ? `SW ${SW_VERSION} received push`
      : String(data.body || rawText || "").trim() || fallback.body;
    const url = String(data.url || "").trim() || fallback.url;

    return self.registration.showNotification(title, {
      body,
      icon: "/static/icons/icon.svg",
      badge: "/static/icons/maskable-icon.svg",
      data: { url }
    });
  };

  event.waitUntil(showPushNotification());
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "GET_VERSION") {
    if (event.source) {
      event.source.postMessage({
        type: "SERVICE_WORKER_VERSION",
        version: SW_VERSION
      });
    }
    if (event.ports && event.ports[0]) {
      event.ports[0].postMessage({ version: SW_VERSION });
    }
    return;
  }

  if (!event.data || event.data.type !== "SHOW_TEST_NOTIFICATION") {
    return;
  }

  const notificationPromise = self.registration.showNotification("Push診断通知", {
    body: `Service Worker showNotification OK\nSW ${SW_VERSION}`,
    icon: "/static/icons/icon.svg",
    badge: "/static/icons/maskable-icon.svg",
    data: { url: "/" }
  });

  if (event.waitUntil) {
    event.waitUntil(notificationPromise);
  }
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url
    ? event.notification.data.url
    : "/";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      const absoluteUrl = new URL(url, self.location.origin).href;

      for (const client of clientList) {
        if (client.url === absoluteUrl && "focus" in client) {
          return client.focus();
        }
      }

      if (clients.openWindow) {
        return clients.openWindow(absoluteUrl);
      }
      return undefined;
    })
  );
});

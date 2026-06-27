const CACHE_NAME = "emergency-contact-v4";
const APP_SHELL = [
  "/",
  "/static/manifest.json",
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
    let data = {};

    try {
      if (event.data) {
        data = event.data.json();
      }
    } catch (error) {
      data = {};
    }

    if (!data || typeof data !== "object") {
      data = {};
    }

    const title = String(data.title || "").trim() || fallback.title;
    const body = String(data.body || "").trim() || fallback.body;
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
  if (!event.data || event.data.type !== "SHOW_TEST_NOTIFICATION") {
    return;
  }

  const notificationPromise = self.registration.showNotification("端末通知テスト", {
    body: "この通知が表示されれば、端末の通知表示は有効です。",
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

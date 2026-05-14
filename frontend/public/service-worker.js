self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

function parsePushPayload(event) {
  if (!event.data) return null;

  try {
    return event.data.json();
  } catch {
    try {
      return JSON.parse(event.data.text());
    } catch {
      return null;
    }
  }
}

function targetUrl(sessionId) {
  const url = new URL("/", self.location.origin);
  if (sessionId) {
    url.searchParams.set("session", sessionId);
  }
  return url.toString();
}

async function focusOrOpenSession(sessionId) {
  const destination = targetUrl(sessionId);
  const windowClients = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  });

  for (const client of windowClients) {
    const url = new URL(client.url);
    if (url.origin !== self.location.origin) continue;
    if (!sessionId || url.searchParams.get("session") === sessionId) {
      if (typeof client.focus === "function") {
        await client.focus();
      }
      if (
        url.toString() !== destination &&
        typeof client.navigate === "function"
      ) {
        await client.navigate(destination);
      }
      return;
    }
  }

  if (windowClients.length > 0) {
    const client = windowClients[0];
    if (typeof client.focus === "function") {
      await client.focus();
    }
    if (typeof client.navigate === "function") {
      await client.navigate(destination);
    }
    return;
  }

  await self.clients.openWindow(destination);
}

async function closeNotificationsByTag(tag) {
  if (!tag) return;
  const notifications = await self.registration.getNotifications({ tag });
  for (const notification of notifications) {
    notification.close();
  }
}

self.addEventListener("push", (event) => {
  event.waitUntil(
    (async () => {
      const payload = parsePushPayload(event);
      if (!payload || typeof payload !== "object") return;

      const tag = payload.tag || payload.notif_id;
      if (payload.kind === "notification_clear") {
        await closeNotificationsByTag(tag);
        return;
      }

      await self.registration.showNotification(payload.title || "carapace", {
        body: payload.body || "",
        tag: tag || undefined,
        icon: payload.icon || "/pwa-192x192.png",
        badge:
          payload.badge && payload.badge !== "/badge-icon.png"
            ? payload.badge
            : "/pwa-192x192.png",
        actions: Array.isArray(payload.actions) ? payload.actions : [],
        requireInteraction: payload.kind === "escalation_pending",
        data: {
          sessionId: payload.session_id || null,
          notifId: payload.notif_id || null,
        },
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    focusOrOpenSession(event.notification.data?.sessionId || null),
  );
});

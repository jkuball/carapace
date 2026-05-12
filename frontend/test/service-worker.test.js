import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

async function loadServiceWorkerHarness() {
  const source = await readFile(
    new URL("../public/service-worker.js", import.meta.url),
    "utf-8",
  );
  const listeners = new Map();
  const showNotificationCalls = [];
  const notificationQueryCalls = [];
  const openWindowCalls = [];
  const notifications = [];

  const self = {
    location: { origin: "https://carapace.example.test" },
    addEventListener(type, handler) {
      listeners.set(type, handler);
    },
    skipWaiting: async () => undefined,
    registration: {
      showNotification: async (...args) => {
        showNotificationCalls.push(args);
      },
      getNotifications: async (options) => {
        notificationQueryCalls.push(options);
        return notifications;
      },
    },
    clients: {
      claim: async () => undefined,
      matchAll: async () => [],
      openWindow: async (url) => {
        openWindowCalls.push(url);
      },
    },
  };

  const context = vm.createContext({
    self,
    URL,
    JSON,
    Array,
    Promise,
    console,
  });
  vm.runInContext(source, context, { filename: "service-worker.js" });

  return {
    self,
    listeners,
    notifications,
    notificationQueryCalls,
    openWindowCalls,
    showNotificationCalls,
  };
}

function waitableEvent(properties = {}) {
  return {
    ...properties,
    promise: Promise.resolve(),
    waitUntil(promise) {
      this.promise = promise;
    },
  };
}

test("push notification_clear closes matching notifications by tag", async () => {
  const harness = await loadServiceWorkerHarness();
  const closed = [];
  harness.notifications.push(
    { close: () => closed.push("first") },
    { close: () => closed.push("second") },
  );

  const event = waitableEvent({
    data: {
      json: () => ({
        kind: "notification_clear",
        notif_id: "esc:session-1:req-1",
      }),
    },
  });

  harness.listeners.get("push")(event);
  await event.promise;

  assert.equal(harness.notificationQueryCalls.length, 1);
  assert.equal(harness.notificationQueryCalls[0].tag, "esc:session-1:req-1");
  assert.deepEqual(closed, ["first", "second"]);
  assert.equal(harness.showNotificationCalls.length, 0);
});

test("push escalation payload shows notification with fallback tag and interaction", async () => {
  const harness = await loadServiceWorkerHarness();
  const event = waitableEvent({
    data: {
      json: () => ({
        kind: "escalation_pending",
        notif_id: "esc:session-2:req-9",
        title: "Escalation",
        body: "Review required",
        session_id: "session-2",
      }),
    },
  });

  harness.listeners.get("push")(event);
  await event.promise;

  assert.equal(harness.showNotificationCalls.length, 1);
  const [title, options] = harness.showNotificationCalls[0];
  assert.equal(title, "Escalation");
  assert.equal(options.tag, "esc:session-2:req-9");
  assert.equal(options.requireInteraction, true);
  assert.equal(options.data.sessionId, "session-2");
});

test("notificationclick focuses existing client and navigates to session", async () => {
  const harness = await loadServiceWorkerHarness();
  let focused = false;
  let navigatedTo = null;

  harness.self.clients.matchAll = async () => [
    {
      url: "https://carapace.example.test/?view=settings",
      focus: async () => {
        focused = true;
      },
      navigate: async (url) => {
        navigatedTo = url;
      },
    },
  ];

  let closed = false;
  const event = waitableEvent({
    notification: {
      close: () => {
        closed = true;
      },
      data: { sessionId: "session-7" },
    },
  });

  harness.listeners.get("notificationclick")(event);
  await event.promise;

  assert.equal(closed, true);
  assert.equal(focused, true);
  assert.equal(navigatedTo, "https://carapace.example.test/?session=session-7");
  assert.deepEqual(harness.openWindowCalls, []);
});

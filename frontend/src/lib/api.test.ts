import assert from "node:assert/strict";
import test from "node:test";
import {
  deleteNotificationSubscription,
  getVapidPublicKey,
  sendTestNotification,
} from "./api";
import {
  listNotificationSubscriptions,
  postNotificationSubscriptionPresence,
} from "./api";

const originalFetch = globalThis.fetch;

function setFetch(handler: typeof fetch): void {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: handler,
  });
}

test.afterEach(() => {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: originalFetch,
  });
});

test("getVapidPublicKey returns configured key", async () => {
  setFetch(
    async () =>
      new Response(JSON.stringify({ vapid_public_key: "test-public-key" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
  );

  const vapidPublicKey = await getVapidPublicKey(
    "https://carapace.example.test",
  );

  assert.equal(vapidPublicKey, "test-public-key");
});

test("getVapidPublicKey surfaces backend detail messages on failure", async () => {
  setFetch(
    async () =>
      new Response(
        JSON.stringify({ detail: "VAPID public key is not configured" }),
        {
          status: 404,
          headers: { "Content-Type": "application/json" },
        },
      ),
  );

  await assert.rejects(
    () => getVapidPublicKey("https://carapace.example.test"),
    /VAPID public key is not configured/,
  );
});

test("deleteNotificationSubscription ignores missing subscriptions", async () => {
  let called = 0;
  setFetch(async () => {
    called += 1;
    return new Response(null, { status: 404 });
  });

  await deleteNotificationSubscription(
    "https://carapace.example.test",
    "token-1",
    "sub-1",
  );

  assert.equal(called, 1);
});

test("listNotificationSubscriptions surfaces backend detail messages on failure", async () => {
  setFetch(
    async () =>
      new Response(
        JSON.stringify({ detail: "subscription store unavailable" }),
        {
          status: 503,
          headers: { "Content-Type": "application/json" },
        },
      ),
  );

  await assert.rejects(
    () =>
      listNotificationSubscriptions("https://carapace.example.test", "token-1"),
    /subscription store unavailable/,
  );
});

test("postNotificationSubscriptionPresence rejects failed heartbeats", async () => {
  setFetch(async () => new Response(null, { status: 500 }));

  await assert.rejects(
    () =>
      postNotificationSubscriptionPresence(
        "https://carapace.example.test",
        "token-1",
        "sub-1",
        {
          session_id: "session-1",
          client_type: "web",
          focus_state: "visible",
        },
      ),
    /Failed to update notification subscription presence: 500/,
  );
});


test("sendTestNotification surfaces backend detail messages on failure", async () => {
  setFetch(
    async () =>
      new Response(
        JSON.stringify({ detail: "Failed to deliver test notification" }),
        {
          status: 502,
          headers: { "Content-Type": "application/json" },
        },
      ),
  );

  await assert.rejects(
    () =>
      sendTestNotification(
        "https://carapace.example.test",
        "token-1",
        "sub-1",
      ),
    /Failed to deliver test notification/,
  );
});

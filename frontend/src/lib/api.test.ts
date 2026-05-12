import assert from "node:assert/strict";
import test from "node:test";
import { deleteNotificationSubscription, getVapidPublicKey } from "./api";

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

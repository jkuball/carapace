import assert from "node:assert/strict";
import test from "node:test";
import {
  createAdminUser,
  deleteNotificationSubscription,
  getVapidPublicKey,
  listAdminUsers,
  sendTestNotification,
  updateAdminUser,
  upgradeAdminUserData,
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

test("admin user helpers send bearer token and parse users", async () => {
  const calls: Request[] = [];
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    calls.push(request);
    return new Response(
      JSON.stringify([
        {
          username: "thies",
          enabled: true,
          token_version: 2,
          display_name: "Thies",
          email: "thies@example.test",
          roles: ["admin"],
          created_at: "2026-05-24T12:00:00Z",
          updated_at: "2026-05-24T12:00:00Z",
          password_changed_at: "2026-05-24T12:00:00Z",
          last_login_at: null,
          config: {},
        },
      ]),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

  const users = await listAdminUsers("https://carapace.example.test", "admin-token");

  assert.equal(calls[0].headers.get("Authorization"), "Bearer admin-token");
  assert.equal(users[0].username, "thies");
  assert.equal(users[0].roles[0], "admin");
});

test("createAdminUser posts admin payload", async () => {
  let capturedBody = "";
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    capturedBody = await request.text();
    return new Response(
      JSON.stringify({
        username: "ada",
        enabled: true,
        token_version: 1,
        display_name: "Ada",
        email: null,
        roles: [],
        created_at: "2026-05-24T12:00:00Z",
        updated_at: "2026-05-24T12:00:00Z",
        password_changed_at: "2026-05-24T12:00:00Z",
        last_login_at: null,
        config: {},
      }),
      { status: 201, headers: { "Content-Type": "application/json" } },
    );
  });

  const user = await createAdminUser("https://carapace.example.test", "admin-token", {
    username: "ada",
    password: "secret",
    display_name: "Ada",
  });

  assert.equal(JSON.parse(capturedBody).username, "ada");
  assert.equal(user.username, "ada");
});

test("updateAdminUser encodes username and surfaces backend errors", async () => {
  let capturedUrl = "";
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    capturedUrl = request.url;
    return new Response(JSON.stringify({ detail: "User not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  });

  await assert.rejects(
    () => updateAdminUser("https://carapace.example.test", "admin-token", "ada lovelace", { enabled: false }),
    /User not found/,
  );
  assert.equal(capturedUrl, "https://carapace.example.test/api/admin/users/ada%20lovelace");
});

test("upgradeAdminUserData posts to the selected user's upgrade endpoint", async () => {
  let capturedRequest: Request | null = null;
  setFetch(async (input, init) => {
    capturedRequest = new Request(input, init);
    return new Response(
      JSON.stringify({ username: "thies", summary: { sessions: ["set owner for session-1"] } }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

  const result = await upgradeAdminUserData("https://carapace.example.test", "admin-token", "thies");

  assert.equal(capturedRequest?.method, "POST");
  assert.equal(capturedRequest?.url, "https://carapace.example.test/api/admin/users/thies/upgrade-data");
  assert.equal(capturedRequest?.headers.get("Authorization"), "Bearer admin-token");
  assert.deepEqual(result.summary.sessions, ["set owner for session-1"]);
});

import assert from "node:assert/strict";
import test from "node:test";
import { useSessionPresence } from "./use-session-presence";
import {
  flushReact,
  installDom,
  renderReact,
} from "../../test/react-test-utils";

const originalFetch = globalThis.fetch;

function setDocumentHidden(hidden: boolean): void {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
}

function HookHarness({
  server,
  token,
  sessionId,
  status,
  sourceId,
}: {
  server: string;
  token: string;
  sessionId: string;
  status: "disconnected" | "connecting" | "connected";
  sourceId: string;
}) {
  useSessionPresence(server, token, sessionId, status, sourceId);
  return null;
}

test.afterEach(() => {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: originalFetch,
  });
});

test("useSessionPresence sends visible, hidden, and inactive heartbeats including subscription-backed presence", async () => {
  const restoreDom = installDom();
  const fetchCalls: Array<{ url: string; body: Record<string, unknown> }> = [];

  try {
    localStorage.setItem("carapace_notification_subscription_id", "sub-1");
    setDocumentHidden(false);
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      writable: true,
      value: async (input: string | URL | Request, init?: RequestInit) => {
        fetchCalls.push({
          url: String(input),
          body: JSON.parse(String(init?.body ?? "{}")),
        });
        return new Response(null, { status: 200 });
      },
    });

    const view = await renderReact(
      <HookHarness
        server="https://carapace.example.test"
        token="token-1"
        sessionId="session-1"
        status="connected"
        sourceId="tab-1"
      />,
    );
    await flushReact();

    assert.equal(fetchCalls.length, 2);
    assert.equal(fetchCalls[0]?.url.endsWith("/api/notifications/presence"), true);
    assert.deepEqual(fetchCalls[0]?.body, {
      session_id: "session-1",
      source_id: "tab-1",
      client_type: "web",
      focus_state: "visible",
    });
    assert.equal(
      fetchCalls[1]?.url.endsWith("/api/notifications/subscriptions/sub-1/presence"),
      true,
    );
    assert.deepEqual(fetchCalls[1]?.body, {
      session_id: "session-1",
      client_type: "web",
      focus_state: "visible",
    });

    setDocumentHidden(true);
    document.dispatchEvent(new window.Event("visibilitychange"));
    await flushReact();

    assert.deepEqual(fetchCalls.slice(2, 4).map((call) => call.body.focus_state), [
      "hidden",
      "hidden",
    ]);

    await view.unmount();
    await flushReact();

    assert.deepEqual(fetchCalls.slice(4, 6).map((call) => call.body.focus_state), [
      "inactive",
      "inactive",
    ]);
  } finally {
    restoreDom();
  }
});

test("useSessionPresence does nothing until websocket status is connected", async () => {
  const restoreDom = installDom();
  let fetchCount = 0;

  try {
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      writable: true,
      value: async () => {
        fetchCount += 1;
        return new Response(null, { status: 200 });
      },
    });

    const view = await renderReact(
      <HookHarness
        server="https://carapace.example.test"
        token="token-1"
        sessionId="session-1"
        status="connecting"
        sourceId="tab-1"
      />,
    );
    await flushReact();

    assert.equal(fetchCount, 0);

    await view.unmount();
  } finally {
    restoreDom();
  }
});

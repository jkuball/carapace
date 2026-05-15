import assert from "node:assert/strict";
import test from "node:test";
import {
  dispatchWindowEvent,
  flushReact,
  installDom,
  renderReact,
  runInAct,
} from "../../test/react-test-utils";

const messages = {
  preferences: {
    notifications: {
      title: "Push notifications",
      description: "Deliver escalations and turn outcomes to this browser or installed PWA.",
      status: {
        loading: "Checking notification support…",
        loadingShort: "Checking",
        enabled: "Notifications are enabled for this browser.",
        enabledShort: "Enabled",
        disabled: "Notifications are off for this browser.",
        disabledShort: "Off",
        unsupported: "This browser cannot receive Web Push notifications in the current context.",
        permissionDenied: "Browser notification permission is blocked. Re-enable it in browser or device settings.",
        permissionRequired: "Notification permission was not granted.",
        invalidSubscription: "Browser returned an incomplete push subscription.",
        loadFailed: "Failed to load notification settings.",
        enableFailed: "Failed to enable notifications.",
        disableFailed: "Failed to disable notifications.",
        preferencesFailed: "Failed to update notification preferences.",
        testFailed: "Failed to send test notification.",
        testSent: "Test notification sent.",
      },
      deviceName: {
        label: "Device name",
        placeholder: "Android phone",
        hint: "Shown in server-side notification subscriptions for this browser.",
      },
      actions: {
        enable: "Enable notifications",
        enabling: "Enabling…",
        disable: "Disable notifications",
        disabling: "Disabling…",
        test: "Send test notification",
        testing: "Sending test notification…",
      },
      preferences: {
        label: "Send notifications for",
        escalation_pending: "Escalations that need approval",
        attended_turn_completed: "Attended sessions when a turn finishes",
        unattended_turn_completed: "Unattended jobs that finish successfully",
        unattended_turn_failed: "Unattended jobs that fail",
      },
      meta: {
        permission: "Browser permission: {permission}",
        heartbeat: "Last heartbeat: {timestamp}",
        expires: "Subscription expires: {timestamp}",
      },
      permission: {
        default: "not requested",
        granted: "granted",
        denied: "denied",
      },
    },
  },
};

function translate(path: string, values?: Record<string, string>): string {
  const result = path.split(".").reduce<unknown>((current, key) => {
    if (current && typeof current === "object" && key in current) {
      return (current as Record<string, unknown>)[key];
    }
    return undefined;
  }, messages);
  if (typeof result !== "string") {
    return path;
  }
  if (!values) {
    return result;
  }
  return Object.entries(values).reduce(
    (message, [key, value]) => message.replaceAll(`{${key}}`, value),
    result,
  );
}

const originalFetch = globalThis.fetch;
const originalNotification = globalThis.Notification;

type FetchCall = {
  url: string;
  init?: RequestInit;
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mountNotification(permission: NotificationPermission, nextPermission = permission): void {
  let currentPermission = permission;
  const notification = {
    get permission() {
      return currentPermission;
    },
    async requestPermission() {
      currentPermission = nextPermission;
      return currentPermission;
    },
  } as unknown as typeof Notification;

  Object.defineProperty(globalThis, "Notification", {
    configurable: true,
    writable: true,
    value: notification,
  });
  Object.defineProperty(window, "Notification", {
    configurable: true,
    writable: true,
    value: notification,
  });
}

function installPushSupport(registration: ServiceWorkerRegistration): void {
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value: true,
  });
  Object.defineProperty(window, "PushManager", {
    configurable: true,
    writable: true,
    value: class PushManager {},
  });
  Object.defineProperty(window.navigator, "serviceWorker", {
    configurable: true,
    value: {
      register: async () => registration,
    },
  });
}

async function renderSubscription(): Promise<Awaited<ReturnType<typeof renderReact>>> {
  const { NotificationSubscription } = await import("./notification-subscription");
  const view = await renderReact(
    <NotificationSubscription
      server="https://carapace.example.test"
      token="token-1"
      translate={(key, values) => translate(`preferences.notifications.${key}`, values)}
    />,
  );
  await runInAct(async () => {
    await Promise.resolve();
  });
  return view;
}

async function settleSubscriptionView(): Promise<void> {
  await flushReact();
  await runInAct(async () => {
    await new Promise<void>((resolve) => {
      window.setTimeout(resolve, 0);
    });
  });
  await flushReact();
}

test.afterEach(() => {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: originalFetch,
  });
  Object.defineProperty(globalThis, "Notification", {
    configurable: true,
    writable: true,
    value: originalNotification,
  });
});

test("NotificationSubscription hydrates an active subscription and renders enabled preferences", async () => {
  const restoreDom = installDom();
  const fetchCalls: FetchCall[] = [];
  const savedSubscription = {
    subscription_id: "sub-1",
    device_name: "Android device (Chrome)",
    endpoint: "https://push.example.test/sub-1",
    subscribed_at: "2026-05-12T10:00:00Z",
    expires_at: "2026-06-11T10:00:00Z",
    last_heartbeat: "2026-05-12T10:00:00Z",
    preferences: {
      escalation_pending: true,
      attended_turn_completed: true,
      unattended_turn_completed: false,
      unattended_turn_failed: true,
    },
  };

  try {
    localStorage.setItem("carapace_notification_subscription_id", "sub-1");
    mountNotification("granted");
    installPushSupport({
      pushManager: {
        getSubscription: async () => ({
          endpoint: savedSubscription.endpoint,
          expirationTime: null,
          options: { applicationServerKey: null, userVisibleOnly: true },
          getKey: () => null,
          toJSON: () => ({ keys: { p256dh: "key-1", auth: "auth-1" } }),
          unsubscribe: async () => true,
        }),
        subscribe: async () => {
          throw new Error("subscribe should not run during hydration");
        },
      },
    } as unknown as ServiceWorkerRegistration);

    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      writable: true,
      value: async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        fetchCalls.push({ url, init });
        if (url.endsWith("/api/notifications/subscriptions") && !init?.method) {
          return jsonResponse([savedSubscription]);
        }
        throw new Error(`Unhandled fetch ${url}`);
      },
    });

    const view = await renderSubscription();
    await settleSubscriptionView();

    const notificationSwitch = view.container.querySelector('button[role="switch"]');
    assert.ok(notificationSwitch);
    assert.equal(notificationSwitch.getAttribute("aria-checked"), "true");

    assert.equal(localStorage.getItem("carapace_notification_subscription_id"), "sub-1");
    assert.equal(localStorage.getItem("carapace_notification_device_name"), "Android device (Chrome)");
    assert.equal(view.container.querySelectorAll('button[role="switch"]').length, 5);
    assert.match(view.container.textContent ?? "", /Browser permission: granted/);
    assert.match(view.container.textContent ?? "", /Send test notification/);

    await view.unmount();
  } finally {
    restoreDom();
  }
});


test("NotificationSubscription sends a test notification for the active browser subscription", async () => {
  const restoreDom = installDom();
  const fetchCalls: FetchCall[] = [];
  const savedSubscription = {
    subscription_id: "sub-1",
    device_name: "Android device (Chrome)",
    endpoint: "https://push.example.test/sub-1",
    subscribed_at: "2026-05-12T10:00:00Z",
    expires_at: "2026-06-11T10:00:00Z",
    last_heartbeat: "2026-05-12T10:00:00Z",
    preferences: {
      escalation_pending: true,
      attended_turn_completed: true,
      unattended_turn_completed: false,
      unattended_turn_failed: true,
    },
  };

  try {
    localStorage.setItem("carapace_notification_subscription_id", "sub-1");
    mountNotification("granted");
    installPushSupport({
      pushManager: {
        getSubscription: async () => ({
          endpoint: savedSubscription.endpoint,
          expirationTime: null,
          options: { applicationServerKey: null, userVisibleOnly: true },
          getKey: () => null,
          toJSON: () => ({ keys: { p256dh: "key-1", auth: "auth-1" } }),
          unsubscribe: async () => true,
        }),
        subscribe: async () => {
          throw new Error("subscribe should not run during test notification");
        },
      },
    } as unknown as ServiceWorkerRegistration);

    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      writable: true,
      value: async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        fetchCalls.push({ url, init });
        if (url.endsWith("/api/notifications/subscriptions") && !init?.method) {
          return jsonResponse([savedSubscription]);
        }
        if (url.endsWith("/api/notifications/subscriptions/sub-1/test") && init?.method === "POST") {
          return jsonResponse({ delivered: true });
        }
        throw new Error(`Unhandled fetch ${url}`);
      },
    });

    const view = await renderSubscription();
    await flushReact();
    await flushReact();

    const testButton = Array.from(view.container.querySelectorAll("button")).find((button) =>
      (button.textContent ?? "").includes("Send test notification"),
    );
    assert.ok(testButton);

    testButton.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await flushReact();
    await flushReact();

    assert.equal(
      fetchCalls.some(
        ({ url, init }) =>
          url.endsWith("/api/notifications/subscriptions/sub-1/test") && init?.method === "POST",
      ),
      true,
    );
    assert.match(view.container.textContent ?? "", /Test notification sent\./);

    await view.unmount();
  } finally {
    restoreDom();
  }
});

test("NotificationSubscription surfaces load failures from the subscription API", async () => {
  const restoreDom = installDom();
  const fetchCalls: FetchCall[] = [];

  try {
    mountNotification("granted");
    installPushSupport({
      pushManager: {
        getSubscription: async () => null,
        subscribe: async () => {
          throw new Error("subscribe should not run during error handling");
        },
      },
    } as unknown as ServiceWorkerRegistration);

    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      writable: true,
      value: async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        fetchCalls.push({ url, init });
        if (url.endsWith("/api/notifications/subscriptions") && !init?.method) {
          return jsonResponse({ detail: "subscription store unavailable" }, 503);
        }
        throw new Error(`Unhandled fetch ${url}`);
      },
    });

    const view = await renderSubscription();
    await flushReact();
    await flushReact();

    assert.match(view.container.textContent ?? "", /subscription store unavailable/);
    assert.equal(fetchCalls.length, 1);

    await view.unmount();
  } finally {
    restoreDom();
  }
});

test("NotificationSubscription refreshes displayed permission when the window regains focus", async () => {
  const restoreDom = installDom();

  try {
    mountNotification("default");
    installPushSupport({
      pushManager: {
        getSubscription: async () => null,
        subscribe: async () => {
          throw new Error("subscribe should not run");
        },
      },
    } as unknown as ServiceWorkerRegistration);

    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      writable: true,
      value: async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/notifications/subscriptions") && !init?.method) {
          return jsonResponse([]);
        }
        throw new Error(`Unhandled fetch ${url}`);
      },
    });

    const view = await renderSubscription();
    await settleSubscriptionView();

    const notificationSwitch = view.container.querySelector('button[role="switch"]');
    assert.ok(notificationSwitch);
    assert.equal(notificationSwitch.getAttribute("aria-checked"), "false");
    assert.match(view.container.textContent ?? "", /Deliver escalations and turn outcomes/);

    mountNotification("denied");
    await dispatchWindowEvent(new window.Event("focus"));
    await settleSubscriptionView();

    assert.match(view.container.textContent ?? "", /Browser notification permission is blocked/);
    assert.equal(notificationSwitch.hasAttribute("disabled"), true);

    await view.unmount();
  } finally {
    restoreDom();
  }
});

test("ensureCurrentPushSubscription replaces stale browser subscriptions after VAPID key rotation", async () => {
  const { ensureCurrentPushSubscription } = await import("./notification-subscription");
  const currentVapidKey = Uint8Array.from([1, 2, 3, 4, 5, 6]);
  const previousVapidKey = Uint8Array.from([6, 5, 4, 3, 2, 1]);
  let unsubscribed = false;
  let subscribedWithKey: Uint8Array | null = null;

  const nextSubscription = await ensureCurrentPushSubscription(
    {
      pushManager: {
        getSubscription: async () => ({
          endpoint: "https://push.example.test/sub-stale",
          expirationTime: null,
          options: { applicationServerKey: previousVapidKey.buffer, userVisibleOnly: true },
          getKey: () => null,
          toJSON: () => ({ keys: { p256dh: "stale-key", auth: "stale-auth" } }),
          unsubscribe: async () => {
            unsubscribed = true;
            return true;
          },
        }),
        subscribe: async ({ applicationServerKey }: PushSubscriptionOptionsInit) => {
          subscribedWithKey = new Uint8Array(applicationServerKey as ArrayBuffer);
          return {
            endpoint: "https://push.example.test/sub-new",
            expirationTime: null,
            options: { applicationServerKey, userVisibleOnly: true },
            getKey: () => null,
            toJSON: () => ({ keys: { p256dh: "new-key", auth: "new-auth" } }),
            unsubscribe: async () => true,
          } as PushSubscription;
        },
      },
    } as unknown as ServiceWorkerRegistration,
    currentVapidKey.buffer,
  );

  assert.equal(unsubscribed, true);
  assert.deepEqual(Array.from(subscribedWithKey ?? []), Array.from(currentVapidKey));
  assert.equal(nextSubscription.endpoint, "https://push.example.test/sub-new");
});

test("pushServerKeysMatch detects stale VAPID-bound browser subscriptions", async () => {
  const { pushServerKeysMatch } = await import("./notification-subscription");
  const currentVapidKey = Uint8Array.from([1, 2, 3, 4, 5, 6]).buffer;
  const previousVapidKey = Uint8Array.from([6, 5, 4, 3, 2, 1]).buffer;

  assert.equal(pushServerKeysMatch(currentVapidKey, currentVapidKey), true);
  assert.equal(pushServerKeysMatch(previousVapidKey, currentVapidKey), false);
  assert.equal(
    pushServerKeysMatch(Uint8Array.from([1, 2, 3, 4, 5, 6]), currentVapidKey),
    true,
  );
  assert.equal(pushServerKeysMatch(null, currentVapidKey), false);
});

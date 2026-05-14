import assert from "node:assert/strict";
import test from "node:test";
import {
  buildNotificationDeviceName,
  decodeVapidPublicKey,
  registerNotificationServiceWorker,
  supportsPushNotifications,
} from "./notifications";

const originalWindow = globalThis.window;
const originalNavigator = globalThis.navigator;

function setGlobal(name: string, value: unknown): void {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    writable: true,
    value,
  });
}

function restoreGlobals(): void {
  if (originalWindow === undefined) {
    delete (globalThis as { window?: Window }).window;
  } else {
    setGlobal("window", originalWindow);
  }

  if (originalNavigator === undefined) {
    delete (globalThis as { navigator?: Navigator }).navigator;
  } else {
    setGlobal("navigator", originalNavigator);
  }
}

test.afterEach(() => {
  restoreGlobals();
});

test("supportsPushNotifications returns true only for secure browsers with required APIs", () => {
  setGlobal("window", {
    isSecureContext: true,
    Notification: class Notification {},
    PushManager: class PushManager {},
  });
  setGlobal("navigator", {
    serviceWorker: {
      register: async () => null,
    },
  });

  assert.equal(supportsPushNotifications(), true);

  setGlobal("window", {
    isSecureContext: false,
    Notification: class Notification {},
    PushManager: class PushManager {},
  });

  assert.equal(supportsPushNotifications(), false);
});

test("decodeVapidPublicKey decodes url-safe base64 into an ArrayBuffer", () => {
  const bytes = Uint8Array.from([1, 2, 3, 4, 250, 251]);
  const encoded = Buffer.from(bytes)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");

  setGlobal("window", {
    atob,
  });

  const decoded = new Uint8Array(decodeVapidPublicKey(encoded));

  assert.deepEqual(Array.from(decoded), Array.from(bytes));
});

test("buildNotificationDeviceName derives a readable device and browser label", () => {
  setGlobal("navigator", {
    userAgent:
      "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Mobile Safari/537.36",
  });

  assert.equal(buildNotificationDeviceName(), "Android device (Chrome)");
});

test("registerNotificationServiceWorker delegates to navigator.serviceWorker when supported", async () => {
  const registration = { scope: "/" } as ServiceWorkerRegistration;
  let registerCall: { url: string; options: { scope: string } } | null = null;

  setGlobal("window", {
    isSecureContext: true,
    Notification: class Notification {},
    PushManager: class PushManager {},
  });
  setGlobal("navigator", {
    serviceWorker: {
      register: async (url: string, options: { scope: string }) => {
        registerCall = { url, options };
        return registration;
      },
    },
  });

  const result = await registerNotificationServiceWorker();

  assert.equal(result, registration);
  assert.deepEqual(registerCall, {
    url: "/service-worker.js",
    options: { scope: "/" },
  });
});

test("registerNotificationServiceWorker returns null when push is unsupported", async () => {
  setGlobal("window", {
    isSecureContext: false,
  });
  setGlobal("navigator", {});

  const result = await registerNotificationServiceWorker();

  assert.equal(result, null);
});

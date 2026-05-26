import assert from "node:assert/strict";
import test from "node:test";
import {
  clearConnection,
  clearNotificationSubscriptionId,
  getNotificationDeviceName,
  getNotificationSubscriptionId,
  getPresenceClientId,
  getShowArchivedSessionsPreference,
  getServer,
  getToken,
  hasConnection,
  saveConnection,
  saveNotificationDeviceName,
  saveNotificationSubscriptionId,
  saveShowArchivedSessionsPreference,
} from "./storage";

type StorageLike = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

const originalWindow = globalThis.window;
const originalCrypto = globalThis.crypto;
const originalLocalStorage = globalThis.localStorage;
const originalSessionStorage = globalThis.sessionStorage;

function createStorage(): StorageLike {
  const values = new Map<string, string>();
  return {
    getItem(key: string): string | null {
      return values.get(key) ?? null;
    },
    setItem(key: string, value: string): void {
      values.set(key, value);
    },
    removeItem(key: string): void {
      values.delete(key);
    },
  };
}

function setWindow(value: unknown): void {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    writable: true,
    value,
  });
}

function setCrypto(value: unknown): void {
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    writable: true,
    value,
  });
}

test.beforeEach(() => {
  const localStorage = createStorage();
  const sessionStorage = createStorage();
  setWindow({
    localStorage,
    sessionStorage,
    location: { origin: "https://carapace.example.test" },
  });
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: localStorage,
  });
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    writable: true,
    value: sessionStorage,
  });
  setCrypto({
    randomUUID: () => "presence-uuid-1",
  });
});

test.afterEach(() => {
  if (originalWindow === undefined) {
    delete (globalThis as { window?: Window }).window;
  } else {
    setWindow(originalWindow);
  }

  if (originalCrypto === undefined) {
    delete (globalThis as { crypto?: Crypto }).crypto;
  } else {
    setCrypto(originalCrypto);
  }

  if (originalLocalStorage === undefined) {
    delete (globalThis as { localStorage?: Storage }).localStorage;
  } else {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      writable: true,
      value: originalLocalStorage,
    });
  }

  if (originalSessionStorage === undefined) {
    delete (globalThis as { sessionStorage?: Storage }).sessionStorage;
  } else {
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      writable: true,
      value: originalSessionStorage,
    });
  }
});

test("connection helpers use same-origin server and username state", () => {
  localStorage.setItem("carapace_server", "https://old.example.test");

  assert.equal(getServer(), "https://carapace.example.test");
  assert.equal(localStorage.getItem("carapace_server"), null);
  assert.equal(hasConnection(), false);

  saveConnection("thies");

  assert.equal(getServer(), "https://carapace.example.test");
  assert.equal(getToken(), "thies");
  assert.equal(hasConnection(), true);
  assert.equal(localStorage.getItem("carapace_server"), null);

  clearConnection();

  assert.equal(getServer(), "https://carapace.example.test");
  assert.equal(getToken(), "");
  assert.equal(hasConnection(), false);
});

test("getPresenceClientId is stable within one browser session", () => {
  const first = getPresenceClientId();
  const second = getPresenceClientId();

  assert.equal(first, "presence-uuid-1");
  assert.equal(second, "presence-uuid-1");
});

test("notification subscription helpers persist and clear local state", () => {
  saveNotificationSubscriptionId("sub-1");
  saveNotificationDeviceName("Android Phone");

  assert.equal(getNotificationSubscriptionId(), "sub-1");
  assert.equal(getNotificationDeviceName(), "Android Phone");

  clearNotificationSubscriptionId();

  assert.equal(getNotificationSubscriptionId(), "");
  assert.equal(getNotificationDeviceName(), "Android Phone");
});

test("archived chat visibility preference defaults to hidden and persists", () => {
  assert.equal(getShowArchivedSessionsPreference(), false);

  saveShowArchivedSessionsPreference(true);
  assert.equal(getShowArchivedSessionsPreference(), true);

  saveShowArchivedSessionsPreference(false);
  assert.equal(getShowArchivedSessionsPreference(), false);
});

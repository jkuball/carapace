const SERVICE_WORKER_URL = "/service-worker.js";

export function supportsPushNotifications(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    window.isSecureContext &&
    "Notification" in window &&
    "serviceWorker" in navigator &&
    "PushManager" in window
  );
}

export async function registerNotificationServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!supportsPushNotifications()) return null;
  return navigator.serviceWorker.register(SERVICE_WORKER_URL, { scope: "/" });
}

export function decodeVapidPublicKey(vapidPublicKey: string): ArrayBuffer {
  const padding = "=".repeat((4 - (vapidPublicKey.length % 4)) % 4);
  const normalized = (vapidPublicKey + padding)
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const decoded = window.atob(normalized);
  const output = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) {
    output[index] = decoded.charCodeAt(index);
  }
  const arrayBuffer = new ArrayBuffer(output.byteLength);
  new Uint8Array(arrayBuffer).set(output);
  return arrayBuffer;
}

export function buildNotificationDeviceName(): string {
  if (typeof navigator === "undefined") return "This device";

  const userAgent = navigator.userAgent.toLowerCase();
  let device = "This device";
  if (userAgent.includes("android")) {
    device = "Android device";
  } else if (
    userAgent.includes("iphone") ||
    userAgent.includes("ipad") ||
    userAgent.includes("ipod")
  ) {
    device = "iPhone or iPad";
  } else if (userAgent.includes("mac")) {
    device = "Mac";
  } else if (userAgent.includes("windows")) {
    device = "Windows PC";
  } else if (userAgent.includes("linux")) {
    device = "Linux device";
  }

  let browser = "";
  if (userAgent.includes("edg/")) {
    browser = "Edge";
  } else if (userAgent.includes("chrome/")) {
    browser = "Chrome";
  } else if (userAgent.includes("firefox/")) {
    browser = "Firefox";
  } else if (userAgent.includes("safari/") && !userAgent.includes("chrome/")) {
    browser = "Safari";
  }

  return browser ? `${device} (${browser})` : device;
}

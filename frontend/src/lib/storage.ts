const SERVER_KEY = "carapace_server";
const TOKEN_KEY = "carapace_token";
const LOCALE_OVERRIDE_KEY = "carapace_locale_override";
const PRESENCE_CLIENT_ID_KEY = "carapace_presence_client_id";
const NOTIFICATION_SUBSCRIPTION_ID_KEY =
  "carapace_notification_subscription_id";
const NOTIFICATION_DEVICE_NAME_KEY = "carapace_notification_device_name";

export type LocaleOverride = "system" | "en" | "de";

export function getServer(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(SERVER_KEY) ?? "";
}

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function saveConnection(server: string, token: string) {
  localStorage.setItem(SERVER_KEY, server);
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearConnection() {
  localStorage.removeItem(SERVER_KEY);
  localStorage.removeItem(TOKEN_KEY);
}

export function hasConnection(): boolean {
  return !!getServer() && !!getToken();
}

export function getLocaleOverride(): LocaleOverride {
  if (typeof window === "undefined") return "system";

  const value = localStorage.getItem(LOCALE_OVERRIDE_KEY);
  return value === "en" || value === "de" || value === "system"
    ? value
    : "system";
}

export function saveLocaleOverride(localeOverride: LocaleOverride): void {
  localStorage.setItem(LOCALE_OVERRIDE_KEY, localeOverride);
}

export function getPresenceClientId(): string {
  if (typeof window === "undefined") return "";

  const existing = window.sessionStorage.getItem(PRESENCE_CLIENT_ID_KEY);
  if (existing) return existing;

  const generated =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `presence-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  window.sessionStorage.setItem(PRESENCE_CLIENT_ID_KEY, generated);
  return generated;
}

export function getNotificationSubscriptionId(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(NOTIFICATION_SUBSCRIPTION_ID_KEY) ?? "";
}

export function saveNotificationSubscriptionId(subscriptionId: string): void {
  localStorage.setItem(NOTIFICATION_SUBSCRIPTION_ID_KEY, subscriptionId);
}

export function clearNotificationSubscriptionId(): void {
  localStorage.removeItem(NOTIFICATION_SUBSCRIPTION_ID_KEY);
}

export function getNotificationDeviceName(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(NOTIFICATION_DEVICE_NAME_KEY) ?? "";
}

export function saveNotificationDeviceName(deviceName: string): void {
  localStorage.setItem(NOTIFICATION_DEVICE_NAME_KEY, deviceName);
}

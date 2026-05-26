import { normalizeServer } from "./server-url";

const SERVER_KEY = "carapace_server";
const USERNAME_KEY = "carapace_username";
const LOCALE_OVERRIDE_KEY = "carapace_locale_override";
const SHOW_ARCHIVED_SESSIONS_KEY = "carapace_show_archived_sessions";
const PRESENCE_CLIENT_ID_KEY = "carapace_presence_client_id";
const NOTIFICATION_SUBSCRIPTION_ID_KEY =
  "carapace_notification_subscription_id";
const NOTIFICATION_DEVICE_NAME_KEY = "carapace_notification_device_name";

export type LocaleOverride = "system" | "en" | "de";

export function getServer(): string {
  if (typeof window === "undefined") return "";
  localStorage.removeItem(SERVER_KEY);
  return normalizeServer(window.location.origin);
}

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(USERNAME_KEY) ?? "";
}

export function saveConnection(username: string) {
  localStorage.removeItem(SERVER_KEY);
  localStorage.setItem(USERNAME_KEY, username);
}

export function clearConnection() {
  localStorage.removeItem(SERVER_KEY);
  localStorage.removeItem(USERNAME_KEY);
}

export function hasConnection(): boolean {
  return !!getToken();
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

export function getShowArchivedSessionsPreference(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(SHOW_ARCHIVED_SESSIONS_KEY) === "true";
}

export function saveShowArchivedSessionsPreference(
  showArchivedSessions: boolean,
): void {
  localStorage.setItem(
    SHOW_ARCHIVED_SESSIONS_KEY,
    showArchivedSessions ? "true" : "false",
  );
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

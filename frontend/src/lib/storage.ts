const SERVER_KEY = "carapace_server";
const TOKEN_KEY = "carapace_token";
const LOCALE_OVERRIDE_KEY = "carapace_locale_override";

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

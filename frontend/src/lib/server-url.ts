export function defaultServer(): string {
  if (typeof window === "undefined") return "";
  return normalizeServer(window.location.origin);
}

export function normalizeServer(server: string): string {
  return server.trim().replace(/\/$/, "");
}

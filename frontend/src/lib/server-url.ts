export function defaultServer(): string {
  if (typeof window === "undefined") return "http://127.0.0.1:8321";
  const url = new URL(window.location.origin);
  if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
    return `${url.protocol}//${url.hostname}:8321`;
  }
  return window.location.origin;
}

export function normalizeServer(server: string): string {
  return server.trim().replace(/\/$/, "");
}

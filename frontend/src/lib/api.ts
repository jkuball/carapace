import type {
  HistoryMessage,
  JobDefinition,
  JobRunResult,
  JobsFile,
  NotificationPreferencesPatch,
  NotificationSubscriptionCreateRequest,
  NotificationSubscriptionRecord,
  SessionArchiveCommitResponse,
  SessionAttributesPatch,
  SessionInfo,
  SessionListPage,
  SessionSandboxSnapshot,
} from "./types";
import { isRecord, readNumber, readString, readStringArray } from "./decoding";

export const AUTH_REQUIRED_EVENT = "carapace:auth-required";

function requestPath(input: RequestInfo | URL): string {
  if (input instanceof Request) return new URL(input.url).pathname;
  if (input instanceof URL) return input.pathname;
  return new URL(input, "http://carapace.local").pathname;
}

function shouldEmitAuthRequired(input: RequestInfo | URL): boolean {
  const path = requestPath(input);
  return path !== "/api/auth/login" && path !== "/api/auth/logout";
}

function emitAuthRequired(input: RequestInfo | URL): void {
  if (typeof window === "undefined" || !shouldEmitAuthRequired(input)) return;
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
}

async function fetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const response = await globalThis.fetch(input, {
    ...init,
    credentials: "include",
  });
  if (response.status === 401) {
    emitAuthRequired(input);
  }
  return response;
}

function headers(_session: string): HeadersInit {
  void _session;
  return {
    "Content-Type": "application/json",
  };
}

async function readErrorMessage(
  res: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = await res.json();
    if (isRecord(body)) {
      const detail = readString(body, "detail");
      if (detail) return detail;
    }
  } catch {
    // Ignore parse errors and fall back to the generic status message below.
  }
  return `${fallback}: ${res.status}`;
}

export interface ServerMeta {
  version: string;
}

export interface AuthUserInfo {
  username: string;
  display_name: string | null;
  roles: string[];
}

export interface WebSocketTicketResponse {
  ticket: string;
}

export interface AdminUserInfo {
  username: string;
  enabled: boolean;
  token_version: number;
  display_name: string;
  email: string | null;
  roles: string[];
  created_at: string;
  updated_at: string;
  password_changed_at: string;
  last_login_at: string | null;
  config: unknown;
}

export interface AdminUserCreateInput {
  username: string;
  password: string;
  display_name?: string;
  email?: string | null;
  roles?: string[];
}

export interface AdminUserUpdateInput {
  display_name?: string;
  email?: string | null;
  roles?: string[];
  enabled?: boolean;
  password?: string;
}

function decodeAdminUser(raw: unknown): AdminUserInfo | null {
  if (!isRecord(raw)) return null;

  const username = readString(raw, "username");
  const displayName = readString(raw, "display_name");
  const createdAt = readString(raw, "created_at");
  const updatedAt = readString(raw, "updated_at");
  const passwordChangedAt = readString(raw, "password_changed_at");
  const tokenVersion = readNumber(raw, "token_version");
  if (
    !username ||
    displayName === undefined ||
    !createdAt ||
    !updatedAt ||
    !passwordChangedAt ||
    tokenVersion === undefined ||
    typeof raw.enabled !== "boolean"
  ) {
    return null;
  }

  return {
    username,
    enabled: raw.enabled,
    token_version: tokenVersion,
    display_name: displayName,
    email: readString(raw, "email") ?? null,
    roles: readStringArray(raw, "roles") ?? [],
    created_at: createdAt,
    updated_at: updatedAt,
    password_changed_at: passwordChangedAt,
    last_login_at: readString(raw, "last_login_at") ?? null,
    config: raw.config,
  };
}

function decodeAdminUsers(raw: unknown): AdminUserInfo[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => decodeAdminUser(item))
    .filter((item): item is AdminUserInfo => item !== null);
}

function decodeAuthUser(raw: unknown): AuthUserInfo | null {
  if (!isRecord(raw)) return null;
  const username = readString(raw, "username");
  if (!username) return null;
  return {
    username,
    display_name: readString(raw, "display_name") ?? null,
    roles: readStringArray(raw, "roles") ?? [],
  };
}

export async function login(
  server: string,
  username: string,
  password: string,
): Promise<AuthUserInfo> {
  const res = await fetch(`${server}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Login failed"));
  }
  const body: unknown = await res.json();
  if (!isRecord(body) || !isRecord(body.user)) {
    throw new Error("Invalid login response");
  }
  const user = decodeAuthUser(body.user);
  if (user === null) {
    throw new Error("Invalid login response");
  }
  return user;
}

export async function getCurrentUser(server: string): Promise<AuthUserInfo> {
  const res = await fetch(`${server}/api/auth/me`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(
      await readErrorMessage(res, "Failed to fetch current user"),
    );
  }
  const user = decodeAuthUser(await res.json());
  if (user === null) {
    throw new Error("Invalid user response");
  }
  return user;
}

export async function getWebSocketTicket(
  server: string,
  token: string,
): Promise<string> {
  const res = await fetch(`${server}/api/auth/ws-ticket`, {
    method: "POST",
    headers: headers(token),
  });
  if (!res.ok)
    throw new Error(
      await readErrorMessage(res, "Failed to create websocket ticket"),
    );
  const body = (await res.json()) as WebSocketTicketResponse;
  return body.ticket;
}

export async function logout(server: string): Promise<void> {
  const res = await fetch(`${server}/api/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok && res.status !== 401) {
    throw new Error(await readErrorMessage(res, "Logout failed"));
  }
}

export async function listAdminUsers(server: string): Promise<AdminUserInfo[]> {
  const res = await fetch(`${server}/api/admin/users`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to list users"));
  }
  return decodeAdminUsers(await res.json());
}

export async function createAdminUser(
  server: string,
  body: AdminUserCreateInput,
): Promise<AdminUserInfo> {
  const res = await fetch(`${server}/api/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to create user"));
  }
  const user = decodeAdminUser(await res.json());
  if (user === null) {
    throw new Error("Invalid user response");
  }
  return user;
}

export async function updateAdminUser(
  server: string,
  username: string,
  body: AdminUserUpdateInput,
): Promise<AdminUserInfo> {
  const res = await fetch(
    `${server}/api/admin/users/${encodeURIComponent(username)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to update user"));
  }
  const user = decodeAdminUser(await res.json());
  if (user === null) {
    throw new Error("Invalid user response");
  }
  return user;
}

export async function deleteAdminUser(
  server: string,
  username: string,
): Promise<void> {
  const res = await fetch(
    `${server}/api/admin/users/${encodeURIComponent(username)}`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to delete user"));
  }
}

export async function getServerMeta(
  server: string,
  token: string,
): Promise<ServerMeta> {
  const res = await fetch(`${server}/api/meta`, {
    headers: headers(token),
  });
  if (!res.ok)
    throw new Error(`Failed to fetch server metadata: ${res.status}`);
  return res.json();
}

export async function listSessions(
  server: string,
  token: string,
  options?: {
    includeArchived?: boolean;
    includeMessageCount?: boolean;
    limit?: number;
    cursor?: string | null;
  },
): Promise<SessionListPage> {
  const params = new URLSearchParams();
  if (options?.includeMessageCount ?? true) {
    params.set("include_message_count", "true");
  }
  if (options?.includeArchived) {
    params.set("include_archived", "true");
  }
  if (typeof options?.limit === "number") {
    params.set("limit", String(options.limit));
  }
  if (options?.cursor) {
    params.set("cursor", options.cursor);
  }
  const res = await fetch(`${server}/api/sessions?${params.toString()}`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.status}`);
  return res.json();
}

export async function getSession(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionInfo> {
  const res = await fetch(`${server}/api/sessions/${sessionId}`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to fetch session: ${res.status}`);
  return res.json();
}

export async function createSession(
  server: string,
  token: string,
  options?: {
    private?: boolean;
    unattended?: boolean;
    ask_mode?: boolean;
    yolo_mode?: boolean;
  },
): Promise<SessionInfo> {
  const res = await fetch(`${server}/api/sessions`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({ channel_type: "web", ...(options ?? {}) }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  return res.json();
}

export async function updateSession(
  server: string,
  token: string,
  sessionId: string,
  body: {
    attributes?: SessionAttributesPatch;
    agent_model_name?: string | null;
    sentinel_model_name?: string | null;
  },
): Promise<SessionInfo> {
  const res = await fetch(`${server}/api/sessions/${sessionId}`, {
    method: "PATCH",
    headers: headers(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed to update session: ${res.status}`);
  return res.json();
}

export async function forkSession(
  server: string,
  token: string,
  sessionId: string,
  body: {
    eventIndex: number;
    channelType: string;
    channelRef?: string;
    unattended?: boolean;
    ask_mode?: boolean;
    yolo_mode?: boolean;
  },
): Promise<SessionInfo> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/fork`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({
      event_index: body.eventIndex,
      channel_type: body.channelType,
      channel_ref: body.channelRef ?? "",
      unattended: body.unattended,
      ask_mode: body.ask_mode,
      yolo_mode: body.yolo_mode,
    }),
  });
  if (!res.ok) throw new Error(`Failed to fork session: ${res.status}`);
  return res.json();
}

export async function commitSessionKnowledge(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionArchiveCommitResponse> {
  const res = await fetch(
    `${server}/api/sessions/${sessionId}/knowledge/commit`,
    {
      method: "POST",
      headers: headers(token),
    },
  );
  if (!res.ok)
    throw new Error(`Failed to commit session knowledge: ${res.status}`);
  return res.json();
}

export async function deleteSession(
  server: string,
  token: string,
  sessionId: string,
): Promise<void> {
  const res = await fetch(`${server}/api/sessions/${sessionId}`, {
    method: "DELETE",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to delete session: ${res.status}`);
}

export async function fetchSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to fetch sandbox: ${res.status}`);
  return res.json();
}

export async function startSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox/up`, {
    method: "POST",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to start sandbox: ${res.status}`);
  return res.json();
}

export async function stopSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox/down`, {
    method: "POST",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to scale down sandbox: ${res.status}`);
  return res.json();
}

export async function wipeSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox/wipe`, {
    method: "POST",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to wipe sandbox: ${res.status}`);
  return res.json();
}

export async function fetchHistory(
  server: string,
  token: string,
  sessionId: string,
): Promise<HistoryMessage[]> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/history`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to fetch history: ${res.status}`);
  return res.json();
}

export async function postInteractivePresence(
  server: string,
  token: string,
  body: {
    session_id: string;
    source_id: string;
    client_type: "web" | "matrix" | "cli";
    focus_state: "visible" | "hidden" | "inactive";
  },
  options?: { keepalive?: boolean },
): Promise<void> {
  const res = await fetch(`${server}/api/notifications/presence`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify(body),
    keepalive: options?.keepalive,
  });
  if (!res.ok) {
    throw new Error(`Failed to update presence: ${res.status}`);
  }
}

export async function postNotificationSubscriptionPresence(
  server: string,
  token: string,
  subscriptionId: string,
  body: {
    session_id: string;
    client_type: "web" | "matrix" | "cli";
    focus_state: "visible" | "hidden" | "inactive";
  },
  options?: { keepalive?: boolean },
): Promise<void> {
  const res = await fetch(
    `${server}/api/notifications/subscriptions/${subscriptionId}/presence`,
    {
      method: "POST",
      headers: headers(token),
      body: JSON.stringify(body),
      keepalive: options?.keepalive,
    },
  );
  if (!res.ok) {
    throw new Error(
      `Failed to update notification subscription presence: ${res.status}`,
    );
  }
}

export async function getVapidPublicKey(server: string): Promise<string> {
  const res = await fetch(`${server}/api/config/vapid-public-key`);
  if (!res.ok) {
    throw new Error(
      await readErrorMessage(res, "Failed to fetch VAPID public key"),
    );
  }
  const body = await res.json();
  if (!isRecord(body)) {
    throw new Error("Invalid VAPID public key response");
  }
  const vapidPublicKey = readString(body, "vapid_public_key");
  if (!vapidPublicKey) {
    throw new Error("Missing VAPID public key in response");
  }
  return vapidPublicKey;
}

export async function listNotificationSubscriptions(
  server: string,
  token: string,
): Promise<NotificationSubscriptionRecord[]> {
  const res = await fetch(`${server}/api/notifications/subscriptions`, {
    headers: headers(token),
  });
  if (!res.ok) {
    throw new Error(
      await readErrorMessage(res, "Failed to list notification subscriptions"),
    );
  }
  return res.json();
}

export async function upsertNotificationSubscription(
  server: string,
  token: string,
  body: NotificationSubscriptionCreateRequest,
): Promise<NotificationSubscriptionRecord> {
  const res = await fetch(`${server}/api/notifications/subscriptions`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(
      await readErrorMessage(res, "Failed to save notification subscription"),
    );
  }
  return res.json();
}

export async function updateNotificationSubscriptionPreferences(
  server: string,
  token: string,
  subscriptionId: string,
  body: NotificationPreferencesPatch,
): Promise<NotificationSubscriptionRecord> {
  const res = await fetch(
    `${server}/api/notifications/subscriptions/${subscriptionId}/preferences`,
    {
      method: "PATCH",
      headers: headers(token),
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorMessage(res, "Failed to update notification preferences"),
    );
  }
  return res.json();
}

export async function sendTestNotification(
  server: string,
  token: string,
  subscriptionId: string,
): Promise<void> {
  const res = await fetch(
    `${server}/api/notifications/subscriptions/${subscriptionId}/test`,
    {
      method: "POST",
      headers: headers(token),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorMessage(res, "Failed to send test notification"),
    );
  }
}

export async function deleteNotificationSubscription(
  server: string,
  token: string,
  subscriptionId: string,
): Promise<void> {
  const res = await fetch(
    `${server}/api/notifications/subscriptions/${subscriptionId}`,
    {
      method: "DELETE",
      headers: headers(token),
    },
  );
  if (!res.ok && res.status !== 404) {
    throw new Error(
      await readErrorMessage(res, "Failed to delete notification subscription"),
    );
  }
}

export interface SlashCommand {
  command: string;
  description: string;
}

export function decodeSlashCommand(raw: unknown): SlashCommand | null {
  if (!isRecord(raw)) return null;

  const command = readString(raw, "command");
  const description = readString(raw, "description");
  if (!command || description === undefined) return null;

  return { command, description };
}

function decodeSlashCommands(raw: unknown): SlashCommand[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => decodeSlashCommand(item))
    .filter((item): item is SlashCommand => item !== null);
}

export async function fetchCommands(
  server: string,
  token: string,
): Promise<SlashCommand[]> {
  const res = await fetch(`${server}/api/commands`, {
    headers: headers(token),
  });
  if (!res.ok) return [];
  const raw: unknown = await res.json();
  return decodeSlashCommands(raw);
}

export interface AvailableModelInfo {
  id: string;
  provider: string;
  name: string;
  max_input_tokens?: number | null;
}

export interface SessionBudgetSettings {
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: string | null;
  tool_calls?: number | null;
}

export interface UserDefaultModelsSettings {
  agent?: string | null;
  sentinel?: string | null;
  title?: string | null;
}

export interface MatrixSettingsInfo {
  enabled: boolean;
  homeserver: string;
  user_id: string;
  device_name: string;
  password_set: boolean;
  token_set: boolean;
  allowed_rooms: string[];
  allowed_users: string[];
}

export interface BasicAuthSettingsInfo {
  username: string;
  password_set: boolean;
}

export type CredentialBackendSettingsInfo =
  | {
      type: "file";
      path: string;
      expose: string[];
      hide: string[];
    }
  | {
      type: "bitwarden";
      url: string;
      basic_auth?: BasicAuthSettingsInfo | null;
      expose: string[];
      hide: string[];
    };

export interface CredentialsSettingsInfo {
  backends: Record<string, CredentialBackendSettingsInfo>;
}

export interface GitSettingsInfo {
  remote: string;
  branch: string;
  author: string;
  token_set: boolean;
}

export interface UserSettingsInfo {
  default_models: UserDefaultModelsSettings;
  default_budget: SessionBudgetSettings;
  matrix: MatrixSettingsInfo;
  credentials: CredentialsSettingsInfo;
  git: GitSettingsInfo;
}

export interface UserSettingsResponseInfo {
  capabilities: {
    credentials: {
      bitwarden: boolean;
      file: boolean;
    };
  };
  server_defaults: {
    models: {
      agent: string;
      sentinel: string;
      title: string;
    };
    budget: SessionBudgetSettings;
  };
  available_models: AvailableModelInfo[];
  settings: UserSettingsInfo;
}

export interface UserSettingsPatchInput {
  default_models?: UserDefaultModelsSettings | null;
  default_budget?: SessionBudgetSettings | null;
  matrix?: Partial<{
    enabled: boolean;
    homeserver: string | null;
    user_id: string | null;
    device_name: string | null;
    password: string | null;
    clear_password: boolean;
    token: string | null;
    clear_token: boolean;
    allowed_rooms: string[];
    allowed_users: string[];
  }> | null;
  credentials?: unknown;
  git?: Partial<{
    remote: string | null;
    branch: string | null;
    author: string | null;
    token: string | null;
    clear_token: boolean;
  }> | null;
}

function readBoolean(
  record: Record<string, unknown>,
  key: string,
  fallback = false,
): boolean {
  const value = record[key];
  return typeof value === "boolean" ? value : fallback;
}

function decodeBudget(raw: unknown): SessionBudgetSettings {
  if (!isRecord(raw)) return {};
  const cost =
    readString(raw, "cost_usd") ??
    (typeof raw.cost_usd === "number" ? String(raw.cost_usd) : undefined);
  return {
    input_tokens: readNumber(raw, "input_tokens") ?? null,
    output_tokens: readNumber(raw, "output_tokens") ?? null,
    cost_usd: cost ?? null,
    tool_calls: readNumber(raw, "tool_calls") ?? null,
  };
}

function decodeDefaultModels(raw: unknown): UserDefaultModelsSettings {
  if (!isRecord(raw)) return {};
  return {
    agent: readString(raw, "agent") ?? null,
    sentinel: readString(raw, "sentinel") ?? null,
    title: readString(raw, "title") ?? null,
  };
}

function decodeMatrixSettings(raw: unknown): MatrixSettingsInfo {
  const record = isRecord(raw) ? raw : {};
  return {
    enabled: readBoolean(record, "enabled"),
    homeserver: readString(record, "homeserver") ?? "",
    user_id: readString(record, "user_id") ?? "",
    device_name: readString(record, "device_name") ?? "carapace",
    password_set: readBoolean(record, "password_set"),
    token_set: readBoolean(record, "token_set"),
    allowed_rooms: readStringArray(record, "allowed_rooms") ?? [],
    allowed_users: readStringArray(record, "allowed_users") ?? [],
  };
}

function decodeCredentialsSettings(raw: unknown): CredentialsSettingsInfo {
  if (!isRecord(raw) || !isRecord(raw.backends)) return { backends: {} };
  const backends: Record<string, CredentialBackendSettingsInfo> = {};
  for (const [name, backend] of Object.entries(raw.backends)) {
    if (!isRecord(backend)) continue;
    const type = readString(backend, "type");
    if (type === "file") {
      backends[name] = {
        type: "file",
        path: readString(backend, "path") ?? "",
        expose: readStringArray(backend, "expose") ?? [],
        hide: readStringArray(backend, "hide") ?? [],
      };
    } else if (type === "bitwarden") {
      const basicAuth = isRecord(backend.basic_auth)
        ? {
            username: readString(backend.basic_auth, "username") ?? "",
            password_set: readBoolean(backend.basic_auth, "password_set"),
          }
        : null;
      backends[name] = {
        type: "bitwarden",
        url: readString(backend, "url") ?? "http://127.0.0.1:8087",
        basic_auth: basicAuth,
        expose: readStringArray(backend, "expose") ?? [],
        hide: readStringArray(backend, "hide") ?? [],
      };
    }
  }
  return { backends };
}

function decodeGitSettings(raw: unknown): GitSettingsInfo {
  const record = isRecord(raw) ? raw : {};
  return {
    remote: readString(record, "remote") ?? "",
    branch: readString(record, "branch") ?? "main",
    author: readString(record, "author") ?? "carapace <carapace@%h>",
    token_set: readBoolean(record, "token_set"),
  };
}

function decodeUserSettingsResponse(raw: unknown): UserSettingsResponseInfo {
  if (!isRecord(raw)) throw new Error("Invalid settings response");
  const capabilities = isRecord(raw.capabilities) ? raw.capabilities : {};
  const credentialCapabilities = isRecord(capabilities.credentials)
    ? capabilities.credentials
    : {};
  const serverDefaults = isRecord(raw.server_defaults)
    ? raw.server_defaults
    : {};
  const serverModels = isRecord(serverDefaults.models)
    ? serverDefaults.models
    : {};
  const settings = isRecord(raw.settings) ? raw.settings : {};
  return {
    capabilities: {
      credentials: {
        bitwarden: readBoolean(credentialCapabilities, "bitwarden", true),
        file: readBoolean(credentialCapabilities, "file"),
      },
    },
    server_defaults: {
      models: {
        agent: readString(serverModels, "agent") ?? "",
        sentinel: readString(serverModels, "sentinel") ?? "",
        title: readString(serverModels, "title") ?? "",
      },
      budget: decodeBudget(serverDefaults.budget),
    },
    available_models: decodeAvailableModels(raw.available_models),
    settings: {
      default_models: decodeDefaultModels(settings.default_models),
      default_budget: decodeBudget(settings.default_budget),
      matrix: decodeMatrixSettings(settings.matrix),
      credentials: decodeCredentialsSettings(settings.credentials),
      git: decodeGitSettings(settings.git),
    },
  };
}

export function decodeAvailableModel(raw: unknown): AvailableModelInfo | null {
  if (typeof raw === "string") {
    if (!raw) return null;
    const splitIndex = raw.indexOf(":");
    if (splitIndex === -1) {
      return { id: raw, provider: "", name: raw, max_input_tokens: null };
    }

    return {
      id: raw,
      provider: raw.slice(0, splitIndex),
      name: raw.slice(splitIndex + 1),
      max_input_tokens: null,
    };
  }

  if (!isRecord(raw)) return null;

  const rawId =
    readString(raw, "id") ??
    (typeof raw.id === "number" ? String(raw.id) : undefined);
  if (!rawId) return null;

  return {
    id: rawId,
    provider: readString(raw, "provider") ?? "",
    name: readString(raw, "name") ?? "",
    max_input_tokens: readNumber(raw, "max_input_tokens") ?? null,
  };
}

function decodeAvailableModels(raw: unknown): AvailableModelInfo[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => decodeAvailableModel(item))
    .filter((item): item is AvailableModelInfo => item !== null);
}

export async function fetchModels(
  server: string,
  token: string,
): Promise<AvailableModelInfo[]> {
  const res = await fetch(`${server}/api/models`, { headers: headers(token) });
  if (!res.ok) return [];
  const raw: unknown = await res.json();
  return decodeAvailableModels(raw);
}

export async function getUserSettings(
  server: string,
  token: string,
): Promise<UserSettingsResponseInfo> {
  const res = await fetch(`${server}/api/user/settings`, {
    headers: headers(token),
  });
  if (!res.ok)
    throw new Error(
      await readErrorMessage(res, "Failed to load user settings"),
    );
  return decodeUserSettingsResponse(await res.json());
}

export async function updateUserSettings(
  server: string,
  token: string,
  body: UserSettingsPatchInput,
): Promise<UserSettingsResponseInfo> {
  const res = await fetch(`${server}/api/user/settings`, {
    method: "PATCH",
    headers: headers(token),
    body: JSON.stringify(body),
  });
  if (!res.ok)
    throw new Error(
      await readErrorMessage(res, "Failed to update user settings"),
    );
  return decodeUserSettingsResponse(await res.json());
}

export async function listJobs(
  server: string,
  token: string,
): Promise<JobsFile> {
  const res = await fetch(`${server}/api/jobs`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to list jobs: ${res.status}`);
  return res.json();
}

export async function createJob(
  server: string,
  token: string,
  body: JobDefinition,
): Promise<JobDefinition> {
  const res = await fetch(`${server}/api/jobs`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed to create job: ${res.status}`);
  return res.json();
}

export async function updateJob(
  server: string,
  token: string,
  jobId: string,
  body: JobDefinition,
): Promise<JobDefinition> {
  const res = await fetch(`${server}/api/jobs/${encodeURIComponent(jobId)}`, {
    method: "PUT",
    headers: headers(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed to update job: ${res.status}`);
  return res.json();
}

export async function deleteJob(
  server: string,
  token: string,
  jobId: string,
): Promise<void> {
  const res = await fetch(`${server}/api/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to delete job: ${res.status}`);
}

export async function runJob(
  server: string,
  token: string,
  jobId: string,
  data?: string,
): Promise<JobRunResult> {
  const res = await fetch(
    `${server}/api/jobs/${encodeURIComponent(jobId)}/run`,
    {
      method: "POST",
      headers: headers(token),
      body: JSON.stringify({ data: data ?? null }),
    },
  );
  if (!res.ok) throw new Error(`Failed to run job: ${res.status}`);
  return res.json();
}

export function wsUrl(
  server: string,
  sessionId: string,
  _session: string,
  clientId?: string,
  ticket?: string,
): string {
  void _session;
  const base = server.replace("http://", "ws://").replace("https://", "wss://");
  const params = new URLSearchParams();
  if (clientId) {
    params.set("client_id", clientId);
  }
  if (ticket) {
    params.set("ticket", ticket);
  }
  const query = params.toString();
  return `${base}/api/chat/${sessionId}${query ? `?${query}` : ""}`;
}

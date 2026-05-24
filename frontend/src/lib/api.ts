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

async function fetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  return globalThis.fetch(input, { ...init, credentials: "include" });
}

function headers(_session: string): HeadersInit {
  void _session;
  return {
    "Content-Type": "application/json",
  };
}

function adminHeaders(adminToken: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${adminToken}`,
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
    !username
    || displayName === undefined
    || !createdAt
    || !updatedAt
    || !passwordChangedAt
    || tokenVersion === undefined
    || typeof raw.enabled !== "boolean"
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
  const parsedUsername = readString(body.user, "username");
  if (!parsedUsername) {
    throw new Error("Invalid login response");
  }
  return {
    username: parsedUsername,
    display_name: readString(body.user, "display_name") ?? null,
  };
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

export async function listAdminUsers(
  server: string,
  adminToken: string,
): Promise<AdminUserInfo[]> {
  const res = await fetch(`${server}/api/admin/users`, {
    headers: adminHeaders(adminToken),
  });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to list users"));
  }
  return decodeAdminUsers(await res.json());
}

export async function createAdminUser(
  server: string,
  adminToken: string,
  body: AdminUserCreateInput,
): Promise<AdminUserInfo> {
  const res = await fetch(`${server}/api/admin/users`, {
    method: "POST",
    headers: adminHeaders(adminToken),
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
  adminToken: string,
  username: string,
  body: AdminUserUpdateInput,
): Promise<AdminUserInfo> {
  const res = await fetch(`${server}/api/admin/users/${encodeURIComponent(username)}`, {
    method: "PATCH",
    headers: adminHeaders(adminToken),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to update user"));
  }
  const user = decodeAdminUser(await res.json());
  if (user === null) {
    throw new Error("Invalid user response");
  }
  return user;
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
): string {
  void _session;
  const base = server.replace("http://", "ws://").replace("https://", "wss://");
  const params = new URLSearchParams();
  if (clientId) {
    params.set("client_id", clientId);
  }
  const query = params.toString();
  return `${base}/api/chat/${sessionId}${query ? `?${query}` : ""}`;
}

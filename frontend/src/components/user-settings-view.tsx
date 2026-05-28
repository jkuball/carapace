"use client";

import { Check, Loader2, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getUserSettings,
  updateUserSettings,
  type AvailableModelInfo,
  type CredentialsSettingsInfo,
  type MatrixSettingsInfo,
  type SessionBudgetSettings,
  type UserDefaultModelsSettings,
  type UserSettingsPatchInput,
  type UserSettingsResponseInfo,
} from "@/lib/api";
import { ModelPicker, withSelectedModelOption } from "@/components/model-picker";
import { SwitchRow } from "@/components/switch-row";
import { cn } from "@/lib/utils";

interface UserSettingsDraft {
  defaultModels: UserDefaultModelsSettings;
  budget: Record<keyof Required<SessionBudgetSettings>, string>;
  matrix: MatrixSettingsInfo;
  matrixPassword: string;
  matrixToken: string;
  clearMatrixPassword: boolean;
  clearMatrixToken: boolean;
  credentialsJson: string;
  git: {
    remote: string;
    branch: string;
    author: string;
    token_set: boolean;
  };
  gitToken: string;
  clearGitToken: boolean;
}

const inputClassName = cn(
  "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm",
  "outline-none transition-colors placeholder:text-muted-foreground/50",
  "focus:border-ring focus:ring-2 focus:ring-ring/30",
);

const FILE_CREDENTIAL_BACKEND_ENV = "CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND";

function linesToArray(value: string): string[] {
  return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function arrayToLines(values: string[]): string {
  return values.join("\n");
}

function credentialConfigForEdit(credentials: CredentialsSettingsInfo): unknown {
  const backends: Record<string, unknown> = {};
  for (const [name, backend] of Object.entries(credentials.backends)) {
    if (backend.type === "file") {
      backends[name] = {
        type: "file",
        path: backend.path,
        expose: backend.expose,
        hide: backend.hide,
      };
      continue;
    }
    backends[name] = {
      type: "bitwarden",
      url: backend.url,
      ...(backend.basic_auth ? { basic_auth: { username: backend.basic_auth.username } } : {}),
      expose: backend.expose,
      hide: backend.hide,
    };
  }
  return { backends };
}

function stringifyCredentials(credentials: CredentialsSettingsInfo): string {
  return JSON.stringify(credentialConfigForEdit(credentials), null, 2);
}

function budgetValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function draftFromSettings(response: UserSettingsResponseInfo): UserSettingsDraft {
  const budget = response.settings.default_budget;
  return {
    defaultModels: response.settings.default_models,
    budget: {
      input_tokens: budgetValue(budget.input_tokens),
      output_tokens: budgetValue(budget.output_tokens),
      cost_usd: budgetValue(budget.cost_usd),
      tool_calls: budgetValue(budget.tool_calls),
    },
    matrix: response.settings.matrix,
    matrixPassword: "",
    matrixToken: "",
    clearMatrixPassword: false,
    clearMatrixToken: false,
    credentialsJson: stringifyCredentials(response.settings.credentials),
    git: response.settings.git,
    gitToken: "",
    clearGitToken: false,
  };
}

function parseOptionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed.replaceAll(",", "").replaceAll("_", ""));
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

function budgetFromDraft(draft: UserSettingsDraft): SessionBudgetSettings {
  return {
    input_tokens: parseOptionalNumber(draft.budget.input_tokens),
    output_tokens: parseOptionalNumber(draft.budget.output_tokens),
    cost_usd: draft.budget.cost_usd.trim() || null,
    tool_calls: parseOptionalNumber(draft.budget.tool_calls),
  };
}

export function UserSettingsView({ server, token }: { server: string; token: string }) {
  const [settings, setSettings] = useState<UserSettingsResponseInfo | null>(null);
  const [draft, setDraft] = useState<UserSettingsDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getUserSettings(server, token);
      setSettings(response);
      setDraft(draftFromSettings(response));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load user settings");
    } finally {
      setLoading(false);
    }
  }, [server, token]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSettings();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [loadSettings]);

  const availableModels: AvailableModelInfo[] = useMemo(
    () => settings?.available_models ?? [],
    [settings?.available_models],
  );
  const agentOptions = useMemo(
    () => withSelectedModelOption(availableModels, draft?.defaultModels.agent),
    [availableModels, draft?.defaultModels.agent],
  );
  const sentinelOptions = useMemo(
    () => withSelectedModelOption(availableModels, draft?.defaultModels.sentinel),
    [availableModels, draft?.defaultModels.sentinel],
  );
  const titleOptions = useMemo(
    () => withSelectedModelOption(availableModels, draft?.defaultModels.title),
    [availableModels, draft?.defaultModels.title],
  );

  function updateDraft(patch: Partial<UserSettingsDraft>): void {
    setDraft((current) => current ? { ...current, ...patch } : current);
  }

  function updateMatrix(patch: Partial<MatrixSettingsInfo>): void {
    setDraft((current) => current ? { ...current, matrix: { ...current.matrix, ...patch } } : current);
  }

  async function handleSave(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!draft) return;

    let credentialsPayload: unknown;
    try {
      credentialsPayload = JSON.parse(draft.credentialsJson || "{\"backends\":{}}");
    } catch {
      setError("Credential backend JSON is invalid");
      setNotice(null);
      return;
    }

    const body: UserSettingsPatchInput = {
      default_models: {
        agent: draft.defaultModels.agent?.trim() || null,
        sentinel: draft.defaultModels.sentinel?.trim() || null,
        title: draft.defaultModels.title?.trim() || null,
      },
      default_budget: budgetFromDraft(draft),
      matrix: {
        enabled: draft.matrix.enabled,
        homeserver: draft.matrix.homeserver,
        user_id: draft.matrix.user_id,
        device_name: draft.matrix.device_name,
        allowed_rooms: draft.matrix.allowed_rooms,
        allowed_users: draft.matrix.allowed_users,
        ...(draft.matrixPassword ? { password: draft.matrixPassword } : {}),
        ...(draft.matrixToken ? { token: draft.matrixToken } : {}),
        ...(draft.clearMatrixPassword ? { clear_password: true } : {}),
        ...(draft.clearMatrixToken ? { clear_token: true } : {}),
      },
      credentials: credentialsPayload,
      git: {
        remote: draft.git.remote,
        branch: draft.git.branch,
        author: draft.git.author,
        ...(draft.gitToken ? { token: draft.gitToken } : {}),
        ...(draft.clearGitToken ? { clear_token: true } : {}),
      },
    };

    setSaving(true);
    setError(null);
    try {
      const response = await updateUserSettings(server, token, body);
      setSettings(response);
      setDraft(draftFromSettings(response));
      setNotice("Saved.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to update user settings");
      setNotice(null);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading settings
      </div>
    );
  }

  if (!draft || !settings) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-sm text-destructive">
        {error ?? "Settings are unavailable"}
      </div>
    );
  }

  const fileBackendText = settings.capabilities.credentials.file
    ? `file backend enabled by ${FILE_CREDENTIAL_BACKEND_ENV}`
    : `file backend disabled by ${FILE_CREDENTIAL_BACKEND_ENV}`;

  return (
    <form onSubmit={(event) => void handleSave(event)} className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        {(error || notice) ? (
          <div className={cn("rounded-xl border border-border bg-background px-4 py-3 text-sm", error ? "text-destructive" : "text-muted-foreground")}>
            {error ?? <span className="inline-flex items-center gap-2"><Check className="h-4 w-4" />{notice}</span>}
          </div>
        ) : null}

        <Section title="Default models">
          <div className="grid gap-4 lg:grid-cols-3">
            <Field label="Agent">
              <ModelPicker
                value={draft.defaultModels.agent}
                entries={agentOptions}
                onChange={(agent) => updateDraft({ defaultModels: { ...draft.defaultModels, agent } })}
                disabled={saving}
                defaultLabel={settings.server_defaults.models.agent || "Server default"}
              />
            </Field>
            <Field label="Sentinel">
              <ModelPicker
                value={draft.defaultModels.sentinel}
                entries={sentinelOptions}
                onChange={(sentinel) => updateDraft({ defaultModels: { ...draft.defaultModels, sentinel } })}
                disabled={saving}
                defaultLabel={settings.server_defaults.models.sentinel || "Server default"}
              />
            </Field>
            <Field label="Title">
              <ModelPicker
                value={draft.defaultModels.title}
                entries={titleOptions}
                onChange={(title) => updateDraft({ defaultModels: { ...draft.defaultModels, title } })}
                disabled={saving}
                defaultLabel={settings.server_defaults.models.title || "Server default"}
              />
            </Field>
          </div>
        </Section>

        <Section title="Default budget">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <BudgetInput label="Input tokens" value={draft.budget.input_tokens} onChange={(value) => updateDraft({ budget: { ...draft.budget, input_tokens: value } })} />
            <BudgetInput label="Output tokens" value={draft.budget.output_tokens} onChange={(value) => updateDraft({ budget: { ...draft.budget, output_tokens: value } })} />
            <BudgetInput label="Cost USD" value={draft.budget.cost_usd} onChange={(value) => updateDraft({ budget: { ...draft.budget, cost_usd: value } })} />
            <BudgetInput label="Tool calls" value={draft.budget.tool_calls} onChange={(value) => updateDraft({ budget: { ...draft.budget, tool_calls: value } })} />
          </div>
        </Section>

        <Section title="Matrix">
          <div className="space-y-4">
            <SwitchRow checked={draft.matrix.enabled} label="Enabled" onCheckedChange={(enabled) => updateMatrix({ enabled })} />
            <div className="grid gap-4 md:grid-cols-2">
              <TextInput label="Homeserver" value={draft.matrix.homeserver} onChange={(homeserver) => updateMatrix({ homeserver })} />
              <TextInput label="User ID" value={draft.matrix.user_id} onChange={(user_id) => updateMatrix({ user_id })} />
              <TextInput label="Device name" value={draft.matrix.device_name} onChange={(device_name) => updateMatrix({ device_name })} />
              <SecretInput label="Password" configured={draft.matrix.password_set} value={draft.matrixPassword} clear={draft.clearMatrixPassword} onValueChange={(matrixPassword) => updateDraft({ matrixPassword })} onClearChange={(clearMatrixPassword) => updateDraft({ clearMatrixPassword })} />
              <SecretInput label="Access token" configured={draft.matrix.token_set} value={draft.matrixToken} clear={draft.clearMatrixToken} onValueChange={(matrixToken) => updateDraft({ matrixToken })} onClearChange={(clearMatrixToken) => updateDraft({ clearMatrixToken })} />
              <TextAreaInput label="Allowed rooms" value={arrayToLines(draft.matrix.allowed_rooms)} onChange={(value) => updateMatrix({ allowed_rooms: linesToArray(value) })} />
              <TextAreaInput label="Allowed users" value={arrayToLines(draft.matrix.allowed_users)} onChange={(value) => updateMatrix({ allowed_users: linesToArray(value) })} />
            </div>
          </div>
        </Section>

        <Section title="Credentials">
          <div className="space-y-3">
            <div className="text-xs text-muted-foreground">{fileBackendText}</div>
            <textarea
              value={draft.credentialsJson}
              onChange={(event) => updateDraft({ credentialsJson: event.target.value })}
              className={cn(inputClassName, "min-h-64 font-mono text-xs leading-relaxed")}
              spellCheck={false}
            />
          </div>
        </Section>

        <Section title="Git remote">
          <div className="grid gap-4 md:grid-cols-2">
            <TextInput label="Remote" value={draft.git.remote} onChange={(remote) => updateDraft({ git: { ...draft.git, remote } })} />
            <TextInput label="Branch" value={draft.git.branch} onChange={(branch) => updateDraft({ git: { ...draft.git, branch } })} />
            <TextInput label="Author" value={draft.git.author} onChange={(author) => updateDraft({ git: { ...draft.git, author } })} />
            <SecretInput label="Token" configured={draft.git.token_set} value={draft.gitToken} clear={draft.clearGitToken} onValueChange={(gitToken) => updateDraft({ gitToken })} onClearChange={(clearGitToken) => updateDraft({ clearGitToken })} />
          </div>
        </Section>

        <div className="sticky bottom-0 flex justify-end border-t border-border bg-background/90 py-4 backdrop-blur">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? "Saving" : "Save"}
          </button>
        </div>
      </div>
    </form>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-background/88 p-4 shadow-sm sm:p-5">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <Field label={label}>
      <input value={value} onChange={(event) => onChange(event.target.value)} className={inputClassName} />
    </Field>
  );
}

function TextAreaInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <Field label={label}>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} className={cn(inputClassName, "min-h-28")} />
    </Field>
  );
}

function BudgetInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <Field label={label}>
      <input inputMode="decimal" value={value} onChange={(event) => onChange(event.target.value)} placeholder="No limit" className={inputClassName} />
    </Field>
  );
}

function SecretInput({
  label,
  configured,
  value,
  clear,
  onValueChange,
  onClearChange,
}: {
  label: string;
  configured: boolean;
  value: string;
  clear: boolean;
  onValueChange: (value: string) => void;
  onClearChange: (value: boolean) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="block text-xs font-medium text-muted-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">{configured ? "configured" : "not set"}</span>
      </div>
      <input type="password" value={value} onChange={(event) => onValueChange(event.target.value)} className={inputClassName} />
      <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
        <input type="checkbox" checked={clear} onChange={(event) => onClearChange(event.target.checked)} className="h-4 w-4 rounded border-border accent-foreground" />
        Clear value
      </label>
    </div>
  );
}

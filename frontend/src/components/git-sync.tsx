"use client";

import { ArrowDown, ArrowUp, Check, Download, Loader2, RotateCcw, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import {
  type GitActionResult,
  getGlobalGit,
  getSandboxGit,
  globalGitPull,
  globalGitPush,
  sandboxGitPull,
  sandboxGitPush,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Tone = "info" | "success" | "error";

interface AheadBehindCounts {
  ahead: number | null;
  behind: number | null;
}

function AheadBehind({
  counts,
  upToDateLabel,
}: {
  counts: AheadBehindCounts;
  upToDateLabel: string;
}) {
  const ahead = counts.ahead ?? 0;
  const behind = counts.behind ?? 0;
  if (ahead === 0 && behind === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-700">
        <Check className="h-3 w-3 shrink-0" />
        {upToDateLabel}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 font-mono text-foreground">
      <span className={cn("inline-flex items-center gap-0.5", ahead > 0 ? "text-amber-700" : "text-muted-foreground")}>
        <ArrowUp className="h-3 w-3 shrink-0" />
        {ahead}
      </span>
      <span className={cn("inline-flex items-center gap-0.5", behind > 0 ? "text-sky-700" : "text-muted-foreground")}>
        <ArrowDown className="h-3 w-3 shrink-0" />
        {behind}
      </span>
    </span>
  );
}

/** Shared presentational shell for both git-sync boundaries. */
function GitSyncControls({
  title,
  counts,
  emptyLabel,
  loading,
  notice,
  busy,
  disabled,
  pullDisabled,
  pushDisabled,
  onRefresh,
  onPull,
  onPush,
}: {
  title: string;
  counts: AheadBehindCounts | null;
  // Shown when there are no counts to display (e.g. no remote). Null hides the
  // line entirely — used on error, where the notice already explains the state.
  emptyLabel: string | null;
  loading: boolean;
  notice: { tone: Tone; message: string } | null;
  busy: "pull" | "push" | null;
  disabled: boolean;
  pullDisabled: boolean;
  pushDisabled: boolean;
  onRefresh: () => void;
  onPull: () => void;
  onPush: () => void;
}) {
  const t = useTranslations("git");
  const anyBusy = busy !== null || loading;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-muted-foreground">{title}</div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onRefresh}
            disabled={disabled || anyBusy}
            title={t("actions.refresh")}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            onClick={onPull}
            disabled={disabled || anyBusy || pullDisabled}
            title={t("actions.pull")}
            className="rounded-md p-1 text-sky-900 transition-colors hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "pull" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            onClick={onPush}
            disabled={disabled || anyBusy || pushDisabled}
            title={t("actions.push")}
            className="rounded-md p-1 text-emerald-900 transition-colors hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "push" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
      {counts ? (
        <div className="text-xs">
          <AheadBehind counts={counts} upToDateLabel={t("upToDate")} />
        </div>
      ) : emptyLabel ? (
        <div className="text-xs text-muted-foreground">{emptyLabel}</div>
      ) : null}
      {notice ? (
        <div
          className={cn(
            "break-words text-xs",
            notice.tone === "error" ? "text-destructive" : notice.tone === "success" ? "text-emerald-700" : "text-muted-foreground",
          )}
        >
          {notice.message}
        </div>
      ) : null}
    </div>
  );
}

/** B1: sandbox /workspace clone ↔ backend repo. */
export function SandboxGitControls({
  server,
  token,
  sessionId,
  disabled = false,
  refreshKey,
}: {
  server: string;
  token: string;
  sessionId: string;
  disabled?: boolean;
  refreshKey?: unknown;
}) {
  const t = useTranslations("git");
  const [counts, setCounts] = useState<AheadBehindCounts | null>(null);
  const [upstream, setUpstream] = useState(true);
  const [errored, setErrored] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"pull" | "push" | null>(null);
  const [notice, setNotice] = useState<{ tone: Tone; message: string } | null>(null);

  const refresh = useCallback(
    async (fetch: boolean) => {
      setLoading(true);
      setNotice(null);
      try {
        const status = await getSandboxGit(server, token, sessionId, { fetch });
        setErrored(false);
        setUpstream(status.upstream);
        setCounts({ ahead: status.ahead, behind: status.behind });
      } catch {
        setErrored(true);
        setCounts(null);
        setNotice({ tone: "error", message: t("errors.status") });
      } finally {
        setLoading(false);
      }
    },
    [server, token, sessionId, t],
  );

  useEffect(() => {
    const id = setTimeout(() => void refresh(true), 0);
    return () => clearTimeout(id);
  }, [refresh, refreshKey]);

  const runAction = useCallback(
    async (action: "pull" | "push", fn: () => Promise<GitActionResult>) => {
      setBusy(action);
      setNotice(null);
      try {
        const result = await fn();
        // Refresh first — it clears the notice on entry — then surface the
        // action result so the confirmation/denial text survives.
        await refresh(true);
        setNotice({
          tone: result.ok ? "success" : "error",
          message: result.denied ? t("errors.denied", { reason: result.message }) : result.message,
        });
      } catch {
        setNotice({ tone: "error", message: t(`errors.${action}`) });
      } finally {
        setBusy(null);
      }
    },
    [refresh, t],
  );

  return (
    <GitSyncControls
      title={t("sandbox.label")}
      counts={upstream ? counts : null}
      emptyLabel={errored ? null : t("noRemote")}
      loading={loading}
      notice={notice}
      busy={busy}
      disabled={disabled}
      pullDisabled={!upstream || (counts?.behind ?? 0) === 0}
      pushDisabled={!upstream || (counts?.ahead ?? 0) === 0}
      onRefresh={() => void refresh(true)}
      onPull={() => void runAction("pull", () => sandboxGitPull(server, token, sessionId))}
      onPush={() => void runAction("push", () => sandboxGitPush(server, token, sessionId))}
    />
  );
}

/** B2: backend per-user repo ↔ external remote. Renders nothing when no remote is configured. */
export function GlobalGitControls({
  server,
  token,
  className,
}: {
  server: string;
  token: string;
  className?: string;
}) {
  const t = useTranslations("git");
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [counts, setCounts] = useState<AheadBehindCounts | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"pull" | "push" | null>(null);
  const [notice, setNotice] = useState<{ tone: Tone; message: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setNotice(null);
    try {
      const status = await getGlobalGit(server, token);
      setConfigured(status.remote_configured);
      setCounts(status.remote_configured ? { ahead: status.ahead, behind: status.behind } : null);
    } catch {
      setCounts(null);
      setNotice({ tone: "error", message: t("errors.status") });
    } finally {
      setLoading(false);
    }
  }, [server, token, t]);

  useEffect(() => {
    const id = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(id);
  }, [refresh]);

  const runAction = useCallback(
    async (action: "pull" | "push", fn: () => Promise<GitActionResult>) => {
      setBusy(action);
      setNotice(null);
      try {
        const result = await fn();
        // Refresh first — it clears the notice on entry — then surface the result.
        await refresh();
        setNotice({ tone: result.ok ? "success" : "error", message: result.message });
      } catch {
        setNotice({ tone: "error", message: t(`errors.${action}`) });
      } finally {
        setBusy(null);
      }
    },
    [refresh, t],
  );

  // Hide entirely until we know a remote is configured.
  if (configured === false) return null;

  return (
    <div className={className}>
      <GitSyncControls
        title={t("global.label")}
        counts={counts}
        emptyLabel={null}
        loading={loading}
        notice={notice}
        busy={busy}
        disabled={false}
        pullDisabled={(counts?.behind ?? 0) === 0}
        pushDisabled={(counts?.ahead ?? 0) === 0}
        onRefresh={() => void refresh()}
        onPull={() => void runAction("pull", () => globalGitPull(server, token))}
        onPush={() => void runAction("push", () => globalGitPush(server, token))}
      />
    </div>
  );
}

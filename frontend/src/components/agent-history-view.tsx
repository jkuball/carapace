"use client";

import { Archive, Loader2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { fetchAgentHistory } from "@/lib/api";
import type { AgentHistoryRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./markdown-content";

/**
 * Read-only overlay showing the model history exactly as the agent sees it: fold
 * summaries in place of collapsed turns, short-form compacted tool returns. Debug aid.
 */
export function AgentHistoryView({
  server,
  token,
  sessionId,
  onClose,
}: {
  server: string;
  token: string;
  sessionId: string;
  onClose: () => void;
}) {
  const t = useTranslations("compaction");
  const [rows, setRows] = useState<AgentHistoryRow[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAgentHistory(server, token, sessionId)
      .then((res) => {
        if (!cancelled) setRows(res.rows);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [server, token, sessionId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-border bg-background shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Archive className="h-4 w-4" />
            {t("agentView")}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="px-4 pt-2 text-xs text-muted-foreground">{t("agentViewHint")}</p>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
          {rows === null && !error ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : null}
          {error ? <p className="text-sm text-destructive">{t("agentEmpty")}</p> : null}
          {rows?.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("agentEmpty")}</p>
          ) : null}
          {rows?.map((row, i) => (
            <AgentHistoryRowView key={i} row={row} summaryLabel={t("agentSummary")} />
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentHistoryRowView({
  row,
  summaryLabel,
}: {
  row: AgentHistoryRow;
  summaryLabel: string;
}) {
  if (row.role === "compaction_summary") {
    return (
      <div className="rounded-lg border border-dashed border-amber-500/50 bg-amber-500/5 p-3">
        <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-400">
          <Archive className="h-3 w-3" />
          {summaryLabel}
        </div>
        <div className="whitespace-pre-wrap text-xs text-muted-foreground">{row.content}</div>
      </div>
    );
  }

  if (row.role === "tool_call") {
    return (
      <div className="rounded-md bg-muted/50 px-2 py-1 font-mono text-xs text-muted-foreground">
        → {row.tool}({Object.keys(row.args ?? {}).length > 0 ? "…" : ""})
      </div>
    );
  }

  if (row.role === "tool_result") {
    return (
      <div className="rounded-md border border-border/50 bg-muted/30 p-2 text-xs">
        {row.compaction?.method ? (
          <div className="mb-1 inline-flex items-center gap-0.5 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400">
            <Archive className="h-2.5 w-2.5" />
            {row.compaction.method}
          </div>
        ) : null}
        <pre className="whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">
          {row.content}
        </pre>
      </div>
    );
  }

  if (row.role === "thinking") {
    return (
      <div className="rounded-md border border-border/40 bg-muted/20 p-2 text-[11px] italic text-muted-foreground">
        {row.content}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-lg px-3 py-2 text-sm",
        row.role === "user"
          ? "border border-border/60 bg-muted/30"
          : "bg-background",
      )}
    >
      <div className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {row.role}
      </div>
      <MarkdownContent content={row.content} />
    </div>
  );
}

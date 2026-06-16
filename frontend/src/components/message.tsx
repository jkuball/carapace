"use client";

import { AlertTriangle, Archive, Brain, Check, ChevronRight, Copy, GitBranch, Info, Loader2, Paperclip, RotateCcw, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { ChatMessage, EscalationDecision, LlmActivity } from "@/lib/types";
import { useAppLocale } from "@/components/locale-provider";
import { MarkdownContent } from "./markdown-content";
import { FilePreview } from "./file-preview";
import { ToolCallBadge } from "./tool-call-badge";
import { ApprovalCard } from "./approval-card";
import { CredentialApprovalCard } from "./credential-approval-card";
import { DomainAccessApprovalCard } from "./domain-access-approval-card";
import { GitPushApprovalCard } from "./git-push-approval-card";
import { CommandResultView } from "./command-result";
import { cn } from "@/lib/utils";

function formatDuration(ms: number, locale: string): string {
  if (ms < 1_000) return `${ms}ms`;
  if (ms < 10_000) {
    const seconds = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }).format(ms / 1_000);
    return `${seconds}s`;
  }
  return `${Math.round(ms / 1_000)}s`;
}

function MessageCopyButton({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const t = useTranslations("message");
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be denied; avoid throwing in UI */
    }
  }, [text]);

  if (!text) return null;

  return (
    <button
      type="button"
      className={cn(
        "rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className,
      )}
      aria-label={copied ? t("copied") : t("copy")}
      title={copied ? t("copied") : t("copy")}
      onClick={() => void copy()}
    >
      {copied ? (
        <Check className="size-3.5" strokeWidth={2} />
      ) : (
        <Copy className="size-3.5" strokeWidth={2} />
      )}
    </button>
  );
}

function ThinkingBadge({
  content,
  streaming,
  reasoningDurationMs,
  reasoningTokens,
  activeLlmActivity,
}: {
  content: string;
  streaming: boolean;
  reasoningDurationMs?: number;
  reasoningTokens?: number;
  activeLlmActivity?: LlmActivity | null;
}) {
  const t = useTranslations("message");
  const { locale } = useAppLocale();
  const [manualOpen, setManualOpen] = useState(false);
  const [liveReasoningDuration, setLiveReasoningDuration] = useState<{
    startedAt: string;
    durationMs: number;
  } | null>(null);
  const open = streaming || manualOpen;
  const liveThinkingStartedAt =
    streaming &&
    activeLlmActivity?.phase === "thinking" &&
    typeof activeLlmActivity.first_thinking_at === "string"
      ? activeLlmActivity.first_thinking_at
      : null;

  useEffect(() => {
    if (!liveThinkingStartedAt) {
      return;
    }

    const startedAt = Date.parse(liveThinkingStartedAt);
    if (Number.isNaN(startedAt)) {
      return;
    }

    const updateDuration = () => {
      setLiveReasoningDuration({
        startedAt: liveThinkingStartedAt,
        durationMs: Math.max(0, Date.now() - startedAt),
      });
    };

    const timeoutId = window.setTimeout(updateDuration, 0);
    const intervalId = window.setInterval(updateDuration, 100);
    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
    };
  }, [liveThinkingStartedAt]);

  const shownDurationMs =
    liveThinkingStartedAt && liveReasoningDuration?.startedAt === liveThinkingStartedAt
      ? liveReasoningDuration.durationMs
      : reasoningDurationMs;
  const meta: string[] = [];
  if (typeof shownDurationMs === "number") {
    meta.push(
      t(
        streaming
          ? "thinkingMeta.durationStreaming"
          : "thinkingMeta.durationComplete",
        { duration: formatDuration(shownDurationMs, locale) },
      ),
    );
  }
  if (typeof reasoningTokens === "number" && reasoningTokens > 0) {
    meta.push(t("thinkingMeta.reasoning", { count: reasoningTokens.toLocaleString() }));
  }

  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setManualOpen((prev) => !prev)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "bg-muted/60 text-muted-foreground",
          "hover:bg-accent transition-colors",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        {streaming ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-foreground/65 dark:text-foreground/70" />
        ) : (
          <Brain className="h-3 w-3 shrink-0 text-foreground/65 dark:text-foreground/70" />
        )}
        <span className="shrink-0 font-mono font-medium text-foreground/85 dark:text-foreground/90">
          {streaming ? t("thinking.streaming") : t("thinking.complete")}
        </span>
        {meta.length > 0 && (
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/60 dark:text-foreground/65">
            {meta.join(", ")}
          </span>
        )}
      </button>

      {open && (
        <div className="thinking-details tool-row-details ml-5 mt-1.5 rounded-lg border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
          <MarkdownContent content={content} />
        </div>
      )}
    </div>
  );
}

function MessageActionButton({
  label,
  icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  if (!onClick) return null;

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex items-center rounded-md border border-border/70 p-1.5 text-muted-foreground transition-colors",
        "hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50",
      )}
    >
      {icon}
    </button>
  );
}

function MessageActions({
  copyText,
  canFork,
  canRetry,
  canReset,
  disabled,
  onFork,
  onRetry,
  onReset,
}: {
  copyText?: string;
  canFork?: boolean;
  canRetry?: boolean;
  canReset?: boolean;
  disabled?: boolean;
  onFork?: () => void;
  onRetry?: () => void;
  onReset?: () => void;
}) {
  const t = useTranslations("message");
  const hasCopy = typeof copyText === "string" && copyText.length > 0;
  if (!hasCopy && !canFork && !canRetry && !canReset) return null;

  return (
    <div className="mt-2 flex items-center gap-2">
      <MessageCopyButton text={copyText ?? ""} className="border border-border/70 p-1.5" />
      <MessageActionButton
        label={t("actions.fork")}
        icon={<GitBranch className="size-3.5" />}
        disabled={disabled}
        onClick={canFork ? onFork : undefined}
      />
      <MessageActionButton
        label={t("actions.retry")}
        icon={<RotateCcw className="size-3.5" />}
        disabled={disabled}
        onClick={canRetry ? onRetry : undefined}
      />
      <MessageActionButton
        label={t("actions.reset")}
        icon={<Undo2 className="size-3.5" />}
        disabled={disabled}
        onClick={canReset ? onReset : undefined}
      />
    </div>
  );
}

function FinalStatusNotice({ status }: { status: "success" | "warning" }) {
  const t = useTranslations("message");
  const isWarning = status === "warning";
  const statusLabel = isWarning
    ? t("finalStatus.status.warning")
    : t("finalStatus.status.success");

  return (
    <div
      className={cn(
        "mt-3 rounded-xl border px-3 py-2.5 text-sm",
        isWarning
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-sky-200 bg-sky-50 text-sky-900",
      )}
    >
      <div className="flex items-start gap-2">
        {isWarning ? (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        ) : (
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
        )}
        <p>
          {t("finalStatus.notice", { status: statusLabel })}
        </p>
      </div>
    </div>
  );
}

function CompactionSummaryBlock({
  message,
  server,
  sessionId,
  activeLlmActivity,
}: {
  message: Extract<ChatMessage, { kind: "compaction_summary" }>;
  server?: string;
  sessionId?: string;
  activeLlmActivity?: LlmActivity | null;
}) {
  const t = useTranslations("compaction");
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "border border-dashed border-border/70 bg-muted/40 text-muted-foreground",
          "hover:bg-accent transition-colors",
        )}
        title={t("foldTitle")}
      >
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-90")}
        />
        <Archive className="h-3 w-3 shrink-0" />
        <span className="font-medium">
          {t("foldedCount", { count: message.foldedCount })}
        </span>
        <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide opacity-70">
          {t("badge")}
        </span>
      </button>
      {open ? (
        <div className="ml-5 mt-1.5 space-y-2 rounded-lg border border-border/60 bg-muted/20 p-3">
          <p className="text-[11px] text-muted-foreground">{t("foldExplainer")}</p>
          {message.children.map((child, idx) => (
            <Message
              key={idx}
              message={child}
              server={server}
              sessionId={sessionId}
              activeLlmActivity={activeLlmActivity}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

interface MessageProps {
  message: ChatMessage;
  server?: string;
  sessionId?: string;
  activeLlmActivity?: LlmActivity | null;
  canFork?: boolean;
  canRetry?: boolean;
  canReset?: boolean;
  actionDisabled?: boolean;
  onApproval?: (toolCallId: string, approved: boolean, message?: string) => void;
  onEscalation?: (
    requestId: string,
    decision: EscalationDecision,
    message?: string,
  ) => void;
  onCredentialApproval?: (
    requestId: string,
    decision: EscalationDecision,
    message?: string,
  ) => void;
  onFork?: () => void;
  onRetry?: () => void;
  onReset?: () => void;
}

export function Message({
  message,
  server,
  sessionId,
  activeLlmActivity,
  canFork,
  canRetry,
  canReset,
  actionDisabled,
  onApproval,
  onEscalation,
  onCredentialApproval,
  onFork,
  onRetry,
  onReset,
}: MessageProps) {
  switch (message.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div
            className={cn(
              "chat-copy-serif max-w-full rounded-2xl rounded-br-md border border-border/60 bg-muted/30 px-3.5 py-2 text-sm text-foreground md:max-w-[85%]",
            )}
          >
            {message.content ? <MarkdownContent content={message.content} /> : null}
            {message.attachments && message.attachments.length > 0 ? (
              <div
                className={cn(
                  "flex flex-col items-end gap-1.5",
                  message.content ? "mt-2" : "",
                )}
              >
                {message.attachments.map((att) =>
                  att.file_id ? (
                    <FilePreview
                      key={att.file_id}
                      fileId={att.file_id}
                      name={att.name}
                      path={att.path}
                      mime={att.mime}
                      size={att.size}
                      server={server}
                      sessionId={sessionId}
                      className="w-full max-w-sm text-left"
                    />
                  ) : (
                    <span
                      key={att.path}
                      title={att.path}
                      className="flex items-center gap-1.5 rounded-lg border border-border bg-background/50 px-2 py-1 text-xs"
                    >
                      <Paperclip className="h-3 w-3 shrink-0" />
                      <span className="max-w-40 truncate">{att.name}</span>
                    </span>
                  ),
                )}
              </div>
            ) : null}
          </div>
        </div>
      );

    case "assistant":
      return (
        <div className="group max-w-full text-sm md:max-w-[85%]">
          <div className="chat-copy-serif min-w-0 flex-1">
            <MarkdownContent content={message.content} />
            {message.finalStatus ? <FinalStatusNotice status={message.finalStatus} /> : null}
          </div>
          <MessageActions
            copyText={message.content}
            canFork={canFork}
            canRetry={canRetry}
            canReset={canReset}
            disabled={actionDisabled}
            onFork={onFork}
            onRetry={onRetry}
            onReset={onReset}
          />
        </div>
      );

    case "streaming":
      return (
        <div className="group flex max-w-full items-start gap-1.5 text-sm md:max-w-[85%]">
          <div className="chat-copy-serif min-w-0 flex-1">
            <MarkdownContent content={message.content} />
          </div>
        </div>
      );

    case "thinking":
      return (
        <ThinkingBadge
          content={message.content}
          streaming={false}
          reasoningDurationMs={message.reasoningDurationMs}
          reasoningTokens={message.reasoningTokens}
        />
      );

    case "thinking_streaming":
      return (
        <ThinkingBadge
          content={message.content}
          streaming
          reasoningDurationMs={message.reasoningDurationMs}
          reasoningTokens={message.reasoningTokens}
          activeLlmActivity={activeLlmActivity}
        />
      );

    case "tool_call":
      return (
        <ToolCallBadge
          tool={message.tool}
          args={message.args}
          detail={message.detail}
          contexts={message.contexts}
          approvalSource={message.approvalSource}
          approvalVerdict={message.approvalVerdict}
          approvalExplanation={message.approvalExplanation}
          decisionMessage={message.decisionMessage}
          result={message.result}
          files={message.files}
          exitCode={message.exitCode}
          loading={message.loading}
          compaction={message.compaction}
          server={server}
          sessionId={sessionId}
          childCalls={message.children?.map((c) => ({
            tool: c.tool,
            args: c.args,
            detail: c.detail,
            contexts: c.contexts,
            approvalSource: c.approvalSource,
            approvalVerdict: c.approvalVerdict,
            approvalExplanation: c.approvalExplanation,
            decisionMessage: c.decisionMessage,
            result: c.result,
            files: c.files,
            exitCode: c.exitCode,
            loading: c.loading,
          }))}
        />
      );

    case "approval":
      return (
        <ApprovalCard
          request={message.request}
          onRespond={(approved, responseMessage) =>
            onApproval?.(message.request.tool_call_id, approved, responseMessage)
          }
        />
      );

    case "domain_access_approval":
      return (
        <DomainAccessApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision, responseMessage) =>
            onEscalation?.(message.request.request_id, decision, responseMessage)
          }
        />
      );

    case "git_push_approval":
      return (
        <GitPushApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision, responseMessage) =>
            onEscalation?.(message.request.request_id, decision, responseMessage)
          }
        />
      );

    case "credential_approval":
      return (
        <CredentialApprovalCard
          request={message.request}
          decision={message.decision}
          onRespond={(decision, responseMessage) =>
            onCredentialApproval?.(
              message.request.request_id,
              decision,
              responseMessage,
            )
          }
        />
      );

    case "compaction_summary":
      return (
        <CompactionSummaryBlock
          message={message}
          server={server}
          sessionId={sessionId}
          activeLlmActivity={activeLlmActivity}
        />
      );

    case "command":
      return (
        <CommandResultView command={message.command} data={message.data} />
      );

    case "error":
      return (
        <div className="my-1 max-w-full rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive md:max-w-[85%]">
          <pre className="whitespace-pre-wrap font-mono text-xs">{message.detail}</pre>
          <MessageActions
            copyText={message.detail}
            canRetry={canRetry}
            canReset={canReset}
            disabled={actionDisabled}
            onRetry={onRetry}
            onReset={onReset}
          />
        </div>
      );
  }
}

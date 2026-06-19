"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { ChevronRight, Layers, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ToolCallGroupProps {
  /** The grouped tool_call / thinking messages, for summary counting. */
  items: ChatMessage[];
  /** Pre-rendered child rows, shown when expanded. */
  children: ReactNode;
  /** Run still active (last message in the conversation) → start expanded. */
  inProgress: boolean;
}

function distinctPathCount(
  items: ChatMessage[],
  tool: string,
): { calls: number; files: number } {
  let calls = 0;
  const paths = new Set<string>();
  for (const m of items) {
    if (m.kind !== "tool_call" || m.tool !== tool) continue;
    calls++;
    const p = m.args.path;
    if (typeof p === "string" && p.length > 0) paths.add(p);
  }
  return { calls, files: paths.size || calls };
}

function buildSummary(
  items: ChatMessage[],
  inProgress: boolean,
  t: (key: string, values?: Record<string, number>) => string,
): string {
  const tense = inProgress ? "present" : "past";
  const exec = items.filter(
    (m) => m.kind === "tool_call" && m.tool === "exec",
  ).length;
  const read = distinctPathCount(items, "read");
  const write = distinctPathCount(items, "write");
  const edit = distinctPathCount(items, "str_replace");
  const skill = items.filter(
    (m) => m.kind === "tool_call" && m.tool === "use_skill",
  ).length;
  const counted = new Set([
    "exec",
    "read",
    "write",
    "str_replace",
    "use_skill",
  ]);
  const other = items.filter(
    (m) => m.kind === "tool_call" && !counted.has(m.tool),
  ).length;

  const parts: string[] = [];
  if (exec > 0) parts.push(t(`${tense}.exec`, { count: exec }));
  if (read.calls > 0) parts.push(t(`${tense}.read`, { count: read.files }));
  if (write.calls > 0) parts.push(t(`${tense}.write`, { count: write.files }));
  if (edit.calls > 0) parts.push(t(`${tense}.edit`, { count: edit.files }));
  if (skill > 0) parts.push(t(`${tense}.skill`, { count: skill }));
  if (other > 0) parts.push(t(`${tense}.other`, { count: other }));

  const joined = parts.join(", ");
  if (joined.length === 0) return t("empty");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

export function ToolCallGroup({
  items,
  children,
  inProgress,
}: ToolCallGroupProps) {
  const t = useTranslations("toolCallGroup");
  const [open, setOpen] = useState(inProgress);
  const [touched, setTouched] = useState(false);

  // Follow inProgress (collapse when the run finishes) until the user toggles.
  useEffect(() => {
    if (!touched) setOpen(inProgress);
  }, [inProgress, touched]);

  const summary = buildSummary(items, inProgress, t);

  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => {
          setTouched(true);
          setOpen((o) => !o);
        }}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "text-muted-foreground hover:bg-accent transition-colors",
          open && "bg-accent",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        <Layers className="h-3 w-3 shrink-0 text-foreground/65 dark:text-foreground/70" />
        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-medium text-foreground/75 dark:text-foreground/80">
          {summary}
        </span>
        {inProgress && (
          <Loader2 className="ml-auto h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
        )}
      </button>

      {open && (
        <div className="ml-3 mt-0.5 border-l border-border/80 pl-3">
          {children}
        </div>
      )}
    </div>
  );
}

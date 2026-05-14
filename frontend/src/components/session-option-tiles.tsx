"use client";

import { BookOpen, Bot, Eye, Lock, MessageSquare, PencilLine, ShieldCheck, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

export type SessionOptionKey = "private" | "ask_mode" | "yolo_mode" | "unattended";

export interface SessionOptionTileItem {
  key: SessionOptionKey;
  active: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

export const SESSION_OPTION_ORDER: SessionOptionKey[] = [
  "private",
  "ask_mode",
  "yolo_mode",
  "unattended",
];

function getOptionCopy(
  t: ReturnType<typeof useTranslations<"newSessionButton">>,
  key: SessionOptionKey,
  active: boolean,
): { title: string; description: string } {
  switch (key) {
    case "private":
      return active
        ? {
            title: t("private.enabledTitle"),
            description: t("private.enabledDescription"),
          }
        : {
            title: t("private.disabledTitle"),
            description: t("private.disabledDescription"),
          };
    case "ask_mode":
      return active
        ? {
            title: t("ask.enabledTitle"),
            description: t("ask.enabledDescription"),
          }
        : {
            title: t("ask.disabledTitle"),
            description: t("ask.disabledDescription"),
          };
    case "yolo_mode":
      return active
        ? {
            title: t("yolo.enabledTitle"),
            description: t("yolo.enabledDescription"),
          }
        : {
            title: t("yolo.disabledTitle"),
            description: t("yolo.disabledDescription"),
          };
    case "unattended":
      return active
        ? {
            title: t("unattended.enabledTitle"),
            description: t("unattended.enabledDescription"),
          }
        : {
            title: t("unattended.disabledTitle"),
            description: t("unattended.disabledDescription"),
          };
  }
}

function getOptionIcon(key: SessionOptionKey, active: boolean): LucideIcon {
  switch (key) {
    case "private":
      return active ? Lock : BookOpen;
    case "ask_mode":
      return active ? Eye : PencilLine;
    case "yolo_mode":
      return active ? Zap : ShieldCheck;
    case "unattended":
      return active ? Bot : MessageSquare;
  }
}

function getOptionClasses(key: SessionOptionKey, active: boolean, disabled: boolean): string {
  if (disabled) {
    return active
      ? "border-border/70 bg-muted/60 text-foreground/70"
      : "border-border/60 bg-background/70 text-muted-foreground";
  }

  if (!active) {
    return "border-border/70 bg-background text-foreground hover:bg-muted/60 dark:hover:bg-muted/80";
  }

  switch (key) {
    case "private":
      return "border-slate-300 bg-slate-100 text-slate-900 hover:bg-slate-200/80 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-100 dark:hover:bg-slate-800/80";
    case "ask_mode":
      return "border-sky-300 bg-sky-50 text-sky-900 hover:bg-sky-100 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-100 dark:hover:bg-sky-900/70";
    case "yolo_mode":
      return "border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100 dark:hover:bg-amber-900/70";
    case "unattended":
      return "border-emerald-300 bg-emerald-50 text-emerald-900 hover:bg-emerald-100 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100 dark:hover:bg-emerald-900/70";
  }
}

interface SessionOptionTilesProps {
  items: SessionOptionTileItem[];
  className?: string;
}

export function SessionOptionTiles({ items, className }: SessionOptionTilesProps) {
  const t = useTranslations("newSessionButton");

  return (
    <div className={cn("grid grid-cols-2 gap-2", className)}>
      {items.map((item) => {
        const active = item.active;
        const disabled = item.disabled ?? false;
        const copy = getOptionCopy(t, item.key, active);
        const Icon = getOptionIcon(item.key, active);

        return (
          <button
            key={item.key}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            onClick={item.onClick}
            className={cn(
              "flex min-h-[7rem] w-full flex-col items-start justify-start rounded-xl border px-3 py-3 text-left transition-colors",
              disabled && "cursor-not-allowed",
              getOptionClasses(item.key, active, disabled),
            )}
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <Icon className="h-4 w-4 shrink-0" />
              <span>{copy.title}</span>
            </span>
            <span
              className={cn(
                "mt-1 block min-h-[2.5rem] overflow-hidden text-xs leading-5 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]",
                active ? "text-current/80" : "text-muted-foreground",
                disabled && "text-current/70",
              )}
            >
              {copy.description}
            </span>
          </button>
        );
      })}
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { BookOpen, Bot, ChevronDown, Eye, Lock, MessageSquare, PencilLine, Plus, ShieldCheck, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

export interface NewSessionOptions {
  private?: boolean;
  unattended?: boolean;
  ask_mode?: boolean;
  yolo_mode?: boolean;
}

interface NewSessionButtonProps {
  onCreate: (options?: NewSessionOptions) => void;
  disabled?: boolean;
  fullWidth?: boolean;
  className?: string;
}

type SessionOptionKey = keyof NewSessionOptions;

const OPTION_ORDER: SessionOptionKey[] = [
  "private",
  "ask_mode",
  "yolo_mode",
  "unattended",
];

export function NewSessionButton({
  onCreate,
  disabled = false,
  fullWidth = false,
  className,
}: NewSessionButtonProps) {
  const t = useTranslations("newSessionButton");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<NewSessionOptions>({});
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  function handleCreate(nextOptions: NewSessionOptions = {}) {
    setOpen(false);
    onCreate(nextOptions);
  }

  function handleToggleOption(key: keyof NewSessionOptions, checked: boolean) {
    setOptions((current) => {
      const next = { ...current, [key]: checked };
      if (key === "ask_mode" && checked) {
        next.yolo_mode = false;
      }
      if (key === "yolo_mode" && checked) {
        next.ask_mode = false;
      }
      return next;
    });
  }

  function getOptionCopy(key: SessionOptionKey, active: boolean): {
    title: string;
    description: string;
  } {
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

  function getOptionClasses(key: SessionOptionKey, active: boolean): string {
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

  return (
    <div
      ref={rootRef}
      className={cn("relative", fullWidth && "w-full", className)}
    >
      <div className="flex w-full items-stretch">
        <button
          onClick={() => handleCreate(options)}
          disabled={disabled}
          className={cn(
            "flex items-center gap-2 rounded-l-lg border border-border px-3 py-2 text-sm transition-colors",
            "bg-background hover:bg-muted",
            "disabled:opacity-50",
            fullWidth && "flex-1 justify-start",
          )}
        >
          <Plus className="h-4 w-4" />
          {t("label")}
        </button>
        <button
          onClick={() => setOpen((current) => !current)}
          disabled={disabled}
          aria-label={t("chooseOptions")}
          aria-expanded={open}
          aria-haspopup="dialog"
          className={cn(
            "rounded-r-lg border border-l-0 border-border px-2.5 transition-colors",
            "bg-background hover:bg-muted",
            "disabled:opacity-50",
          )}
        >
          <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>

      {open ? (
        <div
          role="dialog"
          aria-label={t("chooseOptions")}
          className="absolute right-0 z-20 mt-1 min-w-80 rounded-xl border border-border bg-background p-3 shadow-lg"
        >
          <div className="grid grid-cols-2 gap-2">
            {OPTION_ORDER.map((key) => {
              const active = !!options[key];
              const copy = getOptionCopy(key, active);
              const Icon = getOptionIcon(key, active);

              return (
                <button
                  key={key}
                  type="button"
                  aria-pressed={active}
                  onClick={() => handleToggleOption(key, !active)}
                  className={cn(
                    "flex min-h-[7rem] w-full flex-col items-start justify-start rounded-xl border px-3 py-3 text-left transition-colors",
                    getOptionClasses(key, active),
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
                    )}
                  >
                    {copy.description}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import type { AvailableModelInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

function formatContextWindow(value: number): string {
  return `${new Intl.NumberFormat().format(value)} ctx`;
}

function formatModelSecondaryLabel(entry: AvailableModelInfo): string | null {
  if (!entry.provider || !entry.name) {
    return null;
  }

  const fallbackId = `${entry.provider}:${entry.name}`;
  return entry.id !== fallbackId ? fallbackId : null;
}

function formatModelContextLabel(entry: AvailableModelInfo): string | null {
  return typeof entry.max_input_tokens === "number" ? formatContextWindow(entry.max_input_tokens) : null;
}

export function withSelectedModelOption(
  entries: AvailableModelInfo[],
  selectedId: string | null | undefined,
): AvailableModelInfo[] {
  const normalizedId = selectedId?.trim();
  if (!normalizedId) {
    return entries;
  }
  if (entries.some((entry) => entry.id === normalizedId)) {
    return entries;
  }
  return [...entries, { id: normalizedId, provider: "", name: normalizedId, max_input_tokens: null }];
}

interface ModelPickerProps {
  value: string | null | undefined;
  entries: AvailableModelInfo[];
  onChange: (value: string | null) => void;
  disabled: boolean;
  defaultLabel: string;
}

export function ModelPicker({ value, entries, onChange, disabled, defaultLabel }: ModelPickerProps) {
  const tModels = useTranslations("commandResult.models");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    function handlePointerDown(event: MouseEvent): void {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [open]);

  const normalizedValue = value?.trim() || null;
  const selected = normalizedValue ? entries.find((entry) => entry.id === normalizedValue) ?? null : null;
  const triggerLabel = selected?.id ?? defaultLabel;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        disabled={disabled}
        title={triggerLabel}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-xl border border-border bg-background px-3 py-2.5 text-left outline-none transition-colors",
          "focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60",
          open && "border-ring ring-2 ring-ring/30",
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={cn("min-w-0 break-all font-mono text-xs leading-tight", !selected && "text-muted-foreground")}>{triggerLabel}</span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute z-30 mt-2 w-full overflow-hidden rounded-2xl border border-border bg-background shadow-xl">
          <div className="max-h-72 overflow-y-auto p-2" role="listbox">
            <button
              type="button"
              role="option"
              aria-selected={!selected}
              onMouseDown={(event) => {
                event.preventDefault();
                onChange(null);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                !selected ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
              )}
            >
              <span className="text-sm font-medium">{defaultLabel}</span>
              {!selected && <Check className="h-4 w-4 shrink-0" />}
            </button>

            {entries.length === 0 ? (
              <div className="px-3 py-2 text-sm text-muted-foreground">{tModels("noneAvailable")}</div>
            ) : (
              entries.map((entry) => {
                const secondaryLabel = formatModelSecondaryLabel(entry);
                const contextLabel = formatModelContextLabel(entry);
                const isSelected = entry.id === normalizedValue;
                return (
                  <button
                    key={entry.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      onChange(entry.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "mt-1 flex w-full items-start justify-between gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                      isSelected ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
                    )}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block break-all font-mono text-xs font-medium leading-tight">{entry.id}</span>
                      {secondaryLabel && (
                        <span className="mt-0.5 block break-all text-xs text-muted-foreground">{secondaryLabel}</span>
                      )}
                      {contextLabel && (
                        <span className="mt-0.5 block text-[11px] text-muted-foreground">{contextLabel}</span>
                      )}
                    </span>
                    {isSelected && <Check className="h-4 w-4 shrink-0" />}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

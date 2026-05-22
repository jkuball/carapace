"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Clock, Mic, MicOff, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AvailableModelInfo, SlashCommand } from "@/lib/api";
import type { BudgetGauge, TurnUsage, TurnUsageBreakdownPct } from "@/lib/types";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function budgetGauges(u: TurnUsage): BudgetGauge[] {
  return Array.isArray(u.budget_gauges) ? u.budget_gauges : [];
}

function budgetGaugeCurrentAmount(gauge: BudgetGauge): number | null {
  if (
    typeof gauge.current_amount === "number" &&
    Number.isFinite(gauge.current_amount)
  ) {
    return gauge.current_amount;
  }

  const value = gauge.current_value.trim();
  if (gauge.key === "cost") {
    const match = value.match(/^\$(\d+(?:\.\d+)?)$/);
    return match ? Number(match[1]) : null;
  }

  const match = value.match(/^(\d+(?:\.\d+)?)([kKmM]?) tokens$/);
  if (!match) return null;

  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return null;
  if (match[2] === "k" || match[2] === "K") return amount * 1_000;
  if (match[2] === "m" || match[2] === "M") return amount * 1_000_000;
  return amount;
}

function visibleBudgetGauges(u: TurnUsage): BudgetGauge[] {
  return budgetGauges(u).filter((gauge) => {
    const current = budgetGaugeCurrentAmount(gauge);
    return current !== null && current > 0;
  });
}

interface SpeechRecognitionEvent {
  results: {
    [index: number]: {
      [index: number]: {
        transcript: string;
      };
    };
  };
}

interface SpeechRecognitionErrorEvent {
  error: string;
}

interface SpeechRecognitionInstance {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

const MODEL_COMMANDS = ["/model"];

const MODEL_TARGETS = new Set(["all", "agent", "sentinel", "title"]);

interface ChatInputProps {
  onSend: (content: string) => void;
  onCancel?: () => void;
  onInterrupt?: (content: string) => void;
  connected: boolean;
  disabled?: boolean;
  disabledPlaceholder?: string;
  waiting?: boolean;
  queuedMessage?: string | null;
  commands?: SlashCommand[];
  availableModelEntries?: AvailableModelInfo[];
  usage?: TurnUsage | null;
}

export function ChatInput({
  onSend,
  onCancel,
  onInterrupt,
  connected,
  disabled = false,
  disabledPlaceholder,
  waiting,
  queuedMessage,
  commands = [],
  availableModelEntries = [],
  usage,
}: ChatInputProps) {
  const t = useTranslations("chatInput");
  const [value, setValue] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const [isSpeechSupported, setIsSpeechSupported] = useState(false);

  useEffect(() => {
    const win = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionInstance;
      webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
    };
    const supported = !!(win.SpeechRecognition || win.webkitSpeechRecognition);
    setTimeout(() => {
      setIsSpeechSupported(supported);
    }, 0);
  }, []);

  const toggleListening = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop();
      return;
    }

    const win = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionInstance;
      webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
    };
    const SpeechRecognition = win.SpeechRecognition || win.webkitSpeechRecognition;

    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.lang = document.documentElement.lang || "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error("Speech recognition error:", event.error);
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = event.results[0][0].transcript;
      if (transcript) {
        setValue((prev) => {
          const space = prev && !prev.endsWith(" ") ? " " : "";
          return prev + space + transcript;
        });
        if (textareaRef.current) {
          setTimeout(() => {
            if (textareaRef.current) {
              textareaRef.current.style.height = "auto";
              textareaRef.current.style.height =
                Math.min(textareaRef.current.scrollHeight, 200) + "px";
            }
          }, 0);
        }
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, [isListening]);

  // Stop listening when disabled
  useEffect(() => {
    if (disabled && isListening) {
      recognitionRef.current?.abort();
    }
  }, [disabled, isListening]);

  // Clean up speech recognition instance on unmount
  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
    };
  }, []);

  const availableModelIds = useMemo(
    () => availableModelEntries.map((e) => e.id),
    [availableModelEntries],
  );

  // Focus textarea on mount (e.g. when a new session is created).
  // Skip on touch devices — programmatic focus opens the keyboard but the
  // browser won't scroll the input into view, leaving it hidden.
  useEffect(() => {
    const isTouch = window.matchMedia("(pointer: coarse)").matches;
    if (!isTouch && !disabled) {
      textareaRef.current?.focus();
    }
  }, [disabled]);

  // Show autocomplete when input starts with "/" and is a single word, but not if it exactly matches a command
  const exactMatch = commands.some(
    (c) => c.command === value.trim().toLowerCase(),
  );
  const showMenu = value.startsWith("/") && !value.includes(" ") && !exactMatch;

  const filtered = useMemo(() => {
    if (!showMenu) return [];
    const prefix = value.toLowerCase();
    return commands.filter((c) => c.command.startsWith(prefix));
  }, [value, showMenu, commands]);

  // Model argument autocomplete for /model
  const modelSuggestions = useMemo(
    (): { items: string[]; replaceFrom: number } => {
      const empty = { items: [], replaceFrom: value.length };
      const lower = value.toLowerCase();
      const match = MODEL_COMMANDS.find((c) => lower.startsWith(c + " "));
      if (!match) return empty;

      const afterCmd = value.slice(match.length + 1);
      const afterCmdTrimmed = afterCmd.trimStart();
      const replaceFromBase = match.length + 1 + (afterCmd.length - afterCmdTrimmed.length);

      if (match === "/model") {
        const firstArgMatch = afterCmdTrimmed.match(/^(\S+)(\s+)(.*)$/);
        if (
          firstArgMatch &&
          MODEL_TARGETS.has(firstArgMatch[1].toLowerCase()) &&
          afterCmdTrimmed.length > firstArgMatch[1].length
        ) {
          const modelPart = firstArgMatch[3] ?? "";
          if (modelPart.trimEnd().includes(" ")) return empty;

          const modelPartTrimmed = modelPart.trimStart();
          const partial = modelPartTrimmed.toLowerCase();
          if (availableModelIds.some((m) => m.toLowerCase() === partial)) {
            return empty;
          }

          return {
            items: availableModelIds.filter((m) =>
              m.toLowerCase().startsWith(partial),
            ),
            replaceFrom:
              replaceFromBase +
              firstArgMatch[1].length +
              firstArgMatch[2].length +
              (modelPart.length - modelPartTrimmed.length),
          };
        }
      }

      const partial = afterCmdTrimmed.toLowerCase();

      // Don't show suggestions if there's already a complete argument with space after
      if (afterCmd.trimEnd().includes(" ")) return empty;

      // Don't show if the argument already exactly matches a model
      if (availableModelIds.some((m) => m.toLowerCase() === partial)) {
        return empty;
      }

      return {
        items: availableModelIds.filter((m) =>
          m.toLowerCase().startsWith(partial),
        ),
        replaceFrom: replaceFromBase,
      };
    },
    [value, availableModelIds],
  );

  const showModelMenu = modelSuggestions.items.length > 0;

  const selectModelSuggestion = useCallback(
    (item: string) => {
      setValue(value.slice(0, modelSuggestions.replaceFrom) + item);
      textareaRef.current?.focus();
    },
    [value, modelSuggestions.replaceFrom],
  );

  // Scroll selected item into view
  useEffect(() => {
    if (!menuRef.current) return;
    const item = menuRef.current.children[selectedIndex] as
      | HTMLElement
      | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const selectCommand = useCallback((cmd: string) => {
    setValue(cmd);
    textareaRef.current?.focus();
  }, []);

  const clearInput = useCallback(() => {
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, []);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (disabled || !trimmed || !connected) return;
    if (waiting && queuedMessage) return;
    onSend(trimmed);
    clearInput();
  }, [value, disabled, connected, waiting, queuedMessage, onSend, clearInput]);

  const interrupt = useCallback(() => {
    const trimmed = value.trim();
    if (disabled || !trimmed || !connected || !waiting || !!queuedMessage) return;
    onInterrupt?.(trimmed);
    clearInput();
  }, [value, disabled, connected, waiting, queuedMessage, onInterrupt, clearInput]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    const activeMenu = showMenu ? "commands" : showModelMenu ? "models" : null;
    const menuLength =
      activeMenu === "commands"
        ? filtered.length
        : activeMenu === "models"
          ? modelSuggestions.items.length
          : 0;

    if (activeMenu && menuLength > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % menuLength);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => (i - 1 + menuLength) % menuLength);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        if (activeMenu === "commands") {
          selectCommand(filtered[selectedIndex].command);
        } else {
          selectModelSuggestion(modelSuggestions.items[selectedIndex]);
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setValue("");
        return;
      }
    } else if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      submit();
    } else if (e.key === "Enter" && e.altKey && !e.shiftKey) {
      e.preventDefault();
      interrupt();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    if (disabled) return;
    setValue(e.target.value);
    setSelectedIndex(0);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }

  const hasText = value.trim().length > 0;
  const disabledPlaceholderText = disabledPlaceholder ?? t("disabled");

  let tooltip: string;
  if (disabled) {
    tooltip = disabledPlaceholderText;
  } else if (!waiting) {
    tooltip = t("sendMessageTooltip");
  } else if (hasText) {
    tooltip = t("queueInterruptStopTooltip");
  } else {
    tooltip = t("stopGenerationTooltip");
  }

  return (
    <div className="border-t border-border bg-background px-4 py-3">
      {queuedMessage && (
        <div className="mx-auto max-w-3xl mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          <span className="truncate">{t("queued", { message: queuedMessage })}</span>
        </div>
      )}
      <div className="relative mx-auto max-w-3xl">
        {/* Slash command autocomplete menu */}
        {showMenu && filtered.length > 0 && (
          <div
            ref={menuRef}
            className={cn(
              "absolute bottom-full left-0 right-0 z-50 mb-1 max-h-60 overflow-y-auto",
              "rounded-xl border border-border bg-background shadow-lg",
              "py-1",
            )}
          >
            {filtered.map((cmd, i) => (
              <button
                key={cmd.command}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault(); // keep textarea focused
                  selectCommand(cmd.command);
                }}
                onMouseEnter={() => setSelectedIndex(i)}
                className={cn(
                  "flex w-full items-baseline gap-3 px-3 py-1.5 text-left text-sm",
                  "transition-colors",
                  i === selectedIndex
                    ? "bg-accent text-accent-foreground"
                    : "text-foreground hover:bg-accent/50",
                )}
              >
                <span className="font-mono text-xs font-medium shrink-0">
                  {cmd.command}
                </span>
                <span className="text-xs text-muted-foreground truncate">
                  {cmd.description}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Model argument autocomplete menu */}
        {showModelMenu && (
          <div
            ref={menuRef}
            className={cn(
              "absolute bottom-full left-0 right-0 z-50 mb-1 max-h-60 overflow-y-auto",
              "rounded-xl border border-border bg-background shadow-lg",
              "py-1",
            )}
          >
            {modelSuggestions.items.map((item, i) => (
              <button
                key={item}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectModelSuggestion(item);
                }}
                onMouseEnter={() => setSelectedIndex(i)}
                className={cn(
                  "flex w-full items-baseline gap-3 px-3 py-1.5 text-left text-sm",
                  "transition-colors",
                  i === selectedIndex
                    ? "bg-accent text-accent-foreground"
                    : "text-foreground hover:bg-accent/50",
                )}
              >
                <span className="font-mono text-xs font-medium shrink-0">
                  {item}
                </span>
              </button>
            ))}
          </div>
        )}

        <div
          className={cn(
            "flex items-end gap-2",
            "rounded-xl border border-border bg-muted/30 px-3 py-2",
            "focus-within:ring-2 focus-within:ring-ring/30 focus-within:border-ring",
            "transition-colors",
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? disabledPlaceholderText : t("placeholder")}
            rows={1}
            disabled={disabled}
            className={cn(
              "flex-1 resize-none bg-transparent text-base sm:text-sm outline-none",
              "placeholder:text-muted-foreground/50",
              disabled && "cursor-not-allowed text-muted-foreground",
            )}
          />
          {isSpeechSupported && !disabled && (
            <button
              type="button"
              onClick={toggleListening}
              title={isListening ? t("stopVoiceInput") : t("startVoiceInput")}
              className={cn(
                "shrink-0 rounded-lg p-2 transition-colors",
                isListening
                  ? "bg-red-500/20 text-red-500 animate-pulse hover:bg-red-500/30"
                  : "text-muted-foreground hover:bg-muted"
              )}
            >
              {isListening ? (
                <MicOff className="h-4 w-4" />
              ) : (
                <Mic className="h-4 w-4" />
              )}
            </button>
          )}
          <button
            onClick={waiting ? onCancel : submit}
            disabled={waiting ? !onCancel : disabled || !connected || !hasText}
            title={tooltip}
            className={cn(
              "shrink-0 rounded-lg p-2 transition-colors",
              waiting
                ? "bg-destructive/60 text-destructive-foreground hover:bg-destructive/75"
                : "bg-foreground text-background hover:bg-foreground/90",
              "disabled:opacity-30 disabled:cursor-not-allowed",
            )}
          >
            {waiting ? (
              <Square className="h-4 w-4" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </button>
        </div>

        {/* Context and session budget gauges */}
        {usage && (turnGaugeTokens(usage) > 0 || visibleBudgetGauges(usage).length > 0) && (
          <UsageGaugeStack
            usage={usage}
            availableModelEntries={availableModelEntries}
            onClickUsage={
              connected && !waiting ? () => onSend("/usage") : undefined
            }
          />
        )}
      </div>
    </div>
  );
}

/** API input+output tokens for the last agent model request (or last turn slice from done). */
function turnGaugeTokens(u: TurnUsage): number {
  return u.input_tokens + u.output_tokens;
}

const GAUGE_BREAKDOWN_ORDER: {
  key: keyof TurnUsageBreakdownPct;
  labelKey: "system" | "user" | "assistant" | "toolCalls" | "toolOutputs" | "other";
  className: string;
}[] = [
  { key: "system", labelKey: "system", className: "bg-sky-500/80" },
  { key: "user", labelKey: "user", className: "bg-emerald-500/80" },
  { key: "assistant", labelKey: "assistant", className: "bg-violet-500/80" },
  { key: "tool_calls", labelKey: "toolCalls", className: "bg-amber-500/80" },
  { key: "tool_returns", labelKey: "toolOutputs", className: "bg-orange-500/80" },
  { key: "other", labelKey: "other", className: "bg-muted-foreground/60" },
];

function breakdownTooltipLines(
  bp: TurnUsageBreakdownPct,
  t: (key: string, values?: Record<string, string | number>) => string,
): string[] {
  const lines: string[] = [];
  for (const { key, labelKey } of GAUGE_BREAKDOWN_ORDER) {
    const v = bp[key];
    if (key === "other" && v <= 0) continue;
    lines.push(t(`usageBreakdown.${labelKey}Line`, { percent: v.toFixed(1) }));
  }
  return lines;
}

const DEFAULT_CONTEXT_CAP = 200_000;

/** Match API ``usage.model`` to a descriptor (canonical id or provider-short name). */
function findModelEntryForGauge(
  modelId: string | null | undefined,
  entries: AvailableModelInfo[],
): AvailableModelInfo | undefined {
  if (!modelId) return undefined;
  const exact = entries.find((e) => e.id === modelId);
  if (exact) return exact;
  const byName = entries.find((e) => e.name === modelId);
  if (byName) return byName;
  return entries.find((e) => e.id.endsWith(`:${modelId}`));
}

function contextTokenCap(
  usage: TurnUsage,
  entries: AvailableModelInfo[],
): number {
  if (
    typeof usage.context_cap_tokens === "number" &&
    usage.context_cap_tokens > 0
  ) {
    return usage.context_cap_tokens;
  }
  const row = findModelEntryForGauge(usage.model, entries);
  if (row?.max_input_tokens != null) return row.max_input_tokens;
  return DEFAULT_CONTEXT_CAP;
}

function gaugeStress(fillPct: number, reached: boolean): "high" | "mid" | "low" {
  if (reached || fillPct > 75) return "high";
  if (fillPct > 50) return "mid";
  return "low";
}

function GaugeRow({
  fillPct,
  tooltip,
  label,
  fillClassName,
  onClick,
  reached = false,
}: {
  fillPct: number;
  tooltip: string;
  label: string;
  fillClassName: string;
  onClick?: () => void;
  reached?: boolean;
}) {
  const stress = gaugeStress(fillPct, reached);
  const trackRing =
    stress === "high"
      ? "ring-1 ring-destructive/35"
      : stress === "mid"
        ? "ring-1 ring-warning/30"
        : "";

  return (
    <div className="flex items-center gap-2">
      <div
        title={tooltip}
        className="flex min-h-6 flex-1 cursor-default items-center py-2 -my-2"
      >
        <div
          className={cn(
            "relative h-1 w-full overflow-hidden rounded-full bg-muted",
            trackRing,
          )}
        >
          <div
            className={cn(
              "absolute left-0 top-0 h-full transition-[width]",
              fillClassName,
            )}
            style={{ width: `${Math.max(0, Math.min(fillPct, 100))}%` }}
          />
        </div>
      </div>
      <button
        type="button"
        onClick={onClick}
        disabled={!onClick}
        title={tooltip}
        className={cn(
          "shrink-0 text-[10px] tabular-nums text-muted-foreground",
          onClick &&
            "cursor-pointer transition-colors hover:text-foreground",
          !onClick && "cursor-default",
        )}
      >
        {label}
      </button>
    </div>
  );
}

/** Compact usage gauge stack rendered below the input box. */
function UsageGaugeStack({
  usage,
  availableModelEntries,
  onClickUsage,
}: {
  usage: TurnUsage;
  availableModelEntries: AvailableModelInfo[];
  onClickUsage?: () => void;
}) {
  const budgets = visibleBudgetGauges(usage);
  const showContextGauge = turnGaugeTokens(usage) > 0;

  return (
    <div className="mt-1.5 space-y-1 px-1">
      {showContextGauge ? (
        <ContextGauge
          usage={usage}
          availableModelEntries={availableModelEntries}
          onClickUsage={onClickUsage}
        />
      ) : null}
      {budgets.map((gauge) => (
        <BudgetGaugeRow
          key={gauge.key}
          gauge={gauge}
          onClickUsage={onClickUsage}
        />
      ))}
    </div>
  );
}

function ContextGauge({
  usage,
  availableModelEntries,
  onClickUsage,
}: {
  usage: TurnUsage;
  availableModelEntries: AvailableModelInfo[];
  onClickUsage?: () => void;
}) {
  const t = useTranslations("chatInput");
  const ctx = turnGaugeTokens(usage);
  const cap = contextTokenCap(usage, availableModelEntries);
  const fillPct = Math.min((ctx / cap) * 100, 100);
  const bp = usage.breakdown_pct;

  const stress = gaugeStress(fillPct, false);

  const matched = findModelEntryForGauge(usage.model, availableModelEntries);
  const limitFromConfig = matched?.max_input_tokens != null;
  const limitNote = limitFromConfig
    ? t("context.limit", { tokens: formatTokens(cap) })
    : t("context.assumedLimit", { tokens: formatTokens(cap) });

  const tooltipLines = [
    t("context.lastRequestTokens", { tokens: formatTokens(ctx) }),
    limitNote,
    t("context.clickForUsage"),
  ];
  if (bp) {
    tooltipLines.push("", ...breakdownTooltipLines(bp, t));
  }

  const tooltip = tooltipLines.join("\n");

  return (
    <div className="flex items-center gap-2">
      <div
        title={tooltip}
        className="flex min-h-6 flex-1 cursor-default items-center py-2 -my-2"
      >
        <div
          className={cn(
            "relative h-1 w-full rounded-full bg-muted overflow-hidden",
            stress === "high"
              ? "ring-1 ring-destructive/35"
              : stress === "mid"
                ? "ring-1 ring-warning/30"
                : "",
          )}
        >
          <div
            className="absolute left-0 top-0 h-full flex overflow-hidden rounded-l-full transition-[width]"
            style={{ width: `${fillPct}%` }}
          >
            {bp ? (
              GAUGE_BREAKDOWN_ORDER.map(({ key, className }) => {
                const w = bp[key];
                if (w <= 0) return null;
                return (
                  <div
                    key={key}
                    className={cn("h-full min-w-px shrink-0", className)}
                    style={{ width: `${w}%` }}
                  />
                );
              })
            ) : (
              <div
                className={cn(
                  "h-full w-full rounded-l-full transition-colors",
                  stress === "high"
                    ? "bg-destructive/70"
                    : stress === "mid"
                      ? "bg-warning/70"
                      : "bg-muted-foreground/30",
                )}
              />
            )}
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onClickUsage}
        disabled={!onClickUsage}
        title={tooltip}
        className={cn(
          "shrink-0 text-[10px] tabular-nums text-muted-foreground",
          onClickUsage &&
            "hover:text-foreground cursor-pointer transition-colors",
          !onClickUsage && "cursor-default",
        )}
      >
        {t("context.tokensLabel", { tokens: formatTokens(ctx) })}
      </button>
    </div>
  );
}

function BudgetGaugeRow({
  gauge,
  onClickUsage,
}: {
  gauge: BudgetGauge;
  onClickUsage?: () => void;
}) {
  const t = useTranslations("chatInput");
  const fillClassName =
    gauge.key === "input"
      ? "rounded-l-full bg-emerald-500/75"
      : gauge.key === "output"
        ? "rounded-l-full bg-sky-500/75"
        : "rounded-l-full bg-amber-500/80";

  const tooltipLines = [
    t("budget.budgetLabel", { label: gauge.label }),
    t("budget.current", { value: gauge.current_value }),
    t("budget.max", { value: gauge.limit_value }),
  ];
  if (gauge.remaining_value) {
    tooltipLines.push(t("budget.remaining", { value: gauge.remaining_value }));
  }
  if (gauge.unavailable_reason) {
    tooltipLines.push(gauge.unavailable_reason);
  }
  if (gauge.reached) {
    tooltipLines.push(t("budget.exhausted"));
  }

  return (
    <GaugeRow
      fillPct={gauge.fill_pct}
      tooltip={tooltipLines.join("\n")}
      label={gauge.current_value}
      fillClassName={fillClassName}
      onClick={onClickUsage}
      reached={gauge.reached}
    />
  );
}

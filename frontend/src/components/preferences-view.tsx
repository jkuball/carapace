"use client";

import { Globe2 } from "lucide-react";
import { useTheme } from "next-themes";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { useAppLocale } from "@/components/locale-provider";
import { NotificationSubscription } from "@/components/notification-subscription";
import type { LocaleOverride } from "@/lib/storage";
import { cn } from "@/lib/utils";

type ThemePreference = "system" | "light" | "dark";

export function PreferencesView({
  embedded = false,
  server,
  token,
  showArchivedSessions,
  onShowArchivedSessionsChange,
}: {
  embedded?: boolean;
  server: string;
  token: string;
  showArchivedSessions: boolean;
  onShowArchivedSessionsChange: (showArchivedSessions: boolean) => void;
}) {
  const t = useTranslations("preferences");
  const { localeOverride, setLocaleOverride, systemLocale } = useAppLocale();
  const { theme, setTheme, systemTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const localeLabels: Record<LocaleOverride, string> = {
    de: t("language.options.de"),
    en: t("language.options.en"),
    system: t("language.options.system"),
  };
  const systemOptionLabel = `${localeLabels.system} (${localeLabels[systemLocale]})`;
  const themeLabels: Record<ThemePreference, string> = {
    dark: t("theme.options.dark"),
    light: t("theme.options.light"),
    system: t("theme.options.system"),
  };
  const themePreference: ThemePreference =
    theme === "light" || theme === "dark" ? theme : "system";
  const currentSystemTheme: Exclude<ThemePreference, "system"> | null =
    systemTheme === "light" || systemTheme === "dark" ? systemTheme : null;
  const systemThemeOptionLabel =
    mounted && currentSystemTheme
      ? `${themeLabels.system} (${themeLabels[currentSystemTheme]})`
      : themeLabels.system;

  return (
    <div className={cn(
      "overflow-y-auto",
      embedded ? "min-h-0 flex-1 px-5 py-5 sm:px-6" : "flex min-h-0 flex-1 px-4 py-5 sm:px-6",
    )}>
      <div className={cn(
        "mx-auto flex w-full flex-col gap-4",
        "max-w-3xl",
      )}>
        <section className={cn(
          "p-5 sm:p-6",
          embedded
            ? "rounded-none border-0 bg-transparent p-0 shadow-none"
            : "rounded-3xl border border-border bg-background/90 shadow-sm",
        )}>
          {!embedded ? (
            <div className="flex items-start gap-3">
              <div className="rounded-2xl border border-border bg-muted/40 p-2.5 text-muted-foreground">
                <Globe2 className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h1 className="text-xl font-semibold tracking-tight text-foreground">
                  {t("title")}
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t("description")}
                </p>
              </div>
            </div>
          ) : null}

          <div className={cn(
            "rounded-2xl border border-border p-4",
            embedded ? "bg-background/88 shadow-sm" : "mt-6 bg-muted/25",
          )}>
            <label className="block space-y-1.5">
              <span className="block text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {t("language.label")}
              </span>
              <select
                value={localeOverride}
                onChange={(event) => setLocaleOverride(event.target.value as LocaleOverride)}
                className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30"
              >
                <option value="system">{systemOptionLabel}</option>
                <option value="en">{localeLabels.en}</option>
                <option value="de">{localeLabels.de}</option>
              </select>
            </label>
          </div>

          <div className={cn(
            "rounded-2xl border border-border p-4",
            embedded ? "mt-4 bg-background/88 shadow-sm" : "mt-4 bg-muted/25",
          )}>
            <label className="block space-y-1.5">
              <span className="block text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {t("theme.label")}
              </span>
              <select
                value={themePreference}
                onChange={(event) => setTheme(event.target.value as ThemePreference)}
                className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30"
              >
                <option value="system">{systemThemeOptionLabel}</option>
                <option value="light">{themeLabels.light}</option>
                <option value="dark">{themeLabels.dark}</option>
              </select>
            </label>
          </div>

          <div className={cn(
            "rounded-2xl border border-border p-4",
            embedded ? "mt-4 bg-background/88 shadow-sm" : "mt-4 bg-muted/25",
          )}>
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  {t("chatList.label")}
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {t("chatList.showArchived.label")}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {t("chatList.showArchived.description")}
                  </p>
                </div>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={showArchivedSessions}
                aria-label={t("chatList.showArchived.label")}
                onClick={() => onShowArchivedSessionsChange(!showArchivedSessions)}
                className={cn(
                  "relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors focus:outline-none focus:ring-2 focus:ring-ring/30 focus:ring-offset-2",
                  showArchivedSessions
                    ? "border-emerald-600 bg-emerald-600"
                    : "border-border bg-muted",
                )}
              >
                <span
                  className={cn(
                    "inline-block h-5 w-5 rounded-full bg-background shadow-sm transition-transform",
                    showArchivedSessions ? "translate-x-6" : "translate-x-1",
                  )}
                />
              </button>
            </div>
          </div>

          <div className="mt-4">
            <NotificationSubscription server={server} token={token} />
          </div>
        </section>
      </div>
    </div>
  );
}

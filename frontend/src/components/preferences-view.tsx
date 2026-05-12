"use client";

import { Globe2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAppLocale } from "@/components/locale-provider";
import { NotificationSubscription } from "@/components/notification-subscription";
import type { LocaleOverride } from "@/lib/storage";
import { cn } from "@/lib/utils";

export function PreferencesView({
  embedded = false,
  server,
  token,
}: {
  embedded?: boolean;
  server: string;
  token: string;
}) {
  const t = useTranslations("preferences");
  const { localeOverride, setLocaleOverride, systemLocale } = useAppLocale();

  const localeLabels: Record<LocaleOverride, string> = {
    de: t("language.options.de"),
    en: t("language.options.en"),
    system: t("language.options.system"),
  };
  const systemOptionLabel = `${localeLabels.system} (${localeLabels[systemLocale]})`;

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

          <div className="mt-4">
            <NotificationSubscription server={server} token={token} />
          </div>
        </section>
      </div>
    </div>
  );
}

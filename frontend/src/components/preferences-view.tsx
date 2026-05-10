"use client";

import { Globe2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAppLocale } from "@/components/locale-provider";
import type { LocaleOverride } from "@/lib/storage";
import { cn } from "@/lib/utils";

export function PreferencesView({ embedded = false }: { embedded?: boolean }) {
  const t = useTranslations("preferences");
  const { locale, localeOverride, setLocaleOverride } = useAppLocale();

  const localeLabels: Record<LocaleOverride, string> = {
    de: t("language.options.de"),
    en: t("language.options.en"),
    system: t("language.options.system"),
  };

  return (
    <div className={cn(
      "overflow-y-auto px-4 py-5 sm:px-6",
      embedded ? "min-h-0 flex-1" : "flex min-h-0 flex-1",
    )}>
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
        <section className="rounded-3xl border border-border bg-background/90 p-5 shadow-sm sm:p-6">
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

          <div className="mt-6 rounded-2xl border border-border bg-muted/25 p-4">
            <label className="block space-y-1.5">
              <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {t("language.label")}
              </span>
              <select
                value={localeOverride}
                onChange={(event) => setLocaleOverride(event.target.value as LocaleOverride)}
                className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30"
              >
                <option value="system">{localeLabels.system}</option>
                <option value="en">{localeLabels.en}</option>
                <option value="de">{localeLabels.de}</option>
              </select>
            </label>

            <p className="mt-2 text-sm text-muted-foreground">
              {t("language.description")}
            </p>
            <p className="mt-3 text-sm text-foreground/80">
              {t("currentLocale", { locale: localeLabels[locale] })}
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

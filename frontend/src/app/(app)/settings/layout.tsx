"use client";

import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAppShell } from "@/components/app-shell-context";
import type { SettingsTab } from "@/lib/settings-tabs";
import { cn } from "@/lib/utils";

const tabButtonClassName = (selected: boolean): string => cn(
  "rounded-t-lg border border-b-0 px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  selected
    ? "relative z-10 -mb-px border-border bg-background text-foreground"
    : "border-transparent text-muted-foreground hover:border-border/60 hover:bg-background/70 hover:text-foreground",
);

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const tJobs = useTranslations("jobs");
  const { isAdmin } = useAppShell();
  const segment = useSelectedLayoutSegment() as SettingsTab | null;
  const activeTab: SettingsTab = segment ?? "preferences";

  useEffect(() => {
    const appTitle = t("app.name");
    const viewTitle = activeTab === "jobs"
      ? t("navigation.jobs")
      : activeTab === "platform-models"
        ? t("navigation.models")
        : activeTab === "platform-users"
          ? t("navigation.users")
          : t("navigation.settings");
    document.title = `${viewTitle} • ${appTitle}`;
  }, [activeTab, t]);

  function tab(value: SettingsTab, label: string) {
    const selected = activeTab === value;
    return (
      <Link
        id={`settings-tab-${value}`}
        href={`/settings/${value}`}
        role="tab"
        aria-selected={selected}
        aria-controls={`settings-panel-${value}`}
        tabIndex={selected ? 0 : -1}
        className={tabButtonClassName(selected)}
      >
        {label}
      </Link>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,_color-mix(in_oklch,var(--accent)_55%,transparent),transparent_35%),linear-gradient(180deg,color-mix(in_oklch,var(--background)_96%,var(--muted))_0%,var(--background)_100%)]">
      <div className="px-5 pt-4 sm:px-6">
        <div className="flex flex-col">
          <div className="pb-4">
            <h1 className="text-2xl font-semibold tracking-tight">{t("navigation.settings")}</h1>
          </div>

          <div
            role="tablist"
            aria-label={tJobs("settingsSections")}
            className="flex flex-wrap items-end gap-x-4 gap-y-2 border-b border-border/80"
          >
            <div className="flex items-end gap-1">
              {tab("preferences", t("navigation.preferences"))}
              {tab("account", t("navigation.account"))}
              {tab("jobs", t("navigation.jobs"))}
              {tab("api-keys", t("navigation.apiKeys"))}
            </div>

            {isAdmin ? (
              <div className="flex items-end gap-1 border-l border-border/80 pl-4">
                <span className="pb-2 pr-1 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  {t("navigation.platform")}
                </span>
                {tab("platform-models", t("navigation.models"))}
                {tab("platform-users", t("navigation.users"))}
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {children}
    </div>
  );
}

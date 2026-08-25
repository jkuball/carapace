"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { useAppShell } from "@/components/app-shell-context";
import { resolveBundledEmojiAsset } from "@/lib/emoji";
import { ADMIN_SETTINGS_TABS } from "@/lib/settings-tabs";

export const DEFAULT_BRAND_ICON = "/icon.svg";

/**
 * How the app identifies itself in the browser tab. Platform administration is the
 * product rather than anyone's agent, so it keeps the default name and icon there.
 */
export function useBrand(): { name: string; icon: string } {
  const t = useTranslations();
  const shell = useAppShell();
  const pathname = usePathname() ?? "";

  if (ADMIN_SETTINGS_TABS.some((tab) => pathname.startsWith(`/settings/${tab}`))) {
    return { name: t("app.name"), icon: DEFAULT_BRAND_ICON };
  }

  return {
    name: shell.currentUser?.agentName?.trim() || t("app.name"),
    icon: agentIcon(shell.currentUser?.agentIcon),
  };
}

export function agentIcon(value: string | undefined): string {
  return resolveBundledEmojiAsset(value?.trim() ?? "") ?? DEFAULT_BRAND_ICON;
}

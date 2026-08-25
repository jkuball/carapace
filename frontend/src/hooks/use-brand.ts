"use client";

import { useTranslations } from "next-intl";

import { useAppShell } from "@/components/app-shell-context";

/** The agent's display name: the user's own, falling back to the product name. */
export function useBrand(): string {
  const t = useTranslations();
  const shell = useAppShell();
  return shell.currentUser?.agentName?.trim() || t("app.name");
}

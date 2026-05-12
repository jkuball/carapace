import type { AbstractIntlMessages } from "next-intl";
import deMessages from "../../messages/de.json";
import enMessages from "../../messages/en.json";

export const supportedLocales = ["en", "de"] as const;

export type SupportedLocale = (typeof supportedLocales)[number];

export const defaultLocale: SupportedLocale = "en";

const localeMessages: Record<SupportedLocale, AbstractIntlMessages> = {
  de: deMessages,
  en: enMessages,
};

export function normalizeLocale(
  locale: string | null | undefined,
): SupportedLocale {
  if (typeof locale !== "string") {
    return defaultLocale;
  }

  const normalizedLocale = locale.trim().toLowerCase();
  if (normalizedLocale === "de" || normalizedLocale.startsWith("de-")) {
    return "de";
  }

  return defaultLocale;
}

export function resolvePreferredLocale(
  locales: readonly (string | null | undefined)[] | null | undefined,
): SupportedLocale {
  if (!Array.isArray(locales)) {
    return defaultLocale;
  }

  for (const locale of locales) {
    if (normalizeLocale(locale) === "de") {
      return "de";
    }
  }

  for (const locale of locales) {
    if (normalizeLocale(locale) === "en") {
      return "en";
    }
  }

  return defaultLocale;
}

export function resolveLocale(
  localeOverride: "system" | SupportedLocale,
  browserLocale: string | null | undefined,
): SupportedLocale {
  if (localeOverride !== "system") {
    return localeOverride;
  }

  return normalizeLocale(browserLocale);
}

export function getLocaleMessages(
  locale: SupportedLocale,
): AbstractIntlMessages {
  return localeMessages[locale];
}

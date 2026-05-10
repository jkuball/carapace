"use client";

import { NextIntlClientProvider } from "next-intl";
import type { AbstractIntlMessages } from "next-intl";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  defaultLocale,
  getLocaleMessages,
  type SupportedLocale,
  resolveLocale,
  supportedLocales,
} from "@/lib/i18n";
import {
  getLocaleOverride,
  saveLocaleOverride,
  type LocaleOverride,
} from "@/lib/storage";

interface LocaleContextValue {
  locale: SupportedLocale;
  systemLocale: SupportedLocale;
  localeOverride: LocaleOverride;
  locales: readonly SupportedLocale[];
  setLocaleOverride: (nextLocaleOverride: LocaleOverride) => void;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

function resolveBrowserLocale(): SupportedLocale {
  if (typeof navigator === "undefined") {
    return defaultLocale;
  }

  return resolveLocale(
    "system",
    navigator.languages[0] ?? navigator.language,
  );
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [localeOverride, setLocaleOverrideState] = useState<LocaleOverride>(
    "system",
  );
  const [browserLocale, setBrowserLocale] = useState<SupportedLocale>(
    defaultLocale,
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextLocaleOverride = getLocaleOverride();
      const nextBrowserLocale = resolveBrowserLocale();

      setLocaleOverrideState((current) =>
        current === nextLocaleOverride ? current : nextLocaleOverride,
      );
      setBrowserLocale((current) =>
        current === nextBrowserLocale ? current : nextBrowserLocale,
      );
    }, 0);

    return () => {
      window.clearTimeout(timer);
    };
  }, []);

  const locale = resolveLocale(localeOverride, browserLocale);
  const messages = useMemo<AbstractIntlMessages>(
    () => getLocaleMessages(locale),
    [locale],
  );

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      systemLocale: browserLocale,
      localeOverride,
      locales: supportedLocales,
      setLocaleOverride: (nextLocaleOverride) => {
        saveLocaleOverride(nextLocaleOverride);
        setLocaleOverrideState(nextLocaleOverride);
      },
    }),
    [browserLocale, locale, localeOverride],
  );

  return (
    <LocaleContext.Provider value={value}>
      <NextIntlClientProvider locale={locale} messages={messages}>
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  );
}

export function useAppLocale(): LocaleContextValue {
  const value = useContext(LocaleContext);
  if (value === null) {
    throw new Error("useAppLocale must be used within LocaleProvider");
  }
  return value;
}

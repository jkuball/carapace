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
    setLocaleOverrideState(getLocaleOverride());
    setBrowserLocale(resolveBrowserLocale());
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
      localeOverride,
      locales: supportedLocales,
      setLocaleOverride: (nextLocaleOverride) => {
        saveLocaleOverride(nextLocaleOverride);
        setLocaleOverrideState(nextLocaleOverride);
      },
    }),
    [locale, localeOverride],
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

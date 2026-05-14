"use client";

import { useEffect, type ReactNode } from "react";
import { LocaleProvider } from "@/components/locale-provider";
import { ThemeProvider } from "@/components/theme-provider";
import { registerNotificationServiceWorker } from "@/lib/notifications";

export function AppProviders({ children }: { children: ReactNode }) {
  useEffect(() => {
    void registerNotificationServiceWorker();
  }, []);

  return (
    <ThemeProvider>
      <LocaleProvider>{children}</LocaleProvider>
    </ThemeProvider>
  );
}

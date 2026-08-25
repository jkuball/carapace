"use client";

import { Suspense, useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { AppShellProvider, useAppShell } from "@/components/app-shell-context";
import { ConnectForm } from "@/components/connect-form";
import { Sidebar } from "@/components/sidebar";
import { VersionBadge } from "@/components/version-badge";
import { resolveBundledEmojiAsset } from "@/lib/emoji";
import { cn } from "@/lib/utils";
import { useSwipeDrawer } from "@/hooks/use-swipe-drawer";

const GITHUB_REPO_URL = "https://github.com/thiesgerken/carapace";
const BUILD_APP_VERSION = process.env.NEXT_PUBLIC_CARAPACE_VERSION?.trim() || null;
const DEFAULT_ICON = "/icon.svg";

function AppChrome({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const pathname = usePathname();
  const shell = useAppShell();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  useSwipeDrawer(sidebarOpen, setSidebarOpen);

  const isSettings = pathname?.startsWith("/settings") ?? false;
  const brand = shell.currentUser?.agentName?.trim() || t("app.name");
  const brandIcon =
    resolveBundledEmojiAsset(shell.currentUser?.agentIcon?.trim() ?? "") ?? DEFAULT_ICON;

  // Next re-applies the static metadata on every client-side navigation, so both
  // the title and the icon link have to be re-asserted whenever the route changes.
  useEffect(() => {
    document.title = brand;
    for (const link of document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]')) {
      link.remove();
    }
    const link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/svg+xml";
    link.href = brandIcon;
    document.head.append(link);
  }, [brand, brandIcon, pathname]);

  if (!shell.connected) {
    return <ConnectForm onConnect={shell.onConnect} />;
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-72 border-r border-border bg-background transition-transform duration-200 md:static md:w-84 md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <Sidebar
          server={shell.server}
          token={shell.token}
          sessions={shell.sessions}
          showArchivedSessions={shell.showArchivedSessions}
          activeSessionId={shell.activeSessionId}
          brandIcon={brandIcon}
          frontendVersion={BUILD_APP_VERSION}
          backendVersion={shell.serverVersion}
          currentUser={shell.currentUser}
          onSelect={shell.onSelectSession}
          onNew={shell.onNewSession}
          onGoHome={shell.onGoHome}
          onOpenSettings={() => shell.onOpenSettings()}
          onUpdateAttributes={shell.onUpdateSessionAttributes}
          onDelete={shell.onDeleteSession}
          onDisconnect={shell.onDisconnect}
          githubUrl={GITHUB_REPO_URL}
          loading={shell.loading}
          hasMore={shell.hasMore}
          loadingMore={shell.loadingMore}
          onLoadMore={shell.onLoadMore}
        />
      </aside>

      {/* Main content */}
      <main className="flex min-h-0 flex-1 flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-2 md:hidden">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded-md p-2.5 hover:bg-muted transition-colors"
          >
            {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold">
              {isSettings ? t("navigation.settings") : brand}
            </span>
            {isSettings ? null : (
              <VersionBadge frontendVersion={BUILD_APP_VERSION} backendVersion={shell.serverVersion} />
            )}
          </div>
        </div>

        {children}
      </main>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense>
      <AppShellProvider>
        <AppChrome>{children}</AppChrome>
      </AppShellProvider>
    </Suspense>
  );
}

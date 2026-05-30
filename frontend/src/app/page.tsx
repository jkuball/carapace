"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Menu, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { ConnectForm } from "@/components/connect-form";
import { JobsView, type SettingsTab } from "@/components/jobs-view";
import { NewSessionButton, type NewSessionOptions } from "@/components/new-session-button";
import { Sidebar } from "@/components/sidebar";
import { ChatView } from "@/components/chat-view";
import { VersionBadge } from "@/components/version-badge";
import { AUTH_REQUIRED_EVENT, createSession, deleteSession, getCurrentUser, getServerMeta, getSession, listSessions, logout, updateSession, type AuthUserInfo } from "@/lib/api";
import {
  clearConnection,
  getShowArchivedSessionsPreference,
  getServer,
  getToken,
  hasConnection,
  saveConnection,
  saveShowArchivedSessionsPreference,
} from "@/lib/storage";
import type { SessionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useSwipeDrawer } from "@/hooks/use-swipe-drawer";

function sandboxTimestampValue(sandbox: SessionInfo["sandbox"] | null | undefined): number {
  const updatedAt = sandbox?.updated_at;
  if (!updatedAt) return 0;
  const value = Date.parse(updatedAt);
  return Number.isNaN(value) ? 0 : value;
}

const SESSION_PAGE_SIZE = 50;
const MAX_DOCUMENT_TITLE_LENGTH = 30;
const BUILD_APP_VERSION = process.env.NEXT_PUBLIC_CARAPACE_VERSION?.trim() || null;

function mergeSessions(
  current: SessionInfo[],
  incoming: SessionInfo[],
  pending: Map<string, SessionInfo["sandbox"]>,
): SessionInfo[] {
  const merged = new Map(current.map((session) => [session.session_id, session]));
  for (const session of incoming) {
    const existing = merged.get(session.session_id);
    const pendingSandbox = pending.get(session.session_id);
    const freshestSandbox = [session.sandbox, existing?.sandbox, pendingSandbox].reduce<SessionInfo["sandbox"]>(
      (freshest, candidate) =>
        sandboxTimestampValue(candidate) > sandboxTimestampValue(freshest) ? candidate : freshest,
      session.sandbox,
    );
    const mergedSession = existing ? { ...existing, ...session } : session;
    merged.set(
      session.session_id,
      freshestSandbox === mergedSession.sandbox
        ? mergedSession
        : { ...mergedSession, sandbox: freshestSandbox },
    );
  }
  return sortSessions([...merged.values()]);
}

function compareSessions(left: SessionInfo, right: SessionInfo): number {
  if (left.attributes.pinned !== right.attributes.pinned) {
    return left.attributes.pinned ? -1 : 1;
  }

  const leftTime = Date.parse(left.last_active);
  const rightTime = Date.parse(right.last_active);
  const normalizedLeft = Number.isNaN(leftTime) ? 0 : leftTime;
  const normalizedRight = Number.isNaN(rightTime) ? 0 : rightTime;
  if (normalizedLeft !== normalizedRight) {
    return normalizedRight - normalizedLeft;
  }

  return left.session_id.localeCompare(right.session_id);
}

function sortSessions(sessions: SessionInfo[]): SessionInfo[] {
  return [...sessions].sort(compareSessions);
}

const GITHUB_REPO_URL = "https://github.com/thiesgerken/carapace";

type ConnectionState = {
  connected: boolean;
  server: string;
  token: string;
};

type AppView = "chat" | "settings";

function loadStoredConnection(): ConnectionState {
  if (!hasConnection()) {
    return {
      connected: false,
      server: "",
      token: "",
    };
  }

  return {
    connected: true,
    server: getServer(),
    token: getToken(),
  };
}

export default function Home() {
  return (
    <Suspense>
      <HomeContent />
    </Suspense>
  );
}

function HomeContent() {
  const t = useTranslations();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const initialView: AppView = (() => {
    const view = searchParams.get("view");
    if (view === "settings" || view === "jobs" || view === "preferences") {
      return "settings";
    }
    return "chat";
  })();
  const initialSettingsTab: SettingsTab = (() => {
    const tab = searchParams.get("tab");
    if (tab === "jobs" || tab === "platform-users" || tab === "account") {
      return tab;
    }
    return "preferences";
  })();
  const [connection, setConnection] = useState<ConnectionState>({
    connected: false,
    server: "",
    token: "",
  });
  const [currentUser, setCurrentUser] = useState<AuthUserInfo | null>(null);
  const [serverVersion, setServerVersion] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    initialView === "chat" ? searchParams.get("session") : null,
  );
  const [activeView, setActiveView] = useState<AppView>(
    initialView,
  );
  const [settingsTab, setSettingsTab] = useState<SettingsTab>(initialSettingsTab);
  const [showArchivedSessions, setShowArchivedSessionsState] = useState(false);
  const [requestedJobId, setRequestedJobId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [refreshingSessions, setRefreshingSessions] = useState(false);
  const [loadingMoreSessions, setLoadingMoreSessions] = useState(false);
  const [sessionListInitialized, setSessionListInitialized] = useState(false);
  const [sessionListCursor, setSessionListCursor] = useState<string | null>(null);
  const [sessionListHasMore, setSessionListHasMore] = useState(false);
  const refreshRequestIdRef = useRef(0);
  const loadingMoreSessionsRef = useRef(false);
  const failedLoadMoreCursorRef = useRef<string | null>(null);
  const pendingSandboxUpdatesRef = useRef(new Map<string, SessionInfo["sandbox"]>());

  const { connected, server, token } = connection;
  const isAdmin = currentUser?.roles.includes("admin") ?? false;
  const loading = creatingSession || refreshingSessions;
  const hasActiveSessionLoaded = activeSessionId != null
    && sessions.some((session) => session.session_id === activeSessionId);

  useSwipeDrawer(sidebarOpen, setSidebarOpen);

  // Sync activeSessionId → URL query param
  useEffect(() => {
    const params = new URLSearchParams();
    if (activeView === "settings") {
      params.set("view", "settings");
      if (settingsTab !== "preferences") {
        params.set("tab", settingsTab);
      }
    } else if (activeSessionId) {
      params.set("session", activeSessionId);
    }

    const query = params.toString();
    if (query) {
      router.replace(`?${query}`, {
        scroll: false,
      });
    } else {
      router.replace("/", { scroll: false });
    }
  }, [activeSessionId, activeView, router, settingsTab]);

  useEffect(() => {
    // Defer to avoid synchronous setState in effect body.
    const timer = setTimeout(() => {
      const nextConnection = loadStoredConnection();
      const nextShowArchivedSessions = getShowArchivedSessionsPreference();
      setConnection((current) => {
        if (
          current.connected === nextConnection.connected
          && current.server === nextConnection.server
          && current.token === nextConnection.token
        ) {
          return current;
        }

        return nextConnection;
      });
      setShowArchivedSessionsState((current) =>
        current === nextShowArchivedSessions ? current : nextShowArchivedSessions,
      );
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, []);

  // Fetch sessions when connected
  const loadInitialSessions = useCallback(async (
    srv: string,
    tok: string,
    includeArchived: boolean,
  ) => {
    if (!srv || !tok) return;

    const requestId = ++refreshRequestIdRef.current;
    setRefreshingSessions(true);
    setSessionListInitialized(false);
    loadingMoreSessionsRef.current = false;
    failedLoadMoreCursorRef.current = null;
    setLoadingMoreSessions(false);

    try {
      const page = await listSessions(srv, tok, {
        includeArchived,
        includeMessageCount: true,
        limit: SESSION_PAGE_SIZE,
      });

      if (requestId !== refreshRequestIdRef.current) return;

      setSessions(mergeSessions([], page.items, pendingSandboxUpdatesRef.current));
      setSessionListCursor(page.next_cursor ?? null);
      setSessionListHasMore(page.has_more);
      failedLoadMoreCursorRef.current = null;
    } catch {
      // If sessions fail to load, connection might be stale
    } finally {
      if (requestId === refreshRequestIdRef.current) {
        setRefreshingSessions(false);
        setSessionListInitialized(true);
      }
    }
  }, []);

  useEffect(() => {
    if (!connected) return;

    // Defer to avoid synchronous setState in effect body.
    const timer = setTimeout(() => {
      void loadInitialSessions(server, token, showArchivedSessions);
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, [connected, loadInitialSessions, server, showArchivedSessions, token]);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      if (!connected || !server) {
        if (!cancelled) setCurrentUser(null);
        return;
      }

      void getCurrentUser(server)
        .then((user) => {
          if (!cancelled) setCurrentUser(user);
        })
        .catch(() => {
          if (!cancelled) setCurrentUser(null);
        });
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [connected, server, token]);

  const requireLogin = useCallback(() => {
    refreshRequestIdRef.current += 1;
    loadingMoreSessionsRef.current = false;
    failedLoadMoreCursorRef.current = null;
    pendingSandboxUpdatesRef.current.clear();
    setCurrentUser(null);
    setRefreshingSessions(false);
    setLoadingMoreSessions(false);
    setSessionListInitialized(false);
    setConnection({ connected: false, server: "", token: "" });
    setServerVersion(null);
    setSessions([]);
    setSessionListCursor(null);
    setSessionListHasMore(false);
    setRequestedJobId(null);
    setActiveSessionId(null);
    setActiveView("chat");
    setSidebarOpen(false);
  }, []);

  useEffect(() => {
    window.addEventListener(AUTH_REQUIRED_EVENT, requireLogin);
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, requireLogin);
    };
  }, [requireLogin]);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      if (!connected || !server || !token) {
        if (!cancelled) {
          setServerVersion(null);
        }
        return;
      }

      void getServerMeta(server, token)
        .then((meta) => {
          if (!cancelled) {
            setServerVersion(meta.version);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setServerVersion(null);
          }
        });
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [connected, server, token]);

  const loadMoreSessions = useCallback(async () => {
    if (
      !server
      || !token
      || refreshingSessions
      || loadingMoreSessionsRef.current
      || !sessionListHasMore
      || !sessionListCursor
      || failedLoadMoreCursorRef.current === sessionListCursor
    ) {
      return;
    }

    const requestId = refreshRequestIdRef.current;
    loadingMoreSessionsRef.current = true;
    setLoadingMoreSessions(true);

    try {
      const page = await listSessions(server, token, {
        includeArchived: showArchivedSessions,
        includeMessageCount: true,
        limit: SESSION_PAGE_SIZE,
        cursor: sessionListCursor,
      });

      if (requestId !== refreshRequestIdRef.current) return;

      setSessions((current) => mergeSessions(current, page.items, pendingSandboxUpdatesRef.current));
      setSessionListCursor(page.next_cursor ?? null);
      setSessionListHasMore(page.has_more);
      failedLoadMoreCursorRef.current = null;
    } catch {
      failedLoadMoreCursorRef.current = sessionListCursor;
    } finally {
      if (requestId === refreshRequestIdRef.current) {
        loadingMoreSessionsRef.current = false;
        setLoadingMoreSessions(false);
      }
    }
  }, [refreshingSessions, server, sessionListCursor, sessionListHasMore, showArchivedSessions, token]);

  const handleShowArchivedSessionsChange = useCallback((nextShowArchivedSessions: boolean) => {
    saveShowArchivedSessionsPreference(nextShowArchivedSessions);
    setShowArchivedSessionsState(nextShowArchivedSessions);
  }, []);

  useEffect(() => {
    if (!connected || !activeSessionId || !sessionListInitialized || hasActiveSessionLoaded) return;

    let cancelled = false;
    const requestId = refreshRequestIdRef.current;
    const timer = setTimeout(() => {
      void getSession(server, token, activeSessionId)
        .then((session) => {
          if (cancelled || requestId !== refreshRequestIdRef.current) return;
          setSessions((current) => mergeSessions(current, [session], pendingSandboxUpdatesRef.current));
        })
        .catch(() => {
          // Leave the active id alone; ChatView will surface session-specific failures if needed.
        });
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [activeSessionId, connected, hasActiveSessionLoaded, server, sessionListInitialized, token]);

  function handleConnect(user: AuthUserInfo) {
    const srv = getServer();
    refreshRequestIdRef.current += 1;
    loadingMoreSessionsRef.current = false;
    failedLoadMoreCursorRef.current = null;
    pendingSandboxUpdatesRef.current.clear();
    setRefreshingSessions(false);
    setLoadingMoreSessions(false);
    setSessionListInitialized(false);
    setSessions([]);
    setSessionListCursor(null);
    setSessionListHasMore(false);
    saveConnection(user.username);
    setCurrentUser(user);
    setConnection({ connected: true, server: srv, token: user.username });
  }

  function handleDisconnect() {
    if (server) {
      void logout(server).catch(() => undefined);
    }
    clearConnection();
    requireLogin();
  }

  async function handleNewSession(options: NewSessionOptions = {}) {
    setCreatingSession(true);
    try {
      const session = await createSession(server, token, options);
      setSessions((prev) => sortSessions([session, ...prev]));
      setRequestedJobId(null);
      setActiveSessionId(session.session_id);
      setActiveView("chat");
      setSidebarOpen(false);
    } catch {
      // handled in UI
    } finally {
      setCreatingSession(false);
    }
  }

  const handleDeleteSession = useCallback(async (id: string) => {
    try {
      await deleteSession(server, token, id);
      pendingSandboxUpdatesRef.current.delete(id);
      setSessions((prev) => prev.filter((s) => s.session_id !== id));
      setActiveSessionId((current) => (current === id ? null : current));
    } catch {
      // deletion failed silently
    }
  }, [server, token]);

  const handleUpdateSessionAttributes = useCallback(async (
    id: string,
    attributes: NonNullable<Parameters<typeof updateSession>[3]["attributes"]>,
  ) => {
    const updated = await updateSession(server, token, id, { attributes });
    pendingSandboxUpdatesRef.current.delete(id);
    setSessions((prev) => sortSessions(prev.map((entry) => (entry.session_id === id ? { ...entry, ...updated } : entry))));
    setActiveSessionId((current) => (updated.attributes.archived && current === id ? null : current));
    return updated;
  }, [server, token]);

  function handleSelectSession(id: string) {
    setRequestedJobId(null);
    setActiveSessionId(id);
    setActiveView("chat");
    setSidebarOpen(false);
  }

  function handleOpenSettings(tab: SettingsTab = "preferences"): void {
    setRequestedJobId(null);
    setActiveSessionId(null);
    setSettingsTab(tab);
    setActiveView("settings");
    setSidebarOpen(false);
  }

  function handleOpenJobSettings(jobId: string): void {
    setRequestedJobId(jobId);
    setActiveSessionId(null);
    setSettingsTab("jobs");
    setActiveView("settings");
    setSidebarOpen(false);
  }

  function handleGoHome(): void {
    setRequestedJobId(null);
    setActiveSessionId(null);
    setActiveView("chat");
    setSidebarOpen(false);
  }

  function handleTitleUpdate(sessionId: string, title: string) {
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, title } : s)),
    );
  }

  function handleSessionUpdate(session: SessionInfo) {
    setSessions((prev) => {
      const next = prev.map((entry) =>
        entry.session_id === session.session_id ? { ...entry, ...session } : entry,
      );
      return sortSessions(
        next.some((entry) => entry.session_id === session.session_id)
          ? next
          : [session, ...next],
      );
    });
  }

  function handleSandboxUpdate(sessionId: string, sandbox: SessionInfo["sandbox"]) {
    pendingSandboxUpdatesRef.current.set(sessionId, sandbox);
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, sandbox } : s)),
    );
  }

  const handleActiveSessionTitleUpdate = useCallback((title: string) => {
    if (!activeSessionId) return;
    handleTitleUpdate(activeSessionId, title);
  }, [activeSessionId]);

  const handleActiveSessionSandboxUpdate = useCallback((sandbox: SessionInfo["sandbox"]) => {
    if (!activeSessionId) return;
    handleSandboxUpdate(activeSessionId, sandbox);
  }, [activeSessionId]);

  const handleActiveSessionUpdate = useCallback((session: SessionInfo) => {
    handleSessionUpdate(session);
  }, []);

  const handleForkSession = useCallback((session: SessionInfo) => {
    handleSessionUpdate(session);
    setActiveSessionId(session.session_id);
    setActiveView("chat");
    setSidebarOpen(false);
  }, []);

  const handleActiveSessionDelete = useCallback(async () => {
    if (!activeSessionId) return;
    await handleDeleteSession(activeSessionId);
  }, [activeSessionId, handleDeleteSession]);

  const activeSession = sessions.find((session) => session.session_id === activeSessionId) ?? null;

  useEffect(() => {
    const appTitle = t("app.name");
    if (activeView === "settings") {
      const viewTitle = settingsTab === "jobs"
        ? t("navigation.jobs")
        : settingsTab === "platform-users"
          ? t("navigation.users")
          : t("navigation.settings");
      document.title = `${viewTitle} • ${appTitle}`;
      return;
    }

    const sessionTitle = activeSession?.title?.trim();
    const useDefaultTitle = !activeSession
      || activeSession.attributes.private
      || !sessionTitle;
    const truncatedTitle = sessionTitle && sessionTitle.length > MAX_DOCUMENT_TITLE_LENGTH
      ? `${sessionTitle.slice(0, MAX_DOCUMENT_TITLE_LENGTH - 3)}...`
      : sessionTitle;

    document.title = useDefaultTitle
      ? appTitle
      : `${truncatedTitle} • ${appTitle}`;
  }, [activeSession, activeView, searchParamsKey, settingsTab, t]);

  if (!connected) {
    return <ConnectForm onConnect={handleConnect} />;
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
          sessions={sessions}
          showArchivedSessions={showArchivedSessions}
          activeSessionId={activeSessionId}
          activeView={activeView}
          frontendVersion={BUILD_APP_VERSION}
          backendVersion={serverVersion}
          currentUser={currentUser}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          onGoHome={handleGoHome}
          onOpenSettings={() => handleOpenSettings()}
          onUpdateAttributes={handleUpdateSessionAttributes}
          onDelete={handleDeleteSession}
          onDisconnect={handleDisconnect}
          githubUrl={GITHUB_REPO_URL}
          loading={loading}
          hasMore={sessionListHasMore}
          loadingMore={loadingMoreSessions}
          onLoadMore={loadMoreSessions}
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
            {sidebarOpen ? (
              <X className="h-5 w-5" />
            ) : (
              <Menu className="h-5 w-5" />
            )}
          </button>
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold">
              {activeView === "settings" ? t("navigation.settings") : t("app.name")}
            </span>
            {activeView === "chat" ? (
              <VersionBadge frontendVersion={BUILD_APP_VERSION} backendVersion={serverVersion} />
            ) : null}
          </div>
        </div>

        {/* Chat or empty state */}
        {activeView === "settings" ? (
          <JobsView
            server={server}
            token={token}
            isAdmin={isAdmin}
            currentUsername={currentUser?.username ?? null}
            sessions={sessions}
            showArchivedSessions={showArchivedSessions}
            onShowArchivedSessionsChange={handleShowArchivedSessionsChange}
            onSessionActivated={handleForkSession}
            requestedJobId={requestedJobId}
            activeTab={settingsTab}
            onTabChange={setSettingsTab}
          />
        ) : activeSessionId ? (
          <ChatView
            key={activeSessionId}
            server={server}
            token={token}
            sessionId={activeSessionId}
            session={activeSession}
            initialSandbox={activeSession?.sandbox ?? null}
            onTitleUpdate={handleActiveSessionTitleUpdate}
            onSessionUpdate={handleActiveSessionUpdate}
            onSandboxUpdate={handleActiveSessionSandboxUpdate}
            onForkSession={handleForkSession}
            onOpenJobSettings={handleOpenJobSettings}
            onUpdateSessionAttributes={handleUpdateSessionAttributes}
            onDeleteSession={handleActiveSessionDelete}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <p className="text-lg font-medium text-foreground/80">{t("app.name")}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("home.empty.description")}
              </p>
              <NewSessionButton
                onCreate={handleNewSession}
                disabled={loading}
                className="mt-4"
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

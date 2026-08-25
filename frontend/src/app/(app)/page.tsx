"use client";

import { useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useAppShell } from "@/components/app-shell-context";
import { useBrand } from "@/hooks/use-brand";
import { ChatView } from "@/components/chat-view";
import { NewSessionButton } from "@/components/new-session-button";
import type { SessionInfo } from "@/lib/types";

const MAX_DOCUMENT_TITLE_LENGTH = 30;

export default function ChatPage() {
  const t = useTranslations();
  const shell = useAppShell();
  const { name: brand } = useBrand();
  const { activeSessionId, activeSession } = shell;

  const onActiveTitleUpdate = useCallback((title: string) => {
    if (!activeSessionId) return;
    shell.onTitleUpdate(activeSessionId, title);
  }, [activeSessionId, shell]);

  const onActiveSandboxUpdate = useCallback((sandbox: SessionInfo["sandbox"]) => {
    if (!activeSessionId) return;
    shell.onSandboxUpdate(activeSessionId, sandbox);
  }, [activeSessionId, shell]);

  const onActiveDelete = useCallback(async () => {
    if (!activeSessionId) return;
    await shell.onDeleteSession(activeSessionId);
  }, [activeSessionId, shell]);

  useEffect(() => {
    const sessionTitle = activeSession?.title?.trim();
    const useDefaultTitle = !activeSession || activeSession.attributes.private || !sessionTitle;
    const truncatedTitle = sessionTitle && sessionTitle.length > MAX_DOCUMENT_TITLE_LENGTH
      ? `${sessionTitle.slice(0, MAX_DOCUMENT_TITLE_LENGTH - 3)}...`
      : sessionTitle;
    document.title = useDefaultTitle ? brand : `${truncatedTitle} • ${brand}`;
  }, [activeSession, brand]);

  if (activeSessionId) {
    return (
      <ChatView
        key={activeSessionId}
        server={shell.server}
        token={shell.token}
        sessionId={activeSessionId}
        session={activeSession}
        initialSandbox={activeSession?.sandbox ?? null}
        onTitleUpdate={onActiveTitleUpdate}
        onSessionUpdate={shell.onSessionUpdate}
        onSandboxUpdate={onActiveSandboxUpdate}
        onForkSession={shell.onForkSession}
        onOpenJobSettings={shell.onOpenJobSettings}
        onUpdateSessionAttributes={shell.onUpdateSessionAttributes}
        onDeleteSession={onActiveDelete}
      />
    );
  }

  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="text-center">
        <p className="text-lg font-medium text-foreground/80">{t("app.name")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("home.empty.description")}</p>
        <NewSessionButton onCreate={shell.onNewSession} disabled={shell.loading} className="mt-4" />
      </div>
    </div>
  );
}

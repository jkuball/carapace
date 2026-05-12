"use client";

import { useEffect, useRef } from "react";
import { postInteractivePresence } from "@/lib/api";
import { getPresenceClientId } from "@/lib/storage";

type WebSocketStatus = "disconnected" | "connecting" | "connected";

export function useSessionPresence(
  server: string,
  token: string,
  sessionId: string,
  status: WebSocketStatus,
  sourceId: string,
): void {
  const sourceIdRef = useRef(sourceId);
  sourceIdRef.current = sourceId;

  useEffect(() => {
    if (!server || !token || !sessionId || status !== "connected") return;

    const sourceId = sourceIdRef.current;

    const sendPresence = async (
      focusState: "visible" | "hidden" | "inactive",
    ) => {
      try {
        await postInteractivePresence(server, token, {
          session_id: sessionId,
          source_id: sourceId,
          client_type: "web",
          focus_state: focusState,
        });
      } catch {
        // Presence updates are best-effort and should not break chat.
      }
    };

    const syncPresence = () => {
      void sendPresence(document.hidden ? "hidden" : "visible");
    };

    syncPresence();
    const interval = window.setInterval(syncPresence, 30000);
    document.addEventListener("visibilitychange", syncPresence);
    window.addEventListener("focus", syncPresence);
    window.addEventListener("blur", syncPresence);

    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", syncPresence);
      window.removeEventListener("focus", syncPresence);
      window.removeEventListener("blur", syncPresence);
      void sendPresence("inactive");
    };
  }, [server, token, sessionId, status]);
}

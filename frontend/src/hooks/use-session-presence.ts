"use client";

import { useEffect } from "react";
import {
  postInteractivePresence,
  postNotificationSubscriptionPresence,
} from "@/lib/api";
import { getNotificationSubscriptionId } from "@/lib/storage";

type WebSocketStatus = "disconnected" | "connecting" | "connected";

export function useSessionPresence(
  server: string,
  token: string,
  sessionId: string,
  status: WebSocketStatus,
  sourceId: string,
): void {
  useEffect(() => {
    if (!server || !token || !sessionId || status !== "connected") return;

    const sendPresence = async (
      focusState: "visible" | "hidden" | "inactive",
      options?: { keepalive?: boolean },
    ) => {
      const subscriptionId = getNotificationSubscriptionId();

      const operations: Array<Promise<void>> = [
        postInteractivePresence(server, token, {
          session_id: sessionId,
          source_id: sourceId,
          client_type: "web",
          focus_state: focusState,
        }, options),
      ];
      if (subscriptionId) {
        operations.push(
          postNotificationSubscriptionPresence(
            server,
            token,
            subscriptionId,
            {
              session_id: sessionId,
              client_type: "web",
              focus_state: focusState,
            },
            options,
          ),
        );
      }

      await Promise.allSettled(operations);
    };

    const syncPresence = (
      focusState: "visible" | "hidden" = document.hidden ? "hidden" : "visible",
    ) => {
      void sendPresence(focusState);
    };
    const handleVisibilityChange = () => syncPresence();
    const handleWindowFocus = () => syncPresence("visible");
    const handleWindowBlur = () => syncPresence("hidden");

    syncPresence();
    const interval = window.setInterval(syncPresence, 30000);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", handleWindowFocus);
    window.addEventListener("blur", handleWindowBlur);

    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", handleWindowFocus);
      window.removeEventListener("blur", handleWindowBlur);
      void sendPresence("inactive", { keepalive: true });
    };
  }, [server, token, sessionId, status, sourceId]);
}

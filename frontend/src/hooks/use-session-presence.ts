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
    ) => {
      const subscriptionId = getNotificationSubscriptionId();

      const operations: Array<Promise<void>> = [
        postInteractivePresence(server, token, {
          session_id: sessionId,
          source_id: sourceId,
          client_type: "web",
          focus_state: focusState,
        }),
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
          ),
        );
      }

      await Promise.allSettled(operations);
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
  }, [server, token, sessionId, status, sourceId]);
}

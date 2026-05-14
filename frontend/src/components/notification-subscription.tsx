"use client";

import { BellOff, BellRing, Loader2, Smartphone } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  deleteNotificationSubscription,
  getVapidPublicKey,
  listNotificationSubscriptions,
  updateNotificationSubscriptionPreferences,
  upsertNotificationSubscription,
} from "@/lib/api";
import {
  buildNotificationDeviceName,
  decodeVapidPublicKey,
  registerNotificationServiceWorker,
  supportsPushNotifications,
} from "@/lib/notifications";
import {
  clearNotificationSubscriptionId,
  getNotificationDeviceName,
  getNotificationSubscriptionId,
  saveNotificationDeviceName,
  saveNotificationSubscriptionId,
} from "@/lib/storage";
import type {
  NotificationPreferences,
  NotificationSubscriptionRecord,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type NotificationPreferenceKey = keyof NotificationPreferences;
type NotificationTranslator = (
  key: string,
  values?: Record<string, string>,
) => string;

const PREFERENCE_KEYS: NotificationPreferenceKey[] = [
  "escalation_pending",
  "attended_turn_completed",
  "unattended_turn_completed",
  "unattended_turn_failed",
];

function resolveErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function formatTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return null;
  return new Date(parsed).toLocaleString();
}

function readPushKeys(pushSubscription: PushSubscription): { p256dh: string; auth: string } | null {
  const json = pushSubscription.toJSON() as {
    keys?: {
      p256dh?: string;
      auth?: string;
    };
  };
  const p256dh = json.keys?.p256dh?.trim();
  const auth = json.keys?.auth?.trim();
  if (!p256dh || !auth) return null;
  return { p256dh, auth };
}

function toUint8Array(value: BufferSource | null | undefined): Uint8Array | null {
  if (!value) return null;
  if (value instanceof ArrayBuffer) {
    return new Uint8Array(value);
  }
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  return null;
}

export function pushServerKeysMatch(
  existingKey: BufferSource | null | undefined,
  nextKey: ArrayBuffer,
): boolean {
  const existingBytes = toUint8Array(existingKey);
  const nextBytes = new Uint8Array(nextKey);
  if (!existingBytes) {
    return false;
  }
  if (existingBytes.byteLength !== nextBytes.byteLength) {
    return false;
  }
  for (let index = 0; index < existingBytes.byteLength; index += 1) {
    if (existingBytes[index] !== nextBytes[index]) {
      return false;
    }
  }
  return true;
}

export function NotificationSubscription({
  server,
  token,
  translate,
}: {
  server: string;
  token: string;
  translate?: NotificationTranslator;
}) {
  if (translate) {
    return (
      <NotificationSubscriptionContent
        server={server}
        token={token}
        translate={translate}
      />
    );
  }

  return <TranslatedNotificationSubscription server={server} token={token} />;
}

function TranslatedNotificationSubscription({
  server,
  token,
}: {
  server: string;
  token: string;
}) {
  const t = useTranslations("preferences.notifications");
  return (
    <NotificationSubscriptionContent
      server={server}
      token={token}
      translate={t}
    />
  );
}

function NotificationSubscriptionContent({
  server,
  token,
  translate: t,
}: {
  server: string;
  token: string;
  translate: NotificationTranslator;
}) {
  const [pushSupported, setPushSupported] = useState(false);
  const [permission, setPermission] = useState<NotificationPermission>(
    typeof Notification === "undefined" ? "default" : Notification.permission,
  );
  const [subscription, setSubscription] = useState<NotificationSubscriptionRecord | null>(null);
  const [deviceName, setDeviceName] = useState(() => getNotificationDeviceName() || buildNotificationDeviceName());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const loadFailedMessageRef = useRef(t("status.loadFailed"));

  useEffect(() => {
    loadFailedMessageRef.current = t("status.loadFailed");
  }, [t]);

  useEffect(() => {
    let cancelled = false;

    queueMicrotask(() => {
      if (cancelled) {
        return;
      }

      const supported = supportsPushNotifications();
      const fallbackDeviceName = getNotificationDeviceName() || buildNotificationDeviceName();

      setPushSupported(supported);
      setPermission(typeof Notification === "undefined" ? "default" : Notification.permission);
      setDeviceName((current) => current || fallbackDeviceName);

      if (!server || !token || !supported) {
        setSubscription(null);
        setError("");
        setLoading(false);
        return;
      }

      setLoading(true);
      void (async () => {
        try {
          const registration = await registerNotificationServiceWorker();
          const browserSubscription = await registration?.pushManager.getSubscription() ?? null;
          const subscriptions = await listNotificationSubscriptions(server, token);
          const storedSubscriptionId = getNotificationSubscriptionId();
          let activeSubscription = subscriptions.find(
            (candidate) => candidate.subscription_id === storedSubscriptionId,
          ) ?? null;
          if (!activeSubscription && browserSubscription) {
            activeSubscription = subscriptions.find(
              (candidate) => candidate.endpoint === browserSubscription.endpoint,
            ) ?? null;
          }

          if (cancelled) {
            return;
          }

          if (activeSubscription) {
            saveNotificationSubscriptionId(activeSubscription.subscription_id);
            saveNotificationDeviceName(activeSubscription.device_name);
            setDeviceName(activeSubscription.device_name || fallbackDeviceName);
          } else {
            clearNotificationSubscriptionId();
          }

          setSubscription(activeSubscription);
          setError("");
        } catch (nextError) {
          if (cancelled) {
            return;
          }
          setError(resolveErrorMessage(nextError, loadFailedMessageRef.current));
        } finally {
          if (!cancelled) {
            setLoading(false);
          }
        }
      })();
    });

    return () => {
      cancelled = true;
    };
  }, [server, token]);

  useEffect(() => {
    const refreshPermission = () => {
      if (typeof Notification !== "undefined") {
        setPermission(Notification.permission);
      }
    };

    window.addEventListener("focus", refreshPermission);
    return () => {
      window.removeEventListener("focus", refreshPermission);
    };
  }, []);

  async function handleEnableNotifications() {
    if (!server || !token) return;

    setSaving(true);
    setError("");
    try {
      const registration = await registerNotificationServiceWorker();
      if (!registration) {
        throw new Error(t("status.unsupported"));
      }

      let nextPermission = Notification.permission;
      if (nextPermission !== "granted") {
        nextPermission = await Notification.requestPermission();
      }
      setPermission(nextPermission);
      if (nextPermission !== "granted") {
        throw new Error(
          nextPermission === "denied"
            ? t("status.permissionDenied")
            : t("status.permissionRequired"),
        );
      }

      const vapidPublicKey = await getVapidPublicKey(server);
      const applicationServerKey = decodeVapidPublicKey(vapidPublicKey);
      let pushSubscription = await registration.pushManager.getSubscription();
      if (
        pushSubscription &&
        !pushServerKeysMatch(
          pushSubscription.options.applicationServerKey,
          applicationServerKey,
        )
      ) {
        await pushSubscription.unsubscribe();
        pushSubscription = null;
      }
      if (!pushSubscription) {
        pushSubscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey,
        });
      }

      const pushKeys = readPushKeys(pushSubscription);
      if (!pushKeys) {
        throw new Error(t("status.invalidSubscription"));
      }

      const nextDeviceName = deviceName.trim() || buildNotificationDeviceName();
      const saved = await upsertNotificationSubscription(server, token, {
        endpoint: pushSubscription.endpoint,
        p256dh: pushKeys.p256dh,
        auth: pushKeys.auth,
        device_name: nextDeviceName,
        preferences: subscription?.preferences,
      });

      saveNotificationSubscriptionId(saved.subscription_id);
      saveNotificationDeviceName(saved.device_name);
      setDeviceName(saved.device_name);
      setSubscription(saved);
    } catch (nextError) {
      setError(resolveErrorMessage(nextError, t("status.enableFailed")));
    } finally {
      setSaving(false);
    }
  }

  async function handleDisableNotifications() {
    if (!server || !token) return;

    setSaving(true);
    setError("");
    try {
      const registration = await registerNotificationServiceWorker();
      const pushSubscription = await registration?.pushManager.getSubscription() ?? null;
      if (pushSubscription) {
        await pushSubscription.unsubscribe();
      }

      const storedSubscriptionId = subscription?.subscription_id || getNotificationSubscriptionId();
      if (storedSubscriptionId) {
        await deleteNotificationSubscription(server, token, storedSubscriptionId);
      }

      clearNotificationSubscriptionId();
      setSubscription(null);
    } catch (nextError) {
      setError(resolveErrorMessage(nextError, t("status.disableFailed")));
    } finally {
      setSaving(false);
    }
  }

  async function handlePreferenceChange(
    key: NotificationPreferenceKey,
    value: boolean,
  ) {
    if (!subscription) return;

    setSaving(true);
    setError("");
    try {
      const updated = await updateNotificationSubscriptionPreferences(
        server,
        token,
        subscription.subscription_id,
        { [key]: value },
      );
      setSubscription(updated);
    } catch (nextError) {
      setError(resolveErrorMessage(nextError, t("status.preferencesFailed")));
    } finally {
      setSaving(false);
    }
  }

  const permissionLabel = t(`permission.${permission}`);
  const lastHeartbeat = formatTimestamp(subscription?.last_heartbeat);
  const expiresAt = formatTimestamp(subscription?.expires_at);

  return (
    <div className="rounded-2xl border border-border bg-muted/25 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="rounded-2xl border border-border bg-background/85 p-2.5 text-muted-foreground shadow-sm">
            <Smartphone className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-foreground">
              {t("title")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("description")}
            </p>
          </div>
        </div>
        <span className={cn(
          "shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.12em]",
          subscription
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700"
            : "border-border bg-background/75 text-muted-foreground",
        )}>
          {loading ? t("status.loadingShort") : subscription ? t("status.enabledShort") : t("status.disabledShort")}
        </span>
      </div>

      <div className="mt-4 space-y-4">
        <div className="space-y-1.5">
          <label className="block text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {t("deviceName.label")}
          </label>
          <input
            value={deviceName}
            onChange={(event) => {
              const nextDeviceName = event.target.value;
              setDeviceName(nextDeviceName);
              saveNotificationDeviceName(nextDeviceName);
            }}
            placeholder={t("deviceName.placeholder")}
            className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30"
          />
          <p className="text-xs text-muted-foreground">
            {t("deviceName.hint")}
          </p>
        </div>

        <div className="rounded-2xl border border-border bg-background/80 px-4 py-3 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : subscription ? <BellRing className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
            <span>
              {loading
                ? t("status.loading")
                : !pushSupported
                ? t("status.unsupported")
                : permission === "denied"
                ? t("status.permissionDenied")
                : subscription
                ? t("status.enabled")
                : t("status.disabled")}
            </span>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {t("meta.permission", { permission: permissionLabel })}
          </p>
          {lastHeartbeat ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("meta.heartbeat", { timestamp: lastHeartbeat })}
            </p>
          ) : null}
          {expiresAt ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("meta.expires", { timestamp: expiresAt })}
            </p>
          ) : null}
          {error ? (
            <p className="mt-3 text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={subscription ? handleDisableNotifications : handleEnableNotifications}
            disabled={loading || saving || (!subscription && !pushSupported) || (!subscription && permission === "denied")}
            className={cn(
              "inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-2.5 text-sm font-medium transition-colors",
              subscription
                ? "border border-border bg-background text-foreground hover:bg-muted"
                : "bg-foreground text-background hover:bg-foreground/90",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {saving ? t(subscription ? "actions.disabling" : "actions.enabling") : t(subscription ? "actions.disable" : "actions.enable")}
          </button>
        </div>

        {subscription ? (
          <fieldset className="space-y-3 rounded-2xl border border-border bg-background/80 p-4 shadow-sm">
            <legend className="px-1 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
              {t("preferences.label")}
            </legend>
            {PREFERENCE_KEYS.map((key) => (
              <label key={key} className="flex items-start gap-3 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={subscription.preferences[key]}
                  onChange={(event) => handlePreferenceChange(key, event.target.checked)}
                  disabled={saving}
                  className="mt-0.5 h-4 w-4 rounded border-border text-foreground focus:ring-ring/40"
                />
                <span>{t(`preferences.${key}`)}</span>
              </label>
            ))}
          </fieldset>
        ) : null}
      </div>
    </div>
  );
}

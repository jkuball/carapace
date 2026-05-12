# Notifications Stage 3: Frontend UX & Hardening

**Objective:** Implement client-side service worker and notification UI; add comprehensive tests, rate limiting, and production safeguards.

**Deliverable:** Users can install PWA, enable notifications, receive and interact with push notifications on desktop and mobile; system passes full test matrix.

**Prerequisite:** Stage 1 and Stage 2 complete (subscriptions, presence, dispatch all functional).

---

## Phase 3.1 — Service Worker & Push Integration

### Service Worker Setup

**New file:** `frontend/public/service-worker.js`

Implement push event handlers and notification lifecycle:

```javascript
self.addEventListener("push", (event) => {
  const payload = event.data.json();
  if (payload.kind === "notification_clear") {
    event.waitUntil(
      self.registration
        .getNotifications({ tag: payload.notif_id })
        .then((notifs) => notifs.forEach((n) => n.close())),
    );
    return;
  }

  const options = {
    body: payload.body,
    icon: payload.icon,
    badge: payload.badge,
    tag: payload.notif_id, // for tag-based dedup
    data: {
      session_id: payload.session_id,
      kind: payload.kind,
      notif_id: payload.notif_id,
    },
  };
  event.waitUntil(self.registration.showNotification(payload.title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: "window" }).then((windowClients) => {
      const target = `/?session=${encodeURIComponent(event.notification.data.session_id)}`;
      // Focus or open app window, navigate to selected session via query param
      const client = windowClients.find((c) => c.visibilityState === "visible");
      if (client) {
        client.navigate(target);
        return client.focus();
      } else {
        return clients.openWindow(target);
      }
    }),
  );
});
```

### Service Worker Registration

**Modify:** `frontend/src/components/app-providers.tsx` (or equivalent bootstrap)

```tsx
useEffect(() => {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch((err) => {
      console.debug("Service Worker registration failed", err);
    });
  }
}, []);
```

---

## Phase 3.2 — Push Subscription UI Flow

### Subscription Component

**New file:** `frontend/src/components/notification-subscription.tsx`

```tsx
export function NotificationSubscription() {
  const [status, setStatus] = useState<
    "idle" | "requesting" | "subscribed" | "error"
  >("idle");
  const [subscription, setSubscription] = useState<PushSubscription | null>(
    null,
  );

  const handleSubscribe = async () => {
    setStatus("requesting");
    try {
      // Request notification permission
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setStatus("error");
        return;
      }

      // Get service worker registration
      const registration = await navigator.serviceWorker.ready;

      // Generate VAPID application server key from backend config
      const vapidPublicKey = await fetchVapidPublicKey();

      // Subscribe to push
      const pushSubscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
      });

      // Send subscription to backend
      const response = await fetch("/api/notifications/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: pushSubscription.endpoint,
          p256dh: arrayBufferToBase64(pushSubscription.getKey("p256dh")),
          auth: arrayBufferToBase64(pushSubscription.getKey("auth")),
          device_name: getDeviceName(),
        }),
      });

      const data = await response.json();
      setSubscription(pushSubscription);
      setStatus("subscribed");
      storeSubscriptionId(data.subscription_id);
    } catch (error) {
      logger.error("Subscription failed", error);
      setStatus("error");
    }
  };

  return (
    <div>
      <button onClick={handleSubscribe} disabled={status !== "idle"}>
        {status === "subscribed"
          ? "✓ Notifications Enabled"
          : "Enable Notifications"}
      </button>
      {status === "error" && (
        <p className="text-red-600">Failed to enable notifications</p>
      )}
    </div>
  );
}
```

Helper functions:

```tsx
function getDeviceName(): string {
  // e.g., "Chrome on macOS", "Safari on iPhone"
  const ua = navigator.userAgent;
  return ua.substring(0, 50); // truncate for storage
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return new Uint8Array([...rawData].map((char) => char.charCodeAt(0)));
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
```

---

## Phase 3.3 — Preferences UI

### Extend Preferences Component

**Modify:** `frontend/src/components/preferences-view.tsx`

Add notification preferences section:

```tsx
export function PreferencesView() {
  const [subscriptionId, setSubscriptionId] = useState<string | null>(null);
  const [preferences, setPreferences] = useState<NotificationPreferences>({
    escalation_pending: true,
    attended_turn_completed: true,
    unattended_turn_completed: false,
    unattended_turn_failed: true,
  });

  useEffect(() => {
    const id = getStoredSubscriptionId();
    setSubscriptionId(id);
  }, []);

  const handlePreferenceChange = async (
    key: keyof NotificationPreferences,
    value: boolean,
  ) => {
    const updated = { ...preferences, [key]: value };
    setPreferences(updated);

    if (subscriptionId) {
      try {
        await fetch(
          `/api/notifications/subscriptions/${subscriptionId}/preferences`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ [key]: value }),
          },
        );
      } catch (error) {
        logger.error("Failed to update preferences", error);
        // Revert on error
        setPreferences(preferences);
      }
    }
  };

  return (
    <section>
      <h3>Notifications</h3>
      <label>
        <input
          type="checkbox"
          checked={preferences.escalation_pending}
          onChange={(e) =>
            handlePreferenceChange("escalation_pending", e.target.checked)
          }
        />
        Escalation requests require attention
      </label>
      <label>
        <input
          type="checkbox"
          checked={preferences.attended_turn_completed}
          onChange={(e) =>
            handlePreferenceChange("attended_turn_completed", e.target.checked)
          }
        />
        Agent turn completed (attended session)
      </label>
      <label>
        <input
          type="checkbox"
          checked={preferences.unattended_turn_completed}
          onChange={(e) =>
            handlePreferenceChange(
              "unattended_turn_completed",
              e.target.checked,
            )
          }
        />
        Job completed successfully (unattended)
      </label>
      <label>
        <input
          type="checkbox"
          checked={preferences.unattended_turn_failed}
          onChange={(e) =>
            handlePreferenceChange("unattended_turn_failed", e.target.checked)
          }
        />
        Job completed with error (unattended)
      </label>
      <p className="text-sm text-gray-600">
        Notifications are per-device. Configure separately for each device you
        use.
      </p>
    </section>
  );
}
```

---

## Phase 3.4 — Presence Heartbeat

### Periodic Presence Updates

**Modify:** `frontend/src/hooks/use-websocket.ts` or notification context

Send presence update on connection and periodically:

```typescript
export function useNotificationPresence(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return;

    const sendPresence = async () => {
      const subscriptionId = getStoredSubscriptionId();
      if (!subscriptionId) return;

      const focusState = document.hidden ? "hidden" : "visible";

      try {
        await fetch(
          `/api/notifications/subscriptions/${subscriptionId}/presence`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: sessionId,
              client_type: "web",
              focus_state: focusState,
            }),
          },
        );
      } catch (error) {
        logger.debug("Presence update failed", error);
      }
    };

    // Send immediately and then every 30s
    sendPresence();
    const interval = setInterval(sendPresence, 30000);

    // Send on focus/blur
    const handleFocus = () => sendPresence();
    const handleBlur = () => sendPresence();
    window.addEventListener("focus", handleFocus);
    window.addEventListener("blur", handleBlur);

    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener("blur", handleBlur);
    };
  }, [sessionId]);
}
```

---

## Phase 3.5 — Tests & Validation

### Backend Tests

**New file:** `tests/test_notifications_integration.py`

```python
async def test_escalation_notification_sent():
  """Escalation callback path triggers notification dispatch."""
    engine = await create_test_session()
    subscription = await create_test_subscription()

  escalate = engine._make_escalation_cb(engine._ensure_active(engine_session_id))
  await escalate(engine_session_id, "example.com", {"kind": "domain_access", "command": "curl ..."})
    # Assert: WebPushSender.send called with correct payload
    # Assert: notif_id matches pattern esc:*:*

async def test_escalation_cleared_on_resolution():
    """Escalation resolution clears notification."""
    # Setup: create escalation, verify notification sent
    # Act: resolve escalation
    # Assert: clear_notifications called with correct notif_id

async def test_attended_turn_completion_sends():
  """Attended session completion path sends notification."""
    engine = await create_attended_session()
    subscription = await create_test_subscription()

  await engine._finalize_successful_turn(...)
  # Assert: dispatch_turn_outcome called with kind="attended_turn_completed"

async def test_unattended_success_respects_default():
    """Unattended success respects default (off) preference."""
    subscription = await create_test_subscription(
        unattended_turn_completed=False  # default
    )
  await engine._finalize_successful_turn(...)
    # Assert: dispatch NOT called (or called with empty list)

async def test_unattended_failure_respects_default():
    """Unattended failure respects default (on) preference."""
    subscription = await create_test_subscription(
        unattended_turn_failed=True  # default
    )
  engine._save_user_message_on_failure(..., final_status="warning")
    # Assert: dispatch_turn_outcome called

async def test_suppression_when_actively_handled():
    """No notification sent when interactive client active."""
    engine = await create_test_session()
    subscription = await create_test_subscription()

    # Simulate active web presence
    await router.presence.update(
        session_id=engine.session_id,
        client_type="web",
        focus_state="visible"
    )

    escalate = engine._make_escalation_cb(engine._ensure_active(engine_session_id))
    await escalate(engine_session_id, "example.com", {"kind": "domain_access", "command": "curl ..."})
    # Assert: dispatch NOT called (suppressed by presence check)

async def test_clear_closes_notification_by_tag():
    """Clear notification payload causes client to close by tag."""
    # This is client-side tested; backend assertion:
    # Assert: clear_notifications sends payload with kind="notification_clear"

async def test_subscription_endpoint_404_triggers_cleanup():
    """Invalid endpoint (404) triggers subscription deletion."""
    subscription = await create_test_subscription()
    sender.mock_endpoint_invalid(subscription.endpoint)

    await router.dispatch_escalation(...)
    # Assert: subscription deleted after failed send
```

### Frontend Tests

**Extend:** `frontend/__tests__/` with notification tests

```typescript
describe("NotificationSubscription", () => {
  it("should request permission and subscribe to push", async () => {
    const { getByRole } = render(<NotificationSubscription />);
    const button = getByRole("button", { name: /Enable Notifications/ });

    // Mock Notification API and service worker
    global.Notification.requestPermission = jest.fn().resolveValue("granted");

    await act(async () => {
      fireEvent.click(button);
    });

    // Assert: API called to register subscription
    expect(fetch).toHaveBeenCalledWith("/api/notifications/subscriptions", expect.any(Object));
  });
});

describe("Service Worker", () => {
  it("should handle push event and show notification", async () => {
    const event = createPushEvent({
      title: "Escalation",
      body: "Action required",
      notif_id: "esc:session123:req456"
    });

    // Trigger handler
    await self.onpush(event);

    // Assert: registration.showNotification called
    expect(self.registration.showNotification).toHaveBeenCalledWith(
      "Escalation",
      expect.objectContaining({ tag: "esc:session123:req456" })
    );
  });

  it("should close notification on click", async () => {
    const notification = createMockNotification();
    const event = createNotificationClickEvent(notification);

    await self.onnotificationclick(event);

    // Assert: notification.close() called
    expect(notification.close).toHaveBeenCalled();
    // Assert: clients.openWindow or focus called with session route
  });

  it("should close notifications by tag on clear payload", async () => {
    const clearEvent = createPushEvent({
      kind: "notification_clear",
      notif_id: "esc:session123:req456"
    });

    await self.onpush(clearEvent);

    // Assert: getNotifications called with tag
    expect(self.registration.getNotifications).toHaveBeenCalledWith({
      tag: "esc:session123:req456"
    });
  });
});
```

### Manual Test Matrix

1. **Desktop (macOS, Windows, Linux)**
   - Install PWA via browser install prompt
   - Enable notifications and set preferences
   - Receive escalation notification while app not visible
   - Click notification, app opens to escalation
   - Close notification via app UI, clear payload closes on other device
   - Verify preference changes persist

2. **Android**
   - Install PWA to home screen
   - Open app, enable notifications
   - Switch to another app, trigger escalation
   - Notification appears in Android notification tray
   - Tap notification, app opens to session
   - Verify unattended job notifications respect defaults

3. **Cross-Device Clearing**
   - Device A: enable notifications
   - Device B: enable notifications
   - Trigger escalation from CLI
   - Both devices receive notification
   - Device A: resolve escalation
   - Device B: clear notification appears automatically

4. **Cron Job Scenarios**
   - Schedule unattended job with success outcome
   - Device: has `unattended_turn_completed = false` (default)
   - Result: no notification sent ✓
   - Change preference to true
   - Re-run: notification sent ✓
   - Test failure scenarios with default true ✓

5. **Presence & Suppression**
   - Device A: visible, focused
   - CLI: active connection
   - Trigger escalation from web
   - Result: no notification (suppressed due to active CLI) ✓

---

## Phase 3.6 — Hardening & Operations

### Rate Limiting

**In NotificationRouter:**

- Per-session: max 10 notifications per 60 seconds
- Per-subscription: max 20 notifications per 60 seconds
- Per-kind: escalations max 5 per 60 seconds per session
- Implement token bucket or sliding window

### Payload Sanitization

- Title and body: max 100 and 200 chars, no HTML entities, escaped
- Validate notif*id format (allowed chars: `[:a-z0-9*-]`)
- Reject payloads > 4KB

### Operational Commands

Add CLI tools for diagnostics:

```bash
# List active subscriptions
uv run carapace subscriptions list --format json

# Check subscription health (last heartbeat age, endpoint status)
uv run carapace subscriptions check <subscription_id>

# Expire old subscriptions (manual cleanup if auto-expiry not working)
uv run carapace subscriptions cleanup --older-than 30d

# Resend notification (for testing/recovery)
uv run carapace notifications resend <session_id> <notif_id>
```

### Monitoring & Logging

- Log all push sends with success/failure status
- Track endpoint invalidity rate (404/410)
- Alert on: high retry rate, subscription expiry rate > threshold
- Grafana dashboard: notifications sent vs delivered, preference distribution

---

## Implementation Files & Anchors

### Frontend

- `frontend/public/service-worker.js` — Service worker push/clear handlers
- `frontend/src/components/notification-subscription.tsx` — Subscription flow
- `frontend/src/components/preferences-view.tsx` — Preferences UI
- `frontend/src/hooks/use-notification-presence.ts` — Presence heartbeat
- `frontend/src/app/layout.tsx` — Service worker registration bootstrap
- `frontend/__tests__/notifications.test.ts` — Full test suite

### Backend

- `src/carapace/notifications/router.py` — Rate limiting, sanitization
- `tests/test_notifications_integration.py` — Comprehensive tests
- `src/carapace/cli.py` — Add notification management commands

### Configuration

- `src/carapace/config.py` — Rate limit thresholds, cleanup jobs

---

## Acceptance Criteria

1. ✅ Service worker registers and handles push events
2. ✅ Notification permission request works on desktop and mobile
3. ✅ Subscription endpoint stored and VAPID keys used correctly
4. ✅ Preferences UI updates per-device and persists
5. ✅ Presence heartbeats sent on focus/blur and periodically
6. ✅ Notifications display correctly on all platforms
7. ✅ Notification click navigates to session
8. ✅ Clear notifications close by tag on all subscriptions
9. ✅ Rate limiting prevents spam (logs surplus attempts)
10. ✅ Payload sanitization enforced (no crashes on malformed content)
11. ✅ All tests pass (unit + integration + manual matrix)
12. ✅ CLI diagnostics available for ops
13. ✅ Monitoring and alerting configured

---

## Notes

- VAPID public key exposed via `/api/config/vapid-public-key` (public, no auth required)
- Service worker lifecycle: register once, handle updates automatically via browser
- Notification clicks target `/?session={id}` because current frontend session selection is query-param based, not route-segment based
- Clear payloads may arrive before original notification is read (race condition acceptable)
- Preference changes are immediately effective (no restart needed)
- Backfill testing: after deployment, verify escalations and job outcomes trigger notifications correctly

# Notifications Stage 1: Core APIs & Infrastructure

**Objective:** Establish data contracts, persistence layer, and REST API foundation for per-device push subscriptions and presence tracking.

**Deliverable:** Backend can accept subscriptions, track per-device preferences, and maintain presence signals from connected clients.

---

## Phase 1.1 — Data Model & Contracts

Define canonical notification event taxonomy and stable identifiers for deduplication and clearing across devices.

### Notification Kinds

- `escalation_pending` — Escalation request requires attention
- `attended_turn_completed` — Agent turn finished, client attended the session
- `unattended_turn_completed` — Cron job completed successfully
- `unattended_turn_failed` — Cron job completed with error or warning
- `notification_clear` — Clear notification by id (cross-device)

### Notification IDs (for dedup/update/clear semantics)

- escalation: `esc:{session_id}:{request_id}`
- attended turn complete: `done:{session_id}:{assistant_event_index}`
- unattended complete/fail: `unattended:{session_id}:{assistant_event_index}:{status}`
- clear: `notification_clear:{notif_id}`

### Persistence Models

Create new store under `data/` directory (YAML first, lock semantics matching `SessionManager` patterns):

**Push Subscription** (`data/notifications/subscriptions/{subscription_id}.yaml`)

```yaml
id: <uuid>
owner_key: <sha256> # v1: hash of current long-lived app bearer token
device_name: "user's browser"
endpoint: <web-push-endpoint-url>
p256dh: <base64>
auth: <base64>
subscribed_at: <iso-timestamp>
last_heartbeat: <iso-timestamp>
expires_at: <iso-timestamp> # for cleanup
```

**Per-Subscription Preferences** (in same file or separate)

```yaml
notification_prefs:
  escalation_pending: true
  attended_turn_completed: true
  unattended_turn_completed: false
  unattended_turn_failed: true
```

**Presence Model** (transient runtime registry, not persisted into `SessionState`)

- `session_id` → `Set[{subscription_id | channel_instance_id, client_type, focus_state, last_activity}]`
- `client_type`: web | matrix | cli
- `focus_state`: visible | hidden | inactive
- Helper: `is_session_actively_handled(session_id) -> bool`
- Keep this as a dedicated presence registry; do not infer it from `SessionSubscriber` alone because current subscriber protocol has no channel/focus metadata.

---

## Phase 1.2 — Backend REST API

Add authenticated REST endpoints under `/api/notifications/` for subscription lifecycle and presence updates.

### Endpoints

**POST `/api/notifications/subscriptions`** (Upsert)

- Request: `{endpoint, p256dh, auth, device_name, preferences}`
- Response: `{subscription_id, expires_at}`
- Behavior: Create new subscription or update preferences for existing device

**DELETE `/api/notifications/subscriptions/{subscription_id}`**

- Response: `{success: bool}`
- Cleanup: Remove subscription, log unsubscribe

**PATCH `/api/notifications/subscriptions/{subscription_id}/preferences`**

- Request: `{escalation_pending?: bool, attended_turn_completed?: bool, unattended_turn_completed?: bool, unattended_turn_failed?: bool}`
- Response: `{subscription_id, preferences}`

**POST `/api/notifications/subscriptions/{subscription_id}/presence`** (Heartbeat)

- Request: `{session_id, client_type, focus_state}`
- Response: `{heartbeat_received: bool}`
- Behavior: Update presence TTL; clear stale entries

**GET `/api/notifications/subscriptions`** (Optional, diagnostics)

- Response: List active subscriptions (count, device names, last heartbeat)
- Gating: Admin or diagnostics mode only

---

## Phase 1.3 — Client Presence Transport

Use the REST heartbeat endpoint as the authoritative write path for web presence in Stage 1.

### Web Presence Heartbeat Payload

```json
{
  "session_id": "<session_id>",
  "client_type": "web",
  "focus_state": "visible"
}
```

Emit on:

- Initial connection once a session is selected
- Focus/blur or visibility changes
- Every 30s keepalive while a session is active

Optional later optimization:

- A WebSocket `presence_update` message may be added later, but it must feed the same presence registry and follow the same TTL rules.
- If both REST and WebSocket updates exist, the registry remains source of truth; transport choice must not change behavior.

---

## Phase 1.4 — Presence Computation Logic

Add deterministic helper in session engine to evaluate "actively handled" state.

```python
def is_session_actively_handled(session_id: str) -> bool:
    """
    Check if session has at least one actively connected client.
    Returns True if:
    - Web client with presence heartbeat age < 60s AND focus_state = 'visible'
    - OR Matrix adapter has recently marked the session as active
    - OR CLI adapter has recently marked the session as active
    """
```

Logic:

1. Check web subscriptions: `focus_state == 'visible' AND last_heartbeat < 60s`
2. Check Matrix presence entries written by the Matrix channel integration
3. Check CLI presence entries written by the CLI channel integration
4. Return True if any condition met, else False

---

## Implementation Files & Anchors

### Backend

- `src/carapace/models.py` — Add `PushSubscription`, `NotificationPreferences` pydantic models
- `src/carapace/config.py` — Add VAPID keys, feature flag, notification defaults
- New: `src/carapace/notifications/store.py` — Subscription YAML persistence (lock, load, save, expire)
- New: `src/carapace/notifications/models.py` — Presence state, is_session_actively_handled helper
- `src/carapace/server.py` — Register `/api/notifications/*` routes
- Optional later: `src/carapace/ws_models.py` — Add `PresenceUpdateMessage` payload schema if presence moves onto WebSocket as well

Ownership note:

- In v1, derive `owner_key` from the authenticated app token because that is the only stable principal currently available.
- Keep field name generic (`owner_key`) so token rotation or future user identity can swap the derivation later without reshaping the subscription model.

### Data Directory

- `data/notifications/subscriptions/` — Per-subscription YAML files

---

## Acceptance Criteria

1. ✅ Subscription YAML persistence works (create, read, update, delete, expire)
2. ✅ REST API accepts subscriptions and preferences
3. ✅ Web client sends REST presence heartbeats on focus/blur and session changes
4. ✅ Presence TTL cleanup runs (background task or on-demand)
5. ✅ `is_session_actively_handled()` correctly detects web + matrix + cli clients
6. ✅ Type checks pass (`uv run pyright`)
7. ✅ Basic tests for subscription store and presence logic (`uv run pytest`)

---

## Notes

- Presence heartbeat TTL: 60 seconds (treat stale as disconnected)
- Subscription expiry: 30 days or configurable via config
- Web focus state auto-detected via beforeunload / page visibility API on client
- Subscription ownership is grouped by `owner_key`. In v1, `owner_key` is derived from the current authenticated app token, so dispatch fans out to subscriptions registered under that token-derived key. If token rotation or a user identity layer is added later, the derivation can change without changing per-device preferences.
- No push sending yet; infrastructure only

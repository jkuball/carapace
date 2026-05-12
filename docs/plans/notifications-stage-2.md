# Notifications Stage 2: Dispatch & Engine Integration

**Objective:** Implement push sending, clearing semantics, and integrate notifications with session lifecycle events (escalations, turn outcomes).

**Deliverable:** Notifications are sent to subscribed devices when escalations are created and turns complete; notifications are cleared when resolved. Suppression works when an interactive client is actively handling the session.

**Prerequisite:** Stage 1 complete (subscriptions, preferences, presence APIs functional).

---

## Phase 2.1 — Push Dispatch Subsystem

Build a reusable Web Push sender and notification routing service.

### Web Push Sender Service

**New file:** `src/carapace/notifications/sender.py`

```python
class WebPushSender:
    """Send Web Push notifications via VAPID."""

    async def send(
        self,
        subscription: PushSubscription,
        payload: NotificationPayload
    ) -> bool:
        """
        Send notification. Returns True if successful.
        On 404/410 endpoint invalid, schedule subscription deletion.
        On 429 rate limit, retry with backoff.
        On network error, non-blocking retry queue.
        """

    async def send_batch(
        self,
        subscriptions: List[PushSubscription],
        payload: NotificationPayload
    ) -> Dict[str, bool]:
        """Send to multiple subscriptions; return per-subscription success."""
```

Features:

- VAPID signing with keys from config
- Automatic endpoint invalidation on 404/410 (delete subscription)
- Retry logic with exponential backoff (non-blocking, logged)
- Payload size limit (4KB) with validation
- Request timeout (10s)

### Notification Routing Service

**New file:** `src/carapace/notifications/router.py`

```python
class NotificationRouter:
    """Route and dispatch notifications based on preferences and session state."""

    async def dispatch_escalation(
        self,
        session_id: str,
        request_id: str,
        title: str,
        body: str
    ) -> int:
        """
        Send escalation_pending to subscribed devices where preference enabled.
        Suppress if any interactive client is actively handling session.
        Return count of devices notified.
        """

    async def dispatch_turn_outcome(
        self,
        session_id: str,
        assistant_event_index: int,
        kind: Literal["attended_turn_completed", "unattended_turn_completed", "unattended_turn_failed"],
        title: str,
        body: str
    ) -> int:
        """Send turn outcome notification, respecting preference defaults."""

    async def clear_notifications(
        self,
        session_id: str,
        notif_id: str
    ) -> int:
        """
        Send clear_notifications payload to all subscriptions.
        Clients will close notifications by tag.
        Return count of devices notified.
        """
```

Logic:

1. Fetch all subscriptions for the current authenticated `owner_key` (v1: derived from the app token)
2. Check preference: should_notify(kind, preference_dict)
3. Check suppression: `is_session_actively_handled(session_id)` → skip
4. Filter by focus_state (optional: only notify if not currently visible)
5. Send batch via WebPushSender
6. Log delivery metadata (timestamp, kind, subscription_ids, count)

### Notification Payload Schema

```python
@dataclass
class NotificationPayload:
    kind: str  # escalation_pending | attended_turn_completed | ...
    notif_id: str  # esc:session_id:request_id | done:session_id:index | ...
    title: str
    body: str
    session_id: str
    tag: str = notif_id  # for browser tag-based dedup/replace
    badge: str = "/badge-icon.png"
    icon: str = "/pwa-192x192.png"
    actions: Optional[List[Dict[str, str]]] = None
```

---

## Phase 2.2 — Escalation Notification Hooks

Integrate escalation notifications with session engine lifecycle.

### Modifications to `src/carapace/session/engine.py`

Hook into the real escalation lifecycle inside `_make_escalation_cb(...)`, where pending escalations are appended, broadcast to subscribers, and later resolved from `active.escalation_queue`.

```python
class SessionEngine:
    def _make_escalation_cb(self, active: ActiveSession) -> Callable[..., Awaitable[UserEscalationDecision]]:
        async def _escalate(session_id: str, subject: str, context: dict[str, Any]) -> UserEscalationDecision:
            request_id = secrets.token_hex(8)
            # existing append_events(...) + active.pending_escalations.append(...) + broadcast(...)

            await self.notification_router.dispatch_escalation(
                session_id=session_id,
                request_id=request_id,
                title="Action Required",
                body=f"Escalation pending: {subject}",
            )

            msg = await active.escalation_queue.get()
            if msg is not None and msg.request_id == request_id:
                await self.notification_router.clear_notifications(
                    session_id=session_id,
                    notif_id=f"esc:{session_id}:{request_id}",
                )
                # existing response persistence + pending_escalations cleanup
```

Behavior:

- Send `escalation_pending` immediately on creation
- Clear immediately on resolution (no waiting for user to view)
- Suppress if another client is actively handling session

---

## Phase 2.3 — Turn Outcome Hooks

Integrate attended and unattended turn completion notifications.

### Modifications to `src/carapace/session/turns.py`

Hook into the real turn finalization paths: `_finalize_successful_turn(...)` for successful completions and `_save_user_message_on_failure(...)` for terminal unattended warnings/failures.

```python
async def _finalize_successful_turn(
    self,
    active: ActiveSession,
    session_id: str,
    messages: list[ModelMessage],
    output: str,
    thinking: str,
    final_status: FinalStatus | None = None,
) -> None:
    # existing persistence + broadcast

    if active.state.attributes.unattended:
        await self.notification_router.dispatch_turn_outcome(
            session_id=session_id,
            assistant_event_index=len(self._session_mgr.load_events(session_id)),
            kind="unattended_turn_completed",
            title="Job Completed",
            body="Unattended turn completed successfully",
        )
    else:
        await self.notification_router.dispatch_turn_outcome(
            session_id=session_id,
            assistant_event_index=len(self._session_mgr.load_events(session_id)),
            kind="attended_turn_completed",
            title="Session Update",
            body="Assistant turn completed",
        )


def _save_user_message_on_failure(..., final_status: FinalStatus | None = None) -> None:
    # existing failure persistence
    # if unattended final_status == "warning", route as unattended_turn_failed
```

Behavior:

- Attended: always send (suppressible by global presence)
- Unattended success: send only if user preference enabled (default: off)
- Unattended failure: send only if user preference enabled (default: on)

### Turn Outcome Clear Logic

Clear notification when:

1. User views the session (next user message or explicit view action)
2. Escalation response arrives (if awaiting approval)

Modify turn entry and session focus handling to check for pending notifications and clear them:

```python
async def submit_message(self, session_id: str, content: str, *, origin: SessionSubscriber | None = None) -> None:
    """Existing: Start an agent turn."""
    # ... existing logic ...

    # NEW: Clear any pending turn-outcome notifications once a user is actively back in session
    last_outcome = self.get_last_turn_outcome()
    if last_outcome:
        notif_id = f"unattended:{session_id}:{last_outcome.index}:{last_outcome.status}"
        await self.notification_router.clear_notifications(
            session_id=session_id,
            notif_id=notif_id
        )
```

Implementation note:

- Do not infer attended state from subscriber objects directly; current `SessionSubscriber` has no `client_type` or `focus_state` fields.
- Use `active.state.attributes.unattended` plus the shared presence registry from Stage 1.

---

## Phase 2.4 — Cron Job Unattended Notifications

Ensure cron-triggered jobs emit correct unattended notifications with defaults applied.

### Modifications to Job Runner (relevant in `src/carapace/jobs.py` or turn-loop context)

Jobs already carry `trigger_kind`. Use that plus session unattended state instead of inspecting hypothetical subscriber fields.

```python
async def run_job(job: Job) -> JobResult:
    """Run job and emit notifications based on outcome."""
    result = await execute_job(job)

    final_status = "success" if result.exit_code == 0 else "failure"

    if job.trigger_kind == "cron":
        # Unattended job: use defaults
        # Send unattended_turn_failed if error, skip unattended_turn_completed if success
        # (unless user preference overrides)
        await notification_router.dispatch_turn_outcome(
            session_id=job.session_id,
            assistant_event_index=result.event_index,
            kind=(
                "unattended_turn_completed"
                if final_status == "success"
                else "unattended_turn_failed"
            ),
            title=...,
            body=...
        )
```

**Requirement:** Cron jobs use `trigger_kind == "cron"` (check in job metadata) to qualify as unattended.

---

## Implementation Files & Anchors

### Backend

- `src/carapace/notifications/sender.py` — Web Push sender with VAPID
- `src/carapace/notifications/router.py` — Notification routing and dispatch
- `src/carapace/session/engine.py` — Escalation hooks inside `_make_escalation_cb(...)` and `submit_message(...)`
- `src/carapace/session/turns.py` — Attended/unattended turn hooks inside `_finalize_successful_turn(...)` and failure persistence paths
- `src/carapace/jobs.py` — Cron job unattended dispatch
- Reuse: `src/carapace/notifications/models.py` (presence, is_session_actively_handled)
- Reuse: `src/carapace/notifications/store.py` (subscription lookup)

### Configuration

- `src/carapace/config.py` — Add VAPID public/private keys, feature flag, retry settings

---

## Acceptance Criteria

1. ✅ WebPushSender sends notifications with VAPID signature
2. ✅ Endpoint 404/410 triggers subscription deletion
3. ✅ NotificationRouter filters by preference and presence
4. ✅ Escalation: send on create, clear on resolution
5. ✅ Attended turn: send completion when disconnected
6. ✅ Unattended turn: send success only if preference enabled (default off), failure always (default on)
7. ✅ Cron-triggered unattended jobs respect defaults
8. ✅ Clear notifications reach all subscribed devices
9. ✅ Suppression works: no send when `is_session_actively_handled()`
10. ✅ Delivery logging for diagnostics
11. ✅ Type checks pass, tests pass

---

## Notes

- Retry queue is non-blocking; failures are logged but do not block session operation
- Notification payload size validated against 4KB limit before sending
- Presence state (focus_state) available via Stage 1 heartbeat API
- Clear payloads may be delivered before clients even see the original notification (race condition acceptable per design)

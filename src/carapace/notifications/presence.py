from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from carapace.models.notifications import NotificationClientType, NotificationFocusState


@dataclass(frozen=True, slots=True)
class NotificationPresenceEntry:
    session_id: str
    source_id: str
    client_type: NotificationClientType
    focus_state: NotificationFocusState
    last_activity: datetime


class NotificationPresenceRegistry:
    def __init__(self, *, ttl: timedelta):
        self._ttl = ttl
        self._lock = RLock()
        self._entries: dict[str, dict[str, NotificationPresenceEntry]] = {}

    def update_presence(
        self,
        *,
        session_id: str,
        source_id: str,
        client_type: NotificationClientType,
        focus_state: NotificationFocusState,
        now: datetime | None = None,
    ) -> NotificationPresenceEntry:
        current = now or datetime.now(tz=UTC)
        entry = NotificationPresenceEntry(
            session_id=session_id,
            source_id=source_id,
            client_type=client_type,
            focus_state=focus_state,
            last_activity=current,
        )
        with self._lock:
            self._entries.setdefault(session_id, {})[source_id] = entry
        return entry

    def remove_presence(self, *, session_id: str, source_id: str) -> bool:
        with self._lock:
            session_entries = self._entries.get(session_id)
            if session_entries is None or source_id not in session_entries:
                return False
            del session_entries[source_id]
            if not session_entries:
                del self._entries[session_id]
        return True

    def prune_stale(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(tz=UTC)
        deleted = 0
        with self._lock:
            for session_id in list(self._entries):
                session_entries = self._entries[session_id]
                for source_id, entry in list(session_entries.items()):
                    if current - entry.last_activity <= self._ttl:
                        continue
                    del session_entries[source_id]
                    deleted += 1
                if not session_entries:
                    del self._entries[session_id]
        return deleted

    def list_presence(self, *, session_id: str, now: datetime | None = None) -> list[NotificationPresenceEntry]:
        self.prune_stale(now=now)
        with self._lock:
            return list(self._entries.get(session_id, {}).values())

    def is_session_actively_handled(self, session_id: str, *, now: datetime | None = None) -> bool:
        entries = self.list_presence(session_id=session_id, now=now)
        return any(self._entry_is_active(entry) for entry in entries)

    @staticmethod
    def _entry_is_active(entry: NotificationPresenceEntry) -> bool:
        if entry.client_type == "web":
            return entry.focus_state == "visible"
        return entry.focus_state != "inactive"

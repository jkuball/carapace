from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from loguru import logger

from carapace.models import NotificationPreferences, NotificationSubscription
from carapace.notifications.presence import NotificationPresenceRegistry
from carapace.notifications.store import NotificationStore

NotificationKind = Literal[
    "escalation_pending",
    "attended_turn_completed",
    "unattended_turn_completed",
    "unattended_turn_failed",
    "notification_clear",
]

TurnOutcomeKind = Literal[
    "attended_turn_completed",
    "unattended_turn_completed",
    "unattended_turn_failed",
]


def build_escalation_notification_id(session_id: str, request_id: str) -> str:
    return f"esc:{session_id}:{request_id}"


def build_turn_outcome_notification_id(
    session_id: str,
    assistant_event_index: int,
    kind: TurnOutcomeKind,
) -> str:
    return f"done:{session_id}:{assistant_event_index}:{kind}"


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    kind: NotificationKind
    notif_id: str
    title: str
    body: str
    session_id: str
    tag: str | None = None
    badge: str = "/badge-icon.png"
    icon: str = "/pwa-192x192.png"
    actions: list[dict[str, str]] | None = None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tag"] = self.tag or self.notif_id
        return payload


class NotificationSender(Protocol):
    async def send_batch(
        self,
        subscriptions: list[NotificationSubscription],
        payload: NotificationPayload,
    ) -> dict[str, bool]: ...


class NotificationRouter:
    def __init__(
        self,
        *,
        store: NotificationStore,
        presence: NotificationPresenceRegistry,
        sender: NotificationSender,
        owner_key: str,
    ) -> None:
        self._store = store
        self._presence = presence
        self._sender = sender
        self._owner_key = owner_key

    async def dispatch_escalation(
        self,
        *,
        session_id: str,
        request_id: str,
        title: str,
        body: str,
    ) -> int:
        notif_id = build_escalation_notification_id(session_id, request_id)
        return await self._dispatch(
            session_id=session_id,
            kind="escalation_pending",
            payload=NotificationPayload(
                kind="escalation_pending",
                notif_id=notif_id,
                title=title,
                body=body,
                session_id=session_id,
                actions=[{"action": "open", "title": "Open session"}],
            ),
            suppress_when_active=True,
        )

    async def dispatch_turn_outcome(
        self,
        *,
        session_id: str,
        assistant_event_index: int,
        kind: TurnOutcomeKind,
        title: str,
        body: str,
    ) -> int:
        notif_id = build_turn_outcome_notification_id(session_id, assistant_event_index, kind)
        return await self._dispatch(
            session_id=session_id,
            kind=kind,
            payload=NotificationPayload(
                kind=kind,
                notif_id=notif_id,
                title=title,
                body=body,
                session_id=session_id,
                actions=[{"action": "open", "title": "Open session"}],
            ),
            suppress_when_active=True,
        )

    async def clear_notifications(self, *, session_id: str, notif_id: str) -> int:
        subscriptions = self._store.list_subscriptions(owner_key=self._owner_key)
        if not subscriptions:
            return 0
        results = await self._sender.send_batch(
            subscriptions,
            NotificationPayload(
                kind="notification_clear",
                notif_id=notif_id,
                title="",
                body="",
                session_id=session_id,
            ),
        )
        delivered = sum(1 for sent in results.values() if sent)
        logger.info(f"Notification clear session={session_id} notif_id={notif_id} delivered={delivered}")
        return delivered

    async def _dispatch(
        self,
        *,
        session_id: str,
        kind: Literal[
            "escalation_pending",
            "attended_turn_completed",
            "unattended_turn_completed",
            "unattended_turn_failed",
        ],
        payload: NotificationPayload,
        suppress_when_active: bool,
    ) -> int:
        self._store.cleanup_expired()
        if suppress_when_active and self._presence.is_session_actively_handled(session_id):
            logger.info(
                f"Notification suppressed session={session_id} kind={kind}"
                + f" reason=active_presence notif_id={payload.notif_id}"
            )
            return 0

        subscriptions = [
            subscription
            for subscription in self._store.list_subscriptions(owner_key=self._owner_key)
            if _preferences_allow(subscription.notification_prefs, kind)
        ]
        if not subscriptions:
            return 0

        results = await self._sender.send_batch(subscriptions, payload)
        delivered = sum(1 for sent in results.values() if sent)
        logger.info(
            f"Notification dispatch session={session_id} kind={kind}"
            + f" notif_id={payload.notif_id} delivered={delivered} subscriptions={len(subscriptions)}"
        )
        return delivered


def _preferences_allow(
    prefs: NotificationPreferences,
    kind: Literal[
        "escalation_pending",
        "attended_turn_completed",
        "unattended_turn_completed",
        "unattended_turn_failed",
    ],
) -> bool:
    return getattr(prefs, kind)

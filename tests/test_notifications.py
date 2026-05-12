from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from pywebpush import WebPushException

from carapace.models import NotificationPreferences, NotificationSubscription
from carapace.notifications import NotificationPresenceRegistry, NotificationStore, derive_owner_key
from carapace.notifications.router import NotificationPayload, NotificationRouter
from carapace.notifications.sender import WebPushSender


def test_notification_subscription_defaults_last_heartbeat() -> None:
    subscribed_at = datetime(2026, 5, 12, tzinfo=UTC)
    subscription = NotificationSubscription.model_validate(
        {
            "id": "sub-1",
            "owner_key": "owner-1",
            "endpoint": "https://push.example.test/sub-1",
            "p256dh": "p256dh",
            "auth": "auth",
            "subscribed_at": subscribed_at,
            "expires_at": subscribed_at + timedelta(days=30),
        }
    )

    assert subscription.last_heartbeat == subscribed_at


def test_derive_owner_key_is_stable() -> None:
    token = "very-static-token"
    assert derive_owner_key(token) == derive_owner_key(token)
    assert derive_owner_key(token) != derive_owner_key("other-token")


def test_notification_store_upsert_and_list_by_owner(tmp_path) -> None:
    store = NotificationStore(tmp_path)
    now = datetime(2026, 5, 12, tzinfo=UTC)
    owner_key = derive_owner_key("token-1")
    prefs = NotificationPreferences(attended_turn_completed=False)

    created = store.upsert_subscription(
        owner_key=owner_key,
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=prefs,
        ttl=timedelta(days=30),
        now=now,
    )

    updated = store.upsert_subscription(
        owner_key=owner_key,
        endpoint="https://push.example.test/sub-1",
        p256dh="key-2",
        auth="auth-2",
        device_name="Phone 2",
        notification_prefs=NotificationPreferences(unattended_turn_completed=True),
        ttl=timedelta(days=30),
        now=now + timedelta(hours=1),
    )

    assert updated.id == created.id
    assert updated.device_name == "Phone 2"
    assert updated.p256dh == "key-2"
    assert updated.notification_prefs.unattended_turn_completed is True
    assert [subscription.id for subscription in store.list_subscriptions(owner_key=owner_key)] == [created.id]


def test_notification_store_cleanup_expired(tmp_path) -> None:
    store = NotificationStore(tmp_path)
    now = datetime(2026, 5, 12, tzinfo=UTC)
    subscription = store.upsert_subscription(
        owner_key=derive_owner_key("token-1"),
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Desktop",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=1),
        now=now,
    )

    deleted = store.cleanup_expired(now=now + timedelta(days=2))

    assert deleted == [subscription.id]
    assert store.get_subscription(subscription.id) is None


def test_presence_registry_tracks_visible_web_session() -> None:
    registry = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    now = datetime(2026, 5, 12, tzinfo=UTC)

    registry.update_presence(
        session_id="session-1",
        source_id="sub-1",
        client_type="web",
        focus_state="visible",
        now=now,
    )

    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=30)) is True
    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=61)) is False


def test_presence_registry_hidden_web_is_not_active() -> None:
    registry = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    now = datetime(2026, 5, 12, tzinfo=UTC)

    registry.update_presence(
        session_id="session-1",
        source_id="sub-1",
        client_type="web",
        focus_state="hidden",
        now=now,
    )

    assert registry.is_session_actively_handled("session-1", now=now) is False


def test_presence_registry_cli_entry_is_active_until_stale() -> None:
    registry = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    now = datetime(2026, 5, 12, tzinfo=UTC)

    registry.update_presence(
        session_id="session-1",
        source_id="cli-1",
        client_type="cli",
        focus_state="visible",
        now=now,
    )

    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=30)) is True
    assert registry.is_session_actively_handled("session-1", now=now + timedelta(seconds=70)) is False


async def test_notification_router_dispatch_turn_outcome_filters_by_preference_and_presence(tmp_path) -> None:
    store = NotificationStore(tmp_path)
    sender = AsyncMock()
    sender.send_batch = AsyncMock(return_value={"sub-1": True})
    owner_key = derive_owner_key("token-1")
    now = datetime.now(tz=UTC)
    store.upsert_subscription(
        owner_key=owner_key,
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(attended_turn_completed=True),
        ttl=timedelta(days=30),
        now=now,
    )
    store.upsert_subscription(
        owner_key=owner_key,
        endpoint="https://push.example.test/sub-2",
        p256dh="key-2",
        auth="auth-2",
        device_name="Laptop",
        notification_prefs=NotificationPreferences(attended_turn_completed=False),
        ttl=timedelta(days=30),
        now=now,
    )
    presence = NotificationPresenceRegistry(ttl=timedelta(seconds=60))
    router = NotificationRouter(
        store=store,
        presence=presence,
        sender=sender,
        owner_key=owner_key,
    )

    count = await router.dispatch_turn_outcome(
        session_id="session-1",
        assistant_event_index=3,
        kind="attended_turn_completed",
        title="Session Update",
        body="Assistant turn completed",
    )

    assert count == 1
    payload = sender.send_batch.await_args.args[1]
    assert isinstance(payload, NotificationPayload)
    assert payload.notif_id == "done:session-1:3:attended_turn_completed"

    sender.send_batch.reset_mock()
    presence.update_presence(
        session_id="session-1",
        source_id="web-tab-1",
        client_type="web",
        focus_state="visible",
        now=now,
    )

    suppressed = await router.dispatch_turn_outcome(
        session_id="session-1",
        assistant_event_index=4,
        kind="attended_turn_completed",
        title="Session Update",
        body="Assistant turn completed",
    )

    assert suppressed == 0
    sender.send_batch.assert_not_awaited()


async def test_web_push_sender_deletes_expired_subscription(tmp_path) -> None:
    store = NotificationStore(tmp_path)
    now = datetime.now(tz=UTC)
    subscription = store.upsert_subscription(
        owner_key=derive_owner_key("token-1"),
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=30),
        now=now,
    )

    def _raise_gone(**_kwargs: object) -> object:
        exc = WebPushException("gone")
        exc.response = MagicMock(status_code=410)
        raise exc

    sender = WebPushSender(
        store=store,
        vapid_private_key="private-key",
        vapid_subject="mailto:test@example.com",
        timeout_seconds=10,
        retry_attempts=0,
        retry_backoff_seconds=0,
        max_payload_bytes=4096,
        delivery_ttl_seconds=600,
        push_func=_raise_gone,
    )

    sent = await sender.send(
        subscription,
        NotificationPayload(
            kind="attended_turn_completed",
            notif_id="done:session-1:1:attended_turn_completed",
            title="Done",
            body="Completed",
            session_id="session-1",
        ),
    )

    assert sent is False
    assert store.get_subscription(subscription.id) is None


async def test_web_push_sender_skips_oversized_payload(tmp_path) -> None:
    store = NotificationStore(tmp_path)
    subscription = store.upsert_subscription(
        owner_key=derive_owner_key("token-1"),
        endpoint="https://push.example.test/sub-1",
        p256dh="key-1",
        auth="auth-1",
        device_name="Phone",
        notification_prefs=NotificationPreferences(),
        ttl=timedelta(days=30),
        now=datetime.now(tz=UTC),
    )

    sender = WebPushSender(
        store=store,
        vapid_private_key="private-key",
        vapid_subject="mailto:test@example.com",
        timeout_seconds=10,
        retry_attempts=0,
        retry_backoff_seconds=0,
        max_payload_bytes=32,
        delivery_ttl_seconds=600,
    )

    sent = await sender.send(
        subscription,
        NotificationPayload(
            kind="attended_turn_completed",
            notif_id="done:session-1:1:attended_turn_completed",
            title="Done",
            body="x" * 128,
            session_id="session-1",
        ),
    )

    assert sent is False
    assert store.get_subscription(subscription.id) is not None

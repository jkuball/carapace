from __future__ import annotations

from datetime import UTC, datetime, timedelta

from carapace.models import NotificationPreferences, NotificationSubscription
from carapace.notifications import NotificationPresenceRegistry, NotificationStore, derive_owner_key


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

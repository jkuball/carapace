from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

import yaml

from .models import NotificationPreferences, NotificationSubscription


class NotificationStore:
    def __init__(self, data_dir: Path):
        self._dir = data_dir / "notifications" / "subscriptions"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @property
    def path(self) -> Path:
        return self._dir

    def _subscription_path(self, subscription_id: str) -> Path:
        return self._dir / f"{subscription_id}.yaml"

    def get_subscription(self, subscription_id: str) -> NotificationSubscription | None:
        path = self._subscription_path(subscription_id)
        if not path.exists():
            return None
        with self._lock, open(path) as f:
            raw = yaml.safe_load(f) or {}
        return NotificationSubscription.model_validate(raw)

    def list_subscriptions(
        self,
        *,
        user: str | None = None,
    ) -> list[NotificationSubscription]:
        with self._lock:
            subscriptions = [
                NotificationSubscription.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
                for path in sorted(self._dir.glob("*.yaml"))
            ]
        if user is None:
            return subscriptions
        return [subscription for subscription in subscriptions if subscription.user == user]

    def find_by_endpoint(self, *, user: str, endpoint: str) -> NotificationSubscription | None:
        normalized_endpoint = endpoint.strip()
        for subscription in self.list_subscriptions(user=user):
            if subscription.endpoint == normalized_endpoint:
                return subscription
        return None

    def save_subscription(self, subscription: NotificationSubscription) -> NotificationSubscription:
        path = self._subscription_path(subscription.id)
        payload = subscription.model_dump(mode="json", exclude_none=True)
        with self._lock, open(path, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False)
        return subscription

    def delete_subscription(self, subscription_id: str) -> bool:
        path = self._subscription_path(subscription_id)
        if not path.exists():
            return False
        with self._lock:
            path.unlink(missing_ok=True)
        return True

    def cleanup_expired(self, *, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(tz=UTC)
        deleted: list[str] = []
        for subscription in self.list_subscriptions():
            if subscription.expires_at > current:
                continue
            if self.delete_subscription(subscription.id):
                deleted.append(subscription.id)
        return deleted

    def upsert_subscription(
        self,
        *,
        user: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        device_name: str,
        notification_prefs: NotificationPreferences,
        ttl: timedelta,
        now: datetime | None = None,
    ) -> NotificationSubscription:
        current = now or datetime.now(tz=UTC)
        existing = self.find_by_endpoint(user=user, endpoint=endpoint)
        if existing is None:
            subscription = NotificationSubscription(
                id=uuid.uuid4().hex,
                user=user,
                device_name=device_name,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                notification_prefs=notification_prefs,
                subscribed_at=current,
                last_heartbeat=current,
                expires_at=current + ttl,
            )
        else:
            subscription = existing.model_copy(
                update={
                    "device_name": device_name,
                    "p256dh": p256dh,
                    "auth": auth,
                    "notification_prefs": notification_prefs,
                    "last_heartbeat": current,
                    "expires_at": current + ttl,
                }
            )
        return self.save_subscription(subscription)

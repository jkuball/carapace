from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

NotificationClientType = Literal["web", "matrix", "cli"]
NotificationFocusState = Literal["visible", "hidden", "inactive"]


class NotificationPreferences(BaseModel):
    escalation_pending: bool = True
    attended_turn_completed: bool = True
    unattended_turn_completed: bool = False
    unattended_turn_failed: bool = True


class NotificationSubscription(BaseModel):
    id: str
    user: str
    device_name: str = ""
    endpoint: str
    p256dh: str
    auth: str
    notification_prefs: Annotated[NotificationPreferences, Field(default_factory=NotificationPreferences)]
    subscribed_at: datetime
    last_heartbeat: datetime | None = None
    expires_at: datetime

    @model_validator(mode="after")
    def _normalize(self) -> NotificationSubscription:
        self.id = self.id.strip()
        if not self.id:
            raise ValueError("notification subscription id must not be empty")
        self.user = self.user.strip().lower()
        if not self.user:
            raise ValueError("notification subscription user must not be empty")
        self.device_name = self.device_name.strip()
        self.endpoint = self.endpoint.strip()
        if not self.endpoint:
            raise ValueError("notification subscription endpoint must not be empty")
        self.p256dh = self.p256dh.strip()
        if not self.p256dh:
            raise ValueError("notification subscription p256dh must not be empty")
        self.auth = self.auth.strip()
        if not self.auth:
            raise ValueError("notification subscription auth must not be empty")
        if self.last_heartbeat is None:
            self.last_heartbeat = self.subscribed_at
        if self.expires_at <= self.subscribed_at:
            raise ValueError("notification subscription expires_at must be after subscribed_at")
        return self


class NotificationsConfig(BaseModel):
    enabled: bool = True
    presence_ttl_seconds: int = 60
    subscription_ttl_days: int = 30
    default_preferences: NotificationPreferences = Field(default_factory=NotificationPreferences)
    vapid_private_key: str | None = None
    vapid_subject: str | None = None
    send_timeout_seconds: int = 10
    retry_attempts: int = 2
    retry_backoff_seconds: float = 1.0
    max_payload_bytes: int = 4096
    delivery_ttl_seconds: int = 600

    @model_validator(mode="after")
    def _validate(self) -> NotificationsConfig:
        if self.presence_ttl_seconds <= 0:
            raise ValueError("notifications.presence_ttl_seconds must be > 0")
        if self.subscription_ttl_days <= 0:
            raise ValueError("notifications.subscription_ttl_days must be > 0")
        if self.vapid_private_key is not None:
            self.vapid_private_key = self.vapid_private_key.strip() or None
        if self.vapid_subject is not None:
            self.vapid_subject = self.vapid_subject.strip() or None
        if self.send_timeout_seconds <= 0:
            raise ValueError("notifications.send_timeout_seconds must be > 0")
        if self.retry_attempts < 0:
            raise ValueError("notifications.retry_attempts must be >= 0")
        if self.retry_backoff_seconds < 0:
            raise ValueError("notifications.retry_backoff_seconds must be >= 0")
        if self.max_payload_bytes <= 0:
            raise ValueError("notifications.max_payload_bytes must be > 0")
        if self.delivery_ttl_seconds < 0:
            raise ValueError("notifications.delivery_ttl_seconds must be >= 0")
        return self

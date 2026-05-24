from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

from ..auth import UserIdentity
from ..notifications.models import (
    NotificationClientType,
    NotificationFocusState,
    NotificationPreferences,
    NotificationSubscription,
)
from .auth import verify_token
from .state import server_module

server = server_module()

router = APIRouter()


class NotificationPreferencesPatch(BaseModel):
    escalation_pending: bool | None = None
    attended_turn_completed: bool | None = None
    unattended_turn_completed: bool | None = None
    unattended_turn_failed: bool | None = None

    def apply(self, prefs: NotificationPreferences) -> NotificationPreferences:
        return prefs.model_copy(update=self.model_dump(exclude_none=True))


class NotificationSubscriptionCreateRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    device_name: str = ""
    preferences: NotificationPreferencesPatch | None = None

    @field_validator("endpoint", "p256dh", "auth", "device_name", mode="before")
    @classmethod
    def _normalize_string_field(cls, value: str) -> str:
        return value.strip()


class NotificationSubscriptionResponse(BaseModel):
    subscription_id: str
    device_name: str
    endpoint: str
    subscribed_at: str
    expires_at: str
    last_heartbeat: str | None = None
    preferences: NotificationPreferences


class NotificationTestResponse(BaseModel):
    delivered: bool


class NotificationPresenceRequest(BaseModel):
    session_id: str
    client_type: NotificationClientType
    focus_state: NotificationFocusState

    @field_validator("session_id", mode="before")
    @classmethod
    def _normalize_session_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        return normalized


class InteractivePresenceRequest(NotificationPresenceRequest):
    source_id: str

    @field_validator("source_id", mode="before")
    @classmethod
    def _normalize_source_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source_id must not be empty")
        return normalized


def _notification_ttl() -> timedelta:
    return timedelta(days=server._config.notifications.subscription_ttl_days)


def _default_notification_preferences() -> NotificationPreferences:
    return server._config.notifications.default_preferences.model_copy(deep=True)


def _notification_response(subscription: NotificationSubscription) -> NotificationSubscriptionResponse:
    return NotificationSubscriptionResponse(
        subscription_id=subscription.id,
        device_name=subscription.device_name,
        endpoint=subscription.endpoint,
        subscribed_at=subscription.subscribed_at.isoformat(),
        expires_at=subscription.expires_at.isoformat(),
        last_heartbeat=subscription.last_heartbeat.isoformat() if subscription.last_heartbeat is not None else None,
        preferences=subscription.notification_prefs.model_copy(deep=True),
    )


def _owned_notification_subscription(subscription_id: str, user: UserIdentity) -> NotificationSubscription:
    subscription = server._notification_store.get_subscription(subscription_id)
    if subscription is None or subscription.user != user.username:
        raise HTTPException(status_code=404, detail="Notification subscription not found")
    return subscription


async def _set_notification_presence(
    *,
    session_id: str,
    source_id: str,
    client_type: NotificationClientType,
    focus_state: NotificationFocusState,
    now: datetime | None = None,
) -> None:
    if focus_state == "inactive":
        server._notification_presence.remove_presence(session_id=session_id, source_id=source_id)
        return
    server._notification_presence.update_presence(
        session_id=session_id,
        source_id=source_id,
        client_type=client_type,
        focus_state=focus_state,
        now=now,
    )
    if server._notification_presence.is_session_actively_handled(session_id, now=now):
        await server._engine.clear_pending_notifications(session_id)


@router.get("/notifications/subscriptions", response_model=list[NotificationSubscriptionResponse])
async def list_notification_subscriptions(
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> list[NotificationSubscriptionResponse]:
    server._notification_store.cleanup_expired()
    subscriptions = server._notification_store.list_subscriptions(user=user.username)
    return [_notification_response(subscription) for subscription in subscriptions]


@router.post("/notifications/subscriptions", response_model=NotificationSubscriptionResponse)
async def upsert_notification_subscription(
    request: NotificationSubscriptionCreateRequest,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> NotificationSubscriptionResponse:
    server._notification_store.cleanup_expired()
    prefs = _default_notification_preferences()
    if request.preferences is not None:
        prefs = request.preferences.apply(prefs)
    subscription = server._notification_store.upsert_subscription(
        user=user.username,
        endpoint=request.endpoint,
        p256dh=request.p256dh,
        auth=request.auth,
        device_name=request.device_name,
        notification_prefs=prefs,
        ttl=_notification_ttl(),
    )
    return _notification_response(subscription)


@router.delete("/notifications/subscriptions/{subscription_id}", status_code=204)
async def delete_notification_subscription(
    subscription_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> Response:
    subscription = _owned_notification_subscription(subscription_id, user)
    server._notification_store.delete_subscription(subscription.id)
    return Response(status_code=204)


@router.patch(
    "/notifications/subscriptions/{subscription_id}/preferences",
    response_model=NotificationSubscriptionResponse,
)
async def patch_notification_subscription_preferences(
    subscription_id: str,
    request: NotificationPreferencesPatch,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> NotificationSubscriptionResponse:
    subscription = _owned_notification_subscription(subscription_id, user)
    updated = subscription.model_copy(update={"notification_prefs": request.apply(subscription.notification_prefs)})
    server._notification_store.save_subscription(updated)
    return _notification_response(updated)


@router.post(
    "/notifications/subscriptions/{subscription_id}/test",
    response_model=NotificationTestResponse,
)
async def test_notification_subscription(
    subscription_id: str,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> NotificationTestResponse:
    server._notification_store.cleanup_expired()
    subscription = _owned_notification_subscription(subscription_id, user)
    delivered = await server._notification_router.dispatch_test(subscription=subscription)
    if not delivered:
        raise HTTPException(status_code=502, detail="Failed to deliver test notification")
    return NotificationTestResponse(delivered=True)


@router.post("/notifications/subscriptions/{subscription_id}/presence")
async def update_notification_presence(
    subscription_id: str,
    request: NotificationPresenceRequest,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> dict[str, bool]:
    subscription = _owned_notification_subscription(subscription_id, user)
    if not server._engine.session_mgr.is_owned_by(request.session_id, user.username):
        raise HTTPException(status_code=404, detail="Session not found")
    now = datetime.now(tz=UTC)
    updated = subscription.model_copy(update={"last_heartbeat": now, "expires_at": now + _notification_ttl()})
    server._notification_store.save_subscription(updated)
    await _set_notification_presence(
        session_id=request.session_id,
        source_id=subscription_id,
        client_type=request.client_type,
        focus_state=request.focus_state,
        now=now,
    )
    return {"heartbeat_received": True}


@router.post("/notifications/presence")
async def update_interactive_presence(
    request: InteractivePresenceRequest,
    user: Annotated[UserIdentity, Depends(verify_token)],
) -> dict[str, bool]:
    if not server._engine.session_mgr.is_owned_by(request.session_id, user.username):
        raise HTTPException(status_code=404, detail="Session not found")
    await _set_notification_presence(
        session_id=request.session_id,
        source_id=request.source_id,
        client_type=request.client_type,
        focus_state=request.focus_state,
    )
    return {"heartbeat_received": True}

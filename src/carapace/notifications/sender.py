from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from loguru import logger
from pywebpush import WebPushException, webpush
from requests import RequestException

from carapace.models import NotificationSubscription
from carapace.notifications.router import NotificationPayload
from carapace.notifications.store import NotificationStore


class WebPushSender:
    def __init__(
        self,
        *,
        store: NotificationStore,
        vapid_private_key: str | None,
        vapid_subject: str | None,
        timeout_seconds: int,
        retry_attempts: int,
        retry_backoff_seconds: float,
        max_payload_bytes: int,
        delivery_ttl_seconds: int,
        push_func: Callable[..., object] = webpush,
    ) -> None:
        self._store = store
        self._vapid_private_key = vapid_private_key
        self._vapid_subject = vapid_subject
        self._timeout_seconds = timeout_seconds
        self._retry_attempts = retry_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_payload_bytes = max_payload_bytes
        self._delivery_ttl_seconds = delivery_ttl_seconds
        self._push_func = push_func

    async def send(self, subscription: NotificationSubscription, payload: NotificationPayload) -> bool:
        encoded_payload = self._encode_payload(payload)
        if encoded_payload is None:
            return False
        if not self._vapid_private_key or not self._vapid_subject:
            logger.debug(
                f"Web push skipped subscription={subscription.id} "
                + f"reason=missing_vapid_configuration kind={payload.kind}"
            )
            return False

        attempts = self._retry_attempts + 1
        for attempt in range(attempts):
            try:
                await asyncio.to_thread(
                    self._push_func,
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=encoded_payload,
                    vapid_private_key=self._vapid_private_key,
                    vapid_claims={"sub": self._vapid_subject},
                    ttl=self._delivery_ttl_seconds,
                    timeout=self._timeout_seconds,
                )
                return True
            except WebPushException as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code in {404, 410}:
                    self._store.delete_subscription(subscription.id)
                    logger.info(
                        f"Web push removed expired subscription={subscription.id} "
                        + f"status={status_code} endpoint={subscription.endpoint}"
                    )
                    return False
                if status_code == 429 and attempt + 1 < attempts:
                    await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                    continue
                logger.warning(
                    f"Web push failed subscription={subscription.id} status={status_code} kind={payload.kind}: {exc}"
                )
                return False
            except RequestException as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                    continue
                logger.warning(f"Web push request failed subscription={subscription.id} kind={payload.kind}: {exc}")
                return False
            except OSError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                    continue
                logger.warning(f"Web push transport failed subscription={subscription.id} kind={payload.kind}: {exc}")
                return False
        return False

    async def send_batch(
        self,
        subscriptions: list[NotificationSubscription],
        payload: NotificationPayload,
    ) -> dict[str, bool]:
        results = await asyncio.gather(
            *(self.send(subscription, payload) for subscription in subscriptions),
            return_exceptions=False,
        )
        return {subscription.id: result for subscription, result in zip(subscriptions, results, strict=False)}

    def _encode_payload(self, payload: NotificationPayload) -> str | None:
        encoded = json.dumps(payload.as_dict(), separators=(",", ":"))
        encoded_bytes = encoded.encode("utf-8")
        if len(encoded_bytes) > self._max_payload_bytes:
            logger.warning(
                f"Web push skipped notif_id={payload.notif_id} kind={payload.kind} "
                + f"reason=payload_too_large bytes={len(encoded_bytes)}"
            )
            return None
        return encoded

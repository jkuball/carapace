from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01

from carapace.models import NotificationsConfig

_DEFAULT_VAPID_SUBJECT = "mailto:carapace@localhost"


def ensure_vapid_config(config: NotificationsConfig, data_dir: Path) -> NotificationsConfig:
    notifications_dir = data_dir / "notifications"
    notifications_dir.mkdir(parents=True, exist_ok=True)

    vapid_subject = config.vapid_subject or _DEFAULT_VAPID_SUBJECT
    vapid_private_key = config.vapid_private_key
    vapid_public_key = config.vapid_public_key

    if vapid_private_key and vapid_public_key:
        return config.model_copy(
            update={
                "vapid_private_key": vapid_private_key,
                "vapid_public_key": vapid_public_key,
                "vapid_subject": vapid_subject,
            }
        )

    if vapid_private_key or vapid_public_key:
        raise ValueError("notifications.vapid_public_key and notifications.vapid_private_key must be set together")

    private_key_path = notifications_dir / "vapid_private_key.pem"
    if private_key_path.exists():
        vapid = Vapid01.from_file(str(private_key_path))
    else:
        vapid = Vapid01()
        vapid.generate_keys()
        private_key_path.write_bytes(vapid.private_pem())

    generated_public_key = _encode_public_key(vapid)
    return config.model_copy(
        update={
            "vapid_private_key": private_key_path.read_text(encoding="utf-8"),
            "vapid_public_key": generated_public_key,
            "vapid_subject": vapid_subject,
        }
    )


def _encode_public_key(vapid: Vapid01) -> str:
    assert vapid.public_key is not None
    public_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")

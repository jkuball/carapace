from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01

from carapace.notifications.models import NotificationsConfig

_DEFAULT_VAPID_SUBJECT = "mailto:carapace@localhost"


def ensure_vapid_config(config: NotificationsConfig, data_dir: Path) -> NotificationsConfig:
    notifications_dir = data_dir / "notifications"
    notifications_dir.mkdir(parents=True, exist_ok=True)

    vapid_subject = config.vapid_subject or _DEFAULT_VAPID_SUBJECT
    vapid_private_key = config.vapid_private_key

    if vapid_private_key:
        vapid = load_vapid_private_key(vapid_private_key)
        return config.model_copy(
            update={
                "vapid_private_key": _private_key_pem(vapid),
                "vapid_subject": vapid_subject,
            }
        )

    private_key_path = notifications_dir / "vapid_private_key.pem"
    if private_key_path.exists():
        vapid = Vapid01.from_file(str(private_key_path))
    else:
        vapid = Vapid01()
        vapid.generate_keys()
        private_key_path.write_bytes(vapid.private_pem())

    return config.model_copy(
        update={
            "vapid_private_key": _private_key_pem(vapid),
            "vapid_subject": vapid_subject,
        }
    )


def derive_vapid_public_key(vapid_private_key: str) -> str:
    vapid = load_vapid_private_key(vapid_private_key)
    return _encode_public_key(vapid)


def load_vapid_private_key(vapid_private_key: str) -> Vapid01:
    normalized = vapid_private_key.strip()
    private_key_path = Path(normalized).expanduser()
    if private_key_path.is_file():
        return Vapid01.from_file(str(private_key_path))
    if "BEGIN PRIVATE KEY" in normalized:
        return Vapid01.from_pem(normalized.encode("utf-8"))
    return Vapid01.from_string(normalized)


def _private_key_pem(vapid: Vapid01) -> str:
    return vapid.private_pem().decode("utf-8").strip()


def _encode_public_key(vapid: Vapid01) -> str:
    assert vapid.public_key is not None
    public_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")

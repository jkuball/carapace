from __future__ import annotations

from .bitwarden import BitwardenBackend
from .file import FileVaultBackend
from .protocol import VaultBackend, is_exposed
from .registry import (
    CredentialRegistry,
    SessionCredentialRegistry,
    build_credential_registry,
)

__all__ = [
    "BitwardenBackend",
    "CredentialRegistry",
    "FileVaultBackend",
    "SessionCredentialRegistry",
    "VaultBackend",
    "build_credential_registry",
    "is_exposed",
]

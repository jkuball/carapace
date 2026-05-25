from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CredentialMetadata(BaseModel):
    """Vault credential metadata returned by backends and stored in session state."""

    vault_path: str
    name: str
    description: str = ""


@runtime_checkable
class CredentialRegistryProtocol(Protocol):
    """Structural type for credential registries — avoids importing the concrete class."""

    async def fetch(self, vault_path: str) -> str: ...
    async def fetch_metadata(self, vault_path: str) -> CredentialMetadata: ...
    async def list(self, query: str = "") -> list[CredentialMetadata]: ...


class FileCredentialBackendConfig(ConfigModel):
    """Configuration for the file-based credential backend."""

    type: Literal["file"] = "file"
    path: str = ""
    expose: list[str] = []
    hide: list[str] = []


class BitwardenCredentialBackendConfig(ConfigModel):
    """Configuration for a Bitwarden/Vaultwarden credential backend."""

    type: Literal["bitwarden"] = "bitwarden"
    url: str = "http://127.0.0.1:8087"
    expose: list[str] = []
    hide: list[str] = []


CredentialBackendConfig = Annotated[
    FileCredentialBackendConfig | BitwardenCredentialBackendConfig,
    Field(discriminator="type"),
]


class CredentialsConfig(ConfigModel):
    """Top-level credential configuration with named backends."""

    backends: dict[str, CredentialBackendConfig] = {}

    @model_validator(mode="after")
    def _validate_backend_names(self) -> CredentialsConfig:
        for name in self.backends:
            if "/" in name:
                raise ValueError(f"Backend name {name!r} must not contain '/' (used as vault_path separator)")
        return self

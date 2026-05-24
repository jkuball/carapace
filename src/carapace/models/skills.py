from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator

from ..sandbox.runtime import NetworkTunnel


class SkillCredentialDecl(BaseModel):
    """A credential requirement declared in a skill's carapace metadata."""

    vault_path: str
    description: str = ""
    env_var: str | None = None
    file: str | None = None
    base64: Annotated[
        bool, Field(description="If true, the stored value is base64-encoded and will be decoded before injection.")
    ] = False


class SkillNetworkConfig(BaseModel):
    domains: list[str] = []
    tunnels: list[NetworkTunnel] = []

    @model_validator(mode="after")
    def _validate_tunnels(self) -> SkillNetworkConfig:
        seen_local_ports: set[int] = set()
        seen_endpoints: set[tuple[str, int]] = set()
        for tunnel in self.tunnels:
            if tunnel.local_port in seen_local_ports:
                raise ValueError(f"network.tunnels local_port {tunnel.local_port} must be unique within a skill")
            endpoint = (tunnel.host, tunnel.remote_port)
            if endpoint in seen_endpoints:
                raise ValueError(
                    f"network.tunnels duplicate endpoint {tunnel.host}:{tunnel.remote_port} is not allowed"
                )
            seen_local_ports.add(tunnel.local_port)
            seen_endpoints.add(endpoint)
        return self


_SKILL_COMMAND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SkillCommandDecl(BaseModel):
    """A command alias declared in a skill's carapace metadata."""

    name: str
    command: str

    @model_validator(mode="after")
    def _validate(self) -> SkillCommandDecl:
        if not _SKILL_COMMAND_NAME_RE.match(self.name):
            raise ValueError(
                "skill command name must start with an alphanumeric character and contain only letters, "
                "numbers, dots, underscores, or hyphens"
            )

        command = self.command.strip()
        if not command:
            raise ValueError("skill command must not be empty")
        if "\n" in command or "\r" in command:
            raise ValueError("skill command must be a single line")

        self.command = command
        return self


class SkillCarapaceConfig(BaseModel):
    """Parsed carapace config declared inline in SKILL.md frontmatter."""

    network: SkillNetworkConfig = SkillNetworkConfig()
    credentials: list[SkillCredentialDecl] = []
    commands: list[SkillCommandDecl] = []
    hints: dict[str, str] = {}

    @model_validator(mode="after")
    def _validate_commands(self) -> SkillCarapaceConfig:
        seen_names: set[str] = set()
        for command in self.commands:
            if command.name in seen_names:
                raise ValueError(f"duplicate skill command name {command.name!r} is not allowed")
            seen_names.add(command.name)
        return self


class ContextGrant(BaseModel):
    """Context-scoped grant for a skill's declared domains, tunnels, and credentials.

    Registered at ``use_skill`` time, keyed by skill name.  The agent must pass
    matching ``contexts`` on ``exec`` for these grants to take effect.
    """

    skill_name: str
    domains: set[str] = set()
    tunnels: list[NetworkTunnel] = []
    credential_decls: list[SkillCredentialDecl] = []
    credential_names: dict[str, str] = {}  # vault_path → human-readable name

    @property
    def vault_paths(self) -> set[str]:
        return {c.vault_path for c in self.credential_decls}


def context_grants_session_summary(
    session_id: str,
    context_grants: Mapping[str, ContextGrant],
    get_cached_credential: Callable[[str, str], str | None],
) -> dict[str, dict[str, Any]]:
    """Build per-skill ``context_grants`` payload for ``/session`` (all channels)."""
    summary: dict[str, dict[str, Any]] = {}
    for skill, grant in context_grants.items():
        cached = sum(1 for vp in grant.vault_paths if get_cached_credential(session_id, vp) is not None)
        summary[skill] = {
            "domains": sorted(grant.domains),
            "tunnels": [tunnel.display for tunnel in grant.tunnels],
            "vault_paths": sorted(grant.vault_paths),
            "cached_credentials": cached,
        }
    return summary


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    path: Path

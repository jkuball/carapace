from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from .matrix import MatrixChannelConfig


class UserConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserChannelsConfig(UserConfigModel):
    matrix: MatrixChannelConfig = MatrixChannelConfig()


class UserGitConfig(UserConfigModel):
    remote: str = ""
    branch: str = "main"
    author: str = "carapace <carapace@%h>"
    token: str | None = None


class UserConfig(UserConfigModel):
    credentials: dict[str, Any] = {}
    channels: UserChannelsConfig = UserChannelsConfig()
    git: UserGitConfig = UserGitConfig()
    default_models: dict[str, str] = {}
    budgets: dict[str, Any] = {}

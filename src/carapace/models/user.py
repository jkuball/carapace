from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from .credentials import CredentialsConfig
from .matrix import MatrixChannelConfig

DEFAULT_GIT_BRANCH = "main"
DEFAULT_GIT_AUTHOR = "carapace <carapace@%h>"


class UserConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserChannelsConfig(UserConfigModel):
    matrix: MatrixChannelConfig = MatrixChannelConfig()


class UserGitConfig(UserConfigModel):
    remote: str = ""
    branch: str = DEFAULT_GIT_BRANCH
    author: str = DEFAULT_GIT_AUTHOR
    token: str | None = None

    @model_validator(mode="after")
    def _normalize(self) -> UserGitConfig:
        self.remote = self.remote.strip()
        self.branch = self.branch.strip() or DEFAULT_GIT_BRANCH
        self.author = self.author.strip() or DEFAULT_GIT_AUTHOR
        if self.token is not None:
            self.token = self.token.strip() or None
        return self


class UserConfig(UserConfigModel):
    credentials: CredentialsConfig = CredentialsConfig()
    channels: UserChannelsConfig = UserChannelsConfig()
    git: UserGitConfig = UserGitConfig()
    default_models: dict[str, str] = {}
    budgets: dict[str, object] = {}

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MatrixConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatrixTokenFile(MatrixConfigModel):
    """Schema for one persisted Matrix access token."""

    access_token: str
    device_id: str | None = None
    user_id: str | None = None
    user: str


class MatrixTokensFile(MatrixConfigModel):
    """Schema for the persisted ``matrix_token.yaml`` file."""

    version: int = 1
    tokens: list[MatrixTokenFile] = []


class MatrixChannelConfig(MatrixConfigModel):
    enabled: bool = False
    homeserver: str = ""
    user_id: str = ""
    device_name: str = "carapace"
    password: str | None = None
    token: str | None = None
    allowed_rooms: list[str] = []
    allowed_users: list[str] = []

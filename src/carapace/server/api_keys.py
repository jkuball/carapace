from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..api_keys import ApiKeyGrant, ApiKeyInfo
from ..auth import UserIdentity
from .auth import _api_key_store, current_user

router = APIRouter()

MAX_EXPIRY_DAYS = 3650


class ApiKeyCreateRequest(BaseModel):
    name: str = ""
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = Field(default=None, ge=1, le=MAX_EXPIRY_DAYS)


class ApiKeyCreateResponse(BaseModel):
    key: ApiKeyInfo
    # Plaintext token — returned only here, never again.
    secret: str


def _parse_grants(scopes: list[str]) -> list[ApiKeyGrant]:
    try:
        return [ApiKeyGrant.parse(scope) for scope in scopes]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid scope: {exc}") from exc


@router.post("/keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreateRequest,
    user: Annotated[UserIdentity, Depends(current_user)],
) -> ApiKeyCreateResponse:
    grants = _parse_grants(body.scopes)
    expires_at = (
        datetime.now(tz=UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days is not None else None
    )
    try:
        info, secret = _api_key_store().create_key(
            user=user.username,
            name=body.name,
            grants=grants,
            expires_at=expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiKeyCreateResponse(key=info, secret=secret)


@router.get("/keys", response_model=list[ApiKeyInfo])
async def list_api_keys(user: Annotated[UserIdentity, Depends(current_user)]) -> list[ApiKeyInfo]:
    return _api_key_store().list_keys(user.username)


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    user: Annotated[UserIdentity, Depends(current_user)],
) -> None:
    if not _api_key_store().revoke_key(user=user.username, key_id=key_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

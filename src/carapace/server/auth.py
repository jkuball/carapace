from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..auth import get_token

_bearer_scheme = HTTPBearer()


async def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> str:
    expected = get_token()
    if credentials.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return credentials.credentials


async def verify_ws_token(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
) -> str:
    expected = get_token()
    if token and token == expected:
        return token
    auth = websocket.headers.get("authorization", "")
    if auth.startswith("Bearer ") and auth.removeprefix("Bearer ") == expected:
        return expected
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

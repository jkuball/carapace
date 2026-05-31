from __future__ import annotations

import re

_USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]+$")


def normalize_username(username: str) -> str:
    candidate = username.strip()
    if not candidate:
        raise ValueError("username must not be empty")
    if candidate != username:
        raise ValueError("username must not contain leading or trailing whitespace")
    if candidate.lower() != candidate:
        raise ValueError("username must be lowercase")
    if _USERNAME_PATTERN.fullmatch(candidate) is None:
        raise ValueError("username may only contain lowercase letters, digits, '_', '-', or '.'")
    return candidate

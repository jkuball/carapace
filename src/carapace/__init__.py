from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    try:
        return version("carapace")
    except PackageNotFoundError:
        return os.environ.get("CARAPACE_VERSION", "dev")


__all__ = ["get_version"]

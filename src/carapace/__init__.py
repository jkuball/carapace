from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    try:
        return version("carapace")
    except PackageNotFoundError:
        return "dev"


__all__ = ["get_version"]

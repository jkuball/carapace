from __future__ import annotations

import sys
from types import ModuleType


def server_module() -> ModuleType:
    return sys.modules[__name__.rsplit(".", 1)[0]]

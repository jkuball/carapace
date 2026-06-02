from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import NotFound

from carapace.sandbox.docker import DockerRuntime


def _make_runtime(data_dir: Path | None) -> DockerRuntime:
    with patch.object(DockerRuntime, "__init__", lambda self, **_kw: None):
        runtime = DockerRuntime.__new__(DockerRuntime)
    runtime._client = MagicMock()
    runtime._data_dir = data_dir
    runtime._host_data_dir = None
    runtime._network_name = "carapace-sandbox"
    runtime._network_name_cache = {}
    return runtime


@pytest.mark.asyncio
async def test_inspect_sandbox_missing_without_workspace_returns_missing(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime._client.containers.get.side_effect = NotFound("missing")

    inspection = await runtime.inspect_sandbox("sess-1", "carapace-sandbox-sess-1")

    assert inspection.exists is False
    assert inspection.status == "missing"
    assert inspection.storage_present is False


@pytest.mark.asyncio
async def test_inspect_sandbox_missing_with_workspace_returns_scaled_down(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime._client.containers.get.side_effect = NotFound("missing")
    (tmp_path / "sessions" / "sess-1" / "workspace").mkdir(parents=True)

    inspection = await runtime.inspect_sandbox("sess-1", "carapace-sandbox-sess-1")

    assert inspection.exists is False
    assert inspection.status == "scaled_down"
    assert inspection.storage_present is True


@pytest.mark.asyncio
async def test_list_sandboxes_skips_pool_containers(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    session_container = MagicMock()
    session_container.id = "container-1"
    session_container.labels = {"carapace.session": "sess-1", "carapace.managed": "true"}
    pool_container = MagicMock()
    pool_container.id = "container-2"
    pool_container.labels = {
        "carapace.session": "warm-1",
        "carapace.managed": "true",
        "carapace.pool": "true",
    }
    runtime._client.containers.list.return_value = [session_container, pool_container]

    sandboxes = await runtime.list_sandboxes()

    assert sandboxes == {"sess-1": "container-1"}


@pytest.mark.asyncio
async def test_list_pool_sandboxes_returns_pool_containers(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    session_container = MagicMock()
    session_container.id = "container-1"
    session_container.labels = {"carapace.session": "sess-1", "carapace.managed": "true"}
    pool_container = MagicMock()
    pool_container.id = "container-2"
    pool_container.labels = {
        "carapace.session": "warm-1",
        "carapace.sandbox": "warm-1",
        "carapace.managed": "true",
        "carapace.pool": "true",
    }
    runtime._client.containers.list.return_value = [session_container, pool_container]

    sandboxes = await runtime.list_pool_sandboxes()

    assert sandboxes == {"warm-1": "container-2"}

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from carapace.git.store import GitStore
from carapace.models.user import UserConfig
from carapace.sandbox.manager import SandboxManager
from carapace.server.runtime import KnowledgeGitConfig, KnowledgeGitRuntime, MatrixChannelManager


class _FakeMatrixChannel:
    def __init__(self, *, start_error: Exception | None = None) -> None:
        self.start_error = start_error
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.anyio
async def test_matrix_channel_manager_replaces_running_channel() -> None:
    created: list[_FakeMatrixChannel] = []

    def channel_factory(_username: str, _config: UserConfig) -> _FakeMatrixChannel:
        channel = _FakeMatrixChannel()
        created.append(channel)
        return channel

    manager = MatrixChannelManager(channel_factory)
    config = UserConfig.model_validate({"channels": {"matrix": {"enabled": True}}})

    await manager.reload_user("Thies", config)
    await manager.reload_user("Thies", config)

    assert manager.channel_count == 1
    assert created[0].started is True
    assert created[0].stopped is True
    assert created[1].started is True


@pytest.mark.anyio
async def test_matrix_channel_manager_keeps_old_channel_when_replacement_fails() -> None:
    created = [_FakeMatrixChannel(), _FakeMatrixChannel(start_error=RuntimeError("login failed"))]

    def channel_factory(_username: str, _config: UserConfig) -> _FakeMatrixChannel:
        return created.pop(0)

    manager = MatrixChannelManager(channel_factory)
    config = UserConfig.model_validate({"channels": {"matrix": {"enabled": True}}})

    await manager.reload_user("thies", config)
    with pytest.raises(RuntimeError, match="login failed"):
        await manager.reload_user("thies", config)

    assert manager.channel_count == 1
    assert created == []


@pytest.mark.anyio
async def test_knowledge_git_runtime_applies_remote_and_updates_sandbox_identity() -> None:
    git_store = MagicMock(spec=GitStore)
    git_store.remote_branch = "main"
    git_store.author_template = "carapace <carapace@%h>"
    git_store.remote_configured = False
    git_store.add_remote = AsyncMock()
    git_store.remove_remote = AsyncMock()
    git_store.pull_from_remote = AsyncMock(return_value="Already up to date.")
    git_store.push_to_remote = AsyncMock()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.set_git_author = MagicMock()
    sandbox_mgr.refresh_git_identities = AsyncMock()
    runtime = KnowledgeGitRuntime(git_store=git_store, sandbox_mgr=sandbox_mgr)

    await runtime.apply_config(
        KnowledgeGitConfig(
            owner="thies",
            remote="https://git.example.test/knowledge.git",
            branch="prod",
            author="Thies <thies@example.test>",
            token="secret-token",
        )
    )

    assert git_store.remote_branch == "prod"
    assert git_store.author_template == "Thies <thies@example.test>"
    git_store.add_remote.assert_awaited_once_with("https://git.example.test/knowledge.git", "secret-token")
    git_store.pull_from_remote.assert_awaited_once()
    sandbox_mgr.set_git_author.assert_called_once_with("Thies <thies@example.test>")
    sandbox_mgr.refresh_git_identities.assert_awaited_once()


@pytest.mark.anyio
async def test_knowledge_git_runtime_rolls_back_when_remote_pull_fails() -> None:
    previous = KnowledgeGitConfig(
        owner="ada",
        remote="https://git.example.test/old.git",
        branch="main",
        author="Ada <ada@example.test>",
        token="old-token",
    )
    git_store = MagicMock(spec=GitStore)
    git_store.remote_branch = previous.branch
    git_store.author_template = previous.author
    git_store.add_remote = AsyncMock()
    git_store.remove_remote = AsyncMock()
    git_store.pull_from_remote = AsyncMock(side_effect=RuntimeError("pull failed"))
    sandbox_mgr = MagicMock(spec=SandboxManager)
    sandbox_mgr.set_git_author = MagicMock()
    sandbox_mgr.refresh_git_identities = AsyncMock()
    runtime = KnowledgeGitRuntime(git_store=git_store, sandbox_mgr=sandbox_mgr, current_config=previous)

    with pytest.raises(RuntimeError, match="pull failed"):
        await runtime.apply_config(
            KnowledgeGitConfig(
                owner="thies",
                remote="https://git.example.test/new.git",
                branch="prod",
                author="Thies <thies@example.test>",
                token="new-token",
            )
        )

    assert runtime.config == previous
    assert git_store.remote_branch == previous.branch
    assert git_store.author_template == previous.author
    assert git_store.add_remote.await_args_list == [
        call("https://git.example.test/new.git", "new-token"),
        call(previous.remote, previous.token),
    ]
    sandbox_mgr.set_git_author.assert_called_once_with(previous.author)
    sandbox_mgr.refresh_git_identities.assert_awaited_once()


@pytest.mark.anyio
async def test_knowledge_git_runtime_push_callback_checks_current_remote_state() -> None:
    git_store = MagicMock(spec=GitStore)
    git_store.remote_configured = False
    git_store.push_to_remote = AsyncMock()
    sandbox_mgr = MagicMock(spec=SandboxManager)
    runtime = KnowledgeGitRuntime(git_store=git_store, sandbox_mgr=sandbox_mgr)

    await runtime.push_if_configured()
    git_store.push_to_remote.assert_not_awaited()

    git_store.remote_configured = True
    await runtime.push_if_configured()

    git_store.push_to_remote.assert_awaited_once()

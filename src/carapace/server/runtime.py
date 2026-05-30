from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from ..auth import normalize_username
from ..git.store import GitStore
from ..models.user import DEFAULT_GIT_AUTHOR, DEFAULT_GIT_BRANCH, UserConfig
from ..sandbox.manager import SandboxManager


@dataclass(frozen=True)
class KnowledgeGitConfig:
    owner: str | None = None
    remote: str = ""
    branch: str = DEFAULT_GIT_BRANCH
    author: str = DEFAULT_GIT_AUTHOR
    token: str | None = None


class MatrixChannelHandle(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


type MatrixChannelFactory = Callable[[str, UserConfig], MatrixChannelHandle]


class MatrixChannelManager:
    def __init__(self, channel_factory: MatrixChannelFactory) -> None:
        self._channel_factory = channel_factory
        self._channels: dict[str, MatrixChannelHandle] = {}
        self._configs: dict[str, UserConfig] = {}
        self._lock = asyncio.Lock()

    @property
    def channel_count(self) -> int:
        return len(self._channels)

    async def reload_user(self, username: str, user_config: UserConfig) -> None:
        normalized_username = normalize_username(username)
        if not normalized_username:
            raise ValueError("Matrix channel owner user must not be empty")

        async with self._lock:
            current = self._channels.get(normalized_username)
            if not user_config.channels.matrix.enabled:
                if current is not None:
                    await current.stop()
                    del self._channels[normalized_username]
                    self._configs.pop(normalized_username, None)
                return

            previous_config = self._configs.get(normalized_username)
            if current is not None:
                await current.stop()
                del self._channels[normalized_username]

            replacement = self._channel_factory(normalized_username, user_config)
            try:
                await replacement.start()
            except Exception:
                if previous_config is not None and previous_config.channels.matrix.enabled:
                    rollback = self._channel_factory(normalized_username, previous_config)
                    try:
                        await rollback.start()
                        self._channels[normalized_username] = rollback
                    except Exception as rollback_exc:
                        logger.warning(f"Matrix channel rollback for {normalized_username!r} failed: {rollback_exc}")
                raise
            self._channels[normalized_username] = replacement
            self._configs[normalized_username] = user_config.model_copy(deep=True)

    async def stop_all(self) -> None:
        async with self._lock:
            channels = list(self._channels.items())
            self._channels.clear()
            self._configs.clear()
        for username, channel in channels:
            try:
                await channel.stop()
            except Exception as exc:
                logger.warning(f"Matrix channel stop for {username!r} failed: {exc}")


class KnowledgeGitRuntime:
    def __init__(
        self,
        *,
        git_store: GitStore,
        sandbox_mgr: SandboxManager,
        current_config: KnowledgeGitConfig | None = None,
    ) -> None:
        self._git_store = git_store
        self._sandbox_mgr = sandbox_mgr
        self._config = current_config or KnowledgeGitConfig()
        self._lock = asyncio.Lock()

    @property
    def config(self) -> KnowledgeGitConfig:
        return self._config

    async def apply_config(self, config: KnowledgeGitConfig) -> None:
        async with self._lock:
            previous_config = self._config
            previous_branch = self._git_store.remote_branch
            previous_author = self._git_store.author_template
            try:
                self._git_store.remote_branch = config.branch
                self._git_store.author_template = config.author

                if config.remote:
                    logger.info(f"Using knowledge Git remote from user {config.owner}")
                    await self._git_store.add_remote(config.remote, config.token)
                    summary = await self._git_store.pull_from_remote()
                    logger.info(f"Pulled from remote: {summary}")
                else:
                    await self._git_store.remove_remote()

                self._sandbox_mgr.set_git_author(config.author)
                await self._sandbox_mgr.refresh_git_identities()
            except Exception:
                self._config = previous_config
                self._git_store.remote_branch = previous_branch
                self._git_store.author_template = previous_author
                self._sandbox_mgr.set_git_author(previous_author)
                try:
                    if previous_config.remote:
                        await self._git_store.add_remote(previous_config.remote, previous_config.token)
                    else:
                        await self._git_store.remove_remote()
                    await self._sandbox_mgr.refresh_git_identities()
                except Exception as rollback_exc:
                    logger.warning(f"Knowledge Git runtime rollback failed: {rollback_exc}")
                raise

            self._config = config

    async def push_if_configured(self) -> None:
        async with self._lock:
            if self._git_store.remote_configured:
                await self._git_store.push_to_remote()

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from ..auth import normalize_username
from ..knowledge import KnowledgeRepoRegistry
from ..models.user import DEFAULT_GIT_AUTHOR, DEFAULT_GIT_BRANCH, UserConfig, UserGitConfig
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
        repo_registry: KnowledgeRepoRegistry,
        sandbox_mgr: SandboxManager,
        current_configs: Mapping[str, KnowledgeGitConfig] | None = None,
    ) -> None:
        self._repo_registry = repo_registry
        self._sandbox_mgr = sandbox_mgr
        self._configs = {
            normalize_username(username): self._normalize_config(username, config)
            for username, config in (current_configs or {}).items()
        }
        self._lock = asyncio.Lock()

    def _normalize_config(self, username: str, config: KnowledgeGitConfig | UserGitConfig) -> KnowledgeGitConfig:
        owner = normalize_username(username)
        if isinstance(config, UserGitConfig):
            return KnowledgeGitConfig(
                owner=owner,
                remote=config.remote,
                branch=config.branch,
                author=config.author,
                token=config.token,
            )

        config_owner = normalize_username(config.owner) if config.owner is not None else owner
        if config_owner != owner:
            raise ValueError(f"knowledge Git config owner mismatch: expected {owner!r}, got {config_owner!r}")
        return KnowledgeGitConfig(
            owner=owner,
            remote=config.remote,
            branch=config.branch,
            author=config.author,
            token=config.token,
        )

    def config_for_user(self, username: str) -> KnowledgeGitConfig:
        owner = normalize_username(username)
        return self._configs.get(owner, KnowledgeGitConfig(owner=owner))

    async def apply_user_config(self, username: str, config: KnowledgeGitConfig | UserGitConfig) -> None:
        owner = normalize_username(username)
        next_config = self._normalize_config(owner, config)
        async with self._lock:
            handle = self._repo_registry.ensure_user_repo(owner)
            git_store = handle.git_store
            previous_config = self.config_for_user(owner)
            previous_branch = git_store.remote_branch
            previous_author = git_store.author_template
            try:
                git_store.remote_branch = next_config.branch
                git_store.author_template = next_config.author
                await git_store.ensure_repo()

                if next_config.remote:
                    logger.info(f"Using knowledge Git remote from user {owner}")
                    await git_store.add_remote(next_config.remote, next_config.token)
                    summary = await git_store.pull_from_remote()
                    logger.info(f"Pulled from remote for user {owner}: {summary}")
                else:
                    await git_store.remove_remote()

                await self._sandbox_mgr.refresh_git_identities()
            except Exception:
                git_store.remote_branch = previous_branch
                git_store.author_template = previous_author
                try:
                    if previous_config.remote:
                        await git_store.add_remote(previous_config.remote, previous_config.token)
                    else:
                        await git_store.remove_remote()
                    await self._sandbox_mgr.refresh_git_identities()
                except Exception as rollback_exc:
                    logger.warning(f"Knowledge Git runtime rollback failed for user {owner}: {rollback_exc}")
                raise

            self._configs[owner] = next_config

    async def push_if_configured(self, owner: str) -> None:
        normalized_owner = normalize_username(owner)
        async with self._lock:
            handle = self._repo_registry.ensure_user_repo(normalized_owner)
            config = self._configs.get(normalized_owner)
            if config is not None:
                handle.git_store.remote_branch = config.branch
                handle.git_store.author_template = config.author
            if handle.git_store.remote_configured:
                await handle.git_store.push_to_remote()

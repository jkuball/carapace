from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from ..auth import normalize_username
from ..knowledge import KnowledgeRepoHandle, KnowledgeRepoRegistry
from ..models.git import GlobalGitStatus
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
            previous_config = self._configs.get(owner)
            previous_branch = git_store.remote_branch
            previous_author = git_store.author_template
            previous_remote_url = await git_store.get_remote_url()
            previous_remote_configured = git_store.remote_configured
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
                    if previous_config is not None and previous_config.remote:
                        await git_store.add_remote(previous_config.remote, previous_config.token)
                    elif previous_remote_url is not None:
                        await git_store.restore_remote(previous_remote_url)
                    elif not previous_remote_configured:
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

    def _apply_config_to_store(self, owner: str, handle: KnowledgeRepoHandle) -> None:
        config = self._configs.get(owner)
        if config is not None:
            handle.git_store.remote_branch = config.branch
            handle.git_store.author_template = config.author

    async def status_for_user(self, owner: str) -> GlobalGitStatus:
        """Return the backend ↔ remote status; ``head`` is filled even without a remote."""
        normalized_owner = normalize_username(owner)
        async with self._lock:
            handle = self._repo_registry.ensure_user_repo(normalized_owner)
            self._apply_config_to_store(normalized_owner, handle)
            revision = await handle.git_store.head_revision()
            head, head_subject = revision if revision is not None else (None, None)
            if not handle.git_store.remote_configured:
                return GlobalGitStatus(head=head, head_subject=head_subject)
            ahead, behind = await handle.git_store.remote_status()
            return GlobalGitStatus(
                remote_configured=True,
                ahead=ahead,
                behind=behind,
                head=head,
                head_subject=head_subject,
            )

    async def pull_for_user(self, owner: str) -> tuple[bool, str]:
        """Pull the backend repo from the external remote and invalidate skills.

        Returns ``(ok, message)``; ``ok`` is False when no remote is configured.
        """
        normalized_owner = normalize_username(owner)
        async with self._lock:
            handle = self._repo_registry.ensure_user_repo(normalized_owner)
            self._apply_config_to_store(normalized_owner, handle)
            if not handle.git_store.remote_configured:
                return False, "No external remote configured."
            summary = await handle.git_store.pull_from_remote()
            handle.skill_registry.invalidate()
            return True, summary

    async def push_for_user(self, owner: str) -> tuple[bool, str]:
        """Push the backend repo to the external remote.

        Returns ``(ok, message)``; ``ok`` is False when no remote is configured.
        """
        normalized_owner = normalize_username(owner)
        async with self._lock:
            handle = self._repo_registry.ensure_user_repo(normalized_owner)
            self._apply_config_to_store(normalized_owner, handle)
            if not handle.git_store.remote_configured:
                return False, "No external remote configured."
            if await handle.git_store.push_to_remote():
                return True, "Pushed to external remote."
            return False, "Push to the external remote failed."

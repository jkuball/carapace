from __future__ import annotations

import pytest
from pydantic import ValidationError

from carapace.models.config import (
    AgentConfig,
    AvailableModelEntry,
    Config,
    Secret,
    SessionCommitConfig,
    SessionsConfig,
)
from carapace.platform_store import PlatformSettingsStore


def _agent(**overrides) -> AgentConfig:
    base = dict(
        model="anthropic:claude-sonnet-4-6",
        sentinel_model="anthropic:claude-haiku-4-5",
        title_model="anthropic:claude-haiku-4-5",
        available_models=[
            AvailableModelEntry.model_validate("anthropic:claude-sonnet-4-6"),
            AvailableModelEntry.model_validate("anthropic:claude-haiku-4-5"),
        ],
    )
    base.update(overrides)
    return AgentConfig(**base)


def test_seed_is_idempotent(db_factory):
    store = PlatformSettingsStore(db_factory)
    config = Config(agent=_agent())

    assert store.seed_from_config(config) is True
    assert store.seed_from_config(config) is False  # second run is a no-op

    models = store.load_models()
    assert {m.model_id for m in models} == {"anthropic:claude-sonnet-4-6", "anthropic:claude-haiku-4-5"}
    assert store.load_section("agent") is not None
    assert store.load_section("sessions") is not None


def test_replace_models_round_trips_api_key_sources(db_factory):
    store = PlatformSettingsStore(db_factory)
    entries = [
        AvailableModelEntry(provider="openai", name="gpt-x", api_key=Secret(raw="sk-raw")),
        AvailableModelEntry(
            provider="openai-chat", name="local", base_url="http://x", api_key=Secret(env="OPENAI_KEY")
        ),
        AvailableModelEntry(provider="openrouter", name="r1", api_key=Secret(file="/run/secrets/key")),
    ]
    store.replace_models(entries)

    loaded = {m.model_id: m for m in store.load_models()}
    assert loaded["openai:gpt-x"].api_key == Secret(raw="sk-raw")
    assert loaded["openai-chat:local"].api_key == Secret(env="OPENAI_KEY")
    assert loaded["openrouter:r1"].api_key == Secret(file="/run/secrets/key")


def test_replace_models_is_wholesale(db_factory):
    store = PlatformSettingsStore(db_factory)
    store.replace_models([AvailableModelEntry.model_validate("anthropic:a")])
    store.replace_models([AvailableModelEntry.model_validate("anthropic:b")])
    assert {m.model_id for m in store.load_models()} == {"anthropic:b"}


def test_duplicate_model_ids_are_deduplicated(db_factory):
    # Same id listed twice was valid before (last wins); must not PK-conflict on seed/save.
    store = PlatformSettingsStore(db_factory)
    agent = _agent(
        model="dup",
        sentinel_model="dup",
        title_model="dup",
        available_models=[
            AvailableModelEntry(provider="x", name="y", id="dup", max_input_tokens=1),
            AvailableModelEntry(provider="x", name="y", id="dup", max_input_tokens=2),
        ],
    )

    assert store.seed_from_config(Config(agent=agent)) is True
    loaded = store.load_models()
    assert len(loaded) == 1
    assert loaded[0].max_input_tokens == 2  # last entry wins

    store.save_agent_config(agent)  # must also not conflict
    assert len(store.load_models()) == 1


def test_assemble_agent_config_validates_defaults_in_catalog(db_factory):
    store = PlatformSettingsStore(db_factory)
    # Catalog lacks the configured default model -> AgentConfig validation must reject.
    store.replace_models([AvailableModelEntry.model_validate("anthropic:claude-haiku-4-5")])
    store.save_section("agent", {"model": "anthropic:missing"})

    with pytest.raises(ValidationError):
        store.assemble_agent_config(_agent())


def test_save_agent_config_persists_models_and_scalars(db_factory):
    store = PlatformSettingsStore(db_factory)
    agent = _agent(max_parallel_llm=7, model="anthropic:claude-haiku-4-5")
    store.save_agent_config(agent)

    assembled = store.assemble_agent_config(_agent())
    assert assembled.max_parallel_llm == 7
    assert assembled.model == "anthropic:claude-haiku-4-5"
    assert {m.model_id for m in assembled.available_models} == {
        "anthropic:claude-sonnet-4-6",
        "anthropic:claude-haiku-4-5",
    }


def test_overlay_config_replaces_agent_and_sessions_only(db_factory):
    store = PlatformSettingsStore(db_factory)
    config = Config(
        agent=_agent(),
        sessions=SessionsConfig(commit=SessionCommitConfig(path_prefix="sessions")),
    )
    store.seed_from_config(config)
    # Mutate the DB sources after seeding.
    store.save_agent_config(_agent(max_parallel_llm=9))
    store.save_section("sessions", {"commit": {"path_prefix": "archived"}})

    overlaid = store.overlay_config(config)
    assert overlaid.agent.max_parallel_llm == 9
    assert overlaid.sessions.commit.path_prefix == "archived"
    # Operator sections untouched.
    assert overlaid.database == config.database
    assert overlaid.server == config.server


def test_assemble_sessions_falls_back_to_file_when_unset(db_factory):
    store = PlatformSettingsStore(db_factory)
    file_sessions = SessionsConfig(commit=SessionCommitConfig(path_prefix="custom"))
    assert store.assemble_sessions_config(file_sessions) == file_sessions

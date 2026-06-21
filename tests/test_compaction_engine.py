"""Integration tests for /compact orchestration (engine + summarizer with TestModel)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from carapace.session.compaction import is_fold_message, split_lead_folds, tool_return_is_compacted
from carapace.session.transcript import completed_model_turn_end_indexes
from tests.session_helpers import _make_engine, _patch_sentinel


def _turn(i: int, *, tool_output: str | None = None) -> list:
    msgs: list = [ModelRequest(parts=[UserPromptPart(content=f"question {i}")])]
    if tool_output is not None:
        cid = f"call-{i}"
        msgs.append(ModelResponse(parts=[ToolCallPart(tool_name="exec", args={"cmd": "ls"}, tool_call_id=cid)]))
        msgs.append(ModelRequest(parts=[ToolReturnPart(tool_name="exec", content=tool_output, tool_call_id=cid)]))
    msgs.append(ModelResponse(parts=[TextPart(content=f"answer {i}")]))
    return msgs


def _seed(engine, sid: str, n: int, *, tool_output: str | None = None) -> None:
    history: list = []
    events: list = []
    for i in range(n):
        history += _turn(i, tool_output=tool_output)
        events.append({"role": "user", "content": f"question {i}"})
        if tool_output is not None:
            events.append({"role": "tool_call", "tool": "exec", "tool_id": f"call-{i}"})
            events.append({"role": "tool_result", "tool": "exec", "tool_id": f"call-{i}", "result": tool_output})
        events.append({"role": "assistant", "content": f"answer {i}"})
    engine.session_mgr.save_history(sid, history)
    engine.session_mgr.save_events(sid, events)


def test_reset_warns_when_history_desynced_from_events(tmp_path: Path, db_factory) -> None:
    """A source whose model history lags its events must log a loud truncation warning, not silently cut."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        # 6 full event turns, but a model history with only the first turn (desynced source).
        _seed(engine, sid, 6)
        full = engine.session_mgr.load_history(sid)
        engine.session_mgr.save_history(sid, full[:2])  # turn 0 only (user-prompt + response)

        logs: list[str] = []
        sink_id = logger.add(lambda m: logs.append(m.record["message"]), level="WARNING")
        try:
            assert await engine.reset_to_turn(sid, 11) is True  # reset to turn 5
        finally:
            logger.remove(sink_id)

        assert any("out of sync with the event transcript" in m for m in logs)

    asyncio.run(_run())


def test_compaction_model_precedence(tmp_path: Path, db_factory) -> None:
    """Resolution order: per-session override → platform compaction_model → title model."""
    with _patch_sentinel():
        engine = _make_engine(tmp_path, session_factory=db_factory)
    sid = engine.session_mgr.create_session(user="thies").session_id
    active = engine.get_or_activate(sid)

    agent_cfg = engine.config.agent
    # No override, no platform compaction model → fall back to the title model.
    agent_cfg.compaction_model = None
    active.compaction_model_name = None
    assert engine._compaction_model(active) == agent_cfg.title_model

    # Platform compaction model wins over the title model.
    agent_cfg.compaction_model = "openai:gpt-4o-mini"
    assert engine._compaction_model(active) == "openai:gpt-4o-mini"

    # A per-session override wins over everything.
    active.compaction_model_name = "anthropic:claude-haiku-4-5"
    assert engine._compaction_model(active) == "anthropic:claude-haiku-4-5"


def test_reset_into_folded_region_collapses_to_lead_fold(tmp_path: Path, db_factory) -> None:
    """Rewinding to a turn the fold swallowed keeps only the fold summary, consistent with events."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        await engine.run_compaction(active, mode="fold", keep_turns=3)  # folds turns 0-6

        # Reset to turn 2 (assistant event index 5) — inside the folded region.
        assert await engine.reset_to_turn(sid, 5) is True

        history = engine.session_mgr.load_history(sid)
        lead, rest = split_lead_folds(history)
        # Tail turns = 0: only the fold summary survives, no dangling verbatim turns.
        assert len(lead) == 1 and is_fold_message(lead[0])
        assert completed_model_turn_end_indexes(rest) == []
        # The fold still has turns in the (truncated) events, so its tree node is retained.
        assert len(engine.session_mgr.load_compaction(sid).nodes) == 1

    asyncio.run(_run())


def test_compact_fold_collapses_old_turns(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)

        report = await engine.run_compaction(active, mode="fold", keep_turns=3)

        assert report.turns_folded == 7
        assert report.after_tokens < report.before_tokens
        history = engine.session_mgr.load_history(sid)
        lead, rest = split_lead_folds(history)
        assert len(lead) == 1 and is_fold_message(lead[0])
        assert len(completed_model_turn_end_indexes(rest)) == 3
        # tree persisted
        tree = engine.session_mgr.load_compaction(sid)
        assert len(tree.nodes) == 1 and tree.nodes[0].kind == "fold"
        # oldest events annotated with the fold node id
        events = list(engine.session_mgr.load_events(sid))
        assert any(e.get("compaction", {}).get("folded_into") == tree.nodes[0].id for e in events)

    asyncio.run(_run())


def test_reset_after_fold_keeps_history_in_sync(tmp_path: Path, db_factory) -> None:
    """Reset past the verbatim tail must slice folded history by events, not raw model-turn count."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        await engine.run_compaction(active, mode="fold", keep_turns=3)

        # Reset to turn 8 (assistant event index 17): drops turn 9, keeps the fold + turns 7,8.
        assert await engine.reset_to_turn(sid, 17) is True

        history = engine.session_mgr.load_history(sid)
        lead, rest = split_lead_folds(history)
        assert len(lead) == 1 and is_fold_message(lead[0])
        # Only the two surviving verbatim turns remain — not the stale turn 9.
        assert len(completed_model_turn_end_indexes(rest)) == 2
        # Tree still references the surviving fold; no dangling nodes.
        tree = engine.session_mgr.load_compaction(sid)
        assert len(tree.nodes) == 1

    asyncio.run(_run())


def test_fork_after_fold_carries_trimmed_tree(tmp_path: Path, db_factory) -> None:
    """A fork of a folded session inherits matching folds + a compaction tree (not a dangling one)."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10)
        await engine.run_compaction(active, mode="fold", keep_turns=3)

        forked = engine.fork_session(sid, event_index=17, channel_type="cli")
        history = engine.session_mgr.load_history(forked.session_id)
        lead, rest = split_lead_folds(history)
        assert len(lead) == 1 and is_fold_message(lead[0])
        assert len(completed_model_turn_end_indexes(rest)) == 2
        # The fork carries the fold's tree node so fold UI / agent-view render.
        assert len(engine.session_mgr.load_compaction(forked.session_id).nodes) == 1

    asyncio.run(_run())


def test_compact_tools_summarizes_large_returns(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 3, tool_output="line\n" * 3000)

        report = await engine.run_compaction(active, mode="tools")

        assert report.tool_returns_compacted >= 1
        history = engine.session_mgr.load_history(sid)
        compacted = [
            p
            for m in history
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, ToolReturnPart) and tool_return_is_compacted(p)
        ]
        assert compacted
        # tool_result events annotated with method
        events = list(engine.session_mgr.load_events(sid))
        assert any(e.get("compaction", {}).get("method") == "summarize" for e in events)
        # idempotent: a second run compacts nothing new
        report2 = await engine.run_compaction(active, mode="tools")
        assert report2.tool_returns_compacted == 0

    asyncio.run(_run())


def test_compact_tools_keeps_verbatim_hot_zone(tmp_path: Path, db_factory) -> None:
    """The newest verbatim_tool_turns turns keep tool outputs verbatim; older ones get summarized."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        engine._config.agent.compaction.verbatim_tool_turns = 2
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 5, tool_output="line\n" * 3000)

        await engine.run_compaction(active, mode="tools")

        history = engine.session_mgr.load_history(sid)
        compacted_ids = {
            p.tool_call_id
            for m in history
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, ToolReturnPart) and tool_return_is_compacted(p)
        }
        # 5 turns, hot zone of 2 → the newest two (call-3, call-4) stay verbatim.
        assert "call-4" not in compacted_ids
        assert "call-3" not in compacted_ids
        assert {"call-0", "call-1", "call-2"} <= compacted_ids

    asyncio.run(_run())


def test_compact_command_parsing(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        engine.get_or_activate(sid)
        _seed(engine, sid, 8)

        res = await engine.handle_slash_command(sid, "/compact fold 2")
        assert res is not None and res["command"] == "compact"
        assert res["data"]["mode"] == "fold"
        assert res["data"]["turns_folded"] == 6

        bad = await engine.handle_slash_command(sid, "/compact tools 5")
        assert "error" in bad["data"]

    asyncio.run(_run())


def test_compact_all_ladder_end_to_end(tmp_path: Path, db_factory) -> None:
    """`/compact` (all): thinking dropped + old turns folded + big tool outputs summarized."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)

        # 10 turns, each with a large tool output and a thinking part in the response.
        history: list = []
        events: list = []
        for i in range(10):
            cid = f"call-{i}"
            history.append(ModelRequest(parts=[UserPromptPart(content=f"q{i}")]))
            history.append(
                ModelResponse(
                    parts=[
                        ThinkingPart(content=f"reason {i}"),
                        ToolCallPart(tool_name="exec", args={}, tool_call_id=cid),
                    ]
                )
            )
            history.append(
                ModelRequest(parts=[ToolReturnPart(tool_name="exec", content="row\n" * 3000, tool_call_id=cid)])
            )
            history.append(ModelResponse(parts=[TextPart(content=f"a{i}")]))
            events.append({"role": "user", "content": f"q{i}"})
            events.append({"role": "tool_call", "tool": "exec", "tool_id": cid})
            events.append({"role": "tool_result", "tool": "exec", "tool_id": cid, "result": "row\n" * 3000})
            events.append({"role": "assistant", "content": f"a{i}"})
        engine.session_mgr.save_history(sid, history)
        engine.session_mgr.save_events(sid, events)

        report = await engine.run_compaction(active, mode="all", keep_turns=3)

        assert report.thinking_dropped > 0
        assert report.turns_folded == 7
        assert report.tool_returns_compacted >= 1  # only kept-region returns
        assert report.after_tokens < report.before_tokens
        # compaction LLM usage is attributed to its own category, not the agent
        assert "compaction" in active.usage_tracker.categories
        # idempotent second run
        report2 = await engine.run_compaction(active, mode="all", keep_turns=3)
        assert report2.turns_folded == 0
        assert report2.tool_returns_compacted == 0

    asyncio.run(_run())


def test_fold_after_tools_still_badges_turns(tmp_path: Path, db_factory) -> None:
    """`/compact tools` then `/compact fold`: folded turns must still get folded_into badges."""

    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 10, tool_output="line\n" * 3000)

        # Compact tools first — annotates tool_result events with a method.
        await engine.run_compaction(active, mode="tools")
        # Then fold the old turns.
        report = await engine.run_compaction(active, mode="fold", keep_turns=3)

        assert report.turns_folded == 7
        tree = engine.session_mgr.load_compaction(sid)
        node_id = tree.nodes[0].id
        events = list(engine.session_mgr.load_events(sid))
        folded = [e for e in events if e.get("compaction", {}).get("folded_into") == node_id]
        # 7 folded turns, each with user + tool_call + tool_result + assistant events, get the badge.
        assert len(folded) >= 7
        # tool method annotations survived the merge where both apply.
        assert any(e.get("compaction", {}).get("method") and e.get("compaction", {}).get("folded_into") for e in events)

    asyncio.run(_run())


def test_compact_noop_when_short(tmp_path: Path, db_factory) -> None:
    async def _run() -> None:
        with _patch_sentinel():
            engine = _make_engine(tmp_path, session_factory=db_factory)
        sid = engine.session_mgr.create_session(user="thies").session_id
        active = engine.get_or_activate(sid)
        _seed(engine, sid, 2)
        report = await engine.run_compaction(active, mode="all", keep_turns=6)
        assert report.turns_folded == 0
        assert report.message == "Nothing to compact."

    asyncio.run(_run())

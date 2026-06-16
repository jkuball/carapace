"""Integration tests for /compact orchestration (engine + summarizer with TestModel)."""

from __future__ import annotations

import asyncio
from pathlib import Path

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

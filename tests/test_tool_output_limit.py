"""Tests for configurable tool output truncation."""

from carapace.agent.tools import (
    truncate_exec_output_with_saved_path,
    truncate_tool_output,
)


def test_truncate_tool_output_unlimited_zero():
    text = "x" * 10
    assert truncate_tool_output(text, 0) == text


def test_truncate_tool_output_fits():
    text = "hello"
    assert truncate_tool_output(text, 100) == text


def test_truncate_tool_output_truncates():
    text = "abcdefghij"
    out = truncate_tool_output(text, 4)
    assert out.startswith("abcd")
    assert "10 characters total" in out
    assert "limit 4" in out


def test_truncate_exec_output_with_saved_path_includes_read_hint():
    text = "abcdefghij" * 80
    spill_path = "/tmp/out.txt"

    out = truncate_exec_output_with_saved_path(text, 320, spill_path)
    preview, _, suffix = out.partition("\n\n[Output truncated:")

    assert len(out) <= 320
    assert len(preview) == 160
    assert preview == text[:160]
    assert spill_path in out
    assert f'read(path="{spill_path}")' in out
    assert suffix.lstrip().startswith("800 characters total")
    assert "800 characters total" in out

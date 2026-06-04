"""Tests for chunked sandbox file writes (avoiding shell "Argument list too long")."""

from __future__ import annotations

import base64
import re

import pytest

from carapace.sandbox.file_ops import (
    _FILE_WRITE_CHUNK_BYTES,
    SandboxFileOps,
    _file_write_commands,
)
from carapace.sandbox.runtime import ExecResult

# Linux caps a single argv string at MAX_ARG_STRLEN (128 KiB).
MAX_ARG_STRLEN = 128 * 1024


def _reconstruct(commands: list[str]) -> bytes:
    """Decode the base64 payloads back into the bytes the commands would write."""
    out = bytearray()
    for cmd in commands:
        for b64 in re.findall(r"printf %s (\S+) \| base64 -d", cmd):
            out += base64.b64decode(b64)
    return bytes(out)


def test_small_write_is_single_command() -> None:
    commands = _file_write_commands("/tmp/x.txt", "hello", mode=None, quote=True)
    assert len(commands) == 1
    assert commands[0].startswith('mkdir -p "$(dirname')
    assert _reconstruct(commands) == b"hello"


def test_mode_folds_into_last_command() -> None:
    # Single chunk + mode stays one exec (preserves prior behaviour for credential writes).
    commands = _file_write_commands("/tmp/x", "v", mode=0o400, quote=True)
    assert len(commands) == 1
    assert commands[0].endswith("&& chmod 0400 /tmp/x")


def test_large_write_chunks_stay_within_arg_limit() -> None:
    content = "A" * (300 * 1024)
    commands = _file_write_commands("/tmp/big.bin", content, mode=0o644, quote=True)
    assert len(commands) > 1
    assert all(len(cmd) < MAX_ARG_STRLEN for cmd in commands)
    # First truncates, the rest append.
    assert " > /tmp/big.bin" in commands[0]
    assert all(" >> /tmp/big.bin" in cmd for cmd in commands[1:])
    # chmod folded into the final append, not a separate exec.
    assert commands[-1].endswith("&& chmod 0644 /tmp/big.bin")
    assert _reconstruct(commands).decode() == content


def test_empty_content_truncates_file() -> None:
    commands = _file_write_commands("/tmp/x", "", mode=None, quote=True)
    assert len(commands) == 1
    assert " > /tmp/x" in commands[0]
    assert _reconstruct(commands) == b""


def test_chunk_boundary_count() -> None:
    content = "B" * (_FILE_WRITE_CHUNK_BYTES * 2 + 1)
    commands = _file_write_commands("/tmp/x", content, mode=None, quote=True)
    assert len(commands) == 3
    assert _reconstruct(commands).decode() == content


@pytest.mark.asyncio
async def test_multichunk_failure_removes_partial_file() -> None:
    calls: list[str] = []

    async def exec_one(cmd: str) -> ExecResult:
        # Fail on the first append (file already truncated by the first command).
        fail = ">>" in cmd and not any(">>" in c for c in calls)
        calls.append(cmd)
        return ExecResult(exit_code=1, output="boom") if fail else ExecResult(exit_code=0, output="")

    result = await SandboxFileOps._run_file_write(
        exec_one, "/tmp/big", "C" * (_FILE_WRITE_CHUNK_BYTES * 2), mode=None, quote=True
    )
    assert result.exit_code == 1
    assert any(c.startswith("rm -f /tmp/big") for c in calls)


@pytest.mark.asyncio
async def test_single_chunk_failure_does_not_remove_file() -> None:
    calls: list[str] = []

    async def exec_one(cmd: str) -> ExecResult:
        calls.append(cmd)
        return ExecResult(exit_code=1, output="denied")

    result = await SandboxFileOps._run_file_write(exec_one, "/tmp/x", "small", mode=None, quote=True)
    assert result.exit_code == 1
    assert not any(c.startswith("rm -f") for c in calls)

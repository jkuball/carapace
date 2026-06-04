"""Tests for the sandbox inline ``SANDBOX_FILE_READ_BYTES_SCRIPT`` (host Python, same as container logic)."""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

from carapace.sandbox.container_scripts import SANDBOX_FILE_READ_BYTES_SCRIPT


def _run_script(path: Path, max_bytes: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", SANDBOX_FILE_READ_BYTES_SCRIPT, str(path), str(max_bytes)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_returns_base64_of_file_bytes(tmp_path: Path) -> None:
    data = bytes(range(256))
    p = tmp_path / "img.png"
    p.write_bytes(data)
    r = _run_script(p, 1024)
    assert r.returncode == 0
    assert r.stdout.startswith("::B64::")
    assert base64.b64decode(r.stdout[len("::B64::") :]) == data


def test_reports_too_big(tmp_path: Path) -> None:
    p = tmp_path / "big.png"
    p.write_bytes(b"x" * 100)
    r = _run_script(p, 10)
    assert r.returncode == 0
    assert r.stdout.strip() == "::TOOBIG::100"


def test_missing_file_errors(tmp_path: Path) -> None:
    r = _run_script(tmp_path / "nope.png", 1024)
    assert r.returncode == 1
    assert "path not found" in r.stdout


def test_directory_errors(tmp_path: Path) -> None:
    r = _run_script(tmp_path, 1024)
    assert r.returncode == 1
    assert "not a regular file" in r.stdout

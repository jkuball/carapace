"""Tests for the knowledge repo browse endpoint helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from carapace.server.knowledge import MAX_INLINE_TEXT_BYTES, list_dir, read_text_content, resolve_target


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("secret")
    (root / "skills" / "weather").mkdir(parents=True)
    (root / "skills" / "weather" / "SKILL.md").write_text("---\nname: weather\n---\n")
    (root / "SOUL.md").write_text("# soul")
    return root


def test_resolve_target_root(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert resolve_target(root, "") == root.resolve()
    assert resolve_target(root, "skills/weather") == (root / "skills" / "weather").resolve()


def test_resolve_target_rejects_traversal(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (tmp_path / "outside.txt").write_text("nope")
    for bad in ("../outside.txt", "..", "skills/../../outside.txt", "/etc/passwd"):
        with pytest.raises(HTTPException) as exc:
            resolve_target(root, bad)
        assert exc.value.status_code == 404


def test_resolve_target_rejects_git_dir(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    for bad in (".git", ".git/config"):
        with pytest.raises(HTTPException) as exc:
            resolve_target(root, bad)
        assert exc.value.status_code == 404


def test_resolve_target_rejects_symlink_escape(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (tmp_path / "outside.txt").write_text("nope")
    (root / "link.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(HTTPException):
        resolve_target(root, "link.txt")


def test_list_dir_hides_git_and_sorts_dirs_first(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    listing = list_dir(root, root.resolve())
    assert listing.path == ""
    assert [(e.name, e.type) for e in listing.entries] == [("skills", "dir"), ("SOUL.md", "file")]
    assert listing.entries[1].size == len("# soul")


def test_list_dir_subdir_path(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    listing = list_dir(root, (root / "skills" / "weather").resolve())
    assert listing.path == "skills/weather"
    assert [e.name for e in listing.entries] == ["SKILL.md"]


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    target = tmp_path / name
    target.write_bytes(data)
    return target


@pytest.mark.parametrize(
    "name,data",
    [
        (".gitignore", b"__pycache__/\n*.pyc\n"),  # no extension to guess from
        ("Dockerfile", b"FROM python:3.12\n"),
        ("notes.md", "# über\n".encode()),  # multi-byte UTF-8
        ("empty", b""),
    ],
)
def test_read_text_content_returns_text(tmp_path: Path, name: str, data: bytes) -> None:
    target = _write(tmp_path, name, data)
    assert read_text_content(target, len(data)) == data.decode("utf-8")


@pytest.mark.parametrize(
    "name,data",
    [
        ("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00binary"),  # NUL byte
        ("data.bin", b"\xff\xfe\xfd\xfc"),  # invalid UTF-8
    ],
)
def test_read_text_content_rejects_binary(tmp_path: Path, name: str, data: bytes) -> None:
    target = _write(tmp_path, name, data)
    assert read_text_content(target, len(data)) is None


def test_read_text_content_rejects_oversized(tmp_path: Path) -> None:
    target = _write(tmp_path, "big.txt", b"x")
    assert read_text_content(target, MAX_INLINE_TEXT_BYTES + 1) is None

"""Tests for vault write-back (token rotation support)."""

from __future__ import annotations

from pathlib import Path

import pytest

from carapace.credentials.file import FileVaultBackend
from carapace.credentials.registry import CredentialRegistry
from carapace.models.credentials import FileCredentialBackendConfig


def _backend(path: Path) -> FileVaultBackend:
    return FileVaultBackend(name="file", path=path, cfg=FileCredentialBackendConfig())


class TestFileBackendWrite:
    async def test_write_updates_value_and_persists(self, tmp_path: Path):
        p = tmp_path / "secrets.env"
        p.write_text("# comment\nother=keep\nblob=old\n")
        b = _backend(p)
        await b.write("blob", '{"access_token":"new"}')
        assert await b.fetch("blob") == '{"access_token":"new"}'
        # reload from disk: value persisted, other key + comment preserved
        b2 = _backend(p)
        assert await b2.fetch("blob") == '{"access_token":"new"}'
        assert await b2.fetch("other") == "keep"
        assert "# comment" in p.read_text()

    async def test_write_missing_key_raises(self, tmp_path: Path):
        p = tmp_path / "secrets.env"
        p.write_text("a=1\n")
        b = _backend(p)
        with pytest.raises(KeyError):
            await b.write("nope", "x")

    async def test_yaml_round_trip(self, tmp_path: Path):
        p = tmp_path / "secrets.yaml"
        p.write_text("- id: blob\n  name: OAuth\n  value: old\n")
        b = _backend(p)
        await b.write("blob", "new")
        b2 = _backend(p)
        assert await b2.fetch("blob") == "new"
        assert (await b2.fetch_metadata("blob")).name == "OAuth"


class TestRegistryWriteRouting:
    async def test_write_routes_to_backend(self, tmp_path: Path):
        p = tmp_path / "secrets.env"
        p.write_text("blob=old\n")
        reg = CredentialRegistry()
        reg.register("file", _backend(p))
        await reg.write("file/blob", "new")
        assert await reg.fetch("file/blob") == "new"

    async def test_write_unknown_backend_raises(self):
        reg = CredentialRegistry()
        with pytest.raises(KeyError):
            await reg.write("nope/x", "v")

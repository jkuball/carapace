from __future__ import annotations

from carapace.database.engine import resolve_database_url


def test_relative_sqlite_resolved_under_data_dir(tmp_path):
    url = resolve_database_url("sqlite+pysqlite:///carapace.db", tmp_path)
    assert url == f"sqlite+pysqlite:///{(tmp_path / 'carapace.db').resolve()}"


def test_absolute_sqlite_unchanged(tmp_path):
    assert resolve_database_url("sqlite+pysqlite:////abs/x.db", tmp_path) == "sqlite+pysqlite:////abs/x.db"


def test_memory_and_postgres_unchanged(tmp_path):
    assert resolve_database_url("sqlite+pysqlite:///:memory:", tmp_path) == "sqlite+pysqlite:///:memory:"
    pg = "postgresql+psycopg://u:p@h:5432/db"
    assert resolve_database_url(pg, tmp_path) == pg


def test_no_data_dir_unchanged():
    assert resolve_database_url("sqlite+pysqlite:///carapace.db", None) == "sqlite+pysqlite:///carapace.db"

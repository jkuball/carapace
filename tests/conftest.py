from __future__ import annotations

import os

import pytest

from carapace.database import models as _models  # noqa: F401  (register tables on Base.metadata)
from carapace.database.base import Base
from carapace.database.engine import create_engine_and_factory
from carapace.models.config import DatabaseConfig


def _make_factory(url: str):
    engine, factory = create_engine_and_factory(DatabaseConfig(url=url))
    Base.metadata.create_all(engine)
    return engine, factory


@pytest.fixture
def db_factory(tmp_path):
    """A fresh database (SQLite file, or Postgres via CARAPACE_TEST_DATABASE_URL) per test."""
    url = os.environ.get("CARAPACE_TEST_DATABASE_URL") or f"sqlite+pysqlite:///{tmp_path}/carapace-test.db"
    engine, factory = _make_factory(url)
    if url.startswith("postgresql"):
        # Start clean on a shared Postgres instance.
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    try:
        yield factory
    finally:
        if url.startswith("postgresql"):
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_factory_secondary(tmp_path):
    """A second independent SQLite database for tests that need an isolated store.

    Always a private SQLite file (never the shared Postgres URL) so it cannot collide
    with rows written through the primary ``db_factory``.
    """
    url = f"sqlite+pysqlite:///{tmp_path}/carapace-test-secondary.db"
    engine, factory = _make_factory(url)
    try:
        yield factory
    finally:
        engine.dispose()

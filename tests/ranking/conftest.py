"""Shared fixtures for ranking tests."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_ranking_data_dir(tmp_path, monkeypatch):
    """Point the default data directory at a per-test temp directory.

    Several tests construct ``EloSystem()`` without a path (for example via
    ``Tournament`` without an ``elo_system``), which opens the default
    ``analytics.db`` under the shared checkout data dir. Under pytest-xdist the
    workers run that database's first schema migration at the same time, and
    the loser fails with "duplicate column name" or "database is locked".
    """
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))

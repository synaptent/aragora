"""Guard for the per-test data directory set by tests/ranking/conftest.py.

Tests in this directory construct ``EloSystem()`` without a path (for example
through ``Tournament`` without an ``elo_system``). Without isolation every
pytest-xdist worker opens the same default ``analytics.db`` and runs its first
schema migration concurrently, which fails with "duplicate column name".
"""

from pathlib import Path

from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.ranking.elo import EloSystem


def test_default_elo_db_path_is_under_tmp_path(tmp_path: Path) -> None:
    assert get_db_path(DatabaseType.ELO).is_relative_to(tmp_path)


def test_default_elo_system_opens_isolated_db(tmp_path: Path) -> None:
    elo = EloSystem()
    assert elo.db_path.is_relative_to(tmp_path)
    assert elo.db_path.exists()

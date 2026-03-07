from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path


def _reload_for_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    import aragora.config.legacy as legacy

    legacy = importlib.reload(legacy)
    import aragora.storage.schema as schema

    schema = importlib.reload(schema)
    return legacy, schema


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(cwd, "git", *args)


def _make_git_repo_with_linked_worktree(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    linked = tmp_path / "linked-worktree"
    _git(repo, "worktree", "add", "-b", "feature/test", str(linked), "main")

    common_dir = _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    common_dir_path = Path(common_dir)
    if not common_dir_path.is_absolute():
        common_dir_path = (repo / common_dir_path).resolve()

    return repo, linked, common_dir_path


def test_resolve_db_path_uses_data_dir(tmp_path, monkeypatch):
    legacy, _schema = _reload_for_data_dir(tmp_path, monkeypatch)
    resolved = Path(legacy.resolve_db_path("example.db"))
    assert resolved.parent == tmp_path
    assert resolved.name == "example.db"


def test_database_manager_resolves_relative_paths(tmp_path, monkeypatch):
    _legacy, schema = _reload_for_data_dir(tmp_path, monkeypatch)
    schema.DatabaseManager._instances.clear()

    manager = schema.DatabaseManager.get_instance("manager_test.db")
    assert str(tmp_path) in manager.db_path


def test_get_nomic_dir_respects_aragora_data_dir(tmp_path, monkeypatch):
    """get_nomic_dir() should return ARAGORA_DATA_DIR when set."""
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    import aragora.persistence.db_config as db_config

    db_config = importlib.reload(db_config)
    assert db_config.get_nomic_dir() == tmp_path


def test_get_nomic_dir_falls_back_to_nomic_dir(tmp_path, monkeypatch):
    """get_nomic_dir() should fall back to ARAGORA_NOMIC_DIR."""
    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.setenv("ARAGORA_NOMIC_DIR", str(tmp_path))
    import aragora.persistence.db_config as db_config

    db_config = importlib.reload(db_config)
    assert db_config.get_nomic_dir() == tmp_path


def test_get_nomic_dir_default_is_nomic(tmp_path, monkeypatch):
    """get_nomic_dir() should default to .nomic when no env var is set."""
    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    import aragora.persistence.db_config as db_config

    db_config = importlib.reload(db_config)
    assert db_config.get_nomic_dir() == Path(".nomic")


def test_get_nomic_dir_prefers_data_when_present(tmp_path, monkeypatch):
    """get_nomic_dir() should fall back to data/ if .nomic is absent."""
    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    import aragora.persistence.db_config as db_config

    db_config = importlib.reload(db_config)
    assert db_config.get_nomic_dir() == Path("data")


def test_get_nomic_dir_prefers_nomic_over_data(tmp_path, monkeypatch):
    """get_nomic_dir() should prefer .nomic when both exist."""
    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / ".nomic").mkdir()
    import aragora.persistence.db_config as db_config

    db_config = importlib.reload(db_config)
    assert db_config.get_nomic_dir() == Path(".nomic")


def test_get_nomic_dir_uses_git_common_dir_for_linked_worktree(tmp_path, monkeypatch):
    _repo, linked, common_dir = _make_git_repo_with_linked_worktree(tmp_path)

    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    monkeypatch.chdir(linked)

    import aragora.persistence.db_config as db_config

    db_config = importlib.reload(db_config)
    assert db_config.get_nomic_dir() == common_dir / "aragora" / "data" / linked.name


def test_resolve_db_path_absolute_passthrough():
    """Absolute paths should be returned as-is."""
    import aragora.config.legacy as legacy

    result = legacy.resolve_db_path("/absolute/path/to/db.sqlite")
    assert result == "/absolute/path/to/db.sqlite"


def test_resolve_db_path_memory_passthrough():
    """SQLite :memory: should be preserved."""
    import aragora.config.legacy as legacy

    assert legacy.resolve_db_path(":memory:") == ":memory:"


def test_resolve_db_path_file_uri_passthrough():
    """SQLite file: URIs should be preserved."""
    import aragora.config.legacy as legacy

    assert legacy.resolve_db_path("file:test?mode=memory").startswith("file:")


def test_resolve_db_path_uses_git_common_dir_for_linked_worktree(tmp_path, monkeypatch):
    _repo, linked, common_dir = _make_git_repo_with_linked_worktree(tmp_path)

    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    monkeypatch.chdir(linked)

    import aragora.config.legacy as legacy

    legacy = importlib.reload(legacy)
    resolved = Path(legacy.resolve_db_path("example.db"))
    assert resolved == common_dir / "aragora" / "data" / linked.name / "example.db"


def test_guard_repo_clean_scan_paths():
    """guard_repo_clean.py --scan-paths should pass on the codebase."""
    result = subprocess.run(
        [sys.executable, "scripts/guard_repo_clean.py", "--scan-paths"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"guard_repo_clean.py --scan-paths failed:\n{result.stdout}\n{result.stderr}"
    )


def test_guard_repo_clean_no_tracked_artifacts():
    """guard_repo_clean.py should pass (no tracked .db files)."""
    result = subprocess.run(
        [sys.executable, "scripts/guard_repo_clean.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"guard_repo_clean.py failed:\n{result.stdout}\n{result.stderr}"

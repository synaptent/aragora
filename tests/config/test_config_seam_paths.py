"""Old and new import paths for the data-directory and tenant-context seams.

``aragora.persistence.db_config`` and ``aragora.tenancy.context`` re-export the
primitives that now live in ``aragora.config`` so that the config layer no
longer imports persistence or tenancy.
"""

from __future__ import annotations

import ast
import contextvars
import subprocess
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.config import data_dir as new_dd
from aragora.config import tenant_context as new_tc
from aragora.persistence import db_config as old_dd
from aragora.tenancy import context as old_tc

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_FROM_CONFIG = ("aragora.persistence", "aragora.tenancy")
DATA_DIR_NAMES = (
    "CONSOLIDATED_DB_MAPPING DatabaseMode DatabaseType LEGACY_DB_NAMES get_db_mode "
    "get_default_data_dir"
).split()
TENANT_NAMES = (
    "_current_tenant _current_tenant_id get_current_tenant get_current_tenant_id set_tenant "
    "set_tenant_id"
).split()
SHARED_NAMES = [(old_dd, new_dd, n) for n in DATA_DIR_NAMES] + [
    (old_tc, new_tc, n) for n in TENANT_NAMES
]


@pytest.fixture
def no_data_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)


@pytest.mark.parametrize(("old", "new", "name"), SHARED_NAMES)
def test_old_path_reexports_the_config_object(old, new, name: str) -> None:
    assert getattr(old, name) is getattr(new, name)


def test_env_override_wins_at_both_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path / "data"))
    assert old_dd.get_default_data_dir() == new_dd.get_default_data_dir() == tmp_path / "data"


@pytest.mark.parametrize(
    ("existing", "expected"),
    [((), ".nomic"), (("data",), "data"), ((".nomic", "data"), ".nomic"), ((".git",), ".nomic")],
)
def test_directory_precedence_at_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_data_env: None, existing, expected: str
) -> None:
    for name in existing:
        (tmp_path / name).mkdir()
    monkeypatch.chdir(tmp_path)
    assert old_dd.get_default_data_dir() == new_dd.get_default_data_dir() == Path(expected)


def test_linked_worktree_uses_worktree_local_nomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_data_env: None
) -> None:
    worktree = tmp_path / "wt"
    (worktree / "pkg").mkdir(parents=True)
    gitdir = tmp_path / "main" / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    monkeypatch.chdir(worktree / "pkg")
    expected = worktree.resolve() / ".nomic"
    assert old_dd.get_default_data_dir() == new_dd.get_default_data_dir() == expected


def test_config_callers_use_the_seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from aragora.config import legacy
    from aragora.config.settings import _default_nomic_dir

    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    assert _default_nomic_dir() == str(tmp_path)
    monkeypatch.setenv("ARAGORA_DB_MODE", "consolidated")
    assert legacy.get_db_path("agent_elo.db") == tmp_path.resolve() / "analytics.db"
    monkeypatch.setenv("ARAGORA_DB_MODE", "legacy")
    assert legacy.get_db_path("agent_elo.db") == tmp_path.resolve() / "agent_elo.db"


def test_tenant_state_is_shared_across_paths() -> None:
    def body() -> None:
        token = old_tc._current_tenant_id.set("t1")
        assert new_tc.get_current_tenant_id() == "t1"
        new_tc.set_tenant_id("t2")
        assert old_tc.get_current_tenant_id() == "t2"
        old_tc._current_tenant_id.reset(token)
        assert new_tc.get_current_tenant_id() is None

    contextvars.copy_context().run(body)
    assert new_tc.get_current_tenant_id() is None


def test_tenant_context_and_feature_flags_see_the_same_tenant() -> None:
    from aragora.config.feature_flags import FeatureFlagRegistry

    registry = FeatureFlagRegistry(warn_on_unknown=False)
    tenant = SimpleNamespace(id="acme", config=SimpleNamespace(enable_rlm=True))
    with old_tc.TenantContext(tenant=tenant):  # type: ignore[arg-type]
        assert new_tc.get_current_tenant() is tenant
        assert new_tc.get_current_tenant_id() == "acme"
        assert registry._get_tenant_value("enable_rlm") is True
    assert new_tc.get_current_tenant() is None
    assert registry._get_tenant_value("enable_rlm") is None


def test_config_has_no_runtime_import_of_persistence_or_tenancy() -> None:
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "aragora" / "config").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        type_checking = {
            id(inner)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and ast.unparse(node.test).endswith("TYPE_CHECKING")
            for stmt in node.body
            for inner in ast.walk(stmt)
        }
        for node in ast.walk(tree):
            if id(node) in type_checking:
                continue
            if isinstance(node, ast.ImportFrom):
                targets = [node.module or ""]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.Call) and node.args:
                targets = [ast.unparse(node.args[0])] if "import" in ast.unparse(node.func) else []
            else:
                targets = []
            if any(t in target for t in FORBIDDEN_FROM_CONFIG for target in targets):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == []


def test_seam_modules_load_without_persistence_or_tenancy() -> None:
    probe = (
        "import sys, aragora.config.data_dir, aragora.config.tenant_context\n"
        "print(sorted(m for m in sys.modules if m.startswith(('aragora.persistence', 'aragora.tenancy'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"

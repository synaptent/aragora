"""The Teams identity bridge lives in aragora.auth; the connectors path aliases it."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.auth.teams_identity as new_home
import aragora.connectors.chat.teams_identity as old_path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _aragora_imports(relative_path: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return {name for name in found if name == "aragora" or name.startswith("aragora.")}


def test_the_connectors_path_is_the_auth_module() -> None:
    assert old_path is new_home
    assert new_home.__name__ == "aragora.auth.teams_identity"


@pytest.mark.parametrize(
    "name",
    ["TEAMS_PROVIDER", "TeamsUserInfo", "TeamsUserIdentityBridge", "get_teams_identity_bridge"],
)
def test_each_public_name_is_the_same_object_at_both_paths(name: str) -> None:
    assert getattr(old_path, name) is getattr(new_home, name)


def test_user_info_built_at_either_path_is_identical() -> None:
    fields = {
        "aad_object_id": "aad-1",
        "tenant_id": "tenant-1",
        "display_name": "Ada Lovelace",
        "email": "ada@example.com",
    }
    from_old = old_path.TeamsUserInfo(**fields)
    from_new = new_home.TeamsUserInfo(**fields)
    assert from_old == from_new
    assert from_old.to_dict()["aad_object_id"] == "aad-1"
    assert new_home.TEAMS_PROVIDER == old_path.TEAMS_PROVIDER == "azure_ad"


def test_the_bridge_singleton_is_shared_between_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(old_path, "_bridge", None)
    bridge = old_path.get_teams_identity_bridge()
    assert new_home.get_teams_identity_bridge() is bridge
    assert new_home._bridge is bridge


@pytest.mark.parametrize(
    "first", ["aragora.connectors.chat.teams_identity", "aragora.auth.teams_identity"]
)
def test_either_import_order_yields_one_module(first: str) -> None:
    code = (
        f"import {first}\n"
        "import aragora.auth.teams_identity as new\n"
        "import aragora.connectors.chat.teams_identity as old\n"
        "from aragora.connectors.chat.teams_identity import TeamsUserInfo\n"
        "print(old is new, TeamsUserInfo is new.TeamsUserInfo)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "True True"


def test_teams_sso_imports_nothing_from_connectors() -> None:
    imported = _aragora_imports("aragora/auth/teams_sso.py")
    assert not {name for name in imported if name.startswith("aragora.connectors")}


def test_the_moved_bridge_stays_within_its_layer() -> None:
    imported = _aragora_imports("aragora/auth/teams_identity.py")
    allowed = ("aragora.auth.", "aragora.storage.", "aragora.billing.")
    assert imported
    assert all(name.startswith(allowed) for name in imported), sorted(imported)

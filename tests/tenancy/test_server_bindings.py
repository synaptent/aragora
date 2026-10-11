"""The registry through which record_scope reaches the server's auth and responses."""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.tenancy import record_scope, server_bindings
from aragora.tenancy.record_scope import OrgScope
from aragora.tenancy.server_bindings import (
    TENANCY_BINDINGS_ENTRY_POINT_GROUP as GROUP,
    ServerBindings,
    ServerBindingsNotRegisteredError,
    get_server_bindings,
    register_server_bindings,
)
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_REGISTRATION = "aragora.server.tenancy_bindings:register_tenancy_bindings"


@pytest.fixture
def no_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_bindings, "_bindings", None)
    declared = DeclaredRegistrations(GROUP)
    monkeypatch.setattr(declared, "load", lambda: None)
    monkeypatch.setattr(server_bindings, "_declared", declared)


async def _echo(request: Any) -> Any:
    return request


def _fake(config: Any = None) -> ServerBindings:
    return ServerBindings(
        lambda: config,
        _echo,
        lambda message, *, status_code, code: LookupError(message, status_code, code),
        lambda body, *, status: ("json", body, status),
    )


def test_helpers_raise_when_nothing_is_registered(no_bindings: None) -> None:
    with pytest.raises(ServerBindingsNotRegisteredError, match=GROUP):
        get_server_bindings()
    with pytest.raises(ServerBindingsNotRegisteredError):
        record_scope.record_not_found("Plan")
    with pytest.raises(ServerBindingsNotRegisteredError):
        record_scope.carries_static_api_token({"Authorization": "Bearer some-token"})


async def test_helpers_call_the_registered_bindings(no_bindings: None) -> None:
    register_server_bindings(_fake())
    config = SimpleNamespace(api_token="static", validate_token=lambda token: token == "signed")
    register_server_bindings(_fake(config))

    body = {"error": "Plan not found", "code": "not_found"}
    assert record_scope.record_not_found("Plan") == ("json", body, 404)
    assert record_scope.record_not_found_error("Plan").args == ("Plan not found", 404, "not_found")
    assert [
        record_scope.carries_static_api_token({"Authorization": f"Bearer {token}"})
        for token in ("static", "signed", "other")
    ] == [True, True, False]
    member = SimpleNamespace(user_id="u-1", org_id="org-1", roles=["admin"], headers={})
    assert await record_scope.require_org_scope_fastapi(member) == OrgScope("org-1", "u-1", "admin")
    anonymous = SimpleNamespace(user_id="anonymous", org_id=None, roles=[], headers={})
    with pytest.raises(LookupError) as denied:
        await record_scope.require_org_scope_fastapi(anonymous)
    assert denied.value.args == ("Authentication required", 401, "auth_required")


def test_first_lookup_runs_the_declared_server_registration(
    no_bindings: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aragora.server import auth as server_auth
    from aragora.server.tenancy_bindings import SERVER_BINDINGS

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert SERVER_REGISTRATION in project["entry-points"][GROUP].values()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[project]\nname = "aragora"\n[project.entry-points."{GROUP}"]\n'
        f'server = "{SERVER_REGISTRATION}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        server_bindings, "_declared", DeclaredRegistrations(GROUP, source_pyproject=pyproject)
    )
    assert get_server_bindings() is SERVER_BINDINGS

    patched = SimpleNamespace(api_token="patched")
    monkeypatch.setattr(server_auth, "auth_config", patched, raising=False)
    assert SERVER_BINDINGS.auth_config() is patched


def test_a_fresh_process_reaches_the_server_bindings() -> None:
    code = "from aragora.tenancy.record_scope import record_not_found as f; print(f().status_code)"
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "404"


def test_tenancy_has_no_runtime_import_of_the_server_package() -> None:
    """Function-scope imports count too; only ``if TYPE_CHECKING:`` blocks are exempt."""
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "aragora" / "tenancy").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        exempt = {
            id(child)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test)
            for child in ast.walk(node)
        }
        for node in ast.walk(tree):
            if id(node) in exempt:
                continue
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                names = []
            offenders += [
                f"{path.name}: {n}" for n in names if f"{n}.".startswith("aragora.server.")
            ]
    assert offenders == []

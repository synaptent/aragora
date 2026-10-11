"""Tests for the registry through which record_scope reaches the HTTP server.

aragora.tenancy sits below aragora.server in the import layers, so the org-scope
helpers call the server's auth config, FastAPI auth context and error type, and
legacy JSON response through aragora.tenancy.server_bindings, which the server fills.
"""

from __future__ import annotations

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
    TENANCY_BINDINGS_ENTRY_POINT_GROUP,
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
    """Nothing registered, and the declared registrations count as already run."""
    monkeypatch.setattr(server_bindings, "_bindings", None)
    declared = DeclaredRegistrations(TENANCY_BINDINGS_ENTRY_POINT_GROUP)
    monkeypatch.setattr(declared, "load", lambda: None)
    monkeypatch.setattr(server_bindings, "_declared", declared)


def _fake_bindings(config: Any = None) -> ServerBindings:
    async def get_auth_context(request: Any) -> Any:
        return request

    return ServerBindings(
        auth_config=lambda: config,
        get_auth_context=get_auth_context,
        api_error=lambda message, *, status_code, code: LookupError(message, status_code, code),
        json_response=lambda body, *, status: ("json", body, status),
    )


def test_unregistered_bindings_raise(no_bindings: None) -> None:
    with pytest.raises(ServerBindingsNotRegisteredError, match=TENANCY_BINDINGS_ENTRY_POINT_GROUP):
        get_server_bindings()


def test_helpers_raise_instead_of_answering_when_nothing_is_registered(no_bindings: None) -> None:
    with pytest.raises(ServerBindingsNotRegisteredError):
        record_scope.record_not_found("Plan")
    with pytest.raises(ServerBindingsNotRegisteredError):
        record_scope.record_not_found_error("Plan")
    with pytest.raises(ServerBindingsNotRegisteredError):
        record_scope.carries_static_api_token({"Authorization": "Bearer some-token"})


def test_registering_again_replaces_the_bindings(no_bindings: None) -> None:
    first, second = _fake_bindings(), _fake_bindings()
    register_server_bindings(first)
    register_server_bindings(second)
    assert get_server_bindings() is second


def test_legacy_helpers_call_the_registered_bindings(no_bindings: None) -> None:
    config = SimpleNamespace(api_token="static", validate_token=lambda token: token == "signed")
    register_server_bindings(_fake_bindings(config))

    not_found = {"error": "Plan not found", "code": "not_found"}
    assert record_scope.record_not_found("Plan") == ("json", not_found, 404)
    error = record_scope.record_not_found_error("Plan")
    assert isinstance(error, LookupError)
    assert error.args == ("Plan not found", 404, "not_found")
    tokens = ("static", "signed", "other")
    assert [
        record_scope.carries_static_api_token({"Authorization": f"Bearer {token}"})
        for token in tokens
    ] == [True, True, False]


async def test_fastapi_dependency_uses_the_registered_auth_context_and_error(
    no_bindings: None,
) -> None:
    register_server_bindings(_fake_bindings(SimpleNamespace(api_token="")))

    member = SimpleNamespace(user_id="u-1", org_id="org-1", roles=["admin"], headers={})
    assert await record_scope.require_org_scope_fastapi(member) == OrgScope("org-1", "u-1", "admin")
    anonymous = SimpleNamespace(user_id="anonymous", org_id=None, roles=[], headers={})
    with pytest.raises(LookupError) as denied:
        await record_scope.require_org_scope_fastapi(anonymous)
    assert denied.value.args == ("Authentication required", 401, "auth_required")


def test_aragora_declares_the_server_registration() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = project["entry-points"][TENANCY_BINDINGS_ENTRY_POINT_GROUP]
    assert SERVER_REGISTRATION in declared.values()


def test_first_lookup_runs_the_declared_server_registration(
    no_bindings: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aragora.server.tenancy_bindings import SERVER_BINDINGS

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "aragora"\n'
        f'[project.entry-points."{TENANCY_BINDINGS_ENTRY_POINT_GROUP}"]\n'
        f'server = "{SERVER_REGISTRATION}"\n',
        encoding="utf-8",
    )
    declared = DeclaredRegistrations(TENANCY_BINDINGS_ENTRY_POINT_GROUP, source_pyproject=pyproject)
    monkeypatch.setattr(server_bindings, "_declared", declared)

    assert get_server_bindings() is SERVER_BINDINGS
    assert declared.loaded


def test_server_bindings_read_the_auth_config_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.server import auth as server_auth
    from aragora.server.tenancy_bindings import SERVER_BINDINGS

    patched = SimpleNamespace(api_token="patched")
    monkeypatch.setattr(server_auth, "auth_config", patched, raising=False)
    assert SERVER_BINDINGS.auth_config() is patched


def test_a_fresh_process_reaches_the_server_through_the_declared_registration() -> None:
    code = (
        "from aragora.tenancy.record_scope import record_not_found\n"
        "print('STATUS', record_not_found('Plan').status_code)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT, timeout=300
    )
    assert proc.returncode == 0, proc.stderr
    assert "STATUS 404" in proc.stdout

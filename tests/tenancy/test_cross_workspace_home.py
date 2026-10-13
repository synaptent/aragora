"""The cross-workspace coordinator lives in ``aragora.tenancy.cross_workspace``.

``aragora.knowledge`` (domain layer) records federation and sharing consent with it.
The coordinator used to live in ``aragora.coordination`` (application layer) and
imports nothing from aragora, so it now sits in the tenancy package.
``aragora.coordination.cross_workspace`` and ``aragora.coordination`` re-export the
same objects; the shared coordinator lives only in the new module.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_HOME = "aragora.tenancy.cross_workspace"
OLD_HOME = "aragora.coordination.cross_workspace"
NAMES = tuple(
    "CrossWorkspaceCoordinator CrossWorkspaceOperation CrossWorkspaceRequest "
    "CrossWorkspaceResult DataSharingConsent FederatedWorkspace FederationMode "
    "FederationPolicy OperationType SharingScope get_coordinator".split()
)
PACKAGE_NAMES = tuple(
    "CrossWorkspaceCoordinator CrossWorkspaceRequest CrossWorkspaceResult "
    "DataSharingConsent FederatedWorkspace FederationPolicy SharingScope".split()
)


@pytest.fixture
def new():
    module = importlib.import_module(NEW_HOME)
    module._coordinator = None
    yield module
    module._coordinator = None


@pytest.mark.parametrize("name", NAMES)
def test_the_old_path_is_the_same_objects(new, name):
    assert getattr(importlib.import_module(OLD_HOME), name) is getattr(new, name)


@pytest.mark.parametrize("name", PACKAGE_NAMES)
def test_the_coordination_package_re_exports_the_same_objects(new, name):
    assert getattr(importlib.import_module("aragora.coordination"), name) is getattr(new, name)


def test_the_coordinator_is_defined_in_the_tenancy_package(new):
    assert new.CrossWorkspaceCoordinator.__module__ == NEW_HOME
    assert new.get_coordinator.__module__ == NEW_HOME
    assert sorted(new.__all__) == sorted(NAMES)
    assert sorted(importlib.import_module(OLD_HOME).__all__) == sorted(NAMES)


def test_the_shared_coordinator_is_shared_with_the_old_path(new):
    old = importlib.import_module(OLD_HOME)
    coordinator = old.get_coordinator()
    assert new.get_coordinator() is coordinator
    assert new._coordinator is coordinator


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
def test_consent_granted_through_either_path_allows_the_same_operations(new, module_name):
    module = importlib.import_module(module_name)
    coordinator = module.CrossWorkspaceCoordinator()
    for workspace_id in ("ws-a", "ws-b"):
        coordinator.register_workspace(
            module.FederatedWorkspace(id=workspace_id, name=workspace_id)
        )

    consent = coordinator.grant_consent(
        source_workspace_id="ws-a",
        target_workspace_id="ws-b",
        scope=module.SharingScope.METADATA,
        data_types={"knowledge"},
        operations={module.OperationType.READ_KNOWLEDGE},
        granted_by="admin",
    )

    assert isinstance(consent, new.DataSharingConsent)
    assert consent.is_valid()
    assert coordinator.get_consent("ws-a", "ws-b", new.OperationType.READ_KNOWLEDGE) is consent
    assert [ws.id for ws in coordinator.list_workspaces()] == ["ws-a", "ws-b"]
    assert module.CrossWorkspaceOperation is new.OperationType


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Call) and node.args:
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if callee in {"import_module", "__import__"}:
                found.append((node.lineno, ast.unparse(node.args[0]).strip("'\"")))
    return found


def test_knowledge_holds_no_import_of_coordination_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "knowledge").rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.coordination" or name.startswith("aragora.coordination.")
    ]
    assert offenders == []


def test_the_home_imports_nothing_from_aragora(new):
    imported = {
        name for _, name in _imported_modules(Path(new.__file__)) if name.startswith("aragora")
    }
    assert imported == set()

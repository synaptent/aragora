"""The change-approval, spec test-generator and role-hierarchy helpers live in ``aragora.agents``.

``aragora.agents.feature_agent`` and ``aragora.agents.spec`` (domain layer) use them. They used
to live in ``aragora.nomic`` (application layer) and import nothing above the domain layer, so
they now sit in the agents package. The old ``aragora.nomic`` paths re-export the same objects.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MOVES = {
    "aragora.nomic.approval": (
        "aragora.agents.change_approval",
        "ApprovalDecision ApprovalGate ApprovalLevel ApprovalPolicy ApprovalRequest ApprovalResult "
        "ApprovalStatus ApprovalWorkflow ApproverVote FileChange is_protected_file "
        "quick_approval_check".split(),
    ),
    "aragora.nomic.test_generator": (
        "aragora.agents.spec_test_generator",
        "FunctionSpec TestCase TestCodeGenerator TestGenerator TestSuite TestType "
        "extract_function_specs generate_tests_for_file".split(),
    ),
    "aragora.nomic.agent_roles": (
        "aragora.agents.roles",
        "AgentHierarchy AgentRole ROLE_CAPABILITIES RoleAssignment RoleBasedRouter RoleCapability "
        "get_agent_hierarchy reset_agent_hierarchy".split(),
    ),
}
CASES = [(old, new, name) for old, (new, names) in MOVES.items() for name in names]
SOURCE = '''
def add(left: int, right: int = 1) -> int:
    """Add two numbers."""
    return left + right


async def fetch(url: str) -> bytes:
    return b""


def _private() -> None:
    pass
'''


@pytest.mark.parametrize(("old", "new", "name"), CASES)
def test_the_old_path_is_the_same_object(old, new, name):
    assert getattr(importlib.import_module(old), name) is getattr(
        importlib.import_module(new), name
    )


@pytest.mark.parametrize(("old", "new"), [(old, new) for old, (new, _) in MOVES.items()])
def test_the_helpers_are_defined_in_the_agents_package(old, new):
    module = importlib.import_module(new)
    names = MOVES[old][1]
    classes = [getattr(module, name) for name in names if isinstance(getattr(module, name), type)]
    assert classes and all(cls.__module__ == new for cls in classes)
    assert sorted(importlib.import_module(old).__all__) == sorted(names)


@pytest.mark.parametrize(
    "module_name", ["aragora.nomic.approval", "aragora.agents.change_approval"]
)
def test_the_approval_policy_classifies_the_same_through_both_paths(module_name):
    module = importlib.import_module(module_name)
    changes = [module.FileChange(path="aragora/__init__.py", change_type="modify")]
    assert module.is_protected_file("aragora/__init__.py") is True
    assert module.is_protected_file("docs/notes.md") is False
    assert module.quick_approval_check(changes) is module.ApprovalLevel.CRITICAL


@pytest.mark.parametrize(
    "module_name", ["aragora.nomic.test_generator", "aragora.agents.spec_test_generator"]
)
def test_function_specs_are_extracted_the_same_through_both_paths(module_name):
    module = importlib.import_module(module_name)
    specs = module.extract_function_specs(SOURCE, "example")
    assert [(spec.name, spec.is_async) for spec in specs] == [("add", False), ("fetch", True)]
    assert specs[0].parameters == [
        {"name": "left", "type": "int"},
        {"name": "right", "type": "int"},
    ]
    assert specs[0].docstring == "Add two numbers."


def test_the_default_hierarchy_is_shared_with_the_old_path(tmp_path):
    old = importlib.import_module("aragora.nomic.agent_roles")
    new = importlib.import_module("aragora.agents.roles")
    new.reset_agent_hierarchy()
    try:
        hierarchy = asyncio.run(new.get_agent_hierarchy(tmp_path))
        assert asyncio.run(old.get_agent_hierarchy()) is hierarchy
        old.reset_agent_hierarchy()
        assert new._default_hierarchy is None
    finally:
        new.reset_agent_hierarchy()


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


def test_agents_holds_no_import_of_nomic_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "agents").rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.nomic" or name.startswith("aragora.nomic.")
    ]
    assert offenders == []


@pytest.mark.parametrize(
    ("module_name", "allowed"),
    [
        ("aragora.agents.change_approval", set()),
        ("aragora.agents.spec_test_generator", set()),
        ("aragora.agents.roles", {"aragora.persistence.db_config"}),
    ],
)
def test_the_homes_import_only_lower_layers(module_name, allowed):
    path = Path(importlib.import_module(module_name).__file__)
    imported = {name for _, name in _imported_modules(path) if name.startswith("aragora")}
    assert imported == allowed

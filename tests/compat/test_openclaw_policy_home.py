"""The OpenClaw policy engine and secure proxy live in ``aragora.compat``.

``aragora.ops``, ``aragora.skills`` and ``aragora.workflow`` (application layer) build
the policy and proxy. Both modules used to live in ``aragora.gateway`` (interface
layer); they now sit next to the rest of the OpenClaw compatibility code, and the
gateway paths re-export the same objects.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_HOME = "aragora.compat.openclaw_policy"
PROXY_HOME = "aragora.compat.openclaw_proxy"
OLD_POLICY = "aragora.gateway.openclaw_policy"
OLD_PROXY = "aragora.gateway.openclaw_proxy"
POLICY_NAMES = (
    "ActionRequest",
    "ActionType",
    "OpenClawPolicy",
    "PolicyDecision",
    "PolicyEvaluationResult",
    "PolicyRule",
    "create_enterprise_policy",
)
PROXY_NAMES = ("OpenClawSecureProxy", "PendingApproval", "ProxyActionResult", "ProxySession")
MOVES = [(OLD_POLICY, POLICY_HOME, name) for name in POLICY_NAMES] + [
    (OLD_PROXY, PROXY_HOME, name) for name in PROXY_NAMES
]
FIXED_REQUESTS = [
    ("file_read", "/etc/passwd", "deny", "block_system_directories"),
    ("file_write", "/workspace/default/notes.txt", "allow", "allow_workspace_files"),
    ("file_delete", "/workspace/other/notes.txt", "deny", None),
]
EXPECTED_PROXY_SCENARIO = {
    "results": [
        (
            False,
            "deny",
            "Matched rule 'block_system_directories': Block access to system directories",
        ),
        (True, "allow", None),
    ],
    "stats": {
        "sessions_created": 1,
        "sessions_ended": 0,
        "actions_allowed": 1,
        "actions_denied": 1,
        "actions_pending_approval": 0,
        "approvals_granted": 0,
        "approvals_denied": 0,
        "approvals_expired": 0,
        "active_sessions": 1,
        "pending_approvals": 0,
        "policy_rules": 8,
    },
    "events": ["session_created", "action_denied", "action_executed"],
}


@pytest.mark.parametrize(("old", "new", "name"), MOVES)
def test_the_names_are_defined_in_compat_and_shared_with_the_gateway_path(old, new, name):
    obj = getattr(importlib.import_module(new), name)
    assert obj.__module__ == new
    assert getattr(importlib.import_module(old), name) is obj


@pytest.mark.parametrize(("old", "names"), [(OLD_POLICY, POLICY_NAMES), (OLD_PROXY, PROXY_NAMES)])
def test_the_gateway_paths_export_only_the_moved_names(old, names):
    assert sorted(importlib.import_module(old).__all__) == sorted(names)


@pytest.mark.parametrize("module_name", [OLD_POLICY, POLICY_HOME])
def test_the_enterprise_policy_decides_the_same_through_both_paths(module_name):
    module = importlib.import_module(module_name)
    policy = module.create_enterprise_policy()
    decisions = []
    for action_type, path, _, _ in FIXED_REQUESTS:
        result = policy.evaluate(
            module.ActionRequest(
                action_type=module.ActionType(action_type),
                user_id="u1",
                session_id="s1",
                path=path,
            )
        )
        decisions.append(
            (
                action_type,
                path,
                result.decision.value,
                result.matched_rule.name if result.matched_rule else None,
            )
        )
    assert decisions == FIXED_REQUESTS


def test_a_rule_added_through_the_old_path_applies_to_a_new_path_request():
    old = importlib.import_module(OLD_POLICY)
    new = importlib.import_module(POLICY_HOME)
    policy = old.OpenClawPolicy(policy_dict={"version": 1, "default_decision": "deny", "rules": []})
    policy.add_rule(
        old.PolicyRule(
            name="allow_tmp",
            action_types=[old.ActionType.FILE_READ],
            decision=old.PolicyDecision.ALLOW,
            path_patterns=["/tmp/**"],
        )
    )
    result = policy.evaluate(
        new.ActionRequest(
            action_type=new.ActionType.FILE_READ, user_id="u", session_id="s", path="/tmp/a"
        )
    )
    assert result.decision is new.PolicyDecision.ALLOW
    assert result.matched_rule is policy.get_rule("allow_tmp")


async def _proxy_scenario(module_name: str) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    events: list[dict[str, Any]] = []
    proxy = module.OpenClawSecureProxy(audit_callback=events.append)
    session = await proxy.create_session(user_id="u1", roles=["developer"])
    denied = await proxy.execute_action(session.session_id, "file_read", path="/etc/passwd")
    allowed = await proxy.execute_action(
        session.session_id, "file_write", path="/workspace/default/notes.txt"
    )
    stats = proxy.get_stats()
    stats.pop("total_execution_time_ms")
    return {
        "results": [
            (result.success, result.policy_decision.value, result.error)
            for result in (denied, allowed)
        ],
        "stats": stats,
        "events": [event["event_type"] for event in events],
    }


@pytest.mark.parametrize("module_name", [OLD_PROXY, PROXY_HOME])
def test_the_proxy_gives_the_same_results_through_both_paths(module_name):
    assert asyncio.run(_proxy_scenario(module_name)) == EXPECTED_PROXY_SCENARIO


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


@pytest.mark.parametrize("package", ["ops", "skills", "workflow"])
def test_application_packages_hold_no_import_of_the_gateway_at_any_scope(package):
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / package).rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.gateway" or name.startswith("aragora.gateway.")
    ]
    assert offenders == []


@pytest.mark.parametrize("module_name", [POLICY_HOME, PROXY_HOME])
def test_the_new_homes_import_only_compat_modules_from_aragora(module_name):
    path = Path(importlib.import_module(module_name).__file__)
    imported = {name for _, name in _imported_modules(path) if name.startswith("aragora")}
    assert all(name.startswith("aragora.compat.") for name in imported), imported

"""The post-debate coordinator reaches the decision bridge through ``aragora.debate.decision_plan_bridges``.

``aragora.debate`` (domain layer) must not import ``aragora.integrations`` (interface layer),
whose ``DecisionBridge`` routes a decision plan to Jira, Linear or n8n. The integrations
package registers that bridge through the ``aragora.decision_plan_bridges`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.debate import decision_plan_bridges as hook
from aragora.debate.post_debate_coordinator import PostDebateCoordinator
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_REGISTRATION = (
    "integrations",
    "aragora.integrations.decision_bridge_registration:register_decision_bridge",
)


class RecordingBridge:
    def __init__(self, result=None, error=None):
        self.plans = []
        self._result, self._error = result, error

    async def handle_decision_plan(self, plan):
        self.plans.append(plan)
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_factory", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.DECISION_PLAN_BRIDGES_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def test_an_unregistered_bridge_raises(isolated_hook):
    with pytest.raises(
        hook.DecisionPlanBridgeNotRegisteredError, match="aragora.decision_plan_bridges"
    ):
        hook.create_decision_plan_bridge()


def test_without_a_bridge_the_step_returns_nothing(isolated_hook):
    assert PostDebateCoordinator()._step_decision_bridge({"id": "plan-1"}) is None


def test_the_step_routes_the_plan_through_a_new_registered_bridge(isolated_hook):
    bridges = []

    def factory():
        bridges.append(RecordingBridge(result={"routed": ["jira"]}))
        return bridges[-1]

    hook.register_decision_plan_bridge_factory(factory)
    coordinator = PostDebateCoordinator()
    plan = {"id": "plan-1"}
    assert coordinator._step_decision_bridge(plan) == {
        "type": "decision_bridge",
        "routed": ["jira"],
    }
    assert coordinator._step_decision_bridge(plan) == {
        "type": "decision_bridge",
        "routed": ["jira"],
    }
    assert [bridge.plans for bridge in bridges] == [[plan], [plan]]


@pytest.mark.parametrize("result", [None, {}])
def test_an_empty_bridge_result_returns_nothing(isolated_hook, result):
    hook.register_decision_plan_bridge_factory(lambda: RecordingBridge(result=result))
    assert PostDebateCoordinator()._step_decision_bridge({"id": "plan-1"}) is None


def test_a_failing_bridge_returns_nothing(isolated_hook):
    hook.register_decision_plan_bridge_factory(lambda: RecordingBridge(error=ValueError("bad")))
    assert PostDebateCoordinator()._step_decision_bridge({"id": "plan-1"}) is None


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_decision_plan_bridge_factory(object)

    entry_point = SimpleNamespace(name="d0", value="tests.declared:d0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            [entry_point] if group == hook.DECISION_PLAN_BRIDGES_ENTRY_POINT_GROUP else []
        ),
    )
    assert hook.create_decision_plan_bridge() is not hook.create_decision_plan_bridge()
    assert calls == ["register"]


def test_pyproject_declares_the_integrations_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(
        hook.DECISION_PLAN_BRIDGES_ENTRY_POINT_GROUP
    )._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [INTEGRATIONS_REGISTRATION]


def test_the_registration_reads_the_bridge_class_at_call_time(isolated_hook, monkeypatch):
    from aragora.integrations import decision_bridge
    from aragora.integrations.decision_bridge_registration import register_decision_bridge

    register_decision_bridge()
    register_decision_bridge()
    monkeypatch.delenv("ARAGORA_DECISION_BRIDGE_TARGETS", raising=False)
    bridge = hook.create_decision_plan_bridge()
    assert type(bridge) is decision_bridge.DecisionBridge
    assert bridge._default_targets == []
    monkeypatch.setattr(decision_bridge, "DecisionBridge", RecordingBridge)
    assert type(hook.create_decision_plan_bridge()) is RecordingBridge


def test_a_debate_only_process_reaches_the_integrations_bridge():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "from aragora.debate.decision_plan_bridges import create_decision_plan_bridge\n"
        "import aragora.debate.post_debate_coordinator\n"
        "assert not any(m.startswith('aragora.integrations') for m in sys.modules), 'preloaded'\n"
        "bridge = create_decision_plan_bridge()\n"
        "print(type(bridge).__module__, type(bridge).__name__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["aragora.integrations.decision_bridge", "DecisionBridge"]


def test_debate_holds_no_import_of_integrations_at_any_scope():
    offenders = []
    for path in sorted((REPO_ROOT / "aragora" / "debate").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}"
                for name in names
                if name == "aragora.integrations" or name.startswith("aragora.integrations.")
            ]
    assert offenders == []

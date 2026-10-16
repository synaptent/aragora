"""The debate engine runs post-debate workflows through ``aragora.debate.workflow_backends``.

``aragora.debate`` (domain layer) must not import ``aragora.workflow`` (application layer) at
runtime. The workflow package registers its engine through the
``aragora.debate_workflow_backends`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.debate import workflow_backends as hook
from aragora.debate.execution_bridge import ActionRule, ActionType, BridgeConfig, ExecutionBridge
from aragora.debate.orchestrator_setup import init_post_debate_workflow
from aragora.debate.phases.feedback_phase import FeedbackPhase
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_REGISTRATION = (
    "workflow",
    "aragora.workflow.debate_registration:register_debate_workflow_backend",
)


class RecordingBackend:
    def __init__(self, matches=True, result=None):
        self.calls = []
        self._matches, self._result = matches, result

    def default_post_debate_workflow(self):
        self.calls.append(("default",))
        return "default-workflow"

    async def execute(self, definition, inputs):
        self.calls.append(("execute", definition, inputs))
        return self._result

    def receipt_rule_matches(self, name, condition, workflow_template, receipt):
        self.calls.append(("match", name, workflow_template, condition(receipt)))
        return self._matches


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_backend", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.WORKFLOW_BACKENDS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def _workflow_rule():
    return ActionRule(
        name="ship",
        condition=lambda receipt: receipt["confidence"] > 0.5,
        action_type=ActionType.WORKFLOW,
        config={"workflow_template": "deploy"},
    )


def _phase_context():
    result = SimpleNamespace(
        winner="a1", confidence=0.9, consensus_reached=True, final_answer="Ship it"
    )
    return SimpleNamespace(
        debate_id="d1",
        env=SimpleNamespace(task="the task"),
        result=result,
        domain="general",
        agents=[SimpleNamespace(name="a1")],
    )


def test_an_unregistered_backend_raises(isolated_hook):
    with pytest.raises(hook.WorkflowBackendNotRegisteredError, match="aragora.debate_workflow"):
        hook.workflow_backend()


def test_without_a_backend_every_site_degrades(isolated_hook):
    arena = MagicMock()
    init_post_debate_workflow(arena, True, None, 0.7)
    assert arena.post_debate_workflow is None

    result = ExecutionBridge(config=BridgeConfig())._execute_workflow(
        _workflow_rule(), {"confidence": 0.9}
    )
    assert (result.success, result.detail) == (False, "Workflow triggers not available")


@pytest.mark.asyncio
async def test_without_a_backend_the_feedback_phase_skips_the_workflow(isolated_hook):
    phase = FeedbackPhase(post_debate_workflow="wf")
    await phase._run_workflow_async(_phase_context())


def test_the_arena_gets_the_backend_default_workflow(isolated_hook):
    backend = RecordingBackend()
    hook.register_workflow_backend(backend)
    arena = MagicMock()
    init_post_debate_workflow(arena, True, None, 0.7)
    assert arena.post_debate_workflow == "default-workflow"
    init_post_debate_workflow(arena, True, "given", 0.7)
    assert arena.post_debate_workflow == "given"
    assert backend.calls == [("default",)]


@pytest.mark.parametrize(("matches", "detail"), [(True, "triggered"), (False, "not matched")])
def test_the_bridge_asks_the_backend_whether_the_rule_fires(isolated_hook, matches, detail):
    backend = RecordingBackend(matches=matches)
    hook.register_workflow_backend(backend)
    result = ExecutionBridge(config=BridgeConfig())._execute_workflow(
        _workflow_rule(), {"confidence": 0.9}
    )
    assert (result.success, result.detail) == (matches, f"Workflow 'deploy' {detail}")
    assert backend.calls == [("match", "ship", "deploy", True)]


@pytest.mark.asyncio
async def test_the_feedback_phase_runs_the_workflow_on_the_backend(isolated_hook):
    backend = RecordingBackend(
        result=SimpleNamespace(success=True, final_output="done", error=None)
    )
    hook.register_workflow_backend(backend)
    await FeedbackPhase(post_debate_workflow="wf")._run_workflow_async(_phase_context())
    ((kind, definition, inputs),) = backend.calls
    assert (kind, definition) == ("execute", "wf")
    assert inputs["debate_id"] == "d1"
    assert inputs["result"]["final_answer"] == "Ship it"
    assert inputs["agents"] == ["a1"]


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_workflow_backend(RecordingBackend())

    entry_point = SimpleNamespace(name="w0", value="tests.declared:w0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.WORKFLOW_BACKENDS_ENTRY_POINT_GROUP else [],
    )
    assert hook.workflow_backend() is hook.workflow_backend()
    assert calls == ["register"]


def test_pyproject_declares_the_workflow_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.WORKFLOW_BACKENDS_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [
        WORKFLOW_REGISTRATION
    ]


def test_the_registered_engine_backend_matches_receipts_and_builds_workflows(isolated_hook):
    from aragora.workflow.debate_registration import register_debate_workflow_backend
    from aragora.workflow.engine import WorkflowDefinition

    register_debate_workflow_backend()
    backend = hook.workflow_backend()
    assert isinstance(backend.default_post_debate_workflow(), WorkflowDefinition)

    def is_confident(receipt):
        return receipt["confidence"] > 0.5

    assert backend.receipt_rule_matches("r", is_confident, "deploy", {"confidence": 0.9})
    assert not backend.receipt_rule_matches("r", is_confident, "deploy", {"confidence": 0.1})


@pytest.mark.asyncio
async def test_the_engine_backend_reads_the_engine_at_call_time(isolated_hook, monkeypatch):
    from aragora.workflow import engine
    from aragora.workflow.debate_registration import register_debate_workflow_backend

    calls = []

    class Engine:
        async def execute(self, definition, inputs):
            calls.append((definition, inputs))
            return "ran"

    register_debate_workflow_backend()
    monkeypatch.setattr(engine, "get_workflow_engine", Engine)
    assert await hook.workflow_backend().execute("wf", {"a": 1}) == "ran"
    assert calls == [("wf", {"a": 1})]


def test_a_debate_only_process_reaches_the_workflow_engine():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "from aragora.debate.workflow_backends import workflow_backend\n"
        "import aragora.debate.orchestrator_setup\n"
        "backend = workflow_backend()\n"
        "print(type(backend).__module__, type(backend).__name__)\n"
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
    assert result.stdout.split()[-2:] == [
        "aragora.workflow.debate_registration",
        "WorkflowEngineBackend",
    ]


def _runtime_imports(tree):
    """Absolute imports outside ``if TYPE_CHECKING:`` blocks."""
    type_only = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            type_only.update(id(child) for stmt in node.body for child in ast.walk(stmt))
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def test_debate_holds_no_runtime_import_of_workflow():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "debate").rglob("*.py"))
        for line, name in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if name == "aragora.workflow" or name.startswith("aragora.workflow.")
    ]
    assert offenders == []

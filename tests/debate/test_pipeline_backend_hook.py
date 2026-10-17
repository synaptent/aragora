"""The debate engine reaches the decision pipeline through ``aragora.debate.pipeline_backends``.

``aragora.debate`` (domain layer) must not import ``aragora.pipeline`` (application layer) at
runtime. The pipeline package registers its backend through the
``aragora.debate_pipeline_backends`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.debate import pipeline_backends as hook
from aragora.debate.execution_bridge import ActionRule, ActionType, BridgeConfig, ExecutionBridge
from aragora.debate.extensions import ArenaExtensions
from aragora.debate.hooks import HookType, create_hook_manager
from aragora.debate.hook_handlers import create_hook_handler_registry
from aragora.debate.orchestrator_runner import _auto_execute_plan
from aragora.debate.phases.feedback_phase import FeedbackPhase
from aragora.debate.post_debate_coordinator import PostDebateCoordinator
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_REGISTRATION = (
    "pipeline",
    "aragora.pipeline.debate_registration:register_debate_pipeline_backend",
)


class FakeExecutor:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def execute_to_github_issue(self, plan):
        return {"url": f"issue-for-{plan.id}"}

    def execute_to_github_pr(self, plan, draft=False):
        return {"pr": plan.id, "draft": draft}


class FakeFactory:
    @staticmethod
    def from_debate_result(result, **kwargs):
        return SimpleNamespace(id="plan-1", metadata=kwargs.get("metadata", {}))


class FakePackage:
    def to_dict(self):
        return {"package": "built"}


class FakePipeline:
    def from_debate(self, cartographer_data, auto_advance):
        return SimpleNamespace(pipeline_id="pipe-1", stage_status={"ideas": "complete"})


class FakeMemo:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class FakeRuntime:
    pass


class RecordingBackend:
    def decision_plan_factory(self):
        return FakeFactory

    def plan_executor(self):
        return FakeExecutor

    def plan_registry(self):
        return (lambda plan_id: None), (lambda plan: None)

    def backbone_plan_runs(self):
        raise AssertionError("not used by these sites")

    def backbone_runtime(self):
        return FakeRuntime

    def integrity_package_builder(self):
        return lambda result, include_receipt, include_plan: FakePackage()

    def idea_to_execution_pipeline(self):
        return FakePipeline

    def decision_memo(self):
        return FakeMemo


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_backend", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.PIPELINE_BACKENDS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def _debate_result(**extra):
    message = SimpleNamespace(agent="a1", content="Ship it", role="proposal", round=1)
    return SimpleNamespace(
        debate_id="d1",
        task="the task",
        final_answer="Ship it",
        confidence=0.9,
        consensus_reached=True,
        participants=["a1"],
        messages=[message],
        metadata={},
        **extra,
    )


def _pr_rule():
    return ActionRule(name="pr", condition=lambda r: True, action_type=ActionType.PR_CREATION)


def test_an_unregistered_backend_raises(isolated_hook):
    with pytest.raises(hook.PipelineBackendNotRegisteredError, match="aragora.debate_pipeline"):
        hook.pipeline_backend()


def test_without_a_backend_every_coordinator_step_degrades(isolated_hook):
    coordinator = PostDebateCoordinator()
    plan_data = {"plan": SimpleNamespace(id="p1", status="approved")}
    assert coordinator._step_create_plan("d1", _debate_result(), "task", None) is None
    assert coordinator._step_execute_plan(plan_data, None) is None
    assert coordinator._step_create_pr(plan_data, "task") is None
    assert coordinator._step_build_integrity_package("d1", _debate_result()) is None
    assert coordinator._step_trigger_canvas("d1", _debate_result(), "task") is None
    assert coordinator._get_backbone_runtime() is None


@pytest.mark.asyncio
async def test_without_a_backend_the_other_sites_degrade(isolated_hook, caplog):
    bridge = ExecutionBridge(config=BridgeConfig(enable_pr_creation=True))
    outcome = bridge._execute_pr_creation(_pr_rule(), {"debate_id": "d1"}, _debate_result())
    assert not outcome.success
    assert "aragora.debate_pipeline_backends" in outcome.detail

    result = _debate_result(decision_plan=SimpleNamespace(id="p1"))
    ArenaExtensions(auto_execute_plan=True)._auto_execute_plan(SimpleNamespace(), result)
    assert "github_issue_url" not in result.metadata

    ctx = SimpleNamespace(debate_id="d1", result=_debate_result(), env=None, agents=[])
    FeedbackPhase()._generate_decision_memo(ctx)
    assert "decision_memo" not in ctx.result.metadata

    arena = SimpleNamespace(post_debate_config=None, agents=[], auth_context=None)
    result = await _auto_execute_plan(arena, _debate_result())
    assert result.metadata["auto_execution_error"] == "PipelineBackendNotRegisteredError"

    manager = create_hook_manager()
    arena_config = SimpleNamespace(auto_create_plan=True, plan_min_confidence=0.5)
    create_hook_handler_registry(manager, arena_config=arena_config)
    hook_result = _debate_result()
    with caplog.at_level(logging.DEBUG, logger="aragora.debate.hook_handlers"):
        await manager.trigger(HookType.POST_DEBATE, ctx=SimpleNamespace(), result=hook_result)
    assert not hasattr(hook_result, "plan_id")
    assert "Decision plan creation unavailable" in caplog.text


def test_the_coordinator_steps_use_the_backend(isolated_hook):
    hook.register_pipeline_backend(RecordingBackend())
    coordinator = PostDebateCoordinator()
    plan = SimpleNamespace(id="p1", status="approved")
    created = coordinator._step_create_plan("d1", _debate_result(), "task", None)
    assert created["plan"].metadata == {"debate_id": "d1", "task": "task"}
    assert coordinator._step_execute_plan({"plan": plan}, None) == {"url": "issue-for-p1"}
    assert coordinator._step_create_pr({"plan": plan}, "task") == {"pr": "p1", "draft": True}
    assert coordinator._step_build_integrity_package("d1", _debate_result()) == {"package": "built"}
    canvas = coordinator._step_trigger_canvas("d1", _debate_result(), "task")
    assert (canvas["pipeline_id"], canvas["stages_completed"]) == ("pipe-1", ["ideas"])
    assert isinstance(coordinator._get_backbone_runtime(), FakeRuntime)


def test_the_other_sites_use_the_backend(isolated_hook):
    hook.register_pipeline_backend(RecordingBackend())
    bridge = ExecutionBridge(config=BridgeConfig(enable_pr_creation=True))
    outcome = bridge._execute_pr_creation(_pr_rule(), {"debate_id": "d1"}, _debate_result())
    assert outcome.success
    assert "'pr': 'plan-1'" in outcome.detail

    result = _debate_result(decision_plan=SimpleNamespace(id="p1"))
    ArenaExtensions(auto_execute_plan=True)._auto_execute_plan(SimpleNamespace(), result)
    assert result.metadata["github_issue_url"] == "issue-for-p1"

    ctx = SimpleNamespace(debate_id="d1", result=_debate_result(), env=None, agents=[])
    FeedbackPhase()._generate_decision_memo(ctx)
    memo = ctx.result.metadata["decision_memo"]
    assert (type(memo), memo.summary, memo.consensus_confidence) == (FakeMemo, "Ship it", 0.9)


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_pipeline_backend(RecordingBackend())

    entry_point = SimpleNamespace(name="p0", value="tests.declared:p0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.PIPELINE_BACKENDS_ENTRY_POINT_GROUP else [],
    )
    assert hook.pipeline_backend() is hook.pipeline_backend()
    assert calls == ["register"]


def test_pyproject_declares_the_pipeline_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.PIPELINE_BACKENDS_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [
        PIPELINE_REGISTRATION
    ]


def test_the_registered_backend_returns_the_pipeline_objects(isolated_hook):
    from aragora.pipeline import decision_integrity, decision_integrity_utils, executor
    from aragora.pipeline.backbone_runtime import BackboneRuntime
    from aragora.pipeline.debate_registration import register_debate_pipeline_backend
    from aragora.pipeline.decision_plan import DecisionPlanFactory
    from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline
    from aragora.pipeline.pr_generator import DecisionMemo

    register_debate_pipeline_backend()
    backend = hook.pipeline_backend()
    assert backend.decision_plan_factory() is DecisionPlanFactory
    assert backend.plan_executor() is executor.PlanExecutor
    assert backend.plan_registry() == (executor.get_plan, executor.store_plan)
    assert backend.backbone_plan_runs() == (
        decision_integrity_utils.ensure_decision_plan_backbone_run,
        decision_integrity_utils.execute_decision_plan_with_backbone,
        decision_integrity_utils.sync_decision_plan_backbone_receipt,
    )
    assert backend.backbone_runtime() is BackboneRuntime
    assert (
        backend.integrity_package_builder()
        is decision_integrity.build_integrity_package_from_result
    )
    assert backend.idea_to_execution_pipeline() is IdeaToExecutionPipeline
    assert backend.decision_memo() is DecisionMemo


def test_the_registered_backend_reads_the_pipeline_at_call_time(isolated_hook, monkeypatch):
    from aragora.pipeline import executor
    from aragora.pipeline.debate_registration import register_debate_pipeline_backend

    register_debate_pipeline_backend()
    replacement = object()
    monkeypatch.setattr(executor, "PlanExecutor", replacement)
    assert hook.pipeline_backend().plan_executor() is replacement

    monkeypatch.setitem(sys.modules, "aragora.pipeline.executor", None)
    with pytest.raises(ImportError):
        hook.pipeline_backend().plan_executor()


def test_a_debate_only_process_reaches_the_pipeline_backend():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "import aragora.debate.post_debate_coordinator\n"
        "loaded_before = 'aragora.pipeline' in sys.modules\n"
        "from aragora.debate.pipeline_backends import pipeline_backend\n"
        "backend = pipeline_backend()\n"
        "print(loaded_before, type(backend).__module__, type(backend).__name__)\n"
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
    assert result.stdout.split()[-3:] == [
        "False",
        "aragora.pipeline.debate_registration",
        "DecisionPipelineBackend",
    ]


_INTEGRITY_BUILDER_SCRIPT = """\
import json
import sys

from aragora.core import decision_route_hooks as hooks
from aragora.debate.pipeline_backends import pipeline_backend
from aragora.debate.post_debate_coordinator import PostDebateCoordinator  # noqa: F401


async def application_builder(*args, **kwargs):
    return {"source": "application"}


async def replacement_builder(*args, **kwargs):
    return {"source": "replacement"}


mode = sys.argv[1]
loaded_before = "aragora.pipeline" in sys.modules
if mode != "nothing-registered":
    hooks.register_decision_integrity_builder(application_builder)
backend = pipeline_backend()
if mode == "registered-again":
    hooks.register_decision_integrity_builder(replacement_builder)
# Read the registry itself: a getter miss would run the decision-route discovery, which
# also installs the default builder and would hide a missing fill.
builder = hooks._hooks.get(hooks.HOOK_DECISION_INTEGRITY)
print(json.dumps([loaded_before, type(backend).__name__, builder and builder.__qualname__]))
"""


@pytest.mark.parametrize(
    ("mode", "expected_builder"),
    [
        ("registered-first", "application_builder"),
        ("nothing-registered", "build_decision_integrity_payload"),
        ("registered-again", "replacement_builder"),
    ],
)
def test_the_first_backend_lookup_keeps_an_integrity_builder_registered_before_it(
    mode, expected_builder
):
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    result = subprocess.run(
        [sys.executable, "-c", _INTEGRITY_BUILDER_SCRIPT, mode],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    loaded_before, backend, builder = json.loads(result.stdout.splitlines()[-1])
    assert (loaded_before, backend) == (False, "DecisionPipelineBackend")
    assert builder == expected_builder


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


def _is_module(name):
    path = REPO_ROOT.joinpath(*name.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def test_debate_holds_no_runtime_import_of_pipeline():
    # Like the import contract, count only modules that exist: an import of a missing
    # pipeline module always raises ImportError and creates no dependency.
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "debate").rglob("*.py"))
        for line, name in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if (name == "aragora.pipeline" or name.startswith("aragora.pipeline.")) and _is_module(name)
    ]
    assert offenders == []

"""Characterization of the decision router registration hooks.

``aragora.core`` (domain layer) must not import the workflow, gauntlet, pipeline,
connectors, audit or server packages. The pipeline and chat connector packages
register their decision-router behaviour from their own package init, the server
registers the audit sink through ``aragora.server.decision_routes``, and the router
looks each hook up at call time. The workflow and gauntlet route targets are covered
by ``test_decision_route_targets.py``.
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.core import decision_route_hooks as hooks
from aragora.core.decision import (
    DecisionConfig,
    DecisionRequest,
    DecisionResult,
    DecisionRouter,
    DecisionType,
    RequestContext,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = REPO_ROOT / "aragora" / "core"
FORBIDDEN_PACKAGES = ("audit", "connectors", "gauntlet", "pipeline", "server", "workflow")
_FORBIDDEN_RE = "|".join(FORBIDDEN_PACKAGES)


@pytest.fixture
def isolated_hooks(monkeypatch):
    """Run a test against an empty registry; the process-wide one is restored afterwards."""
    # A package init that first runs inside the swap would register into the temporary
    # registry only, so load the self-registering packages before swapping.
    import aragora.connectors.chat  # noqa: F401
    import aragora.pipeline  # noqa: F401
    from aragora.core import decision_router as router_module

    monkeypatch.setattr(hooks, "_hooks", {})
    # Treat the declared registrations as already run, so a miss stays a miss.
    monkeypatch.setattr(hooks, "_declared_registrations_loaded", True)
    monkeypatch.setattr(router_module, "_warned_once", set())
    return hooks


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "getter",
    ["get_decision_integrity_builder", "get_tts_bridge_factory", "get_decision_audit_sink"],
)
def test_unregistered_hooks_raise(isolated_hooks, getter):
    with pytest.raises(hooks.DecisionRouteNotRegisteredError, match="registered"):
        getattr(hooks, getter)()


def test_not_registered_error_is_a_runtime_error():
    # DecisionRouter.route() converts RuntimeErrors into a failed DecisionResult.
    assert issubclass(hooks.DecisionRouteNotRegisteredError, RuntimeError)


def test_registering_again_replaces_the_hook(isolated_hooks):
    first, second = MagicMock(), MagicMock()
    hooks.register_decision_audit_sink(first)
    hooks.register_decision_audit_sink(second)
    assert hooks.get_decision_audit_sink() is second


def test_decision_router_reexports_the_error():
    import aragora.core.decision_router as dr

    assert dr.DecisionRouteNotRegisteredError is hooks.DecisionRouteNotRegisteredError


# ---------------------------------------------------------------------------
# Upper packages register themselves
# ---------------------------------------------------------------------------


def test_pipeline_init_registers_the_decision_integrity_builder():
    import aragora.pipeline  # noqa: F401
    from aragora.pipeline.decision_integrity_utils import build_decision_integrity_payload

    assert hooks.get_decision_integrity_builder() is build_decision_integrity_payload


def test_connectors_chat_init_registers_the_tts_bridge_factory():
    import aragora.connectors.chat  # noqa: F401
    from aragora.connectors.chat.tts_bridge import get_tts_bridge

    assert hooks.get_tts_bridge_factory() is get_tts_bridge


def test_server_registration_installs_every_hook(isolated_hooks):
    from aragora.connectors.chat.tts_bridge import get_tts_bridge
    from aragora.pipeline.decision_integrity_utils import build_decision_integrity_payload
    from aragora.server import decision_routes

    decision_routes.register_decision_routes()
    decision_routes.register_decision_routes()

    assert isinstance(hooks.get_decision_audit_sink(), decision_routes.UnifiedAuditDecisionSink)
    assert hooks.get_decision_integrity_builder() is build_decision_integrity_payload
    assert hooks.get_tts_bridge_factory() is get_tts_bridge


# ---------------------------------------------------------------------------
# Declared registrations run on the first lookup that finds nothing
# ---------------------------------------------------------------------------


@pytest.fixture
def undiscovered_hooks(isolated_hooks, monkeypatch):
    """Empty registries on which the declared registrations have not run yet."""
    import aragora.gauntlet  # noqa: F401
    import aragora.workflow  # noqa: F401

    monkeypatch.setattr(hooks, "_route_targets", {})
    monkeypatch.setattr(hooks, "_declared_registrations_loaded", False)
    return hooks


def _declare(monkeypatch, *registrations):
    """Make ``registrations`` the only entry points of the aragora.decision_routes group."""
    entry_points = [
        SimpleNamespace(value=f"tests.declared:{index}", load=lambda fn=fn: fn)
        for index, fn in enumerate(registrations)
    ]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: entry_points if group == "aragora.decision_routes" else [],
    )


def test_a_lookup_miss_runs_the_declared_registrations_once(undiscovered_hooks, monkeypatch):
    sink = MagicMock()
    calls = []

    def register():
        calls.append("register")
        hooks.register_decision_audit_sink(sink)

    _declare(monkeypatch, register)

    assert hooks.get_decision_audit_sink() is sink
    assert hooks.get_decision_audit_sink() is sink
    with pytest.raises(hooks.DecisionRouteNotRegisteredError, match="workflow"):
        hooks.get_route_target(hooks.ROUTE_WORKFLOW)
    assert calls == ["register"]


def test_a_route_lookup_miss_runs_the_declared_registrations(undiscovered_hooks, monkeypatch):
    target = AsyncMock()
    _declare(monkeypatch, lambda: hooks.register_route_target(hooks.ROUTE_GAUNTLET, target))

    assert hooks.get_route_target(hooks.ROUTE_GAUNTLET) is target


def test_the_registry_snapshot_does_not_run_the_declared_registrations(
    undiscovered_hooks, monkeypatch
):
    calls = []
    _declare(monkeypatch, lambda: calls.append("register"))

    assert hooks.get_registered_routes() == {}
    assert calls == []


def test_a_failing_declared_registration_is_logged_and_the_lookup_still_raises(
    undiscovered_hooks, monkeypatch, caplog
):
    def broken():
        raise ImportError("optional dependency missing")

    _declare(monkeypatch, broken)

    with caplog.at_level("WARNING", logger="aragora.core.decision_route_hooks"):
        with pytest.raises(hooks.DecisionRouteNotRegisteredError, match="aragora.decision_routes"):
            hooks.get_decision_integrity_builder()
    assert "optional dependency missing" in caplog.text


def test_a_failing_declared_registration_does_not_stop_the_later_ones(
    undiscovered_hooks, monkeypatch, caplog
):
    sink = MagicMock()

    def broken():
        raise KeyError("missing setting")

    _declare(monkeypatch, broken, lambda: hooks.register_decision_audit_sink(sink))

    with caplog.at_level("WARNING", logger="aragora.core.decision_route_hooks"):
        assert hooks.get_decision_audit_sink() is sink
    assert "missing setting" in caplog.text


def test_an_unexpected_registration_error_reaches_the_caller_after_the_later_ones_ran(
    undiscovered_hooks, monkeypatch
):
    class PluginBug(Exception):
        pass

    sink = MagicMock()

    def broken():
        raise PluginBug("plugin defect")

    _declare(monkeypatch, broken, lambda: hooks.register_decision_audit_sink(sink))

    with pytest.raises(PluginBug):
        hooks.get_decision_audit_sink()
    assert hooks.get_decision_audit_sink() is sink


def _require_toml_parser():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")


def test_a_source_checkout_uses_its_pyproject_declarations_when_metadata_has_none(
    undiscovered_hooks, monkeypatch
):
    # An editable install keeps the entry points it was installed with; a source tree
    # run against older metadata still reaches the registrations its pyproject declares.
    from aragora.server.decision_routes import UnifiedAuditDecisionSink

    _require_toml_parser()
    _declare(monkeypatch)

    assert isinstance(hooks.get_decision_audit_sink(), UnifiedAuditDecisionSink)
    assert sorted(hooks.get_registered_routes()) == ["gauntlet", "workflow"]


def test_source_checkout_declarations_use_tomli_before_python_3_11(monkeypatch):
    # Stands the 3.11+ stdlib parser in for tomli, so the 3.10 branch runs on any interpreter.
    tomllib = pytest.importorskip("tomllib")

    server = [("server", "aragora.server.decision_routes:register_decision_routes")]
    monkeypatch.setattr(sys, "version_info", (3, 10, 14))
    monkeypatch.setitem(sys.modules, "tomli", tomllib)
    assert [(ep.name, ep.value) for ep in hooks._source_checkout_registrations()] == server

    # Without tomli the fallback finds nothing rather than failing the lookup.
    monkeypatch.setitem(sys.modules, "tomli", None)
    assert hooks._source_checkout_registrations() == []


def test_source_checkout_declarations_come_only_from_aragoras_pyproject(monkeypatch, tmp_path):
    _require_toml_parser()
    assert [(ep.name, ep.value) for ep in hooks._source_checkout_registrations()] == [
        ("server", "aragora.server.decision_routes:register_decision_routes")
    ]

    other = tmp_path / "pyproject.toml"
    other.write_text(
        '[project]\nname = "other"\n\n[project.entry-points."aragora.decision_routes"]\n'
        'other = "other.routes:register"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(hooks, "_SOURCE_PYPROJECT", other)
    assert hooks._source_checkout_registrations() == []
    monkeypatch.setattr(hooks, "_SOURCE_PYPROJECT", tmp_path / "missing.toml")
    assert hooks._source_checkout_registrations() == []


# ---------------------------------------------------------------------------
# Declared registrations never replace what a caller registered first
# ---------------------------------------------------------------------------


def test_declared_registrations_only_fill_what_the_caller_left_missing(
    undiscovered_hooks, monkeypatch
):
    workflow, sink = AsyncMock(), MagicMock()
    hooks.register_route_target(hooks.ROUTE_WORKFLOW, workflow)
    hooks.register_decision_audit_sink(sink)
    declared_workflow, declared_gauntlet = AsyncMock(), AsyncMock()
    declared_sink, declared_builder = MagicMock(), AsyncMock()

    def register():
        hooks.register_route_target(hooks.ROUTE_WORKFLOW, declared_workflow)
        hooks.register_route_target(hooks.ROUTE_GAUNTLET, declared_gauntlet)
        hooks.register_decision_audit_sink(declared_sink)
        hooks.register_decision_integrity_builder(declared_builder)

    _declare(monkeypatch, register)

    assert hooks.get_route_target(hooks.ROUTE_GAUNTLET) is declared_gauntlet
    assert hooks.get_route_target(hooks.ROUTE_WORKFLOW) is workflow
    assert hooks.get_decision_audit_sink() is sink
    assert hooks.get_decision_integrity_builder() is declared_builder

    # Outside discovery, registering again still replaces the entry.
    hooks.register_route_target(hooks.ROUTE_WORKFLOW, declared_workflow)
    hooks.register_decision_audit_sink(declared_sink)
    assert hooks.get_route_target(hooks.ROUTE_WORKFLOW) is declared_workflow
    assert hooks.get_decision_audit_sink() is declared_sink


def test_registering_replaces_again_after_a_declared_registration_fails(
    undiscovered_hooks, monkeypatch
):
    class PluginBug(Exception):
        pass

    def broken():
        raise PluginBug("plugin defect")

    _declare(monkeypatch, broken)
    with pytest.raises(PluginBug):
        hooks.get_route_target(hooks.ROUTE_WORKFLOW)

    first, second = AsyncMock(), AsyncMock()
    hooks.register_route_target(hooks.ROUTE_WORKFLOW, first)
    hooks.register_route_target(hooks.ROUTE_WORKFLOW, second)
    assert hooks.get_route_target(hooks.ROUTE_WORKFLOW) is second


_EXPLICIT_REGISTRATION_CALLER = """
    import asyncio, json, sys

    from aragora.core import decision_route_hooks as hooks
    from aragora.core.decision import (
        DecisionConfig,
        DecisionRequest,
        DecisionResult,
        DecisionRouter,
        DecisionType,
    )

    scenario = sys.argv[1]
    called = []

    async def custom_workflow(router, request, span):
        called.append(request.request_id)
        return DecisionResult(
            request_id=request.request_id,
            decision_type=DecisionType.WORKFLOW,
            answer="custom-workflow",
            confidence=1.0,
            consensus_reached=True,
        )

    class Sink:
        def __init__(self):
            self.events = []

        def log_decision_started(self, *, request_id, **_kwargs):
            self.events.append(["started", request_id])

        def log_decision_completed(self, *, request_id, **_kwargs):
            self.events.append(["completed", request_id])

    sink = Sink()
    hooks.register_route_target(hooks.ROUTE_WORKFLOW, custom_workflow)
    if scenario == "sink":
        hooks.register_decision_audit_sink(sink)
        # A route miss runs the declared registrations after both caller registrations.
        hooks.get_route_target(hooks.ROUTE_GAUNTLET)

    request = DecisionRequest(
        content="Run the thing",
        decision_type=DecisionType.WORKFLOW,
        config=DecisionConfig(agents=[]),
    )
    router = DecisionRouter(
        workflow_engine=object(), enable_caching=False, enable_deduplication=False
    )
    result = asyncio.run(router.route(request))
    audit = hooks.get_decision_audit_sink()
    print(json.dumps({
        "server_loaded": "aragora.server.decision_routes" in sys.modules,
        "called": called == [request.request_id],
        "result": [result.success, result.answer, result.error],
        "workflow_kept": hooks.get_registered_routes()[hooks.ROUTE_WORKFLOW] is custom_workflow,
        "gauntlet": hooks.get_route_target(hooks.ROUTE_GAUNTLET).__module__,
        "audit": "caller" if audit is sink else type(audit).__module__,
        "sink_events": sink.events == [
            ["started", request.request_id], ["completed", request.request_id]
        ],
    }))
"""


def _run_core_only_caller(scenario: str, tmp_path: Path) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "ARAGORA_DATA_DIR": str(tmp_path / "data"),
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
        "AWS_EC2_METADATA_DISABLED": "true",
        "ARAGORA_SECRETS_STRICT": "false",
    }
    proc = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", textwrap.dedent(_EXPLICIT_REGISTRATION_CALLER)]
        + [scenario],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_core_only_caller_keeps_its_workflow_target_when_routing(tmp_path):
    out = _run_core_only_caller("route", tmp_path)

    # The audit sink miss ran the declared registrations, which filled only the
    # keys the caller left empty.
    assert out["server_loaded"] is True
    assert out["called"] is True
    assert out["result"] == [True, "custom-workflow", None]
    assert out["workflow_kept"] is True
    assert out["gauntlet"] == "aragora.gauntlet.decision_route"
    assert out["audit"] == "aragora.server.decision_routes"


def test_core_only_caller_keeps_its_audit_sink_through_a_route_miss(tmp_path):
    out = _run_core_only_caller("sink", tmp_path)

    assert out["server_loaded"] is True
    assert out["called"] is True
    assert out["result"] == [True, "custom-workflow", None]
    assert out["workflow_kept"] is True
    assert out["gauntlet"] == "aragora.gauntlet.decision_route"
    assert out["audit"] == "caller"
    assert out["sink_events"] is True


def _function_calls(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return {
                getattr(call.func, "attr", None) or getattr(call.func, "id", "")
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }
    raise AssertionError(f"{function_name} not found in {path}")


@pytest.mark.parametrize(
    ("relative_path", "function_name"),
    [
        ("aragora/server/unified_server.py", "_init_decision_router"),
        ("aragora/server/fastapi/factory.py", "lifespan"),
        ("scripts/control_plane_deliberation_worker.py", "run_worker"),
        ("aragora/bots/commands.py", "_route_via_decision_router"),
    ],
)
def test_process_entrypoints_register_decision_routes(relative_path, function_name):
    # Entry points that can route decisions install every hook, including the audit sink.
    calls = _function_calls(REPO_ROOT / relative_path, function_name)
    assert "register_decision_routes" in calls


def test_unified_server_creates_the_router_when_registration_cannot_import(monkeypatch):
    import sys

    from aragora.core import decision
    from aragora.server import unified_server

    router = object()
    monkeypatch.setitem(sys.modules, "aragora.server.decision_routes", None)
    monkeypatch.setattr(decision, "get_decision_router", lambda **_: router)
    monkeypatch.setattr(unified_server.UnifiedHandler, "decision_router", None, raising=False)

    unified_server.UnifiedServer._init_decision_router(SimpleNamespace())

    assert unified_server.UnifiedHandler.decision_router is router


def test_unified_audit_sink_writes_the_decision_events(monkeypatch):
    from aragora.audit.unified import AuditOutcome, AuditSeverity, UnifiedAuditCategory
    from aragora.server import decision_routes

    logged = []
    monkeypatch.setattr(
        decision_routes,
        "get_unified_audit_logger",
        lambda: SimpleNamespace(log=logged.append),
    )
    sink = decision_routes.UnifiedAuditDecisionSink()
    sink.log_decision_started(
        request_id="req-1",
        decision_type="debate",
        source="http_api",
        user_id="user-1",
        workspace_id="ws-1",
        content_preview="x" * 300,
    )
    sink.log_decision_completed(
        request_id="req-1",
        decision_type="debate",
        success=False,
        consensus_reached=False,
        confidence=0.0,
        duration_seconds=1.5,
        user_id="user-1",
        workspace_id="ws-1",
        error="boom",
    )

    started, completed = logged
    assert started.category is UnifiedAuditCategory.DEBATE_STARTED
    assert started.action == "Decision debate started"
    assert (started.actor_id, started.resource_type, started.resource_id) == (
        "user-1",
        "decision",
        "req-1",
    )
    assert started.workspace_id == "ws-1"
    assert started.details == {
        "decision_type": "debate",
        "source": "http_api",
        "content_preview": "x" * 200,
    }
    assert completed.category is UnifiedAuditCategory.DEBATE_COMPLETED
    assert completed.action == "Decision debate completed"
    assert completed.outcome is AuditOutcome.FAILURE
    assert completed.severity is AuditSeverity.WARNING
    assert completed.details == {
        "decision_type": "debate",
        "consensus_reached": False,
        "confidence": 0.0,
        "duration_seconds": 1.5,
        "error": "boom",
    }


# ---------------------------------------------------------------------------
# Router behaviour through the hooks
# ---------------------------------------------------------------------------


def _request(decision_type: DecisionType, **config) -> DecisionRequest:
    return DecisionRequest(
        content="Run the thing",
        decision_type=decision_type,
        config=DecisionConfig(**config),
        context=RequestContext(user_id="user-1", workspace_id="ws-1"),
    )


def _quick_router(answer: str) -> tuple[DecisionRouter, DecisionRequest]:
    router = DecisionRouter(enable_caching=False, enable_deduplication=False)
    request = _request(DecisionType.QUICK)
    router._route_to_quick = AsyncMock(  # type: ignore[method-assign]
        return_value=DecisionResult(
            request_id=request.request_id,
            decision_type=DecisionType.QUICK,
            answer=answer,
            confidence=0.7,
            consensus_reached=True,
        )
    )
    return router, request


def _debate_router() -> tuple[DecisionRouter, list[object]]:
    arenas: list[object] = []

    class StubArena:
        def __init__(self, **_kwargs):
            arenas.append(self)

        async def run(self):
            return SimpleNamespace(final_answer="Use LRU", consensus_reached=True)

    router = DecisionRouter(
        debate_engine=StubArena, enable_caching=False, enable_deduplication=False
    )
    return router, arenas


async def test_router_optional_hooks_keep_their_fallbacks_when_unregistered(isolated_hooks, caplog):
    router = DecisionRouter(enable_voice_responses=True)
    request = _request(DecisionType.DEBATE)

    with caplog.at_level("WARNING", logger="aragora.core.decision_router"):
        assert await router._maybe_build_decision_integrity(request, SimpleNamespace()) is None
        assert await router._maybe_build_decision_integrity(request, SimpleNamespace()) is None
    assert router._get_tts_bridge() is None
    # A default package that cannot be built is reported once, not dropped silently.
    assert caplog.text.count("Decision integrity package not built") == 1


# Without a builder, a default debate still routes; an explicit integrity request fails
# before the debate engine is constructed.
@pytest.mark.parametrize(("integrity", "routed"), [({}, True), ({"include_plan": True}, False)])
async def test_router_debate_without_an_integrity_builder(isolated_hooks, integrity, routed):
    router, arenas = _debate_router()
    request = _request(DecisionType.DEBATE, rounds=1, agents=[], decision_integrity=integrity)

    result = await router.route(request)

    assert (result.success, len(arenas), result.decision_integrity) == (routed, int(routed), None)


async def test_router_calls_the_registered_integrity_builder_and_tts_factory(isolated_hooks):
    builder = AsyncMock(return_value={"plan": "p"})
    bridge = MagicMock()
    hooks.register_decision_integrity_builder(builder)
    hooks.register_tts_bridge_factory(lambda: bridge)
    document_store, evidence_store = object(), object()
    router = DecisionRouter(document_store=document_store, evidence_store=evidence_store)
    request = _request(DecisionType.DEBATE, decision_integrity={"notify_origin": True})
    debate_result = SimpleNamespace(debate_id="debate-1")

    payload = await router._maybe_build_decision_integrity(request, debate_result, arena="arena")

    assert payload == {"plan": "p"}
    builder.assert_awaited_once_with(
        result=debate_result,
        debate_id="debate-1",
        arena="arena",
        decision_integrity={"notify_origin": True},
        document_store=document_store,
        evidence_store=evidence_store,
        notify_origin_override=True,
    )
    assert router._get_tts_bridge() is bridge


async def test_router_writes_audit_events_through_the_registered_sink(isolated_hooks):
    sink = MagicMock()
    hooks.register_decision_audit_sink(sink)
    router, request = _quick_router("4")

    await router.route(request)

    sink.log_decision_started.assert_called_once_with(
        request_id=request.request_id,
        decision_type="quick",
        source=request.source.value,
        user_id="user-1",
        workspace_id="ws-1",
        content_preview="Run the thing",
    )
    completed = sink.log_decision_completed.call_args.kwargs
    assert completed["request_id"] == request.request_id
    assert completed["success"] is True
    assert completed["confidence"] == 0.7
    assert completed["error"] is None


async def test_router_routes_without_an_audit_sink(isolated_hooks, caplog):
    router, request = _quick_router("ok")

    with caplog.at_level("WARNING", logger="aragora.core.decision_router"):
        result = await router.route(request)
        await router.route(request)

    assert result.success is True
    assert result.answer == "ok"
    assert caplog.text.count("Routing decisions without an audit trail") == 1


# ---------------------------------------------------------------------------
# aragora/core holds no import of these packages (any scope, importlib, text)
# ---------------------------------------------------------------------------


def _module_name(node: ast.ImportFrom, path: Path) -> str:
    if node.level == 0:
        return node.module or ""
    package = path.relative_to(REPO_ROOT).with_suffix("").parts[: -node.level]
    return ".".join([*package, node.module] if node.module else package)


def _forbidden(name: str) -> bool:
    return any(
        name == f"aragora.{p}" or name.startswith(f"aragora.{p}.") for p in FORBIDDEN_PACKAGES
    )


def test_core_has_no_import_of_upper_packages_at_any_scope():
    offenders = []
    for path in sorted(CORE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [_module_name(node, path)]
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                callee = getattr(func, "attr", None) or getattr(func, "id", None)
                first = node.args[0]
                if callee in {"import_module", "__import__"} and isinstance(first, ast.Constant):
                    names = [str(first.value)]
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {n}" for n in names if _forbidden(n)
            ]
    assert offenders == []


def test_core_source_text_names_no_upper_package_import():
    pattern = re.compile(
        rf"(from|import) aragora\.({_FORBIDDEN_RE})|"
        rf"(import_module|__import__)\(\s*['\"]aragora\.({_FORBIDDEN_RE})"
    )
    hits = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for path in sorted(CORE_DIR.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []

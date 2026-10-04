"""Characterization of the decision router registration hooks.

``aragora.core`` (domain layer) must not import the pipeline, connectors, audit or
server packages. The pipeline and chat connector packages register their
decision-router behaviour from their own package init, the server registers the
audit sink through ``aragora.server.decision_routes``, and the router looks each
hook up at call time.
"""

from __future__ import annotations

import ast
import re
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
FORBIDDEN_PACKAGES = ("audit", "connectors", "pipeline", "server")
_FORBIDDEN_RE = "|".join(FORBIDDEN_PACKAGES)


@pytest.fixture
def isolated_hooks(monkeypatch):
    """Run a test against an empty registry; the process-wide one is restored afterwards."""
    # A package init that first runs inside the swap would register into the temporary
    # registry only, so load the self-registering packages before swapping.
    import aragora.connectors.chat  # noqa: F401
    import aragora.pipeline  # noqa: F401

    monkeypatch.setattr(hooks, "_hooks", {})
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


async def test_router_optional_hooks_keep_their_fallbacks_when_unregistered(isolated_hooks, caplog):
    router = DecisionRouter(enable_voice_responses=True)
    request = _request(DecisionType.DEBATE, decision_integrity={"include_plan": True})

    with caplog.at_level("WARNING", logger="aragora.core.decision_router"):
        assert await router._maybe_build_decision_integrity(request, SimpleNamespace()) is None
    assert router._get_tts_bridge() is None
    # A requested integrity package that cannot be built is reported, not dropped silently.
    assert "Decision integrity was requested but cannot be built" in caplog.text


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


async def test_router_routes_without_an_audit_sink(isolated_hooks, monkeypatch, caplog):
    from aragora.core import decision_router as router_module

    monkeypatch.setattr(router_module, "_warned_missing_audit_sink", False)
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

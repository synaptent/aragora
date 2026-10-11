"""Characterization of the decision router's workflow and gauntlet route targets.

``aragora.core`` (domain layer) must not import the workflow or gauntlet packages.
Each registers its route target from its own package init, and the router looks the
target up when it routes a decision of that type.
"""

from __future__ import annotations

import json
import os
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


@pytest.fixture
def isolated_routes(monkeypatch):
    """Run a test against an empty route registry; the process-wide one is restored afterwards."""
    # A package init that first runs inside the swap would register into the temporary
    # registry only, so load the self-registering packages before swapping.
    import aragora.gauntlet  # noqa: F401
    import aragora.workflow  # noqa: F401

    monkeypatch.setattr(hooks, "_route_targets", {})
    # Treat the declared registrations as already run, so a miss stays a miss.
    monkeypatch.setattr(hooks, "_declared_registrations_loaded", True)
    return hooks


def _request(decision_type: DecisionType, **config) -> DecisionRequest:
    return DecisionRequest(
        content="Run the thing",
        decision_type=decision_type,
        config=DecisionConfig(**config),
        context=RequestContext(user_id="user-1", workspace_id="ws-1"),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_unregistered_route_target_raises(isolated_routes):
    with pytest.raises(hooks.DecisionRouteNotRegisteredError, match="workflow"):
        hooks.get_route_target(hooks.ROUTE_WORKFLOW)
    with pytest.raises(hooks.DecisionRouteNotRegisteredError, match="gauntlet"):
        hooks.get_route_target(hooks.ROUTE_GAUNTLET)
    assert hooks.get_registered_routes() == {}


def test_reregistering_a_route_replaces_instead_of_duplicating(isolated_routes):
    first, second = AsyncMock(), AsyncMock()

    hooks.register_route_target("workflow", first)
    hooks.register_route_target("workflow", first)
    assert hooks.get_registered_routes() == {"workflow": first}
    hooks.register_route_target("workflow", second)
    assert hooks.get_registered_routes() == {"workflow": second}


def test_registered_routes_is_a_snapshot(isolated_routes):
    snapshot = hooks.get_registered_routes()
    snapshot["workflow"] = AsyncMock()
    assert hooks.get_registered_routes() == {}


def test_decision_router_reexports_the_registry_accessors():
    import aragora.core.decision_router as dr

    assert dr.get_registered_routes is hooks.get_registered_routes
    assert dr.register_route_target is hooks.register_route_target


# ---------------------------------------------------------------------------
# Upper packages register from their own init
# ---------------------------------------------------------------------------


def test_fresh_interpreter_registers_routes_only_through_upper_package_inits():
    code = """
        import importlib, json, sys
        import aragora.core.decision_router as dr
        before = sorted(dr.get_registered_routes())
        upper_loaded = sorted(
            name for name in ("aragora.workflow", "aragora.gauntlet") if name in sys.modules
        )
        import aragora.workflow, aragora.gauntlet
        routes = dr.get_registered_routes()
        after = {key: f"{fn.__module__}.{fn.__qualname__}" for key, fn in routes.items()}
        importlib.reload(aragora.workflow)
        importlib.reload(aragora.gauntlet)
        print(json.dumps({
            "before": before,
            "upper_loaded": upper_loaded,
            "after": after,
            "reloaded": sorted(dr.get_registered_routes()),
        }))
    """
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
        "AWS_EC2_METADATA_DISABLED": "true",
        "ARAGORA_SECRETS_STRICT": "false",
    }
    proc = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["before"] == []
    assert out["upper_loaded"] == []
    assert out["after"] == {
        "gauntlet": "aragora.gauntlet.decision_route.route_gauntlet_decision",
        "workflow": "aragora.workflow.decision_route.route_workflow_decision",
    }
    assert out["reloaded"] == ["gauntlet", "workflow"]


def test_pyproject_declares_the_server_registration_entry_point():
    tomllib = pytest.importorskip("tomllib")
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    declared = project.get("entry-points", {}).get("aragora.decision_routes")

    assert declared == {"server": "aragora.server.decision_routes:register_decision_routes"}


def test_core_only_caller_routes_through_the_declared_registrations(tmp_path):
    # The caller imports only aragora.core; the first lookup that finds nothing runs the
    # registrations declared under the aragora.decision_routes entry-point group.
    code = """
        import asyncio, json, sys
        from types import SimpleNamespace

        from aragora.core import decision_route_hooks as hooks
        from aragora.core.decision import (
            DecisionConfig,
            DecisionRequest,
            DecisionRouter,
            DecisionType,
        )

        UPPER = ("aragora.gauntlet", "aragora.pipeline", "aragora.server", "aragora.workflow")
        upper_before = sorted(name for name in UPPER if name in sys.modules)

        class StubArena:
            def __init__(self, **_kwargs):
                pass

            async def run(self):
                return SimpleNamespace(
                    final_answer="Use LRU", consensus_reached=True, debate_id="debate-1"
                )

        async def run_gauntlet(config):
            return SimpleNamespace(verdict=None, confidence=0.6)

        def request(decision_type, **config):
            return DecisionRequest(
                content="Run the thing",
                decision_type=decision_type,
                config=DecisionConfig(**config),
            )

        def router(**engines):
            return DecisionRouter(enable_caching=False, enable_deduplication=False, **engines)

        async def main():
            # No workflow id: the workflow target is reached and rejects the request.
            workflow = await router(workflow_engine=object()).route(
                request(DecisionType.WORKFLOW)
            )
            gauntlet = await router(
                gauntlet_engine=SimpleNamespace(run=run_gauntlet)
            ).route(request(DecisionType.GAUNTLET))
            debate = await router(debate_engine=StubArena).route(
                request(
                    DecisionType.DEBATE,
                    rounds=1,
                    agents=[],
                    decision_integrity={"include_plan": True},
                )
            )
            return workflow, gauntlet, debate

        workflow, gauntlet, debate = asyncio.run(main())
        print(json.dumps({
            "upper_before": upper_before,
            "workflow": [workflow.success, workflow.error],
            "gauntlet": [gauntlet.success, gauntlet.error],
            "debate": [debate.success, debate.error, type(debate.decision_integrity).__name__],
            "hooks": {
                "workflow": hooks.get_route_target(hooks.ROUTE_WORKFLOW).__module__,
                "gauntlet": hooks.get_route_target(hooks.ROUTE_GAUNTLET).__module__,
                "integrity": hooks.get_decision_integrity_builder().__module__,
                "tts": hooks.get_tts_bridge_factory().__module__,
                "audit": type(hooks.get_decision_audit_sink()).__module__,
            },
        }))
    """
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
        [sys.executable, "-W", "ignore", "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["upper_before"] == []
    assert out["workflow"] == [False, "Decision routing failed: ValueError"]
    assert out["gauntlet"] == [True, None]
    assert out["debate"] == [True, None, "dict"]
    assert out["hooks"] == {
        "workflow": "aragora.workflow.decision_route",
        "gauntlet": "aragora.gauntlet.decision_route",
        "integrity": "aragora.pipeline.decision_integrity_utils",
        "tts": "aragora.connectors.chat.tts_bridge",
        "audit": "aragora.server.decision_routes",
    }


def test_upper_package_inits_register_their_targets():
    import aragora.gauntlet  # noqa: F401
    import aragora.workflow  # noqa: F401
    from aragora.gauntlet.decision_route import route_gauntlet_decision
    from aragora.workflow.decision_route import route_workflow_decision

    routes = hooks.get_registered_routes()
    assert routes[hooks.ROUTE_WORKFLOW] is route_workflow_decision
    assert routes[hooks.ROUTE_GAUNTLET] is route_gauntlet_decision


def test_server_registration_installs_the_route_targets(isolated_routes):
    from aragora.server import decision_routes

    decision_routes.register_decision_routes()
    decision_routes.register_decision_routes()

    assert sorted(hooks.get_registered_routes()) == ["gauntlet", "workflow"]


# ---------------------------------------------------------------------------
# Router dispatch
# ---------------------------------------------------------------------------


async def test_router_dispatches_workflow_and_gauntlet_to_registered_targets(isolated_routes):
    calls = []

    def make_target(kind: DecisionType):
        async def target(router, request, span):
            calls.append((kind, router, request))
            return DecisionResult(
                request_id=request.request_id,
                decision_type=kind,
                answer=f"{kind.value} answer",
                confidence=0.5,
                consensus_reached=True,
            )

        return target

    hooks.register_route_target(hooks.ROUTE_WORKFLOW, make_target(DecisionType.WORKFLOW))
    hooks.register_route_target(hooks.ROUTE_GAUNTLET, make_target(DecisionType.GAUNTLET))
    router = DecisionRouter(enable_caching=False, enable_deduplication=False)

    workflow_request = _request(DecisionType.WORKFLOW, workflow_id="wf-1")
    gauntlet_request = _request(DecisionType.GAUNTLET)
    workflow_result = await router.route(workflow_request)
    gauntlet_result = await router.route(gauntlet_request)

    assert workflow_result.answer == "workflow answer"
    assert gauntlet_result.answer == "gauntlet answer"
    assert calls == [
        (DecisionType.WORKFLOW, router, workflow_request),
        (DecisionType.GAUNTLET, router, gauntlet_request),
    ]


async def test_router_fails_explicitly_when_a_route_is_not_registered(isolated_routes):
    router = DecisionRouter(enable_caching=False, enable_deduplication=False)
    request = _request(DecisionType.WORKFLOW, workflow_id="wf-1")

    with pytest.raises(hooks.DecisionRouteNotRegisteredError):
        await router._route_to_workflow(request)
    with pytest.raises(hooks.DecisionRouteNotRegisteredError):
        await router._route_to_gauntlet(_request(DecisionType.GAUNTLET))

    result = await router.route(request)
    assert result.success is False
    # The result names what to load, not only the exception type.
    assert result.error.startswith(
        "Decision routing failed: DecisionRouteNotRegisteredError: "
        "No decision route registered for 'workflow'; the aragora.workflow package"
    )
    assert "aragora.decision_routes" in result.error


# ---------------------------------------------------------------------------
# Upper-package targets keep the previous engine behaviour
# ---------------------------------------------------------------------------


async def test_workflow_target_executes_the_stored_definition(monkeypatch):
    from aragora.workflow import decision_route

    engine = MagicMock()
    engine.execute = AsyncMock(
        return_value=SimpleNamespace(success=True, final_output={"answer": "done"})
    )
    store = MagicMock()
    store.get_workflow.return_value = {"id": "wf-1"}
    monkeypatch.setattr(decision_route, "get_workflow_store", lambda: store)
    router = DecisionRouter(workflow_engine=engine)
    request = _request(DecisionType.WORKFLOW, workflow_id="wf-1", workflow_inputs={"k": "v"})
    request.context.metadata = {"document_ids": ["doc-1"]}
    span = MagicMock()

    result = await decision_route.route_workflow_decision(router, request, span)

    assert (result.answer, result.confidence, result.consensus_reached) == ("done", 0.9, True)
    assert result.decision_type is DecisionType.WORKFLOW
    store.get_workflow.assert_called_once_with("wf-1")
    inputs = engine.execute.call_args.kwargs["inputs"]
    assert inputs["content"] == "Run the thing"
    assert inputs["documents"] == ["doc-1"]
    assert inputs["k"] == "v"
    span.set_attribute.assert_any_call("workflow.id", "wf-1")
    span.set_attribute.assert_any_call("workflow.success", True)


async def test_workflow_target_creates_and_caches_the_engine(monkeypatch):
    from aragora.workflow import decision_route

    engine = MagicMock()
    engine.execute = AsyncMock(return_value=SimpleNamespace(success=False, final_output=None))
    store = MagicMock()
    store.get_workflow = AsyncMock(return_value={"id": "wf-1"})
    monkeypatch.setattr(decision_route, "get_workflow_engine", lambda: engine)
    monkeypatch.setattr(decision_route, "get_workflow_store", lambda: store)
    router = DecisionRouter()

    result = await decision_route.route_workflow_decision(
        router, _request(DecisionType.WORKFLOW, workflow_id="wf-1"), None
    )

    assert router.workflow_engine is engine
    assert (result.answer, result.confidence, result.consensus_reached) == ("", 0.0, False)


async def test_workflow_target_requires_a_workflow_id():
    from aragora.workflow import decision_route

    router = DecisionRouter(workflow_engine=MagicMock())
    with pytest.raises(ValueError, match="Workflow ID required"):
        await decision_route.route_workflow_decision(router, _request(DecisionType.WORKFLOW), None)


async def test_gauntlet_target_maps_the_verdict():
    from aragora.gauntlet import decision_route
    from aragora.gauntlet.orchestrator import Verdict

    engine = MagicMock()
    engine.run = AsyncMock(return_value=SimpleNamespace(verdict=Verdict.PASS, confidence=0.8))
    router = DecisionRouter(gauntlet_engine=engine)
    request = _request(DecisionType.GAUNTLET, enable_adversarial=True)

    result = await decision_route.route_gauntlet_decision(router, request, None)

    assert (result.answer, result.confidence, result.consensus_reached) == (
        Verdict.PASS.value,
        0.8,
        True,
    )
    config = engine.run.call_args.kwargs["config"]
    assert config.input_content == "Run the thing"
    assert config.enable_redteam is True

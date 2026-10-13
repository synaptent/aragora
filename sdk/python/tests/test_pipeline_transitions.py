"""Regression tests for the pipeline transitions namespace."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from aragora_sdk.namespaces.pipeline_transitions import (
    AsyncPipelineTransitionsAPI,
    PipelineTransitionsAPI,
)

_LIVE_METHOD_NAMES = (
    "ideas_to_goals",
    "goals_to_tasks",
    "tasks_to_workflow",
    "execute",
)

_V2_METHOD_CASES = (
    pytest.param("transition", ("pipeline-1", "item-1", "goals"), id="transition"),
    pytest.param("get_history", ("pipeline-1", "item-1"), id="get-history"),
    pytest.param("validate", ("pipeline-1", "item-1", "goals"), id="validate"),
    pytest.param("available", ("pipeline-1", "item-1"), id="available"),
    pytest.param("rollback", ("pipeline-1", "item-1", "ideas"), id="rollback"),
)

_V2_SIGNATURES = {
    "transition": ("self", "pipeline_id", "item_id", "target_stage"),
    "get_history": ("self", "pipeline_id", "item_id"),
    "validate": ("self", "pipeline_id", "item_id", "target_stage"),
    "available": ("self", "pipeline_id", "item_id"),
    "rollback": ("self", "pipeline_id", "item_id", "target_stage"),
}

_V1_METHOD_CASES = (
    pytest.param(
        "ideas_to_goals",
        ([{"id": "idea-1", "label": "Ship it"}],),
        {"context": "Quarterly planning"},
        call(
            "POST",
            "/api/v1/pipeline/transitions/ideas-to-goals",
            json={
                "ideas": [{"id": "idea-1", "label": "Ship it"}],
                "context": "Quarterly planning",
            },
        ),
        id="ideas-to-goals",
    ),
    pytest.param(
        "goals_to_tasks",
        ([{"id": "goal-1", "label": "Launch"}],),
        {"constraints": {"max_tasks": 3}},
        call(
            "POST",
            "/api/v1/pipeline/transitions/goals-to-tasks",
            json={
                "goals": [{"id": "goal-1", "label": "Launch"}],
                "constraints": {"max_tasks": 3},
            },
        ),
        id="goals-to-tasks",
    ),
    pytest.param(
        "tasks_to_workflow",
        ([{"id": "task-1", "label": "Deploy"}],),
        {"execution_mode": "sequential"},
        call(
            "POST",
            "/api/v1/pipeline/transitions/tasks-to-workflow",
            json={
                "tasks": [{"id": "task-1", "label": "Deploy"}],
                "execution_mode": "sequential",
            },
        ),
        id="tasks-to-workflow",
    ),
    pytest.param(
        "execute",
        (
            "workflow-1",
            [{"id": "node-1"}],
            [{"source": "node-1", "target": "node-2"}],
        ),
        {"dry_run": True},
        call(
            "POST",
            "/api/v1/pipeline/transitions/execute",
            json={
                "workflow_id": "workflow-1",
                "nodes": [{"id": "node-1"}],
                "edges": [{"source": "node-1", "target": "node-2"}],
                "dry_run": True,
            },
        ),
        id="execute",
    ),
    pytest.param(
        "get_provenance",
        ("node-1",),
        {},
        call("GET", "/api/v1/pipeline/transitions/node-1/provenance"),
        id="get-provenance",
    ),
)


@pytest.mark.parametrize(("method_name", "args"), _V2_METHOD_CASES)
def test_sync_v2_methods_fail_before_request(
    method_name: str,
    args: tuple[str, ...],
) -> None:
    request = MagicMock(side_effect=AssertionError("HTTP request attempted"))
    client = MagicMock()
    client.request = request
    api = PipelineTransitionsAPI(client)

    with pytest.raises(NotImplementedError) as exc_info:
        getattr(api, method_name)(*args)

    request.assert_not_called()
    assert f"{method_name}()" in str(exc_info.value)
    assert "no live v2 pipeline-transition endpoint" in str(exc_info.value)
    for live_method_name in _LIVE_METHOD_NAMES:
        assert f"{live_method_name}()" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method_name", "args"), _V2_METHOD_CASES)
async def test_async_v2_methods_fail_before_request(
    method_name: str,
    args: tuple[str, ...],
) -> None:
    request = AsyncMock(side_effect=AssertionError("HTTP request attempted"))
    client = MagicMock()
    client.request = request
    api = AsyncPipelineTransitionsAPI(client)

    with pytest.raises(NotImplementedError) as exc_info:
        await getattr(api, method_name)(*args)

    request.assert_not_awaited()
    assert f"{method_name}()" in str(exc_info.value)
    assert "no live v2 pipeline-transition endpoint" in str(exc_info.value)
    for live_method_name in _LIVE_METHOD_NAMES:
        assert f"{live_method_name}()" in str(exc_info.value)


@pytest.mark.parametrize(("method_name", "parameter_names"), _V2_SIGNATURES.items())
@pytest.mark.parametrize("api_class", (PipelineTransitionsAPI, AsyncPipelineTransitionsAPI))
def test_v2_method_signatures_remain_stable(
    api_class: type[PipelineTransitionsAPI] | type[AsyncPipelineTransitionsAPI],
    method_name: str,
    parameter_names: tuple[str, ...],
) -> None:
    signature = inspect.signature(getattr(api_class, method_name))

    assert tuple(signature.parameters) == parameter_names


@pytest.mark.parametrize(("method_name", "args", "kwargs", "expected_call"), _V1_METHOD_CASES)
def test_sync_v1_methods_keep_existing_requests(
    method_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    expected_call: Any,
) -> None:
    request = MagicMock(return_value={"ok": True})
    client = MagicMock()
    client.request = request
    api = PipelineTransitionsAPI(client)

    result = getattr(api, method_name)(*args, **kwargs)

    assert result == {"ok": True}
    assert request.call_args == expected_call


@pytest.mark.asyncio
@pytest.mark.parametrize(("method_name", "args", "kwargs", "expected_call"), _V1_METHOD_CASES)
async def test_async_v1_methods_keep_existing_requests(
    method_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    expected_call: Any,
) -> None:
    request = AsyncMock(return_value={"ok": True})
    client = MagicMock()
    client.request = request
    api = AsyncPipelineTransitionsAPI(client)

    result = await getattr(api, method_name)(*args, **kwargs)

    assert result == {"ok": True}
    assert request.call_args == expected_call

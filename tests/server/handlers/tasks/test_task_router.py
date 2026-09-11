"""Tests for task routing in the task execution handler."""

import pytest

from aragora.server.handlers.tasks.execution import (
    VALID_TASK_TYPES,
    TaskRoute,
    TaskRouter,
)


class TestTaskRoute:
    """Tests for TaskRoute dataclass."""

    def test_defaults(self):
        route = TaskRoute(task_type="test", workflow_steps=[{"id": "s1"}])
        assert route.task_type == "test"
        assert route.workflow_steps == [{"id": "s1"}]
        assert route.required_capabilities == []
        assert route.description == ""

    def test_with_all_fields(self):
        route = TaskRoute(
            task_type="debate",
            workflow_steps=[{"id": "s1", "type": "debate"}],
            required_capabilities=["reasoning"],
            description="A debate route",
        )
        assert route.task_type == "debate"
        assert route.required_capabilities == ["reasoning"]
        assert route.description == "A debate route"

    def test_workflow_steps_preserved(self):
        steps = [
            {"id": "a", "type": "debate", "config": {"rounds": 3}},
            {"id": "b", "type": "verify"},
        ]
        route = TaskRoute(task_type="multi", workflow_steps=steps)
        assert len(route.workflow_steps) == 2
        assert route.workflow_steps[0]["config"]["rounds"] == 3


class TestTaskRouter:
    """Tests for TaskRouter."""

    def test_default_routes_registered(self):
        router = TaskRouter()
        for task_type in VALID_TASK_TYPES:
            assert task_type in router.registered_types

    def test_registered_types_sorted(self):
        router = TaskRouter()
        types = router.registered_types
        assert types == sorted(types)

    def test_route_debate(self):
        router = TaskRouter()
        route = router.route("debate", "Test goal", {})
        assert route.task_type == "debate"
        assert len(route.workflow_steps) == 1
        assert route.workflow_steps[0]["type"] == "debate"
        assert "debate" in route.required_capabilities

    def test_route_code_edit(self):
        router = TaskRouter()
        route = router.route("code_edit", "Fix bug", {})
        assert route.task_type == "code_edit"
        assert len(route.workflow_steps) == 3
        step_types = [s["type"] for s in route.workflow_steps]
        assert "analysis" in step_types
        assert "implementation" in step_types
        assert "verification" in step_types

    def test_route_computer_use(self):
        router = TaskRouter()
        route = router.route("computer_use", "Browse web", {})
        assert route.task_type == "computer_use"
        assert "computer_use" in route.required_capabilities

    def test_route_analysis(self):
        router = TaskRouter()
        route = router.route("analysis", "Analyze data", {})
        assert route.task_type == "analysis"
        assert "analysis" in route.required_capabilities

    def test_route_composite(self):
        router = TaskRouter()
        route = router.route("composite", "Multi-step task", {})
        assert route.task_type == "composite"
        assert len(route.workflow_steps) == 3

    def test_route_unknown_type_falls_back(self):
        router = TaskRouter()
        route = router.route("unknown_type", "Something", {})
        assert route.task_type == "unknown_type"
        assert route.workflow_steps[0]["id"] == "fallback_debate_step"
        assert route.workflow_steps[0]["type"] == "debate"
        assert "reasoning" in route.required_capabilities

    def test_route_empty_type_raises(self):
        router = TaskRouter()
        with pytest.raises(ValueError, match="must not be empty"):
            router.route("", "Goal", {})

    def test_route_none_type_raises(self):
        router = TaskRouter()
        with pytest.raises(ValueError, match="must not be empty"):
            router.route(None, "Goal", {})

    def test_register_custom_route(self):
        router = TaskRouter()
        custom = TaskRoute(
            task_type="custom_task",
            workflow_steps=[{"id": "custom_step", "type": "custom"}],
            required_capabilities=["custom_cap"],
            description="A custom route",
        )
        router.register(custom)
        assert "custom_task" in router.registered_types
        result = router.route("custom_task", "Do custom thing", {})
        assert result is custom

    def test_register_overwrites_existing(self):
        router = TaskRouter()
        original = router.route("debate", "Goal", {})
        assert len(original.workflow_steps) == 1

        new_route = TaskRoute(
            task_type="debate",
            workflow_steps=[{"id": "new1"}, {"id": "new2"}],
        )
        router.register(new_route)

        result = router.route("debate", "Goal", {})
        assert len(result.workflow_steps) == 2
        assert result.workflow_steps[0]["id"] == "new1"

    def test_get_route_returns_registered(self):
        router = TaskRouter()
        route = router.get_route("debate")
        assert route is not None
        assert route.task_type == "debate"

    def test_get_route_returns_none_for_unknown(self):
        router = TaskRouter()
        assert router.get_route("nonexistent") is None

    def test_fallback_route_description_contains_type(self):
        router = TaskRouter()
        route = router.route("my_special_task", "Goal", {})
        assert "my_special_task" in route.description

"""
Tests for Workflow Task Node.

Tests cover:
- Task handler registry (register, get)
- TaskStep initialization
- Function execution (sync and async)
- HTTP call execution (GET, POST, errors, timeouts)
- Transform operations (expressions, output formats)
- Validation logic (types, ranges, patterns, custom expressions)
- Result aggregation (merge, list, first_valid)
- Interpolation of variables (text, dict, nested)
- Context propagation
- Error handling
- Built-in handlers (log, set_state, delay)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Task Handler Registry Tests
# ============================================================================


class TestTaskHandlerRegistry:
    """Tests for task handler registration functions."""

    def test_register_and_get_handler(self):
        """Test registering and retrieving a handler."""
        from aragora.workflow.nodes.task import (
            register_task_handler,
            get_task_handler,
            _task_handlers,
        )

        def my_handler(context, **kwargs):
            return {"handled": True}

        test_name = "_test_handler_registry"
        try:
            register_task_handler(test_name, my_handler)
            handler = get_task_handler(test_name)
            assert handler is my_handler
        finally:
            _task_handlers.pop(test_name, None)

    def test_get_nonexistent_handler(self):
        """Test getting a nonexistent handler returns None."""
        from aragora.workflow.nodes.task import get_task_handler

        handler = get_task_handler("nonexistent_handler_xyz")
        assert handler is None

    def test_builtin_handlers_registered(self):
        """Test that built-in handlers are registered."""
        from aragora.workflow.nodes.task import get_task_handler

        assert get_task_handler("log") is not None
        assert get_task_handler("set_state") is not None
        assert get_task_handler("delay") is not None


# ============================================================================
# TaskStep Initialization Tests
# ============================================================================


class TestTaskStepInit:
    """Tests for TaskStep initialization."""

    def test_basic_init(self):
        """Test basic TaskStep initialization."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Test Task",
            config={"task_type": "function", "handler": "log"},
        )
        assert step.name == "Test Task"
        assert step.config["task_type"] == "function"

    def test_default_config(self):
        """Test TaskStep with no config."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(name="Empty Task")
        assert step.config == {}

    def test_default_task_type(self):
        """Test that default task_type is function."""
        from aragora.workflow.nodes.task import TaskStep
        from aragora.workflow.step import WorkflowContext

        step = TaskStep(name="Default Type", config={})
        # task_type will be "function" by default in execute


# ============================================================================
# Function Execution Tests
# ============================================================================


class TestFunctionExecution:
    """Tests for TaskStep function execution."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    @pytest.mark.asyncio
    async def test_sync_function_execution(self):
        """Test executing a synchronous function handler."""
        from aragora.workflow.nodes.task import TaskStep, register_task_handler, _task_handlers

        def sync_handler(context, value=0):
            return value * 2

        test_name = "_test_sync_handler"
        try:
            register_task_handler(test_name, sync_handler)

            step = TaskStep(
                name="Sync Test",
                config={
                    "task_type": "function",
                    "handler": test_name,
                    "args": {"value": 21},
                },
            )
            ctx = self._make_context()
            result = await step.execute(ctx)
            assert result["success"] is True
            assert result["result"] == 42
        finally:
            _task_handlers.pop(test_name, None)

    @pytest.mark.asyncio
    async def test_async_function_execution(self):
        """Test executing an asynchronous function handler."""
        from aragora.workflow.nodes.task import TaskStep, register_task_handler, _task_handlers

        async def async_handler(context, message=""):
            await asyncio.sleep(0.01)
            return f"processed: {message}"

        test_name = "_test_async_handler"
        try:
            register_task_handler(test_name, async_handler)

            step = TaskStep(
                name="Async Test",
                config={
                    "task_type": "function",
                    "handler": test_name,
                    "args": {"message": "hello"},
                },
            )
            ctx = self._make_context()
            result = await step.execute(ctx)
            assert result["success"] is True
            assert result["result"] == "processed: hello"
        finally:
            _task_handlers.pop(test_name, None)

    @pytest.mark.asyncio
    async def test_missing_handler_error(self):
        """Test that missing handler returns error."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Missing Handler",
            config={
                "task_type": "function",
                "handler": "nonexistent_handler_xyz",
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)
        assert result["success"] is False
        assert "Handler not found" in result["error"]

    @pytest.mark.asyncio
    async def test_legacy_action_maps_to_handler(self):
        """Legacy action config should resolve to built-in handlers."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Legacy Action",
            config={
                "task_type": "function",
                "action": "log",
                "message": "hello from legacy action",
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"]["logged"] is True

    @pytest.mark.asyncio
    async def test_legacy_set_state_action_populates_context(self):
        """Legacy set_state action should map state dict into context state."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Legacy Set State",
            config={
                "task_type": "function",
                "action": "set_state",
                "state": {"score": 85, "decision": True},
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is True
        assert ctx.state["score"] == 85
        assert ctx.state["decision"] is True

    @pytest.mark.asyncio
    async def test_function_with_interpolated_args(self):
        """Test function execution with interpolated arguments."""
        from aragora.workflow.nodes.task import TaskStep, register_task_handler, _task_handlers

        def echo_handler(context, data=None):
            return data

        test_name = "_test_interp_handler"
        try:
            register_task_handler(test_name, echo_handler)

            step = TaskStep(
                name="Interp Test",
                config={
                    "task_type": "function",
                    "handler": test_name,
                    "args": {"data": "{user_input}"},
                },
            )
            ctx = self._make_context(inputs={"user_input": "test_value"})
            result = await step.execute(ctx)
            assert result["success"] is True
            assert result["result"] == "test_value"
        finally:
            _task_handlers.pop(test_name, None)


# ============================================================================
# HTTP Execution Tests
# ============================================================================


class TestHTTPExecution:
    """Tests for TaskStep HTTP execution."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    def _make_mock_pool(self, mock_client):
        """Build a mock HTTPClientPool whose get_session yields *mock_client*."""
        from contextlib import asynccontextmanager

        mock_pool = MagicMock()

        @asynccontextmanager
        async def _get_session(provider):
            yield mock_client

        mock_pool.get_session = _get_session
        return mock_pool

    @pytest.mark.asyncio
    async def test_http_get_success(self):
        """Test successful HTTP GET request."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="HTTP GET",
            config={
                "task_type": "http",
                "url": "https://api.example.com/data",
                "method": "GET",
            },
        )
        ctx = self._make_context()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"key": "value"}'
        mock_response.headers = {"Content-Type": "application/json"}

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=self._make_mock_pool(mock_client),
        ):
            result = await step.execute(ctx)

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["response"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_http_post_with_body(self):
        """Test HTTP POST request with body."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="HTTP POST",
            config={
                "task_type": "http",
                "url": "https://api.example.com/create",
                "method": "POST",
                "body": {"name": "{user_name}", "action": "create"},
                "headers": {"Authorization": "Bearer {api_token}"},
            },
        )
        ctx = self._make_context(inputs={"user_name": "John", "api_token": "secret123"})

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = '{"id": "123"}'
        mock_response.headers = {"Content-Type": "application/json"}

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=self._make_mock_pool(mock_client),
        ):
            result = await step.execute(ctx)

        assert result["success"] is True
        assert result["status_code"] == 201
        # Verify the request was made with interpolated values
        call_kwargs = mock_client.request.call_args
        assert call_kwargs[0][0] == "POST"

    @pytest.mark.asyncio
    async def test_http_error_status(self):
        """Test HTTP request returning error status."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="HTTP Error",
            config={
                "task_type": "http",
                "url": "https://api.example.com/notfound",
                "method": "GET",
            },
        )
        ctx = self._make_context()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = '{"error": "not found"}'
        mock_response.headers = {}

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=self._make_mock_pool(mock_client),
        ):
            result = await step.execute(ctx)

        assert result["success"] is False
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_http_timeout(self):
        """Test HTTP request timeout."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="HTTP Timeout",
            config={
                "task_type": "http",
                "url": "https://api.example.com/slow",
                "method": "GET",
                "timeout_seconds": 5,
            },
        )
        ctx = self._make_context()

        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=self._make_mock_pool(mock_client),
        ):
            result = await step.execute(ctx)

        assert result["success"] is False
        assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_http_connection_error(self):
        """Test HTTP connection error handling."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="HTTP Connection Error",
            config={
                "task_type": "http",
                "url": "https://api.example.com/data",
                "method": "GET",
            },
        )
        ctx = self._make_context()

        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=ConnectionError("Connection refused"))

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=self._make_mock_pool(mock_client),
        ):
            result = await step.execute(ctx)

        assert result["success"] is False
        assert result["error"] == "HTTP request failed"

    @pytest.mark.asyncio
    async def test_http_non_json_response(self):
        """Test HTTP request with non-JSON response."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="HTTP Text Response",
            config={
                "task_type": "http",
                "url": "https://api.example.com/text",
                "method": "GET",
            },
        )
        ctx = self._make_context()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Plain text response"
        mock_response.headers = {"Content-Type": "text/plain"}

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=self._make_mock_pool(mock_client),
        ):
            result = await step.execute(ctx)

        assert result["success"] is True
        assert result["response"] == "Plain text response"

    @pytest.mark.asyncio
    async def test_http_pool_unavailable(self):
        """Test HTTP task when the HTTP pool is unavailable."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="HTTP No Pool",
            config={
                "task_type": "http",
                "url": "https://api.example.com/data",
            },
        )
        ctx = self._make_context()

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            side_effect=RuntimeError("HTTPClientPool has been closed"),
        ):
            result = await step.execute(ctx)

        assert result["success"] is False
        assert result["error"] == "HTTP request failed"


# ============================================================================
# Transform Execution Tests
# ============================================================================


class TestTransformExecution:
    """Tests for TaskStep transform execution."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    @pytest.mark.asyncio
    async def test_simple_transform(self):
        """Test simple data transformation."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform",
            config={
                "task_type": "transform",
                "transform": "len(inputs['items'])",
            },
        )
        ctx = self._make_context(inputs={"items": [1, 2, 3, 4, 5]})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == 5

    @pytest.mark.asyncio
    async def test_transform_list_comprehension(self):
        """Test transform with list comprehension."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform List",
            config={
                "task_type": "transform",
                "transform": "[x * 2 for x in inputs['numbers']]",
            },
        )
        ctx = self._make_context(inputs={"numbers": [1, 2, 3]})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_transform_output_format_list(self):
        """Test transform with list output format."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform to List",
            config={
                "task_type": "transform",
                "transform": "range(3)",
                "output_format": "list",
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_transform_output_format_json(self):
        """Test transform with JSON output format."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform to JSON",
            config={
                "task_type": "transform",
                "transform": "{'key': inputs['value']}",
                "output_format": "json",
            },
        )
        ctx = self._make_context(inputs={"value": "test"})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == '{"key": "test"}'

    @pytest.mark.asyncio
    async def test_transform_output_format_text(self):
        """Test transform with text output format."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform to Text",
            config={
                "task_type": "transform",
                "transform": "sum(inputs['numbers'])",
                "output_format": "text",
            },
        )
        ctx = self._make_context(inputs={"numbers": [1, 2, 3]})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == "6"

    @pytest.mark.asyncio
    async def test_transform_no_expression_error(self):
        """Test transform with no expression returns error."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform Empty",
            config={
                "task_type": "transform",
                "transform": "",
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is False
        assert "No transform expression" in result["error"]

    @pytest.mark.asyncio
    async def test_transform_invalid_expression(self):
        """Test transform with invalid expression."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform Invalid",
            config={
                "task_type": "transform",
                "transform": "undefined_var + 1",
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is False
        assert "Transform failed" in result["error"]

    @pytest.mark.asyncio
    async def test_transform_access_step_outputs(self):
        """Test transform can access previous step outputs."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform with Step Output",
            config={
                "task_type": "transform",
                "transform": "outputs['prev_step']['count'] * 2",
            },
        )
        ctx = self._make_context(step_outputs={"prev_step": {"count": 5}})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == 10

    @pytest.mark.asyncio
    async def test_transform_step_output_as_namespace_var(self):
        """Test transform can access step outputs as direct variables."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform Step Var",
            config={
                "task_type": "transform",
                "transform": "prev_step['count'] + 3",
            },
        )
        ctx = self._make_context(step_outputs={"prev_step": {"count": 7}})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == 10

    @pytest.mark.asyncio
    async def test_transform_with_hyphenated_step_id(self):
        """Test transform handles hyphenated step IDs."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform Hyphen",
            config={
                "task_type": "transform",
                "transform": "prev_step_1['value']",
            },
        )
        ctx = self._make_context(step_outputs={"prev-step-1": {"value": "test"}})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == "test"


# ============================================================================
# Validation Execution Tests
# ============================================================================


class TestValidationExecution:
    """Tests for TaskStep validation execution."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    @pytest.mark.asyncio
    async def test_validation_required_field_present(self):
        """Test validation passes when required field is present."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Required",
            config={
                "task_type": "validate",
                "validation": {"name": {"required": True}},
            },
        )
        ctx = self._make_context(inputs={"name": "John"})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_validation_required_field_missing(self):
        """Test validation fails when required field is missing."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Required Missing",
            config={
                "task_type": "validate",
                "validation": {"name": {"required": True}},
            },
        )
        ctx = self._make_context(inputs={})
        result = await step.execute(ctx)

        assert result["success"] is False
        assert result["valid"] is False
        assert any("required" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validation_type_check_string(self):
        """Test validation type check for string."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Type String",
            config={
                "task_type": "validate",
                "validation": {"name": {"type": "string"}},
            },
        )
        ctx = self._make_context(inputs={"name": "John"})
        result = await step.execute(ctx)

        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validation_type_check_fails(self):
        """Test validation type check fails for wrong type."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Type Wrong",
            config={
                "task_type": "validate",
                "validation": {"age": {"type": "int"}},
            },
        )
        ctx = self._make_context(inputs={"age": "not a number"})
        result = await step.execute(ctx)

        assert result["valid"] is False
        assert any("int" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validation_min_max_number(self):
        """Test validation min/max for numbers."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Range",
            config={
                "task_type": "validate",
                "validation": {"score": {"min": 0, "max": 100}},
            },
        )
        ctx = self._make_context(inputs={"score": 150})
        result = await step.execute(ctx)

        assert result["valid"] is False
        assert any("<=" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validation_string_length(self):
        """Test validation string length constraints."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Length",
            config={
                "task_type": "validate",
                "validation": {"password": {"min_length": 8, "max_length": 20}},
            },
        )
        ctx = self._make_context(inputs={"password": "abc"})
        result = await step.execute(ctx)

        assert result["valid"] is False
        assert any("at least 8" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validation_pattern_match(self):
        """Test validation pattern matching."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Pattern",
            config={
                "task_type": "validate",
                "validation": {"email": {"pattern": r"^[\w\.-]+@[\w\.-]+\.\w+$"}},
            },
        )
        ctx = self._make_context(inputs={"email": "invalid-email"})
        result = await step.execute(ctx)

        assert result["valid"] is False
        assert any("pattern" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validation_enum(self):
        """Test validation enum constraint."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Enum",
            config={
                "task_type": "validate",
                "validation": {"status": {"enum": ["pending", "approved", "rejected"]}},
            },
        )
        ctx = self._make_context(inputs={"status": "unknown"})
        result = await step.execute(ctx)

        assert result["valid"] is False
        assert any("must be one of" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validation_custom_expression(self):
        """Test validation with custom expression."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Expression",
            config={
                "task_type": "validate",
                "validation": {
                    "end_date": {
                        "expression": "value > data['start_date']",
                        "message": "End date must be after start date",
                    }
                },
            },
        )
        ctx = self._make_context(inputs={"start_date": 100, "end_date": 50})
        result = await step.execute(ctx)

        assert result["valid"] is False
        assert any("after start date" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validation_invalid_data_expression(self):
        """Test validation with invalid data expression."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Invalid Data",
            config={
                "task_type": "validate",
                "data": "undefined_var",
                "validation": {"field": {"required": True}},
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is False
        assert "Invalid data expression" in result["error"]

    @pytest.mark.asyncio
    async def test_validation_multiple_rules(self):
        """Test validation with multiple rules."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Multiple",
            config={
                "task_type": "validate",
                "validation": {
                    "name": {"required": True, "type": "string", "min_length": 2},
                    "age": {"required": True, "type": "int", "min": 0, "max": 150},
                },
            },
        )
        ctx = self._make_context(inputs={"name": "Jo", "age": 25})
        result = await step.execute(ctx)

        assert result["valid"] is True
        assert len(result["errors"]) == 0


# ============================================================================
# Aggregate Execution Tests
# ============================================================================


class TestAggregateExecution:
    """Tests for TaskStep aggregate execution."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    @pytest.mark.asyncio
    async def test_aggregate_merge_mode(self):
        """Test aggregate with merge mode."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Aggregate Merge",
            config={
                "task_type": "aggregate",
                "inputs": ["step1", "step2"],
                "mode": "merge",
            },
        )
        ctx = self._make_context(
            step_outputs={
                "step1": {"a": 1, "b": 2},
                "step2": {"c": 3, "d": 4},
            }
        )
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == {"a": 1, "b": 2, "c": 3, "d": 4}

    @pytest.mark.asyncio
    async def test_aggregate_list_mode(self):
        """Test aggregate with list mode."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Aggregate List",
            config={
                "task_type": "aggregate",
                "inputs": ["step1", "step2"],
                "mode": "list",
            },
        )
        ctx = self._make_context(
            step_outputs={
                "step1": {"value": 1},
                "step2": {"value": 2},
            }
        )
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == [{"value": 1}, {"value": 2}]

    @pytest.mark.asyncio
    async def test_aggregate_first_valid_mode(self):
        """Test aggregate with first_valid mode."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Aggregate First Valid",
            config={
                "task_type": "aggregate",
                "inputs": ["step1", "step2", "step3"],
                "mode": "first_valid",
            },
        )
        ctx = self._make_context(
            step_outputs={
                "step1": None,
                "step2": "",
                "step3": {"valid": True},
            }
        )
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == {"valid": True}

    @pytest.mark.asyncio
    async def test_aggregate_first_valid_no_valid(self):
        """Test aggregate first_valid with no valid values."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Aggregate No Valid",
            config={
                "task_type": "aggregate",
                "inputs": ["step1", "step2"],
                "mode": "first_valid",
            },
        )
        ctx = self._make_context(
            step_outputs={
                "step1": None,
                "step2": {},
            }
        )
        result = await step.execute(ctx)

        assert result["success"] is False
        assert "No valid values" in result["error"]

    @pytest.mark.asyncio
    async def test_aggregate_all_outputs(self):
        """Test aggregate with all step outputs when inputs not specified."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Aggregate All",
            config={
                "task_type": "aggregate",
                "mode": "merge",
            },
        )
        ctx = self._make_context(
            step_outputs={
                "step1": {"x": 1},
                "step2": {"y": 2},
            }
        )
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == {"x": 1, "y": 2}


# ============================================================================
# Interpolation Tests
# ============================================================================


class TestInterpolation:
    """Tests for TaskStep interpolation methods."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    def test_interpolate_text_inputs(self):
        """Test text interpolation with workflow inputs."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(name="Interp", config={})
        ctx = self._make_context(inputs={"name": "John", "age": "30"})
        result = step._interpolate_text("Hello {name}, you are {age}", ctx)
        assert result == "Hello John, you are 30"

    def test_interpolate_text_step_outputs(self):
        """Test text interpolation with step outputs."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(name="Interp", config={})
        ctx = self._make_context(step_outputs={"prev": {"summary": "test result"}})
        result = step._interpolate_text("Result: {step.prev.summary}", ctx)
        assert result == "Result: test result"

    def test_interpolate_text_state(self):
        """Test text interpolation with state."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(name="Interp", config={})
        ctx = self._make_context(state={"counter": "5"})
        result = step._interpolate_text("Count: {state.counter}", ctx)
        assert result == "Count: 5"

    def test_interpolate_dict_nested(self):
        """Test dict interpolation with nested dicts."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(name="Interp", config={})
        ctx = self._make_context(inputs={"api_key": "secret123"})
        result = step._interpolate_dict(
            {"headers": {"Authorization": "Bearer {api_key}"}},
            ctx,
        )
        assert result["headers"]["Authorization"] == "Bearer secret123"

    def test_interpolate_dict_list(self):
        """Test dict interpolation with list values."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(name="Interp", config={})
        ctx = self._make_context(inputs={"tag1": "urgent", "tag2": "important"})
        result = step._interpolate_dict(
            {"tags": ["{tag1}", "{tag2}", "static"]},
            ctx,
        )
        assert result["tags"] == ["urgent", "important", "static"]

    def test_interpolate_dict_non_string_preserved(self):
        """Test that non-string values are preserved."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(name="Interp", config={})
        ctx = self._make_context()
        result = step._interpolate_dict(
            {"count": 5, "active": True, "ratio": 0.5},
            ctx,
        )
        assert result["count"] == 5
        assert result["active"] is True
        assert result["ratio"] == 0.5


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for TaskStep error handling."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    @pytest.mark.asyncio
    async def test_unknown_task_type(self):
        """Test handling of unknown task type."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Unknown Type",
            config={"task_type": "nonexistent_type"},
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is False
        assert "Unknown task type" in result["error"]

    @pytest.mark.asyncio
    async def test_handler_exception(self):
        """Test handling of handler exception."""
        from aragora.workflow.nodes.task import TaskStep, register_task_handler, _task_handlers

        def failing_handler(context, **kwargs):
            raise ValueError("Handler crashed")

        test_name = "_test_failing_handler"
        try:
            register_task_handler(test_name, failing_handler)

            step = TaskStep(
                name="Failing Handler",
                config={
                    "task_type": "function",
                    "handler": test_name,
                },
            )
            ctx = self._make_context()
            result = await step.execute(ctx)

            assert result["success"] is False
            assert result["error"] == "Task execution failed"
        finally:
            _task_handlers.pop(test_name, None)


# ============================================================================
# Built-in Handler Tests
# ============================================================================


class TestBuiltinHandlers:
    """Tests for built-in task handlers."""

    def _make_context(self, inputs=None, state=None, step_outputs=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
        )

    @pytest.mark.asyncio
    async def test_log_handler(self):
        """Test built-in log handler."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Log Test",
            config={
                "task_type": "function",
                "handler": "log",
                "args": {"message": "Test message", "level": "info"},
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"]["logged"] is True
        assert result["result"]["message"] == "Test message"

    @pytest.mark.asyncio
    async def test_set_state_handler(self):
        """Test built-in set_state handler."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Set State Test",
            config={
                "task_type": "function",
                "handler": "set_state",
                "args": {"key": "my_key", "value": "my_value"},
            },
        )
        ctx = self._make_context()
        result = await step.execute(ctx)

        assert result["success"] is True
        assert ctx.state["my_key"] == "my_value"

    @pytest.mark.asyncio
    async def test_delay_handler(self):
        """Test built-in delay handler."""
        from aragora.workflow.nodes.task import TaskStep
        import time

        step = TaskStep(
            name="Delay Test",
            config={
                "task_type": "function",
                "handler": "delay",
                "args": {"seconds": 0.1},
            },
        )
        ctx = self._make_context()

        start = time.time()
        result = await step.execute(ctx)
        elapsed = time.time() - start

        assert result["success"] is True
        assert result["result"]["delayed_seconds"] == 0.1
        assert elapsed >= 0.1


# ============================================================================
# Context Propagation Tests
# ============================================================================


class TestContextPropagation:
    """Tests for context propagation through TaskStep."""

    def _make_context(self, inputs=None, state=None, step_outputs=None, current_step_config=None):
        from aragora.workflow.step import WorkflowContext

        return WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs=inputs or {},
            state=state or {},
            step_outputs=step_outputs or {},
            current_step_config=current_step_config or {},
        )

    @pytest.mark.asyncio
    async def test_config_merged_with_current_step_config(self):
        """Test that step config is merged with current_step_config."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Config Merge",
            config={
                "task_type": "transform",
                "transform": "1 + 1",
            },
        )
        # Override transform via current_step_config
        ctx = self._make_context(current_step_config={"transform": "2 + 2"})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == 4  # 2 + 2, not 1 + 1

    @pytest.mark.asyncio
    async def test_context_state_accessible(self):
        """Test that context state is accessible in transforms."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="State Access",
            config={
                "task_type": "transform",
                "transform": "state['counter'] + 1",
            },
        )
        ctx = self._make_context(state={"counter": 10})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == 11

    @pytest.mark.asyncio
    async def test_context_inputs_accessible(self):
        """Test that context inputs are accessible in transforms."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Inputs Access",
            config={
                "task_type": "transform",
                "transform": "inputs['multiplier'] * inputs['value']",
            },
        )
        ctx = self._make_context(inputs={"multiplier": 3, "value": 7})
        result = await step.execute(ctx)

        assert result["success"] is True
        assert result["result"] == 21

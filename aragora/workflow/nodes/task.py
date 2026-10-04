"""
Task Step for generic task execution in workflows.

Provides a flexible task step that can execute various operations:
- Python functions
- HTTP requests
- Shell commands (sandboxed)
- Custom actions
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from collections.abc import Callable

from aragora.workflow.safe_eval import SafeEvalError, safe_eval
from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)

# Registry of task handlers
_task_handlers: dict[str, Callable] = {}


def register_task_handler(name: str, handler: Callable) -> None:
    """Register a task handler function."""
    _task_handlers[name] = handler
    logger.debug("Registered task handler: %s", name)


def get_task_handler(name: str) -> Callable | None:
    """Get a registered task handler."""
    return _task_handlers.get(name)


class TaskStep(BaseStep):
    """
    Generic task step for flexible workflow operations.

    Config options:
        task_type: str - Type of task (function, http, transform, validate, aggregate)
        handler: str - Name of registered handler (for function type)
        url: str - URL for HTTP requests (for http type)
        method: str - HTTP method (default: GET)
        headers: dict - HTTP headers
        body: dict - HTTP request body (can use {placeholder} syntax)
        transform: str - Python expression for data transformation
        validation: dict - Validation rules
        inputs: list[str] - Input step IDs to aggregate
        output_format: str - Format of output (json, text, list)

    Task Types:
        - function: Execute a registered Python function
        - http: Make an HTTP request
        - transform: Transform data using expressions
        - validate: Validate data against rules
        - aggregate: Combine outputs from multiple steps

    Usage:
        # Transform task
        step = TaskStep(
            name="Extract Key Points",
            config={
                "task_type": "transform",
                "transform": "[p['content'] for p in inputs.paragraphs if p.get('important')]",
                "output_format": "list",
            }
        )

        # HTTP task
        step = TaskStep(
            name="Notify Webhook",
            config={
                "task_type": "http",
                "url": "https://api.example.com/webhook",
                "method": "POST",
                "headers": {"Authorization": "Bearer {api_token}"},
                "body": {"result": "{step.analysis.summary}"},
            }
        )
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)

    async def execute(self, context: WorkflowContext) -> Any:
        """Execute the task step."""
        config = {**self._config, **context.current_step_config}
        task_type = config.get("task_type", "function")

        try:
            if task_type == "function":
                return await self._execute_function(config, context)
            elif task_type == "http":
                return await self._execute_http(config, context)
            elif task_type == "transform":
                return await self._execute_transform(config, context)
            elif task_type == "validate":
                return await self._execute_validate(config, context)
            elif task_type == "aggregate":
                return await self._execute_aggregate(config, context)
            else:
                return {"success": False, "error": f"Unknown task type: {task_type}"}

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, ImportError) as e:
            logger.error("Task execution failed: %s", e)
            return {"success": False, "error": "Task execution failed"}

    async def _execute_function(self, config: dict[str, Any], context: WorkflowContext) -> Any:
        """Execute a registered function handler."""
        # Support legacy configs that used "action" instead of "handler".
        handler_name = (config.get("handler") or config.get("action") or "").strip()
        handler = get_task_handler(handler_name)

        if not handler:
            return {"success": False, "error": f"Handler not found: {handler_name}"}

        # Build arguments from config
        raw_args = config.get("args", {})
        args = self._interpolate_dict(raw_args, context) if isinstance(raw_args, dict) else {}

        # Backward-compat argument mapping for action-style task definitions.
        if handler_name == "log":
            if "message" not in args and "message" in config:
                args["message"] = self._interpolate_text(str(config.get("message", "")), context)
            if "level" not in args and "level" in config:
                args["level"] = config.get("level")
        elif handler_name == "set_state":
            if "state" not in args and isinstance(config.get("state"), dict):
                args["state"] = self._interpolate_dict(config["state"], context)
            if "key" not in args and "key" in config:
                args["key"] = config.get("key")
            if "value" not in args and "value" in config:
                value = config.get("value")
                if isinstance(value, str):
                    args["value"] = self._interpolate_text(value, context)
                elif isinstance(value, dict):
                    args["value"] = self._interpolate_dict(value, context)
                else:
                    args["value"] = value
        elif handler_name == "delay":
            if "seconds" not in args and "delay_seconds" in config:
                args["seconds"] = config.get("delay_seconds")

        # Execute handler
        if asyncio.iscoroutinefunction(handler):
            result = await handler(context, **args)
        else:
            result = handler(context, **args)

        return {"success": True, "result": result}

    async def _execute_http(self, config: dict[str, Any], context: WorkflowContext) -> Any:
        """Execute an HTTP request."""
        from aragora.observability.http_client_pool import get_http_pool

        url = self._interpolate_text(config.get("url", ""), context)
        method = config.get("method", "GET").upper()
        headers = self._interpolate_dict(config.get("headers", {}), context)
        body = self._interpolate_dict(config.get("body", {}), context)
        timeout = config.get("timeout_seconds", 30)

        try:
            pool = get_http_pool()
            async with pool.get_session("workflow") as client:
                kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
                if method in ("POST", "PUT", "PATCH") and body:
                    kwargs["json"] = body

                response = await client.request(method, url, **kwargs)
                response_text = response.text

                # Try to parse as JSON
                try:
                    import json

                    response_data = json.loads(response_text)
                except (json.JSONDecodeError, ValueError):
                    response_data = response_text

                return {
                    "success": response.status_code < 400,
                    "status_code": response.status_code,
                    "response": response_data,
                    "headers": dict(response.headers),
                }

        except asyncio.TimeoutError:
            return {"success": False, "error": f"Request timed out after {timeout}s"}
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
            logger.warning("HTTP task execution failed: %s", e)
            return {"success": False, "error": "HTTP request failed"}

    async def _execute_transform(self, config: dict[str, Any], context: WorkflowContext) -> Any:
        """Execute a data transformation."""
        transform_expr = config.get("transform", "")
        output_format = config.get("output_format", "auto")

        if not transform_expr:
            return {"success": False, "error": "No transform expression provided"}

        # Build namespace for transformation
        namespace = {
            "inputs": context.inputs,
            "outputs": context.step_outputs,
            "state": context.state,
            # Safe builtins
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "sorted": sorted,
            "filter": filter,
            "map": map,
            "sum": sum,
            "min": min,
            "max": max,
            "abs": abs,
            "round": round,
            "zip": zip,
            "enumerate": enumerate,
            "range": range,
        }

        # Add step outputs as direct variables
        for step_id, output in context.step_outputs.items():
            safe_name = step_id.replace("-", "_").replace(".", "_")
            namespace[safe_name] = output

        try:
            result = safe_eval(transform_expr, namespace)

            # Format output
            if output_format == "list" and not isinstance(result, list):
                result = list(result) if hasattr(result, "__iter__") else [result]
            elif output_format == "json":
                import json

                result = json.dumps(result, default=str)
            elif output_format == "text":
                result = str(result)

            return {"success": True, "result": result}

        except SafeEvalError as e:
            return {"success": False, "error": f"Transform failed: {e}"}

    async def _execute_validate(self, config: dict[str, Any], context: WorkflowContext) -> Any:
        """Execute data validation."""
        rules = config.get("validation", {})
        data_expr = config.get("data", "inputs")

        # Get data to validate
        namespace = {
            "inputs": context.inputs,
            "outputs": context.step_outputs,
            "state": context.state,
        }
        try:
            data = safe_eval(data_expr, namespace)
        except SafeEvalError as e:
            return {"success": False, "valid": False, "error": f"Invalid data expression: {e}"}

        # Validate against rules
        errors = []
        warnings = []

        for field, rule in rules.items():
            value = data.get(field) if isinstance(data, dict) else getattr(data, field, None)

            # Required check
            if rule.get("required", False) and value is None:
                errors.append(f"Field '{field}' is required")
                continue

            if value is None:
                continue

            # Type check
            expected_type = rule.get("type")
            if expected_type:
                type_map = {
                    "string": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                }
                if expected_type in type_map and not isinstance(value, type_map[expected_type]):
                    errors.append(f"Field '{field}' must be {expected_type}")

            # Min/max for numbers
            if isinstance(value, (int, float)):
                if "min" in rule and value < rule["min"]:
                    errors.append(f"Field '{field}' must be >= {rule['min']}")
                if "max" in rule and value > rule["max"]:
                    errors.append(f"Field '{field}' must be <= {rule['max']}")

            # Min/max length for strings
            if isinstance(value, str):
                if "min_length" in rule and len(value) < rule["min_length"]:
                    errors.append(f"Field '{field}' must be at least {rule['min_length']} chars")
                if "max_length" in rule and len(value) > rule["max_length"]:
                    errors.append(f"Field '{field}' must be at most {rule['max_length']} chars")

            # Pattern match
            if "pattern" in rule and isinstance(value, str):
                import re

                if not re.match(rule["pattern"], value):
                    errors.append(f"Field '{field}' does not match pattern")

            # Allowed values
            if "enum" in rule and value not in rule["enum"]:
                errors.append(f"Field '{field}' must be one of: {rule['enum']}")

            # Custom expression
            if "expression" in rule:
                try:
                    ns = {"value": value, "field": field, "data": data, **namespace}
                    if not safe_eval(rule["expression"], ns):
                        errors.append(rule.get("message", f"Field '{field}' failed validation"))
                except SafeEvalError:
                    warnings.append(f"Could not evaluate expression for '{field}'")

        return {
            "success": len(errors) == 0,
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    async def _execute_aggregate(self, config: dict[str, Any], context: WorkflowContext) -> Any:
        """Aggregate outputs from multiple steps."""
        input_steps = config.get("inputs", [])
        mode = config.get("mode", "merge")  # merge, list, first_valid

        if not input_steps:
            # Use all previous step outputs
            input_steps = list(context.step_outputs.keys())

        values = []
        for step_id in input_steps:
            if step_id in context.step_outputs:
                values.append(context.step_outputs[step_id])

        if mode == "list":
            return {"success": True, "result": values}
        elif mode == "first_valid":
            for v in values:
                if v is not None and v != "" and v != {}:
                    return {"success": True, "result": v}
            return {"success": False, "result": None, "error": "No valid values found"}
        else:  # merge
            result = {}
            for v in values:
                if isinstance(v, dict):
                    result.update(v)
            return {"success": True, "result": result}

    def _interpolate_text(self, template: str, context: WorkflowContext) -> str:
        """Interpolate text template with context values."""
        text = template
        for key, value in context.inputs.items():
            text = text.replace(f"{{{key}}}", str(value))
        for step_id, output in context.step_outputs.items():
            if isinstance(output, str):
                text = text.replace(f"{{step.{step_id}}}", output)
            elif isinstance(output, dict):
                for k, v in output.items():
                    text = text.replace(f"{{step.{step_id}.{k}}}", str(v))
        for key, value in context.state.items():
            text = text.replace(f"{{state.{key}}}", str(value))
        return text

    def _interpolate_dict(self, data: dict[str, Any], context: WorkflowContext) -> dict[str, Any]:
        """Interpolate dictionary values with context."""
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._interpolate_text(value, context)
            elif isinstance(value, dict):
                result[key] = self._interpolate_dict(value, context)
            elif isinstance(value, list):
                result[key] = [
                    self._interpolate_text(v, context) if isinstance(v, str) else v for v in value
                ]
            else:
                result[key] = value
        return result


# Built-in task handlers


def _handler_log(
    context: WorkflowContext, message: str = "", level: str = "info"
) -> dict[str, Any]:
    """Log a message."""
    log_func = getattr(logger, level, logger.info)
    log_func(f"[{context.workflow_id}] {message}")
    return {"logged": True, "message": message, "level": level}


def _handler_set_state(
    context: WorkflowContext,
    key: str = "",
    value: Any = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Set one or more state values."""
    if isinstance(state, dict):
        for state_key, state_value in state.items():
            context.set_state(str(state_key), state_value)
        return {"state": state, **state}

    key_str = str(key) if key is not None else ""
    context.set_state(key_str, value)
    return {"key": key_str, "value": value, key_str: value}


async def _handler_delay(context: WorkflowContext, seconds: float = 1.0) -> dict[str, Any]:
    """Delay execution (async-safe)."""
    await asyncio.sleep(seconds)
    return {"delayed_seconds": seconds}


# Register built-in handlers
register_task_handler("log", _handler_log)
register_task_handler("set_state", _handler_set_state)
register_task_handler("delay", _handler_delay)

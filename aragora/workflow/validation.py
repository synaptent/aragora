"""Workflow Definition Validator.

Validates workflow definitions for correctness before execution:
- Reachability (all steps reachable from entry)
- Cycle detection (loops allowed for loop-type only)
- Step type existence check
- Config schema validation
- Orphan transition detection
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationMessage:
    """A single validation finding."""

    level: str  # "error", "warning", "info"
    code: str  # e.g. "UNREACHABLE_STEP", "UNKNOWN_STEP_TYPE"
    message: str
    step_id: str | None = None


@dataclass
class ValidationResult:
    """Result of workflow validation."""

    valid: bool = True
    messages: list[ValidationMessage] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.level == "error"]

    @property
    def warnings(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.level == "warning"]

    @property
    def info(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.level == "info"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "messages": [
                {
                    "level": m.level,
                    "code": m.code,
                    "message": m.message,
                    "step_id": m.step_id,
                }
                for m in self.messages
            ],
        }


def _add(
    result: ValidationResult, level: str, code: str, message: str, step_id: str | None = None
) -> None:
    result.messages.append(
        ValidationMessage(level=level, code=code, message=message, step_id=step_id)
    )
    if level == "error":
        result.valid = False


def validate_workflow(definition: Any) -> ValidationResult:
    """Validate a WorkflowDefinition for correctness.

    Args:
        definition: A WorkflowDefinition instance (from aragora.workflow.types).

    Returns:
        ValidationResult with all findings.
    """
    result = ValidationResult()

    steps = definition.steps
    transitions = definition.transitions
    step_ids = {s.id for s in steps}
    step_map = {s.id: s for s in steps}

    # 1. Entry step exists
    entry = definition.entry_step
    if not steps:
        _add(result, "error", "NO_STEPS", "Workflow has no steps")
        return result

    if entry and entry not in step_ids:
        _add(result, "error", "MISSING_ENTRY", f"Entry step '{entry}' not found in steps")

    # 2. Step type check
    try:
        from aragora.workflow.step_catalog import get_known_step_types

        known_types = get_known_step_types()
    except ImportError:
        known_types = None

    if known_types is not None:
        for step in steps:
            if step.step_type not in known_types:
                _add(
                    result,
                    "warning",
                    "UNKNOWN_STEP_TYPE",
                    f"Step type '{step.step_type}' is not in the step catalog",
                    step_id=step.id,
                )

    # 3. Reachability: BFS from entry step
    if entry and entry in step_ids:
        adj: dict[str, list[str]] = {sid: [] for sid in step_ids}
        for t in transitions:
            if t.from_step in adj:
                adj[t.from_step].append(t.to_step)
        for step in steps:
            for ns in step.next_steps:
                if ns in step_ids and step.id in adj:
                    adj[step.id].append(ns)

        reachable: set[str] = set()
        queue: deque[str] = deque([entry])
        while queue:
            node = queue.popleft()
            if node in reachable:
                continue
            reachable.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in reachable:
                    queue.append(neighbor)

        for step in steps:
            if step.id not in reachable:
                _add(
                    result,
                    "warning",
                    "UNREACHABLE_STEP",
                    f"Step '{step.id}' is not reachable from entry step '{entry}'",
                    step_id=step.id,
                )

    # 4. Cycle detection via DFS back-edge detection
    if step_ids:
        adj_cycle: dict[str, list[str]] = {sid: [] for sid in step_ids}
        for t in transitions:
            if t.from_step in adj_cycle:
                adj_cycle[t.from_step].append(t.to_step)
        for step in steps:
            for ns in step.next_steps:
                if ns in step_ids and step.id in adj_cycle:
                    adj_cycle[step.id].append(ns)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = dict.fromkeys(step_ids, WHITE)

        def _dfs(node: str) -> None:
            color[node] = GRAY
            for neighbor in adj_cycle.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # Back edge found — cycle
                    step = step_map.get(node)
                    neighbor_step = step_map.get(neighbor)
                    # DFS start order over step IDs is not stable; classify loop cycles
                    # as informational if either side of the back edge is a loop step.
                    if (step and step.step_type == "loop") or (
                        neighbor_step and neighbor_step.step_type == "loop"
                    ):
                        loop_step_id = node if (step and step.step_type == "loop") else neighbor
                        _add(
                            result,
                            "info",
                            "LOOP_CYCLE",
                            f"Loop step '{loop_step_id}' forms a cycle (expected)",
                            step_id=loop_step_id,
                        )
                    else:
                        _add(
                            result,
                            "error",
                            "CYCLE_DETECTED",
                            f"Cycle detected at step '{node}' → '{neighbor}'",
                            step_id=node,
                        )
                elif color[neighbor] == WHITE:
                    _dfs(neighbor)
            color[node] = BLACK

        for sid in step_ids:
            if color[sid] == WHITE:
                _dfs(sid)

    # 5. Orphan transitions
    for t in transitions:
        if t.from_step not in step_ids:
            _add(
                result,
                "error",
                "ORPHAN_TRANSITION",
                f"Transition references non-existent source step '{t.from_step}'",
            )
        if t.to_step not in step_ids:
            _add(
                result,
                "error",
                "ORPHAN_TRANSITION",
                f"Transition references non-existent target step '{t.to_step}'",
            )

    # 6. Basic config schema validation (type checking only)
    if known_types is not None:
        try:
            from aragora.workflow.step_catalog import get_step_type_info

            for step in steps:
                info = get_step_type_info(step.step_type)
                if not info or not info.config_schema:
                    continue
                info.config_schema.get("properties", {})
                required = info.config_schema.get("required", [])
                for req_field in required:
                    if req_field not in step.config:
                        _add(
                            result,
                            "warning",
                            "MISSING_REQUIRED_CONFIG",
                            f"Step '{step.id}' is missing required config field '{req_field}'",
                            step_id=step.id,
                        )
        except ImportError:
            pass

    return result

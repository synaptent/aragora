"""
Defines the core TaskBrief data structure.

This module provides a concrete, versioned schema for tasks that are processed
by the Aragora system. It serves as the validated output of the ambiguity
resolution pipeline and the primary input for debate and execution phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, kw_only=True)
class TaskBriefV1:
    """
    A structured, versioned representation of a task.

    This dataclass ensures that all tasks moving through the system have a
    consistent, validated structure.

    Attributes:
        goal: The primary objective of the task. Must be a non-empty string.
        schema_version: The version of the TaskBrief schema.
        constraints: A list of limitations or rules that must be followed.
        success_criteria: A list of conditions that define task completion.
        confidence: A score from 0.0 to 1.0 indicating the system's
            confidence in the interpretation of the task. Defaults to 0.0.
        provenance: A dictionary containing metadata about the task's origin.
        assumptions: A list of assumptions made during task interpretation.
        requires_user_confirmation: If True, the orchestrator must halt
            and await explicit user approval before execution.
    """

    goal: str
    schema_version: str = "1.0"
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    requires_user_confirmation: bool = False

    def __post_init__(self) -> None:
        """Perform validation after the object is initialized."""
        if not self.goal or not self.goal.strip():
            raise ValueError("The 'goal' field cannot be empty.")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("The 'confidence' score must be between 0.0 and 1.0.")

        if self.schema_version != "1.0":
            raise ValueError("Only schema_version '1.0' is currently supported.")

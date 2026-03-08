"""SwarmSpec: structured specification from interrogation to orchestration."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SwarmSpec:
    """Structured specification produced by interrogation, consumed by orchestration.

    This is the contract between the user-facing interrogation phase and
    the technical orchestration phase. It captures user intent in a format
    that maps directly to ``HardenedOrchestrator.execute_goal_coordinated()``.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # User intent
    raw_goal: str = ""
    refined_goal: str = ""

    # Acceptance criteria
    acceptance_criteria: list[str] = field(default_factory=list)

    # Constraints
    constraints: list[str] = field(default_factory=list)
    budget_limit_usd: float | None = 5.0

    # Hints for decomposition
    track_hints: list[str] = field(default_factory=list)
    file_scope_hints: list[str] = field(default_factory=list)
    work_orders: list[dict[str, Any]] = field(default_factory=list)

    # Risk assessment
    estimated_complexity: str = "medium"
    requires_approval: bool = False

    # Proactive suggestions from the interrogation
    proactive_suggestions: list[str] = field(default_factory=list)

    # Research pipeline context (Phase 3)
    research_context: dict[str, Any] = field(default_factory=dict)
    pipeline_stage: str = ""

    # Obsidian source (Phase 4)
    obsidian_source: str = ""

    # Truth-seeking scores (Phase 5)
    epistemic_scores: dict[str, Any] = field(default_factory=dict)

    # Metadata
    interrogation_turns: int = 0
    user_expertise: str = "non-developer"

    @staticmethod
    def _nonempty_strings(values: list[str]) -> list[str]:
        return [str(item).strip() for item in values if str(item).strip()]

    @staticmethod
    def infer_file_scope_hints(text: str) -> list[str]:
        """Extract path-like hints from free-form prompt text."""
        hints: list[str] = []
        for raw in re.split(r"\s+", text or ""):
            token = raw.strip().strip("`'\".,;:()[]{}<>")
            if not token or token.startswith(("http://", "https://")):
                continue
            normalized = token.removeprefix("./")
            if "/" not in normalized:
                continue
            normalized = normalized.rstrip("/")
            if not normalized:
                continue
            hints.append(normalized)
        return list(dict.fromkeys(hints))

    @staticmethod
    def infer_constraints(messages: list[str]) -> list[str]:
        """Extract obvious constraints from user language."""
        markers = (
            "do not ",
            "don't ",
            "must not ",
            "without ",
            "leave ",
            "only touch ",
            "should not ",
        )
        constraints: list[str] = []
        for message in messages:
            text = str(message).strip()
            lower = text.lower()
            if text and any(marker in lower for marker in markers):
                constraints.append(text)
        return list(dict.fromkeys(constraints))

    @staticmethod
    def infer_acceptance_criteria(messages: list[str]) -> list[str]:
        """Extract obvious success criteria from user language."""
        markers = (
            "done looks like",
            "done means",
            "works when",
            "success is",
            "should ",
            "must ",
            "passes ",
            "pass when",
        )
        criteria: list[str] = []
        for message in messages:
            text = str(message).strip()
            lower = text.lower()
            if len(text) >= 12 and any(marker in lower for marker in markers):
                criteria.append(text)
        return list(dict.fromkeys(criteria))

    @classmethod
    def from_direct_goal(
        cls,
        raw_goal: str,
        *,
        budget_limit_usd: float | None,
        requires_approval: bool,
        user_expertise: str,
    ) -> SwarmSpec:
        """Build a direct spec from a raw goal without conversational interrogation."""
        return cls(
            id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            raw_goal=raw_goal,
            refined_goal=raw_goal,
            constraints=cls.infer_constraints([raw_goal]),
            budget_limit_usd=budget_limit_usd,
            file_scope_hints=cls.infer_file_scope_hints(raw_goal),
            requires_approval=requires_approval,
            interrogation_turns=0,
            user_expertise=user_expertise,
        )

    def dispatch_bounds(self) -> dict[str, bool]:
        """Return which fields make this spec safe enough to dispatch."""
        return {
            "acceptance_criteria": bool(self._nonempty_strings(self.acceptance_criteria)),
            "constraints": bool(self._nonempty_strings(self.constraints)),
            "file_scope_hints": bool(self._nonempty_strings(self.file_scope_hints)),
            "work_orders": bool([item for item in self.work_orders if isinstance(item, dict)]),
        }

    def is_dispatch_bounded(self) -> bool:
        """Whether the spec has at least one concrete bound for dispatch."""
        return any(self.dispatch_bounds().values())

    def missing_dispatch_bounds(self) -> list[str]:
        """Human-readable names for missing dispatch-bounding fields."""
        labels = {
            "acceptance_criteria": "acceptance criterion",
            "constraints": "constraint",
            "file_scope_hints": "file-scope hint",
            "work_orders": "explicit work order",
        }
        return [labels[key] for key, present in self.dispatch_bounds().items() if not present]

    def dispatch_gate_reason(self) -> str:
        """Reason why this spec may or may not dispatch."""
        if self.is_dispatch_bounded():
            return "dispatch-bounded"
        return (
            "Swarm spec is under-specified for dispatch. Add at least one acceptance "
            "criterion, constraint, file-scope hint, or explicit work order."
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwarmSpec:
        """Deserialize from dictionary."""
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "work_orders" in data and isinstance(data["work_orders"], list):
            data["work_orders"] = [
                dict(item) for item in data["work_orders"] if isinstance(item, dict)
            ]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> SwarmSpec:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(text))

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        try:
            import yaml

            data = self.to_dict()
            return yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
        except ImportError:
            return self.to_json()

    @classmethod
    def from_yaml(cls, text: str) -> SwarmSpec:
        """Deserialize from YAML string."""
        try:
            import yaml

            data = yaml.safe_load(text)
        except ImportError:
            data = json.loads(text)
        return cls.from_dict(data)

    def summary(self) -> str:
        """Human-readable summary of the spec."""
        lines = [
            f"Goal: {self.refined_goal or self.raw_goal}",
            f"Complexity: {self.estimated_complexity}",
        ]
        if self.acceptance_criteria:
            lines.append(f"Acceptance criteria: {len(self.acceptance_criteria)} items")
        if self.constraints:
            lines.append(f"Constraints: {len(self.constraints)} items")
        if self.budget_limit_usd is not None:
            lines.append(f"Budget: ${self.budget_limit_usd:.2f}")
        if self.track_hints:
            lines.append(f"Tracks: {', '.join(self.track_hints)}")
        if self.file_scope_hints:
            lines.append(f"File scope: {', '.join(self.file_scope_hints[:5])}")
        if self.work_orders:
            lines.append(f"Explicit work orders: {len(self.work_orders)}")
        return "\n".join(lines)

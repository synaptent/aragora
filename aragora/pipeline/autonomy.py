"""Autonomy Level Controls."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Literal, TypedDict


ApprovalLevel = Literal["none", "spec_and_merge", "all_stages", "metrics_gate"]


class OrchestratorConfig(TypedDict):
    require_human_approval: bool
    auto_commit: bool
    auto_merge: bool
    skip_interrogation: bool
    approval_level: ApprovalLevel


class AutonomyLevel(enum.Enum):
    FULLY_AUTONOMOUS = "fully_autonomous"
    PROPOSE_AND_APPROVE = "propose_and_approve"
    HUMAN_GUIDED = "human_guided"
    METRICS_DRIVEN = "metrics_driven"

    def to_orchestrator_config(self) -> OrchestratorConfig:
        configs: dict[AutonomyLevel, OrchestratorConfig] = {
            AutonomyLevel.FULLY_AUTONOMOUS: {
                "require_human_approval": False,
                "auto_commit": True,
                "auto_merge": True,
                "skip_interrogation": True,
                "approval_level": "none",
            },
            AutonomyLevel.PROPOSE_AND_APPROVE: {
                "require_human_approval": True,
                "auto_commit": False,
                "auto_merge": False,
                "skip_interrogation": False,
                "approval_level": "spec_and_merge",
            },
            AutonomyLevel.HUMAN_GUIDED: {
                "require_human_approval": True,
                "auto_commit": False,
                "auto_merge": False,
                "skip_interrogation": False,
                "approval_level": "all_stages",
            },
            AutonomyLevel.METRICS_DRIVEN: {
                "require_human_approval": False,
                "auto_commit": True,
                "auto_merge": False,
                "skip_interrogation": False,
                "approval_level": "metrics_gate",
            },
        }
        return configs[self]

    def to_approval_level(self) -> ApprovalLevel:
        return self.to_orchestrator_config()["approval_level"]

    @property
    def requires_spec_approval(self) -> bool:
        return self in (AutonomyLevel.PROPOSE_AND_APPROVE, AutonomyLevel.HUMAN_GUIDED)

    @property
    def requires_merge_approval(self) -> bool:
        return self in (
            AutonomyLevel.PROPOSE_AND_APPROVE,
            AutonomyLevel.HUMAN_GUIDED,
            AutonomyLevel.METRICS_DRIVEN,
        )

    @property
    def auto_commits(self) -> bool:
        return self in (AutonomyLevel.FULLY_AUTONOMOUS, AutonomyLevel.METRICS_DRIVEN)

    @property
    def skips_interrogation(self) -> bool:
        return self == AutonomyLevel.FULLY_AUTONOMOUS

    @classmethod
    def from_string(cls, value: str) -> AutonomyLevel:
        normalized = value.lower().replace("-", "_").replace(" ", "_")
        for level in cls:
            if level.value == normalized:
                return level
        raise ValueError(
            f"Unknown autonomy level: {value}. Valid: {', '.join(l.value for l in cls)}"
        )


@dataclass
class AutonomyGate:
    level: AutonomyLevel
    stage: str
    metrics_threshold: float = 0.8

    def needs_approval(self, quality_score: float = 0.0) -> bool:
        if self.level == AutonomyLevel.FULLY_AUTONOMOUS:
            return False
        if self.level == AutonomyLevel.HUMAN_GUIDED:
            return True
        if self.level == AutonomyLevel.PROPOSE_AND_APPROVE:
            return self.stage in ("spec", "merge")
        if self.level == AutonomyLevel.METRICS_DRIVEN:
            if self.stage == "merge":
                return True
            return quality_score < self.metrics_threshold
        return True

    @property
    def gate_description(self) -> str:
        descriptions = {
            "interrogation": "Approve question set before asking user",
            "spec": "Approve specification before execution",
            "execution": "Approve execution plan before running",
            "merge": "Approve merge/PR before integration",
        }
        return descriptions.get(self.stage, f"Approve {self.stage}")


def create_gates(level: AutonomyLevel) -> dict[str, AutonomyGate]:
    stages = ["interrogation", "spec", "execution", "merge"]
    return {stage: AutonomyGate(level=level, stage=stage) for stage in stages}

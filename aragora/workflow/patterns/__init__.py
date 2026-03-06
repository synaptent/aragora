"""
Workflow Pattern Library for Enterprise Multi-Agent Control Plane.

Pre-defined workflow patterns for common multi-agent orchestration scenarios:
- HiveMind: Parallel agent execution with consensus merge
- Sequential: Linear agent pipeline with data passing
- MapReduce: Split work, parallel processing, aggregate results
- Hierarchical: Manager-worker delegation pattern
- ReviewCycle: Iterative refinement with convergence check
- Dialectic: Thesis-antithesis-synthesis pattern
- Escalation: Multi-level escalation paths for debate SLA violations

Each pattern provides a factory method to create a WorkflowDefinition
that can be customized and executed by the WorkflowEngine.

Usage:
    from aragora.workflow.patterns import HiveMindPattern, MapReducePattern

    # Create a hive-mind workflow
    workflow = HiveMindPattern.create(
        name="Contract Review",
        agents=["claude", "gpt4", "gemini"],
        task="Analyze this contract for risks",
        consensus_mode="weighted",
    )

    # Execute
    engine = WorkflowEngine()
    result = await engine.execute(workflow, inputs={"contract": "..."})
"""

from aragora.workflow.patterns.base import (
    WorkflowPattern,
    PatternConfig,
    PatternType,
)
from aragora.workflow.patterns.hive_mind import HiveMindPattern
from aragora.workflow.patterns.sequential import SequentialPattern
from aragora.workflow.patterns.map_reduce import MapReducePattern
from aragora.workflow.patterns.hierarchical import HierarchicalPattern
from aragora.workflow.patterns.review_cycle import ReviewCyclePattern
from aragora.workflow.patterns.dialectic import DialecticPattern
from aragora.workflow.patterns.ensemble import EnsemblePattern
from aragora.workflow.patterns.post_debate import (
    PostDebatePattern,
    PostDebateConfig,
    get_default_post_debate_workflow,
)
from aragora.workflow.patterns.escalation import (
    EscalationWorkflowPattern,
    EscalationStep,
    EscalationPathConfig,
    STANDARD_ESCALATION_PATH,
)

# Pattern registry for dynamic pattern creation
PATTERN_REGISTRY = {
    PatternType.HIVE_MIND: HiveMindPattern,
    PatternType.SEQUENTIAL: SequentialPattern,
    PatternType.MAP_REDUCE: MapReducePattern,
    PatternType.HIERARCHICAL: HierarchicalPattern,
    PatternType.REVIEW_CYCLE: ReviewCyclePattern,
    PatternType.DIALECTIC: DialecticPattern,
    PatternType.ENSEMBLE: EnsemblePattern,
}


def create_pattern(pattern_type: PatternType, **kwargs) -> "WorkflowPattern":
    """
    Factory function to create a workflow pattern.

    Args:
        pattern_type: Type of pattern to create
        **kwargs: Pattern-specific configuration

    Returns:
        WorkflowPattern instance
    """
    pattern_class = PATTERN_REGISTRY.get(pattern_type)
    if not pattern_class:
        raise ValueError(f"Unknown pattern type: {pattern_type}")
    return pattern_class(**kwargs)


__all__ = [
    # Base
    "WorkflowPattern",
    "PatternConfig",
    "PatternType",
    # Patterns
    "HiveMindPattern",
    "SequentialPattern",
    "MapReducePattern",
    "HierarchicalPattern",
    "ReviewCyclePattern",
    "DialecticPattern",
    "EnsemblePattern",
    "PostDebatePattern",
    "PostDebateConfig",
    "get_default_post_debate_workflow",
    "EscalationWorkflowPattern",
    "EscalationStep",
    "EscalationPathConfig",
    "STANDARD_ESCALATION_PATH",
    # Registry
    "PATTERN_REGISTRY",
    "create_pattern",
]

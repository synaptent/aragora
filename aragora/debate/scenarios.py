"""
Scenario Matrix Debates - Run debates across multiple scenarios.

Enables systematic exploration of solution spaces by running
parallel debates with varying conditions, constraints, and
assumptions to understand how conclusions change.

Key concepts:
- Scenario: A set of conditions/assumptions for a debate
- ScenarioMatrix: Grid of scenarios to explore
- MatrixDebateRunner: Execute debates across the matrix
- ScenarioComparator: Analyze results across scenarios
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ScenarioType(Enum):
    """Type of scenario variation."""

    CONSTRAINT = "constraint"  # Resource/time/budget constraints
    ASSUMPTION = "assumption"  # Underlying assumptions
    STAKEHOLDER = "stakeholder"  # Different stakeholder perspectives
    SCALE = "scale"  # Scale/size variations
    RISK_TOLERANCE = "risk_tolerance"  # Risk appetite levels
    TIME_HORIZON = "time_horizon"  # Short-term vs long-term
    TECHNOLOGY = "technology"  # Tech stack choices
    REGULATORY = "regulatory"  # Compliance requirements
    CUSTOM = "custom"


class OutcomeCategory(Enum):
    """Category of debate outcome."""

    CONSISTENT = "consistent"  # Same conclusion across scenarios
    CONDITIONAL = "conditional"  # Conclusion depends on scenario
    DIVERGENT = "divergent"  # Different conclusions
    INCONCLUSIVE = "inconclusive"  # No clear pattern


@dataclass
class Scenario:
    """A specific scenario for a debate."""

    id: str
    name: str
    scenario_type: ScenarioType
    description: str

    # Scenario parameters
    parameters: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    # Context modifications
    context_additions: str = ""  # Added to debate context
    context_replacements: dict[str, str] = field(default_factory=dict)

    # Metadata
    priority: int = 1  # Higher = run first
    is_baseline: bool = False  # Is this the baseline scenario?
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scenario_type": self.scenario_type.value,
            "description": self.description,
            "parameters": self.parameters,
            "constraints": self.constraints,
            "assumptions": self.assumptions,
            "context_additions": self.context_additions,
            "context_replacements": self.context_replacements,
            "priority": self.priority,
            "is_baseline": self.is_baseline,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Scenario:
        return cls(
            id=data["id"],
            name=data["name"],
            scenario_type=ScenarioType(data["scenario_type"]),
            description=data["description"],
            parameters=data.get("parameters", {}),
            constraints=data.get("constraints", []),
            assumptions=data.get("assumptions", []),
            context_additions=data.get("context_additions", ""),
            context_replacements=data.get("context_replacements", {}),
            priority=data.get("priority", 1),
            is_baseline=data.get("is_baseline", False),
            tags=data.get("tags", []),
        )

    def apply_to_context(self, base_context: str) -> str:
        """Apply scenario modifications to base context."""
        context = base_context

        # Apply replacements
        for old, new in self.context_replacements.items():
            context = context.replace(old, new)

        # Add scenario context
        if self.context_additions:
            context = f"{context}\n\n{self.context_additions}"

        # Add constraints and assumptions
        if self.constraints:
            context += "\n\nConstraints:\n" + "\n".join(f"- {c}" for c in self.constraints)

        if self.assumptions:
            context += "\n\nAssumptions:\n" + "\n".join(f"- {a}" for a in self.assumptions)

        return context


@dataclass
class ScenarioResult:
    """Result of a debate under a specific scenario."""

    scenario_id: str
    scenario_name: str
    conclusion: str
    confidence: float
    consensus_reached: bool
    key_claims: list[str] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    rounds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "consensus_reached": self.consensus_reached,
            "key_claims": self.key_claims,
            "dissenting_views": self.dissenting_views,
            "duration_seconds": self.duration_seconds,
            "rounds": self.rounds,
            "metadata": self.metadata,
        }


@dataclass
class ScenarioComparison:
    """Comparison between two scenario results."""

    scenario_a_id: str
    scenario_b_id: str
    conclusions_match: bool
    similarity_score: float  # 0-1
    key_differences: list[str] = field(default_factory=list)
    shared_claims: list[str] = field(default_factory=list)
    unique_to_a: list[str] = field(default_factory=list)
    unique_to_b: list[str] = field(default_factory=list)


@dataclass
class MatrixResult:
    """Result of running a full scenario matrix."""

    matrix_id: str
    task: str
    created_at: datetime
    completed_at: datetime | None = None

    # Scenarios and results
    scenarios: list[Scenario] = field(default_factory=list)
    results: list[ScenarioResult] = field(default_factory=list)

    # Analysis
    outcome_category: OutcomeCategory = OutcomeCategory.INCONCLUSIVE
    baseline_scenario_id: str | None = None
    universal_conclusions: list[str] = field(default_factory=list)
    conditional_conclusions: dict[str, list[str]] = field(default_factory=dict)
    scenario_comparisons: list[ScenarioComparison] = field(default_factory=list)

    # Summary
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)

    def get_result(self, scenario_id: str) -> ScenarioResult | None:
        """Get result for a specific scenario."""
        for r in self.results:
            if r.scenario_id == scenario_id:
                return r
        return None

    def to_dict(self) -> dict:
        return {
            "matrix_id": self.matrix_id,
            "task": self.task,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "results": [r.to_dict() for r in self.results],
            "outcome_category": self.outcome_category.value,
            "baseline_scenario_id": self.baseline_scenario_id,
            "universal_conclusions": self.universal_conclusions,
            "conditional_conclusions": self.conditional_conclusions,
            "summary": self.summary,
            "recommendations": self.recommendations,
        }


class ScenarioMatrix:
    """
    A matrix of scenarios for systematic debate exploration.

    Can be built from:
    - Explicit scenario list
    - Parameter grid (cartesian product)
    - Sensitivity analysis (vary one parameter at a time)
    """

    def __init__(self, name: str = "Scenario Matrix"):
        self.name = name
        self.scenarios: list[Scenario] = []
        self.dimensions: dict[str, list[Any]] = {}

    def add_scenario(self, scenario: Scenario) -> ScenarioMatrix:
        """Add a single scenario."""
        self.scenarios.append(scenario)
        return self

    def add_dimension(self, name: str, values: list[Any]) -> ScenarioMatrix:
        """Add a dimension for grid generation."""
        self.dimensions[name] = values
        return self

    def generate_grid(
        self,
        scenario_type: ScenarioType = ScenarioType.CUSTOM,
        name_template: str = "{dims}",
    ) -> ScenarioMatrix:
        """Generate scenarios from cartesian product of dimensions."""

        if not self.dimensions:
            return self

        # Get all combinations
        dim_names = list(self.dimensions.keys())
        dim_values = list(self.dimensions.values())

        for combo in itertools.product(*dim_values):
            params = dict(zip(dim_names, combo))

            # Create name from template
            dims_str = ", ".join(f"{k}={v}" for k, v in params.items())
            name = name_template.format(dims=dims_str, **params)

            scenario = Scenario(
                id=str(uuid.uuid4())[:8],
                name=name,
                scenario_type=scenario_type,
                description=f"Scenario with {dims_str}",
                parameters=params,
            )
            self.scenarios.append(scenario)

        return self

    def generate_sensitivity(
        self,
        baseline_params: dict[str, Any],
        vary_params: dict[str, list[Any]],
        scenario_type: ScenarioType = ScenarioType.CUSTOM,
    ) -> ScenarioMatrix:
        """Generate scenarios for sensitivity analysis (vary one at a time)."""

        # Add baseline
        baseline = Scenario(
            id="baseline",
            name="Baseline",
            scenario_type=scenario_type,
            description="Baseline scenario",
            parameters=baseline_params.copy(),
            is_baseline=True,
        )
        self.scenarios.append(baseline)

        # Vary each parameter
        for param, values in vary_params.items():
            for value in values:
                if value == baseline_params.get(param):
                    continue  # Skip baseline value

                params = baseline_params.copy()
                params[param] = value

                scenario = Scenario(
                    id=str(uuid.uuid4())[:8],
                    name=f"{param}={value}",
                    scenario_type=scenario_type,
                    description=f"Sensitivity: {param} changed to {value}",
                    parameters=params,
                )
                self.scenarios.append(scenario)

        return self

    def get_scenarios(self) -> list[Scenario]:
        """Get all scenarios sorted by priority."""
        return sorted(self.scenarios, key=lambda s: -s.priority)

    @classmethod
    def from_presets(cls, preset: str) -> ScenarioMatrix:
        """Create matrix from common presets."""

        matrix = cls(name=preset)

        if preset == "scale":
            matrix.add_dimension("scale", ["small", "medium", "large", "enterprise"])

        elif preset == "time_horizon":
            matrix.add_dimension("horizon", ["short_term", "medium_term", "long_term"])

        elif preset == "risk":
            matrix.add_dimension("risk_tolerance", ["conservative", "moderate", "aggressive"])

        elif preset == "stakeholder":
            matrix.add_dimension("stakeholder", ["developer", "manager", "executive", "customer"])

        elif preset == "tech_stack":
            matrix.add_dimension("language", ["python", "typescript", "go", "rust"])
            matrix.add_dimension("infra", ["cloud", "on_prem", "hybrid"])

        elif preset == "comprehensive":
            matrix.add_dimension("scale", ["small", "large"])
            matrix.add_dimension("risk", ["low", "high"])
            matrix.add_dimension("time", ["short", "long"])

        return matrix.generate_grid()


class ScenarioComparator:
    """Compare and analyze results across scenarios."""

    def compare_pair(
        self,
        result_a: ScenarioResult,
        result_b: ScenarioResult,
    ) -> ScenarioComparison:
        """Compare two scenario results."""

        # Check conclusion similarity
        conclusions_match = self._conclusions_similar(result_a.conclusion, result_b.conclusion)

        # Compare claims
        claims_a = set(result_a.key_claims)
        claims_b = set(result_b.key_claims)

        shared = claims_a & claims_b
        unique_a = claims_a - claims_b
        unique_b = claims_b - claims_a

        # Calculate similarity
        if claims_a or claims_b:
            similarity = len(shared) / len(claims_a | claims_b)
        else:
            similarity = 1.0 if conclusions_match else 0.0

        # Identify key differences
        differences = []
        if not conclusions_match:
            differences.append("Different conclusions reached")
        if unique_a:
            differences.append(f"Scenario A has unique claims: {list(unique_a)[:3]}")
        if unique_b:
            differences.append(f"Scenario B has unique claims: {list(unique_b)[:3]}")
        if abs(result_a.confidence - result_b.confidence) > 0.2:
            differences.append(
                f"Confidence differs: {result_a.confidence:.0%} vs {result_b.confidence:.0%}"
            )

        return ScenarioComparison(
            scenario_a_id=result_a.scenario_id,
            scenario_b_id=result_b.scenario_id,
            conclusions_match=conclusions_match,
            similarity_score=similarity,
            key_differences=differences,
            shared_claims=list(shared),
            unique_to_a=list(unique_a),
            unique_to_b=list(unique_b),
        )

    def _conclusions_similar(self, a: str, b: str, threshold: float = 0.6) -> bool:
        """Check if two conclusions are similar."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())

        if not words_a or not words_b:
            return False

        intersection = len(words_a & words_b)
        union = len(words_a | words_b)

        return (intersection / union) >= threshold if union > 0 else False

    def analyze_matrix(self, matrix_result: MatrixResult) -> dict[str, Any]:
        """Analyze the full matrix of results."""

        results = matrix_result.results
        if not results:
            return {
                "error": "No results to analyze",
                "outcome_category": OutcomeCategory.INCONCLUSIVE.value,
                "total_scenarios": 0,
                "avg_similarity": 0.0,
                "universal_conclusions": [],
                "conditional_patterns": {},
                "comparisons": [],
            }

        # Compare all pairs
        comparisons = []
        for i, r1 in enumerate(results):
            for r2 in results[i + 1 :]:
                comparisons.append(self.compare_pair(r1, r2))

        # Categorize outcome
        all_match = all(c.conclusions_match for c in comparisons)
        none_match = not any(c.conclusions_match for c in comparisons)
        avg_similarity = (
            sum(c.similarity_score for c in comparisons) / len(comparisons) if comparisons else 0
        )

        if all_match:
            outcome = OutcomeCategory.CONSISTENT
        elif none_match:
            outcome = OutcomeCategory.DIVERGENT
        elif avg_similarity > 0.5:
            outcome = OutcomeCategory.CONDITIONAL
        else:
            outcome = OutcomeCategory.INCONCLUSIVE

        # Find universal conclusions (appear in all scenarios)
        all_claims = [set(r.key_claims) for r in results]
        universal = set.intersection(*all_claims) if all_claims else set()

        # Find conditional conclusions (vary by scenario parameters)
        conditional: dict[str, list[str]] = {}
        for r in results:
            scenario = next((s for s in matrix_result.scenarios if s.id == r.scenario_id), None)
            if scenario:
                for param, value in scenario.parameters.items():
                    key = f"{param}={value}"
                    if key not in conditional:
                        conditional[key] = []
                    conditional[key].extend(r.key_claims)

        return {
            "outcome_category": outcome.value,
            "total_scenarios": len(results),
            "avg_similarity": avg_similarity,
            "universal_conclusions": list(universal),
            "conditional_patterns": {k: list(set(v)) for k, v in conditional.items()},
            "comparisons": [
                {
                    "a": c.scenario_a_id,
                    "b": c.scenario_b_id,
                    "match": c.conclusions_match,
                    "similarity": c.similarity_score,
                }
                for c in comparisons
            ],
        }

    def generate_summary(self, matrix_result: MatrixResult) -> str:
        """Generate a human-readable summary of matrix results."""

        analysis = self.analyze_matrix(matrix_result)

        lines = [
            f"# Scenario Matrix Analysis: {matrix_result.task}",
            "",
            f"**Outcome**: {analysis['outcome_category'].replace('_', ' ').title()}",
            f"**Scenarios Analyzed**: {analysis['total_scenarios']}",
            f"**Average Similarity**: {analysis['avg_similarity']:.0%}",
            "",
        ]

        if analysis["universal_conclusions"]:
            lines.append("## Universal Conclusions (across all scenarios)")
            for c in analysis["universal_conclusions"][:5]:
                lines.append(f"- {c}")
            lines.append("")

        if analysis["conditional_patterns"]:
            lines.append("## Conditional Patterns")
            for condition, claims in list(analysis["conditional_patterns"].items())[:5]:
                if claims:
                    lines.append(f"\n**When {condition}:**")
                    for c in claims[:3]:
                        lines.append(f"- {c}")
            lines.append("")

        # Scenario-by-scenario results
        lines.append("## Individual Scenario Results")
        for r in matrix_result.results:
            lines.append(f"\n### {r.scenario_name}")
            lines.append(f"- Confidence: {r.confidence:.0%}")
            lines.append(f"- Consensus: {'Yes' if r.consensus_reached else 'No'}")
            lines.append(f"- Conclusion: {r.conclusion[:100]}...")

        return "\n".join(lines)


class MatrixDebateRunner:
    """
    Run debates across a scenario matrix.

    Executes debates for each scenario, either sequentially
    or in parallel, and aggregates results.
    """

    def __init__(
        self,
        debate_func: Callable,  # Function to run a single debate
        max_parallel: int = 3,
    ):
        self.debate_func = debate_func
        self.max_parallel = max_parallel
        self.comparator = ScenarioComparator()

    async def run_matrix(
        self,
        task: str,
        matrix: ScenarioMatrix,
        base_context: str = "",
        on_scenario_complete: Callable[[ScenarioResult], None] | None = None,
    ) -> MatrixResult:
        """Run debates for all scenarios in the matrix."""

        result = MatrixResult(
            matrix_id=str(uuid.uuid4()),
            task=task,
            created_at=datetime.now(),
            scenarios=matrix.get_scenarios(),
        )

        # Find baseline
        for s in result.scenarios:
            if s.is_baseline:
                result.baseline_scenario_id = s.id
                break

        # Run debates
        scenarios = matrix.get_scenarios()

        if self.max_parallel > 1:
            # Run in batches
            for i in range(0, len(scenarios), self.max_parallel):
                batch = scenarios[i : i + self.max_parallel]
                batch_results = await asyncio.gather(
                    *[self._run_scenario_debate(task, s, base_context) for s in batch],
                    return_exceptions=True,
                )

                for r in batch_results:
                    if isinstance(r, BaseException):
                        logger.error("Scenario debate failed: %s: %s", type(r).__name__, r)
                        continue  # Skip failed scenarios
                    result.results.append(r)
                    if on_scenario_complete:
                        on_scenario_complete(r)
        else:
            # Run sequentially
            for scenario in scenarios:
                r = await self._run_scenario_debate(task, scenario, base_context)
                result.results.append(r)
                if on_scenario_complete:
                    on_scenario_complete(r)

        result.completed_at = datetime.now()

        # Analyze results
        analysis = self.comparator.analyze_matrix(result)
        result.outcome_category = OutcomeCategory(analysis["outcome_category"])
        result.universal_conclusions = analysis["universal_conclusions"]
        result.summary = self.comparator.generate_summary(result)

        return result

    async def _run_scenario_debate(
        self,
        task: str,
        scenario: Scenario,
        base_context: str,
    ) -> ScenarioResult:
        """Run a single debate for a scenario."""

        # Apply scenario to context
        context = scenario.apply_to_context(base_context)

        # Modify task with scenario info
        scenario_task = f"{task}\n\n[Scenario: {scenario.name}]\n{scenario.description}"

        start_time = datetime.now()

        try:
            # Call the debate function
            debate_result = await self.debate_func(scenario_task, context)

            duration = (datetime.now() - start_time).total_seconds()

            return ScenarioResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                conclusion=getattr(debate_result, "final_answer", str(debate_result)),
                confidence=getattr(debate_result, "confidence", 0.5),
                consensus_reached=getattr(debate_result, "consensus_reached", True),
                key_claims=getattr(debate_result, "key_claims", []),
                dissenting_views=getattr(debate_result, "dissenting_views", []),
                duration_seconds=duration,
                rounds=getattr(debate_result, "rounds", 0),
            )

        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.warning("Scenario %s debate cancelled or timed out: %s", scenario.name, e)
            return ScenarioResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                conclusion="Scenario debate timed out or was cancelled",
                confidence=0.0,
                consensus_reached=False,
                metadata={"error": "timeout_or_cancelled", "error_type": "timeout"},
            )
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("Scenario %s debate data error: %s", scenario.name, e)
            return ScenarioResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                conclusion="Scenario debate encountered a data error",
                confidence=0.0,
                consensus_reached=False,
                metadata={"error": "data_error", "error_type": "data"},
            )
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            logger.exception("Unexpected error in scenario %s debate: %s", scenario.name, e)
            return ScenarioResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                conclusion="Scenario debate encountered an unexpected error",
                confidence=0.0,
                consensus_reached=False,
                metadata={"error": "internal_error", "error_type": "unexpected"},
            )


# Convenience functions for common scenario patterns


def create_scale_scenarios() -> list[Scenario]:
    """Create scenarios for different scales."""
    return [
        Scenario(
            id="small",
            name="Small Scale",
            scenario_type=ScenarioType.SCALE,
            description="Small-scale deployment (10-100 users)",
            parameters={"users": 100, "data_gb": 1},
            constraints=["Limited budget", "Single server"],
        ),
        Scenario(
            id="medium",
            name="Medium Scale",
            scenario_type=ScenarioType.SCALE,
            description="Medium-scale deployment (1K-10K users)",
            parameters={"users": 5000, "data_gb": 100},
            constraints=["Moderate budget", "Small team"],
        ),
        Scenario(
            id="large",
            name="Large Scale",
            scenario_type=ScenarioType.SCALE,
            description="Large-scale deployment (100K+ users)",
            parameters={"users": 100000, "data_gb": 1000},
            constraints=["Enterprise requirements", "SLA requirements"],
        ),
    ]


def create_risk_scenarios() -> list[Scenario]:
    """Create scenarios for different risk tolerances."""
    return [
        Scenario(
            id="conservative",
            name="Conservative",
            scenario_type=ScenarioType.RISK_TOLERANCE,
            description="Risk-averse approach prioritizing stability",
            assumptions=["Prefer proven solutions", "Minimize change risk"],
        ),
        Scenario(
            id="moderate",
            name="Moderate",
            scenario_type=ScenarioType.RISK_TOLERANCE,
            description="Balanced approach to risk and reward",
            assumptions=["Accept calculated risks", "Balance innovation with stability"],
            is_baseline=True,
        ),
        Scenario(
            id="aggressive",
            name="Aggressive",
            scenario_type=ScenarioType.RISK_TOLERANCE,
            description="Growth-focused approach accepting higher risk",
            assumptions=["Prioritize innovation", "Accept higher failure rate"],
        ),
    ]


def create_time_horizon_scenarios() -> list[Scenario]:
    """Create scenarios for different time horizons."""
    return [
        Scenario(
            id="short_term",
            name="Short-Term",
            scenario_type=ScenarioType.TIME_HORIZON,
            description="Focus on next 3-6 months",
            parameters={"horizon_months": 6},
            constraints=["Quick implementation", "Minimal refactoring"],
        ),
        Scenario(
            id="medium_term",
            name="Medium-Term",
            scenario_type=ScenarioType.TIME_HORIZON,
            description="Focus on next 1-2 years",
            parameters={"horizon_months": 18},
            is_baseline=True,
        ),
        Scenario(
            id="long_term",
            name="Long-Term",
            scenario_type=ScenarioType.TIME_HORIZON,
            description="Focus on 3-5 year vision",
            parameters={"horizon_months": 48},
            constraints=["Allow architectural changes", "Consider future scaling"],
        ),
    ]

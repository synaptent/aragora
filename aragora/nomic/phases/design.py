"""
Design phase for nomic loop.

Phase 2: Implementation design
- Multi-agent design collaboration
- Gemini as design lead, others as critics
- Deadlock resolution via counterfactual branching
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from collections.abc import Callable

from . import DesignResult
from ..task_decomposer import TaskDecomposer, TaskDecomposition, DecomposerConfig

# Default protected files
DEFAULT_PROTECTED_FILES = [
    "CLAUDE.md",
    "aragora/__init__.py",
    "aragora/core/__init__.py",
    "aragora/core_types.py",
    ".env",
    "scripts/nomic_loop.py",
]

SAFETY_PREAMBLE = """SAFETY RULES:
1. NEVER delete or modify protected files
2. EXTEND existing APIs, don't break them
3. Focus on MINIMAL viable implementation
4. Prefer simple, direct solutions"""


@dataclass
class DesignConfig:
    """Configuration for design phase."""

    rounds: int = 2
    consensus_mode: str = "judge"
    judge_selection: str = "elo_ranked"
    proposer_count: int = 1
    early_stopping: bool = True
    early_stop_threshold: float = 0.66
    min_rounds_before_early_stop: int = 1
    protected_files: list[str] | None = None
    # Task decomposition settings
    enable_decomposition: bool = True
    decomposition_threshold: int = 6  # Complexity score (1-10) above which to decompose
    max_subtasks: int = 4

    def __post_init__(self):
        if self.protected_files is None:
            self.protected_files = DEFAULT_PROTECTED_FILES


@dataclass
class BeliefContext:
    """Belief analysis context from debate phase."""

    contested_count: int = 0
    crux_count: int = 0
    posteriors: dict[str, Any] | None = None
    convergence_achieved: bool = False

    def to_string(self) -> str:
        """Convert to context string for design prompt."""
        if self.contested_count == 0 and self.crux_count == 0:
            return ""

        lines = ["\n## UNCERTAINTY FROM DEBATE"]
        lines.append(
            f"The debate identified {self.contested_count} contested claims "
            f"and {self.crux_count} crux (high-impact disputed) claims."
        )

        if self.crux_count > 0:
            lines.append("Your design MUST address these disputed points explicitly.")

        if self.posteriors:
            lines.append("Key uncertainty areas:")
            for claim_id, dist in list(self.posteriors.items())[:3]:
                if isinstance(dist, dict) and dist.get("entropy", 0) > 0.5:
                    lines.append(f"  - {claim_id}: entropy={dist.get('entropy', 0):.2f}")

        if self.convergence_achieved:
            lines.append("\n[Belief network converged - good consensus foundation]")
        else:
            lines.append("\n[Belief network did NOT converge - proceed with caution]")

        return "\n".join(lines)


class DesignPhase:
    """
    Handles the implementation design phase.

    Orchestrates multi-agent design collaboration where Gemini leads
    and other agents critique to produce a detailed implementation plan.
    """

    def __init__(
        self,
        aragora_path: Path,
        agents: list[Any] | None = None,
        arena_factory: Callable[..., Any] | None = None,
        environment_factory: Callable[..., Any] | None = None,
        protocol_factory: Callable[..., Any] | None = None,
        config: DesignConfig | None = None,
        nomic_integration: Any | None = None,
        deep_audit_fn: Callable[..., Any] | None = None,
        arbitrate_fn: Callable[..., Any] | None = None,
        max_cycle_seconds: int = 3600,
        cycle_count: int = 0,
        log_fn: Callable[[str], None] | None = None,
        stream_emit_fn: Callable[..., None] | None = None,
        record_replay_fn: Callable[..., None] | None = None,
        # Legacy API compatibility
        claude_agent: Any | None = None,
        protected_files: list[str] | None = None,
        auto_approve_threshold: float = 0.5,
    ):
        """
        Initialize the design phase.

        Args:
            aragora_path: Path to the aragora project root
            agents: List of agent instances for design
            arena_factory: Factory to create Arena instances
            environment_factory: Factory to create Environment instances
            protocol_factory: Factory to create DebateProtocol instances
            config: Design configuration
            nomic_integration: Optional NomicIntegration for probing/checkpointing
            deep_audit_fn: Optional function for deep audit
            arbitrate_fn: Optional function for design arbitration
            max_cycle_seconds: Maximum cycle time budget
            cycle_count: Current cycle number
            log_fn: Function to log messages
            stream_emit_fn: Function to emit streaming events
            record_replay_fn: Function to record replay events
        """
        self.aragora_path = aragora_path

        # Handle legacy API: individual agent -> agents list
        if agents is not None:
            self.agents = agents
        elif claude_agent:
            self.agents = [claude_agent]
        else:
            self.agents = []

        self._arena_factory = arena_factory
        self._environment_factory = environment_factory
        self._protocol_factory = protocol_factory
        self.config = config or DesignConfig()
        self.nomic_integration = nomic_integration
        self._deep_audit = deep_audit_fn
        self._arbitrate = arbitrate_fn
        self.max_cycle_seconds = max_cycle_seconds
        self.cycle_count = cycle_count
        self._log = log_fn or print
        self._stream_emit = stream_emit_fn or (lambda *args: None)
        self._record_replay = record_replay_fn or (lambda *args: None)

        # Legacy API attributes
        self.claude = claude_agent
        self.protected_files = protected_files or DEFAULT_PROTECTED_FILES
        self.auto_approve_threshold = auto_approve_threshold

        # Task decomposition
        self._decomposer = TaskDecomposer(
            config=DecomposerConfig(
                complexity_threshold=self.config.decomposition_threshold,
                max_subtasks=self.config.max_subtasks,
            )
        )

    # =========================================================================
    # Legacy API methods (for backward compatibility with tests)
    # =========================================================================

    async def run(
        self,
        proposal: dict[str, Any] | None = None,
        winning_proposal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Legacy API: Run the design phase.

        Args:
            proposal: Proposal from debate phase
            winning_proposal: Alternative name for proposal (for compatibility)

        Returns:
            Design result dictionary
        """
        # Support both parameter names
        prop = proposal or winning_proposal or {}

        # Generate design
        design = await self.generate_design(prop)

        # Identify affected files
        affected_files = await self.identify_affected_files(design)

        # Review safety
        safety_result = await self.safety_review(design)

        if not safety_result.get("safe", True):
            return {
                "approved": False,
                "design": design,
                "safety_review": safety_result,
                "affected_files": affected_files,
                "error": safety_result.get("reason", "Safety review failed"),
            }

        # Run approval flow
        approval_result = await self.approve_design(design)

        return {
            "approved": approval_result.get("approved", False),
            "design": design,
            "affected_files": affected_files,
            "safety_review": safety_result,
            "requires_human_approval": approval_result.get("requires_human_review", False),
            "auto_approved": approval_result.get("auto_approved", False),
        }

    async def generate_design(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """
        Legacy API: Generate design from proposal.

        Args:
            proposal: Proposal to design for

        Returns:
            Design specification dictionary
        """
        return await self._generate_design(proposal)

    async def _generate_design(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """
        Internal method for design generation.

        Args:
            proposal: Proposal to design for

        Returns:
            Design specification dictionary
        """
        # Default implementation using agent if available
        if self.claude:
            prompt = f"Design an implementation for: {proposal.get('proposal', str(proposal))}"
            response = await self.claude.generate(prompt)
            return {
                "description": response,
                "components": [],
                "files_to_modify": [],
                "files_to_create": [],
            }

        # Default empty design
        return {
            "description": proposal.get("proposal", ""),
            "components": [],
            "files_to_modify": [],
            "files_to_create": [],
        }

    async def identify_affected_files(self, design: dict[str, Any]) -> list[str]:
        """
        Legacy API: Identify files affected by the design.

        Args:
            design: Design specification

        Returns:
            List of affected file paths
        """
        return await self._identify_files(design)

    async def _identify_files(self, design: dict[str, Any]) -> list[str]:
        """
        Internal method for file identification.

        Args:
            design: Design specification

        Returns:
            List of affected file paths
        """
        files = []
        files.extend(design.get("files_to_modify", []))
        files.extend(design.get("files_to_create", []))
        return files

    async def safety_review(self, design: dict[str, Any]) -> dict[str, Any]:
        """
        Legacy API: Review safety of the design.

        Args:
            design: Design specification

        Returns:
            Safety review result
        """
        affected_files = await self.identify_affected_files(design)
        issues = []
        risk_patterns = []

        # Check for protected file modifications
        for file_path in affected_files:
            for protected in self.protected_files:
                if protected in file_path:
                    issues.append(f"Protected file would be modified: {file_path}")

        # Check for high-risk patterns in description
        description = design.get("description", "")
        pattern_result = self._check_risk_patterns(description)
        if pattern_result.get("high_risk"):
            risk_patterns.extend(pattern_result.get("patterns_found", []))

        # Also check with basic keywords as fallback
        high_risk_keywords = ["delete", "remove", "drop", "truncate", "destroy"]
        for keyword in high_risk_keywords:
            if keyword in description.lower():
                pattern_str = f"High-risk keyword detected: {keyword}"
                if pattern_str not in risk_patterns:
                    risk_patterns.append(pattern_str)

        is_safe = len(issues) == 0
        risk_level = "high" if risk_patterns else "medium" if len(affected_files) > 5 else "low"
        risk_score = 0.8 if risk_level == "high" else 0.5 if risk_level == "medium" else 0.2

        return {
            "safe": is_safe,
            "issues": issues,
            "risk_patterns": risk_patterns,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "requires_review": len(risk_patterns) > 0,
            "reason": "; ".join(issues) if issues else "Design is safe",
        }

    def _check_risk_patterns(self, description: str) -> dict[str, Any]:
        """
        Check for high-risk patterns in design description.

        Args:
            description: Design description text

        Returns:
            Risk pattern analysis result
        """
        dangerous_patterns = [
            "eval",
            "exec",
            "subprocess",
            "os.system",
            "shell=True",
            "__import__",
            "compile(",
        ]
        patterns_found = []

        desc_lower = description.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in desc_lower:
                patterns_found.append(pattern)

        return {
            "high_risk": len(patterns_found) > 0,
            "patterns_found": patterns_found,
        }

    async def approve_design(self, design: dict[str, Any]) -> dict[str, Any]:
        """
        Approve or flag design for review.

        Args:
            design: Design specification

        Returns:
            Approval result with approved, auto_approved, requires_human_review flags
        """
        # Get safety review
        safety_result = await self.safety_review(design)

        # If not safe, reject
        if not safety_result.get("safe", True):
            return {
                "approved": False,
                "auto_approved": False,
                "requires_human_review": True,
                "reason": safety_result.get("reason", "Safety check failed"),
            }

        # Get risk score
        risk_score = safety_result.get("risk_score", design.get("risk_score", 0.5))

        # Auto-approve if risk is below threshold
        if risk_score < self.auto_approve_threshold:
            return {
                "approved": True,
                "auto_approved": True,
                "requires_human_review": False,
                "risk_score": risk_score,
            }

        # High risk - requires human review
        return {
            "approved": False,
            "auto_approved": False,
            "requires_human_review": True,
            "risk_score": risk_score,
            "reason": f"Risk score {risk_score} exceeds threshold {self.auto_approve_threshold}",
        }

    # =========================================================================
    # Original execute method
    # =========================================================================

    async def execute(
        self,
        improvement: str,
        belief_context: BeliefContext | None = None,
        learning_context: str = "",
        arena_kwargs: dict[str, Any] | None = None,
    ) -> DesignResult:
        """
        Execute the design phase.

        Args:
            improvement: The improvement proposal from debate phase
            belief_context: Optional belief analysis from debate
            learning_context: Optional learning context (patterns, etc.)
            arena_kwargs: Additional kwargs for Arena creation

        Returns:
            DesignResult with design outcome
        """
        phase_start = datetime.now()
        self._log("\n" + "=" * 70)
        self._log("PHASE 2: IMPLEMENTATION DESIGN")
        self._log("=" * 70)
        self._stream_emit(
            "on_phase_start", "design", self.cycle_count, {"agents": len(self.agents)}
        )
        self._record_replay("phase", "system", "design")

        # Check if deep audit needed
        if self._deep_audit:
            audit_result = await self._check_deep_audit(improvement)
            if audit_result and not audit_result.get("approved", True):
                return self._rejected_result(phase_start, audit_result)

        # Task decomposition for complex improvements
        if self.config.enable_decomposition:
            decomposition = self._decomposer.analyze(improvement)
            if decomposition.should_decompose and len(decomposition.subtasks) > 1:
                self._log(
                    f"  [decomposition] Task complexity {decomposition.complexity_score}/10 "
                    f"- splitting into {len(decomposition.subtasks)} subtasks"
                )
                self._stream_emit(
                    "on_task_decomposed",
                    self.cycle_count,
                    decomposition.complexity_score,
                    [st.title for st in decomposition.subtasks],
                )
                return await self._execute_decomposed(
                    decomposition,
                    belief_context,
                    learning_context,
                    arena_kwargs,
                    phase_start,
                )
            else:
                self._log(
                    f"  [decomposition] Task complexity {decomposition.complexity_score}/10 "
                    f"- proceeding as single task"
                )

        # Build design prompt
        design_prompt = self._build_design_prompt(
            improvement,
            belief_context or BeliefContext(),
            learning_context,
        )

        environment_factory, protocol_factory, arena_factory = self._require_factories()

        # Create environment
        env = environment_factory(
            task=design_prompt,
            context=f"Working directory: {self.aragora_path}\n\nProtected files (NEVER delete): {self.config.protected_files}",
        )

        # Create protocol
        protocol = protocol_factory(
            rounds=self.config.rounds,
            consensus=self.config.consensus_mode,
            judge_selection=self.config.judge_selection,
            proposer_count=self.config.proposer_count,
            early_stopping=self.config.early_stopping,
            early_stop_threshold=self.config.early_stop_threshold,
            min_rounds_before_early_stop=self.config.min_rounds_before_early_stop,
        )

        self._log("  [hybrid] Lead agent as design lead, others as critics")

        # Probe agents for reliability
        agent_weights = await self._probe_agents()

        # Create arena
        arena = arena_factory(
            env,
            self.agents,
            protocol,
            agent_weights=agent_weights,
            **(arena_kwargs or {}),
        )

        # Run design debate
        result = await arena.run()

        # Handle no consensus with fast-track arbitration
        if not result.consensus_reached:
            result = await self._handle_no_consensus(result, arena, improvement, phase_start)

        # Extract proposals and votes
        individual_proposals = self._extract_proposals(result)
        vote_counts = self._count_votes(result)

        # Checkpoint
        await self._checkpoint(result, agent_weights)

        # Build result
        phase_duration = (datetime.now() - phase_start).total_seconds()
        self._stream_emit(
            "on_phase_end", "design", self.cycle_count, result.consensus_reached, phase_duration, {}
        )

        # Identify affected files
        files_affected = self._extract_files_from_design(result.final_answer or "")

        return DesignResult(
            success=result.consensus_reached,
            data={
                "individual_proposals": individual_proposals,
                "vote_counts": vote_counts,
                "agent_weights": agent_weights,
            },
            duration_seconds=phase_duration,
            design=result.final_answer or "",
            files_affected=files_affected,
            complexity_estimate=self._estimate_complexity(result.final_answer or ""),
        )

    async def _execute_decomposed(
        self,
        decomposition: TaskDecomposition,
        belief_context: BeliefContext | None,
        learning_context: str,
        arena_kwargs: dict[str, Any] | None,
        phase_start: datetime,
    ) -> DesignResult:
        """Execute design phase for a decomposed task.

        Runs design for each subtask and merges the results.
        """
        subtask_designs: list[str] = []
        all_files_affected: list[str] = []
        all_proposals: dict[str, str] = {}
        total_complexity = 0

        for i, subtask in enumerate(decomposition.subtasks, 1):
            self._log(f"\n  [subtask {i}/{len(decomposition.subtasks)}] {subtask.title}")
            self._stream_emit(
                "on_subtask_start",
                self.cycle_count,
                subtask.id,
                subtask.title,
            )

            # Build subtask-specific improvement prompt
            subtask_improvement = (
                f"## Subtask: {subtask.title}\n\n"
                f"{subtask.description}\n\n"
                f"**Context:** This is subtask {i} of {len(decomposition.subtasks)} "
                f"for the larger task:\n{decomposition.original_task[:500]}"
            )

            # Build design prompt for this subtask
            design_prompt = self._build_design_prompt(
                subtask_improvement,
                belief_context or BeliefContext(),
                learning_context,
            )

            environment_factory, protocol_factory, arena_factory = self._require_factories()

            # Create environment
            env = environment_factory(
                task=design_prompt,
                context=(
                    f"Working directory: {self.aragora_path}\n\n"
                    f"Protected files (NEVER delete): {self.config.protected_files}"
                ),
            )

            # Create protocol
            protocol = protocol_factory(
                rounds=self.config.rounds,
                consensus=self.config.consensus_mode,
                judge_selection=self.config.judge_selection,
                proposer_count=self.config.proposer_count,
                early_stopping=self.config.early_stopping,
                early_stop_threshold=self.config.early_stop_threshold,
                min_rounds_before_early_stop=self.config.min_rounds_before_early_stop,
            )

            # Probe agents
            agent_weights = await self._probe_agents()

            # Create arena and run
            arena = arena_factory(
                env,
                self.agents,
                protocol,
                agent_weights=agent_weights,
                **(arena_kwargs or {}),
            )

            result = await arena.run()

            # Handle no consensus
            if not result.consensus_reached:
                result = await self._handle_no_consensus(
                    result, arena, subtask_improvement, phase_start
                )

            # Collect subtask results
            if result.final_answer:
                subtask_designs.append(f"### Subtask {i}: {subtask.title}\n\n{result.final_answer}")
                all_files_affected.extend(self._extract_files_from_design(result.final_answer))

            # Collect proposals
            proposals = self._extract_proposals(result)
            for agent, proposal in proposals.items():
                all_proposals[f"{agent}_subtask{i}"] = proposal

            # Track complexity
            complexity = self._estimate_complexity(result.final_answer or "")
            total_complexity += {"low": 1, "medium": 2, "high": 3}.get(complexity, 1)

            self._stream_emit(
                "on_subtask_end",
                self.cycle_count,
                subtask.id,
                result.consensus_reached,
            )

        # Merge all subtask designs
        merged_design = self._merge_subtask_designs(
            decomposition.original_task,
            subtask_designs,
            decomposition,
        )

        # Calculate phase duration
        phase_duration = (datetime.now() - phase_start).total_seconds()
        self._stream_emit(
            "on_phase_end",
            "design",
            self.cycle_count,
            len(subtask_designs) > 0,
            phase_duration,
            {"decomposed": True, "subtask_count": len(decomposition.subtasks)},
        )

        # Determine overall complexity
        avg_complexity = total_complexity / max(len(decomposition.subtasks), 1)
        overall_complexity = (
            "high" if avg_complexity > 2 else "medium" if avg_complexity > 1 else "low"
        )

        return DesignResult(
            success=len(subtask_designs) > 0,
            data={
                "individual_proposals": all_proposals,
                "vote_counts": {},
                "agent_weights": {},
                "decomposed": True,
                "subtask_count": len(decomposition.subtasks),
                "subtask_titles": [st.title for st in decomposition.subtasks],
            },
            duration_seconds=phase_duration,
            design=merged_design,
            files_affected=list(set(all_files_affected))[:15],
            complexity_estimate=overall_complexity,
        )

    def _merge_subtask_designs(
        self,
        original_task: str,
        subtask_designs: list[str],
        decomposition: TaskDecomposition,
    ) -> str:
        """Merge subtask designs into a coherent overall design."""
        if not subtask_designs:
            return ""

        header = (
            f"# Decomposed Design\n\n"
            f"**Original Task:** {original_task[:200]}{'...' if len(original_task) > 200 else ''}\n\n"
            f"**Decomposition Rationale:** {decomposition.rationale}\n\n"
            f"---\n\n"
        )

        body = "\n\n---\n\n".join(subtask_designs)

        footer = (
            f"\n\n---\n\n"
            f"## Integration Notes\n\n"
            f"This design was decomposed into {len(subtask_designs)} subtasks. "
            f"Implementation should follow the subtask order, respecting dependencies:\n\n"
        )

        for st in decomposition.subtasks:
            deps = ", ".join(st.dependencies) if st.dependencies else "none"
            footer += f"- **{st.title}** (complexity: {st.estimated_complexity}, deps: {deps})\n"

        return header + body + footer

    def _require_factories(
        self,
    ) -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
        if (
            self._environment_factory is None
            or self._protocol_factory is None
            or self._arena_factory is None
        ):
            raise RuntimeError(
                "DesignPhase.execute requires arena_factory, environment_factory "
                "and protocol_factory"
            )
        return self._environment_factory, self._protocol_factory, self._arena_factory

    async def _check_deep_audit(self, improvement: str) -> dict | None:
        """Check if deep audit is needed and run it."""
        deep_audit = self._deep_audit
        if deep_audit is None:
            return None
        try:
            should_audit, reason = deep_audit("check", improvement, phase="design")
            if should_audit:
                self._log(f"  [deep-audit] {reason}")
                return await deep_audit("run", improvement)
        except (RuntimeError, ValueError, OSError) as e:
            self._log(f"  [deep-audit] Check failed: {e}")
        return None

    def _rejected_result(self, phase_start: datetime, audit_result: dict) -> DesignResult:
        """Create a rejected result from deep audit."""
        self._log("  [deep-audit] Design rejected - returning issues for rework")
        phase_duration = (datetime.now() - phase_start).total_seconds()
        self._stream_emit("on_phase_end", "design", self.cycle_count, False, phase_duration)
        return DesignResult(
            success=False,
            error="Rejected by deep audit",
            data={
                "rejected_by_deep_audit": True,
                "issues": audit_result.get("unanimous_issues", []),
            },
            duration_seconds=phase_duration,
            design="",
            files_affected=[],
            complexity_estimate="blocked",
        )

    def _build_design_prompt(
        self,
        improvement: str,
        belief: BeliefContext,
        learning: str,
    ) -> str:
        """Build the design task prompt."""
        belief_text = belief.to_string()
        combined_learning = f"{learning}\n{belief_text}" if belief_text else learning

        return f"""{SAFETY_PREAMBLE}

## DESIGN TASK
Create a detailed implementation design for this improvement:

{improvement}

## CONTEXT FROM PRIOR LEARNING
{combined_learning}

## REQUIRED DESIGN SECTIONS

### 1. FILE CHANGES (Required)
List EVERY file to create or modify. Be specific:
- `aragora/path/file.py` - Create new | Modify existing
- Estimated lines of code per file
- NEVER delete or modify protected files: {self.config.protected_files}

### 2. API DESIGN (Required)
Define the public interface:
```python
class ClassName:
    def method_name(self, param: Type) -> ReturnType:
        '''Docstring explaining purpose.'''
        ...
```
- EXTEND existing APIs, don't break them

### 3. INTEGRATION POINTS (Required)
How does this connect to existing modules?
- Which existing classes/functions does it use?
- Which existing classes/functions call it?

### 4. TEST PLAN (Required)
Concrete test cases:
- Unit tests: `test_feature_basic()`, `test_feature_edge_case()`
- Integration tests if needed

### 5. EXAMPLE USAGE (Required)
Working code snippet showing the feature in action.

## REQUIRED: Viability Checklist
- [ ] At least 3 specific file changes with estimated line counts
- [ ] At least 2 function/class signatures with parameters
- [ ] At least 1 integration point showing how components connect
- [ ] 1 concrete example of how to use the feature

Designs missing any of these will be automatically rejected."""

    async def _probe_agents(self) -> dict[str, float]:
        """Probe agents for reliability weights."""
        if not self.nomic_integration:
            return {}

        try:
            self._log("  [integration] Probing agents for reliability...")
            weights = await self.nomic_integration.probe_agents(
                self.agents,
                probe_count=2,
                min_weight=0.5,
            )
            reliable = sum(1 for w in weights.values() if w >= 0.7)
            self._log(f"  [integration] Agent weights: {reliable}/{len(self.agents)} reliable")
            return weights
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            self._log(f"  [integration] Probing failed: {e}")
            return {}

    async def _handle_no_consensus(
        self,
        result: Any,
        arena: Any,
        improvement: str,
        phase_start: datetime,
    ) -> Any:
        """Handle case when no consensus is reached."""
        elapsed = (datetime.now() - phase_start).total_seconds()
        remaining = self.max_cycle_seconds - elapsed

        # Fast-track arbitration if low on time
        if remaining < 600 and self._arbitrate:
            self._log(f"  [fast-track] Time budget critical ({remaining:.0f}s left)")
            proposals = self._extract_proposals(result)
            if len(proposals) >= 2:
                arbitrated = await self._arbitrate(proposals, improvement)
                if arbitrated:
                    result.final_answer = arbitrated
                    result.consensus_reached = True
                    result.confidence = 0.7
                    self._log("  [fast-track] Judge selected design")
                    return result

        # Try counterfactual resolution via nomic integration
        if self.nomic_integration:
            result = await self._counterfactual_resolution(result, arena)

        return result

    async def _counterfactual_resolution(self, result: Any, arena: Any) -> Any:
        """Attempt counterfactual resolution for deadlock."""
        integration = self.nomic_integration
        if integration is None:
            return result
        try:
            self._log("  [deadlock] No design consensus - attempting resolution...")
            post_analysis = await integration.full_post_debate_analysis(
                result=result,
                arena=arena,
                claims_kernel=None,
                changed_files=None,
            )

            conditional = post_analysis.get("conditional")
            if conditional:
                self._log("  [deadlock] Resolved with conditional consensus")
                if hasattr(conditional, "synthesized_answer") and conditional.synthesized_answer:
                    result.final_answer = conditional.synthesized_answer
                    result.consensus_reached = True
                    result.confidence = getattr(conditional, "confidence", 0.7)
                elif hasattr(conditional, "if_true_conclusion"):
                    result.final_answer = self._build_conditional_design(conditional)
                    result.consensus_reached = True
                    result.confidence = max(
                        conditional.if_true_confidence or 0.5,
                        conditional.if_false_confidence or 0.5,
                    )
        except (RuntimeError, OSError, ValueError) as e:
            self._log(f"  [deadlock] Resolution failed: {e}")

        return result

    def _build_conditional_design(self, conditional: Any) -> str:
        """Build conditional design from branches."""
        pivot = getattr(conditional, "pivot_claim", None)
        pivot_text = pivot.text if pivot and hasattr(pivot, "text") else "the disputed assumption"
        return (
            f"## CONDITIONAL DESIGN\n\n"
            f"**Key Decision Point:** {pivot_text}\n\n"
            f"### If True:\n{conditional.if_true_conclusion}\n\n"
            f"### If False:\n{conditional.if_false_conclusion}\n\n"
            f"**Recommended Path:** "
            f"{'True assumption' if conditional.preferred_world else 'False assumption'}"
        )

    def _extract_proposals(self, result: Any) -> dict[str, str]:
        """Extract individual proposals from messages."""
        proposals = {}
        if hasattr(result, "messages"):
            for msg in result.messages:
                if msg.role == "proposer" and msg.content:
                    proposals[msg.agent] = msg.content
        return proposals

    def _count_votes(self, result: Any) -> dict[str, int]:
        """Count votes from result."""
        counts: dict[str, int] = {}
        if hasattr(result, "votes"):
            for vote in result.votes:
                choice = vote.choice
                counts[choice] = counts.get(choice, 0) + 1
        return counts

    async def _checkpoint(self, result: Any, agent_weights: dict) -> None:
        """Checkpoint the design phase."""
        if not self.nomic_integration:
            return

        try:
            await self.nomic_integration.checkpoint(
                phase="design",
                state={"design": result.final_answer, "agent_weights": agent_weights},
                cycle=self.cycle_count,
            )
        except (RuntimeError, ValueError, OSError) as e:
            self._log(f"  [integration] Checkpoint failed: {e}")

    def _extract_files_from_design(self, design: str) -> list[str]:
        """Extract file paths mentioned in the design."""
        import re

        files = []
        # Match patterns like `aragora/path/file.py` or aragora/path/file.py
        pattern = r"`?(aragora/[a-zA-Z0-9_/]+\.py)`?"
        matches = re.findall(pattern, design)
        files.extend(matches)
        return list(set(files))[:10]  # Limit to 10 files

    def _estimate_complexity(self, design: str) -> str:
        """Estimate implementation complexity."""
        if not design:
            return "unknown"

        lines_mentioned = design.lower().count("lines")
        file_count = len(self._extract_files_from_design(design))

        if file_count > 5 or "complex" in design.lower():
            return "high"
        elif file_count > 2 or lines_mentioned > 3:
            return "medium"
        else:
            return "low"


__all__ = ["DesignPhase", "DesignConfig", "BeliefContext"]

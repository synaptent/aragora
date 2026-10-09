"""
Deep Audit Mode - Heavy3.ai-inspired intensive debate protocol.

Deep Audit runs 6 chained research rounds with:
1. Cognitive role rotation (Analyst, Skeptic, Lateral Thinker)
2. Parallel tool integration (web research per round)
3. Synthesizer cross-examination at the end
4. Verdicts with citations and risk assessment

Use for high-stakes decisions: strategy, contracts, code architecture,
legal documentation where blind spots carry significant consequences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from aragora.debate.disagreement import DisagreementReport

logger = logging.getLogger(__name__)

from aragora.core import Agent, DebateResult, Environment
from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.debate.roles import (
    CognitiveRole,
    RoleRotationConfig,
    RoleRotator,
)


@dataclass
class DeepAuditConfig:
    """Configuration for Deep Audit mode."""

    # Number of research rounds (Heavy3 uses 6)
    rounds: int = 6

    # Enable web research between rounds
    enable_research: bool = True

    # Cognitive roles to rotate through
    roles: list[CognitiveRole] = field(
        default_factory=lambda: [
            CognitiveRole.ANALYST,
            CognitiveRole.SKEPTIC,
            CognitiveRole.LATERAL_THINKER,
            CognitiveRole.ADVOCATE,
        ]
    )

    # Force synthesizer in final round
    synthesizer_final_round: bool = True

    # Cross-examination settings
    cross_examination_depth: int = 3  # Questions per finding
    require_citations: bool = True

    # Risk threshold for flagging issues
    risk_threshold: float = 0.7


@dataclass
class AuditFinding:
    """A finding from the Deep Audit process."""

    category: str  # "unanimous", "split", "risk", "insight"
    summary: str
    details: str
    agents_agree: list[str] = field(default_factory=list)
    agents_disagree: list[str] = field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = field(default_factory=list)
    severity: float = 0.0  # 0-1, higher = more critical


@dataclass
class DeepAuditVerdict:
    """The final verdict from a Deep Audit."""

    recommendation: str
    confidence: float
    findings: list[AuditFinding] = field(default_factory=list)
    unanimous_issues: list[str] = field(default_factory=list)
    split_opinions: list[str] = field(default_factory=list)
    risk_areas: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    cross_examination_notes: str = ""

    def summary(self) -> str:
        """Generate a human-readable summary."""
        lines = ["=" * 60, "DEEP AUDIT VERDICT", "=" * 60]

        lines.append(f"\nRecommendation: {self.recommendation[:500]}")
        lines.append(f"Confidence: {self.confidence:.0%}")

        if self.unanimous_issues:
            lines.append(f"\n{len(self.unanimous_issues)} UNANIMOUS ISSUES (address immediately):")
            for issue in self.unanimous_issues[:5]:
                lines.append(f"  - {issue[:200]}")

        if self.split_opinions:
            lines.append(f"\n{len(self.split_opinions)} SPLIT OPINIONS (review carefully):")
            for opinion in self.split_opinions[:5]:
                lines.append(f"  - {opinion[:200]}")

        if self.risk_areas:
            lines.append(f"\n{len(self.risk_areas)} RISK AREAS (monitor):")
            for risk in self.risk_areas[:5]:
                lines.append(f"  - {risk[:200]}")

        if self.citations:
            lines.append(f"\nCitations ({len(self.citations)}):")
            for citation in self.citations[:5]:
                lines.append(f"  - {citation[:100]}")

        return "\n".join(lines)


class DeepAuditOrchestrator:
    """
    Orchestrates Deep Audit debates with intensive multi-round analysis.

    Heavy3-inspired features:
    1. 6 chained research rounds
    2. Cognitive role rotation per round
    3. Parallel tool integration
    4. Synthesizer cross-examination
    5. Verdicts with scholarly references
    """

    def __init__(
        self,
        agents: list[Agent],
        config: DeepAuditConfig | None = None,
        research_fn: Callable[[str], Awaitable[str]] | None = None,
    ):
        self.agents = agents
        self.config = config or DeepAuditConfig()
        self.research_fn = research_fn  # Optional function for web research

        # Initialize role rotator
        self.role_rotator = RoleRotator(
            RoleRotationConfig(
                enabled=True,
                roles=self.config.roles,
                ensure_coverage=True,
                synthesizer_final_round=self.config.synthesizer_final_round,
            )
        )

        # Tracking
        self.findings: list[AuditFinding] = []
        self.round_summaries: list[str] = []
        self.citations: list[str] = []

    async def run(self, task: str, context: str = "") -> DeepAuditVerdict:
        """
        Run a Deep Audit on the given task.

        Args:
            task: The question/decision to audit
            context: Additional context (documents, background info)

        Returns:
            DeepAuditVerdict with recommendation and findings
        """
        logger.info("=" * 60)
        logger.info("DEEP AUDIT MODE")
        logger.info("Task: %s...", task[:80])
        logger.info("Rounds: %s", self.config.rounds)
        logger.info("Agents: %s", ", ".join(a.name for a in self.agents))
        logger.info("=" * 60)

        env = Environment(task=task, context=context)

        # Build protocol with role rotation
        protocol = DebateProtocol(
            rounds=self.config.rounds,
            consensus="judge",  # Use judge for final synthesis
            role_rotation=True,
            role_rotation_config=RoleRotationConfig(
                enabled=True,
                roles=self.config.roles,
                synthesizer_final_round=True,
            ),
            enable_research=self.config.enable_research,
            early_stopping=False,  # Complete all rounds for thoroughness
        )

        # Create arena
        arena = Arena(env, self.agents, protocol)

        # Run the debate
        result = await arena.run()

        # === Cross-Examination Phase ===
        logger.info("-" * 40)
        logger.info("SYNTHESIZER CROSS-EXAMINATION")
        logger.info("-" * 40)

        cross_exam_notes = await self._run_cross_examination(
            task=task,
            result=result,
            findings=result.disagreement_report if result.disagreement_report else None,
        )

        # === Build Verdict ===
        verdict = self._build_verdict(result, cross_exam_notes)

        logger.info("\n%s", verdict.summary())

        return verdict

    async def _run_cross_examination(
        self,
        task: str,
        result: DebateResult,
        findings: DisagreementReport | None = None,
    ) -> str:
        """
        Run synthesizer cross-examination of all findings.

        The synthesizer asks probing questions about:
        1. Evidence quality for key claims
        2. Unaddressed counterarguments
        3. Hidden assumptions
        4. Risk blind spots
        """
        # Select synthesizer (use first agent if no role assigned)
        if not self.agents:
            logger.warning("No agents available for cross-examination")
            return "Cross-examination skipped: no agents available"
        synthesizer = self.agents[0]

        # Build cross-examination prompt
        proposals_summary = result.final_answer[:2000] if result.final_answer else "No final answer"
        critiques_summary = "\n".join(
            f"- {c.agent}: {c.issues[0][:100] if c.issues else 'No issues'}"
            for c in result.critiques[:10]
        )

        disagreement_summary = ""
        if findings:
            if findings.unanimous_critiques:
                disagreement_summary += f"\nUnanimous Issues: {len(findings.unanimous_critiques)}"
                for issue in findings.unanimous_critiques[:3]:
                    disagreement_summary += f"\n  - {issue[:100]}"
            if findings.split_opinions:
                disagreement_summary += f"\nSplit Opinions: {len(findings.split_opinions)}"

        cross_exam_prompt = f"""You are the SYNTHESIZER conducting final cross-examination.

The debate has concluded on this task:
{task}

Final Proposal Summary:
{proposals_summary[:1500]}

Key Critiques Raised:
{critiques_summary}
{disagreement_summary}

Your job is to cross-examine these findings by asking {self.config.cross_examination_depth} probing questions:

1. EVIDENCE QUALITY: What evidence supports the key claims? Are there gaps?
2. COUNTERARGUMENTS: What strong objections weren't fully addressed?
3. HIDDEN ASSUMPTIONS: What unstated assumptions underlie this recommendation?
4. RISK BLIND SPOTS: What risks might we be minimizing or ignoring?

For each question, provide:
- The question itself
- Your assessment of how well the debate addressed it
- Remaining concerns or open issues

Be rigorous but fair. Your goal is to ensure we haven't missed critical issues."""

        try:
            from aragora.server.stream.arena_hooks import streaming_task_context

            synth_name = getattr(synthesizer, "name", "synthesizer")
            task_id = f"{synth_name}:deep_audit_crossexam"
            with streaming_task_context(task_id):
                cross_exam_result = await synthesizer.generate(cross_exam_prompt, [])
            logger.info("Synthesizer cross-examination complete (%s chars)", len(cross_exam_result))
            return cross_exam_result
        except Exception as e:
            logger.warning("Cross-examination failed: %s", e)
            return f"Cross-examination failed: {e}"

    def _build_verdict(
        self,
        result: DebateResult,
        cross_exam_notes: str,
    ) -> DeepAuditVerdict:
        """Build the final verdict from debate results and cross-examination."""
        verdict = DeepAuditVerdict(
            recommendation=result.final_answer or "No recommendation reached",
            confidence=result.confidence,
            cross_examination_notes=cross_exam_notes,
        )

        # Extract findings from disagreement report
        if result.disagreement_report:
            report = result.disagreement_report
            verdict.unanimous_issues = report.unanimous_critiques.copy()
            verdict.risk_areas = report.risk_areas.copy()

            # Format split opinions
            for topic, agree, disagree in report.split_opinions:
                verdict.split_opinions.append(
                    f"{topic} (Agree: {', '.join(agree)}; Disagree: {', '.join(disagree)})"
                )

        # Add findings from critiques
        for critique in result.critiques:
            if critique.severity >= self.config.risk_threshold:
                finding = AuditFinding(
                    category="risk",
                    summary=critique.issues[0] if critique.issues else "High severity issue",
                    details=critique.reasoning,
                    agents_agree=[critique.agent],
                    confidence=1.0 - critique.severity,
                    severity=critique.severity,
                )
                verdict.findings.append(finding)

        return verdict


async def run_deep_audit(
    task: str,
    agents: list[Agent],
    context: str = "",
    config: DeepAuditConfig | None = None,
) -> DeepAuditVerdict:
    """
    Convenience function to run a Deep Audit.

    Args:
        task: The question/decision to audit
        agents: List of agents to participate
        context: Additional context
        config: Optional configuration

    Returns:
        DeepAuditVerdict with recommendation and findings
    """
    orchestrator = DeepAuditOrchestrator(agents, config)
    return await orchestrator.run(task, context)


# Pre-configured Deep Audit protocols for common use cases

STRATEGY_AUDIT = DeepAuditConfig(
    rounds=6,
    enable_research=True,
    roles=[
        CognitiveRole.ANALYST,
        CognitiveRole.SKEPTIC,
        CognitiveRole.LATERAL_THINKER,
        CognitiveRole.DEVIL_ADVOCATE,
    ],
    cross_examination_depth=4,
    require_citations=True,
)

CONTRACT_AUDIT = DeepAuditConfig(
    rounds=4,
    enable_research=False,  # Focus on document analysis
    roles=[
        CognitiveRole.ANALYST,
        CognitiveRole.SKEPTIC,
        CognitiveRole.ADVOCATE,
    ],
    cross_examination_depth=5,
    require_citations=True,
    risk_threshold=0.5,  # Lower threshold for contracts
)

CODE_ARCHITECTURE_AUDIT = DeepAuditConfig(
    rounds=5,
    enable_research=True,
    roles=[
        CognitiveRole.ANALYST,
        CognitiveRole.SKEPTIC,
        CognitiveRole.LATERAL_THINKER,
    ],
    cross_examination_depth=3,
    require_citations=False,
)

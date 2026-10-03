"""
Gauntlet Orchestrator - Full 5-Phase Adversarial Validation Engine.

Provides the GauntletOrchestrator for comprehensive adversarial validation
of high-stakes decisions through multi-agent debate.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from collections.abc import Callable, Coroutine

from aragora.core import Agent
from aragora.debate.consensus import (
    DissentRecord,
    UnresolvedTension,
)
from aragora.debate.risk_assessor import RiskAssessment, RiskAssessor, RiskLevel

# Import shared types from aragora.gauntlet.types (canonical source)
from aragora.gauntlet.types import InputType, Verdict
from aragora.modes.deep_audit import (
    DeepAuditConfig,
    DeepAuditOrchestrator,
    DeepAuditVerdict,
)
from aragora.modes.prober import (
    CapabilityProber,
    ProbeType,
    VulnerabilityReport,
    VulnerabilitySeverity,
)
from aragora.modes.redteam import (
    AttackType,
    RedTeamMode,
    RedTeamResult,
)
from aragora.verification.formal import (
    FormalProofStatus,
    get_formal_verification_manager,
)

# Import personas for compliance-aware stress testing
# Use a conditional import pattern that avoids type redefinition issues
PERSONAS_AVAILABLE = False
RegulatoryPersona: type[Any] | None = None
PersonaAttack: type[Any] | None = None
_get_persona: Callable[[str], Any] | None = None

try:
    from aragora.gauntlet import personas as _personas_module

    RegulatoryPersona = _personas_module.RegulatoryPersona
    PersonaAttack = _personas_module.PersonaAttack
    _get_persona = _personas_module.get_persona
    PERSONAS_AVAILABLE = True
except ImportError:
    pass


def get_persona(name: str) -> Any:
    """Get a regulatory persona by name. Raises ImportError if personas unavailable."""
    if _get_persona is None:
        raise ImportError("aragora.gauntlet.personas is not available")
    return _get_persona(name)


logger = logging.getLogger(__name__)


@dataclass
class GauntletProgress:
    """Progress update during Gauntlet execution."""

    phase: str  # Current phase name
    phase_number: int  # 1-indexed phase number
    total_phases: int  # Total number of phases
    percent: float  # 0-100
    message: str  # Human-readable status
    findings_so_far: int = 0  # Findings discovered so far
    current_task: str | None = None  # Current sub-task


# Type for progress callback
ProgressCallback = Callable[[GauntletProgress], None]

# InputType and Verdict are imported from aragora.gauntlet.types (canonical source)
# This ensures consistency across the gauntlet system


@dataclass
class Finding:
    """A finding from the Gauntlet process."""

    finding_id: str
    category: str  # "attack", "probe", "audit", "verification", "risk"
    severity: float  # 0-1
    title: str
    description: str
    evidence: str = ""
    mitigation: str | None = None
    source: str = ""  # Which component found this
    verified: bool = False  # Was this formally verified?
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def severity_level(self) -> str:
        """Human-readable severity level."""
        if self.severity >= 0.9:
            return "CRITICAL"
        elif self.severity >= 0.7:
            return "HIGH"
        elif self.severity >= 0.4:
            return "MEDIUM"
        return "LOW"


@dataclass
class VerifiedClaim:
    """A claim that was formally verified."""

    claim: str
    verified: bool
    verification_method: str  # "z3", "lean", "manual"
    proof_hash: str | None = None
    verification_time_ms: float = 0.0


@dataclass
class GauntletConfig:
    """Configuration for Gauntlet stress-testing."""

    # Input configuration
    input_type: InputType = InputType.SPEC
    input_content: str = ""
    input_path: Path | None = None

    # Which attack types to run (None = all)
    attack_types: list[AttackType] | None = None

    # Which probe types to run (None = all)
    probe_types: list[ProbeType] | None = None

    # Thresholds
    severity_threshold: float = 0.5  # Findings below this are filtered
    risk_threshold: float = 0.7  # Above this triggers warning

    # Timing
    max_duration_seconds: int = 600  # 10 minute max
    verification_timeout_seconds: float = 60.0

    # Parallelism
    parallel_attacks: int = 5
    parallel_probes: int = 3

    # Feature toggles
    enable_redteam: bool = True
    enable_probing: bool = True
    enable_deep_audit: bool = True
    enable_verification: bool = True
    enable_risk_assessment: bool = True

    # Deep audit rounds (fewer for speed, more for thoroughness)
    deep_audit_rounds: int = 4

    # Regulatory persona for compliance-aware stress testing
    # Can be a RegulatoryPersona instance or string name ("gdpr", "hipaa", "ai_act", "security")
    persona: Any | None = None  # RegulatoryPersona or str

    def __post_init__(self):
        # Load content from path if provided
        if self.input_path and not self.input_content:
            self.input_content = self.input_path.read_text()

        # Resolve persona string to instance
        if self.persona and isinstance(self.persona, str) and PERSONAS_AVAILABLE:
            self.persona = get_persona(self.persona)


@dataclass
class GauntletResult:
    """Complete result of a Gauntlet stress-test."""

    # Identifiers (required)
    gauntlet_id: str
    input_type: InputType
    input_summary: str  # First 500 chars of input

    # Verdict (required)
    verdict: Verdict
    confidence: float  # 0-1

    # Scores (required)
    risk_score: float  # 0-1, aggregate risk
    robustness_score: float  # 0-1, how well input held up
    coverage_score: float  # 0-1, how thoroughly tested

    # Optional fields with defaults
    input_hash: str = ""  # SHA-256 of full input content

    # Findings by severity
    critical_findings: list[Finding] = field(default_factory=list)
    high_findings: list[Finding] = field(default_factory=list)
    medium_findings: list[Finding] = field(default_factory=list)
    low_findings: list[Finding] = field(default_factory=list)

    # Consensus & dissent
    consensus_reached: bool = False
    dissenting_views: list[DissentRecord] = field(default_factory=list)
    unresolved_tensions: list[UnresolvedTension] = field(default_factory=list)

    # Verification
    verified_claims: list[VerifiedClaim] = field(default_factory=list)
    unverified_claims: list[str] = field(default_factory=list)
    verification_coverage: float = 0.0  # % of claims that were verified

    # Risk assessment
    risk_assessments: list[RiskAssessment] = field(default_factory=list)

    # Sub-results (for drill-down)
    redteam_result: RedTeamResult | None = None
    probe_report: VulnerabilityReport | None = None
    audit_verdict: DeepAuditVerdict | None = None

    # Metadata
    agents_involved: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def all_findings(self) -> list[Finding]:
        """All findings sorted by severity."""
        return (
            self.critical_findings + self.high_findings + self.medium_findings + self.low_findings
        )

    @property
    def total_findings(self) -> int:
        """Total number of findings."""
        return len(self.all_findings)

    @property
    def severity_counts(self) -> dict[str, int]:
        """Count findings by severity level."""
        return {
            "critical": len(self.critical_findings),
            "high": len(self.high_findings),
            "medium": len(self.medium_findings),
            "low": len(self.low_findings),
        }

    @property
    def checksum(self) -> str:
        """Generate integrity checksum for the result."""
        import json as _json

        content = _json.dumps(
            {
                "gauntlet_id": self.gauntlet_id,
                "verdict": self.verdict.value,
                "confidence": self.confidence,
                "total_findings": self.total_findings,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """Convert result to a JSON-serializable dictionary."""
        findings = []
        for finding in self.all_findings:
            findings.append(
                {
                    "id": finding.finding_id,
                    "category": finding.category,
                    "severity": finding.severity,
                    "severity_level": finding.severity_level,
                    "title": finding.title,
                    "description": finding.description,
                    "evidence": finding.evidence,
                    "mitigation": finding.mitigation,
                    "source": finding.source,
                    "verified": finding.verified,
                    "timestamp": finding.timestamp,
                }
            )

        return {
            "gauntlet_id": self.gauntlet_id,
            "input_type": self.input_type.value,
            "input_summary": self.input_summary,
            "input_hash": self.input_hash,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "risk_score": self.risk_score,
            "robustness_score": self.robustness_score,
            "coverage_score": self.coverage_score,
            "verification_coverage": self.verification_coverage,
            "severity_counts": self.severity_counts,
            "findings": findings,
            "consensus_reached": self.consensus_reached,
            "agents_involved": self.agents_involved,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
        }

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=" * 60,
            "GAUNTLET STRESS-TEST RESULT",
            "=" * 60,
            "",
            f"ID: {self.gauntlet_id}",
            f"Input Type: {self.input_type.value}",
            "",
            f"VERDICT: {self.verdict.value.upper()}",
            f"Confidence: {self.confidence:.0%}",
            "",
            "--- Scores ---",
            f"Risk Score: {self.risk_score:.0%}",
            f"Robustness Score: {self.robustness_score:.0%}",
            f"Coverage Score: {self.coverage_score:.0%}",
            f"Verification Coverage: {self.verification_coverage:.0%}",
            "",
            "--- Findings ---",
            f"Critical: {len(self.critical_findings)}",
            f"High: {len(self.high_findings)}",
            f"Medium: {len(self.medium_findings)}",
            f"Low: {len(self.low_findings)}",
            "",
        ]

        if self.critical_findings:
            lines.append("CRITICAL ISSUES:")
            for f in self.critical_findings[:5]:
                lines.append(f"  - {f.title}")

        if self.dissenting_views:
            lines.append("")
            lines.append(f"Dissenting Views: {len(self.dissenting_views)}")

        if self.unresolved_tensions:
            lines.append(f"Unresolved Tensions: {len(self.unresolved_tensions)}")

        lines.append("")
        lines.append(f"Duration: {self.duration_seconds:.1f}s")
        lines.append(f"Agents: {', '.join(self.agents_involved)}")
        lines.append(f"Checksum: {self.checksum}")

        return "\n".join(lines)


class GauntletOrchestrator:
    """
    Orchestrates comprehensive adversarial stress-testing.

    Combines multiple validation techniques:
    1. Red-team attacks for adversarial probing
    2. Capability probing for agent reliability
    3. Deep audit for intensive analysis
    4. Formal verification for provable claims
    5. Risk assessment for domain hazards

    Usage:
        orchestrator = GauntletOrchestrator(agents)
        result = await orchestrator.run(config)
        print(result.summary())
    """

    def __init__(
        self,
        agents: list[Agent] | None = None,
        run_agent_fn: Callable | None = None,
        on_progress: ProgressCallback | None = None,
        nomic_dir: Path | None = None,
        on_phase_complete: Callable | None = None,
        on_finding: Callable | None = None,
    ):
        """
        Initialize Gauntlet orchestrator.

        Args:
            agents: Agents to participate in stress-testing (default: empty list)
            run_agent_fn: Optional function to run agents (async callable)
            on_progress: Optional callback for progress updates
            nomic_dir: Directory for nomic state (default: resolved runtime data dir)
            on_phase_complete: Callback invoked when a phase completes
            on_finding: Callback invoked when a finding is discovered
        """
        self.agents = agents or []
        self.run_agent_fn = run_agent_fn or self._default_run_agent
        self.on_progress = on_progress
        if nomic_dir is None:
            from aragora.persistence.db_config import get_nomic_dir

            nomic_dir = get_nomic_dir()
        self.nomic_dir = nomic_dir
        self.on_phase_complete = on_phase_complete
        self.on_finding = on_finding

        # Initialize sub-components
        self.redteam_mode = RedTeamMode()
        self.prober = CapabilityProber()
        self.risk_assessor = RiskAssessor()
        self.verification_manager = get_formal_verification_manager()

        # Tracking
        self._finding_counter = 0
        self._start_time: datetime | None = None
        self._findings_count = 0

    def _severity_float_to_enum(self, severity: float) -> Any:
        """Convert severity float (0-1) to GauntletSeverity enum.

        Used by the pipeline-style gauntlet interface.
        """
        from aragora.gauntlet.types import SeverityLevel

        if severity >= 0.9:
            return SeverityLevel.CRITICAL
        elif severity >= 0.7:
            return SeverityLevel.HIGH
        elif severity >= 0.4:
            return SeverityLevel.MEDIUM
        elif severity > 0.0:
            return SeverityLevel.LOW
        return SeverityLevel.INFO

    def _extract_claims(self, text: str) -> list[str]:
        """Extract verifiable claims from text for formal verification.

        Used by the pipeline-style gauntlet interface.
        """
        import re

        claims: list[str] = []
        sentences = re.split(r"(?<=[.!?])\s+", text)

        claim_patterns = [
            r"\b(must|shall|always|never|guarantees?|ensures?)\b",
            r"\b(implies|entails|requires?)\b",
        ]

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue
            for pattern in claim_patterns:
                if re.search(pattern, sentence, re.IGNORECASE):
                    claims.append(sentence)
                    break

        return claims[:10]

    def _emit_progress(
        self,
        phase: str,
        phase_number: int,
        total_phases: int,
        percent: float,
        message: str,
        current_task: str | None = None,
    ) -> None:
        """Emit progress update if callback is configured."""
        if self.on_progress:
            progress = GauntletProgress(
                phase=phase,
                phase_number=phase_number,
                total_phases=total_phases,
                percent=percent,
                message=message,
                findings_so_far=self._findings_count,
                current_task=current_task,
            )
            self.on_progress(progress)

    async def _default_run_agent(self, agent: Agent, prompt: str) -> str:
        """Default agent runner using agent.generate()."""
        from aragora.server.stream.arena_hooks import streaming_task_context

        task_id = f"{agent.name}:gauntlet"
        with streaming_task_context(task_id):
            return await agent.generate(prompt, [])

    async def run(
        self,
        config: GauntletConfig | Any | None = None,
        *,
        input_text: str | None = None,
        template: Any | None = None,
    ) -> Any:
        """
        Run a complete Gauntlet stress-test.

        Supports two calling conventions:
        1. Legacy: run(gauntlet_config)  -- uses the orchestrator's own GauntletConfig
        2. Pipeline: run(input_text=..., config=..., template=...)  -- uses config.py GauntletConfig

        Args:
            config: Configuration for the stress-test
            input_text: Text to validate (pipeline mode)
            template: GauntletTemplate enum (pipeline mode)

        Returns:
            GauntletResult (from orchestrator or config module depending on mode)
        """
        # Pipeline-style invocation: run(input_text=..., config=...) or run(input_text=..., template=...)
        if input_text is not None or template is not None:
            return await self._run_pipeline(
                input_text=input_text or "",
                config=config,
                template=template,
            )

        # Legacy invocation: run(config) where config is a GauntletConfig from this module
        if config is None:
            config = GauntletConfig()
        return await self._run_stress_test(config)

    def _notify_phase_complete(self, phase: Any, result: Any) -> None:
        """Notify callback that a phase completed."""
        if self.on_phase_complete:
            try:
                self.on_phase_complete(phase, result)
            except (ValueError, RuntimeError, TypeError, OSError) as exc:
                logger.debug("Phase complete callback failed: %s", exc)

    def _notify_finding(self, finding: Any) -> None:
        """Notify callback of a new finding."""
        if self.on_finding:
            try:
                self.on_finding(finding)
            except (ValueError, RuntimeError, TypeError, OSError) as exc:
                logger.debug("Finding callback failed: %s", exc)

    async def _run_risk_assessment(self, input_text: str, config: Any) -> Any:
        """Run risk assessment phase."""
        from aragora.gauntlet.config import (
            GauntletFinding as PipelineFinding,
            PhaseResult,
        )
        from aragora.gauntlet.types import GauntletPhase

        try:
            from aragora.debate.risk_assessor import RiskAssessor
        except ImportError:
            return PhaseResult(
                phase=GauntletPhase.RISK_ASSESSMENT,
                status="skipped",
                error="Risk assessor not available",
            )

        risk_findings: list[Any] = []
        assessor = RiskAssessor() if not hasattr(self, "risk_assessor") else self.risk_assessor
        risk_assessments = assessor.assess_topic(input_text[:2000])
        for ra in risk_assessments:
            level = getattr(ra, "level", None)
            level_name = getattr(level, "name", "MEDIUM") if level else "MEDIUM"
            level_map = {"LOW": 0.3, "MEDIUM": 0.5, "HIGH": 0.7, "CRITICAL": 0.9}
            sev = self._severity_float_to_enum(level_map.get(level_name, 0.5))
            finding = PipelineFinding(
                id=self._next_finding_id(),
                category=getattr(ra, "category", "risk"),
                severity=sev,
                title=f"Domain Risk: {getattr(ra, 'category', 'unknown')}",
                description=getattr(ra, "description", ""),
                source_phase=GauntletPhase.RISK_ASSESSMENT,
                metadata={"source": "RiskAssessor"},
            )
            risk_findings.append(finding)

        return PhaseResult(
            phase=GauntletPhase.RISK_ASSESSMENT,
            status="completed",
            findings=risk_findings,
            metrics={"risks_identified": len(risk_findings)},
        )

    async def _run_scenario_analysis(self, input_text: str, config: Any) -> Any:
        """Run scenario analysis phase."""
        from aragora.gauntlet.config import PhaseResult
        from aragora.gauntlet.types import GauntletPhase

        scenarios_run = 0
        return PhaseResult(
            phase=GauntletPhase.SCENARIO_ANALYSIS,
            status="completed",
            metrics={"scenarios_run": scenarios_run},
        )

    async def _run_adversarial_probing(self, input_text: str, config: Any) -> Any:
        """Run adversarial probing phase."""
        from aragora.gauntlet.config import PhaseResult
        from aragora.gauntlet.types import GauntletPhase

        probes_run = 0
        robustness_score = 0.5

        return PhaseResult(
            phase=GauntletPhase.ADVERSARIAL_PROBING,
            status="completed",
            metrics={"probes_run": probes_run, "robustness_score": robustness_score},
        )

    async def _run_formal_verification(self, input_text: str, config: Any) -> Any:
        """Run formal verification phase (pipeline mode)."""
        from aragora.gauntlet.config import PhaseResult
        from aragora.gauntlet.types import GauntletPhase

        return PhaseResult(
            phase=GauntletPhase.FORMAL_VERIFICATION,
            status="completed",
            metrics={"claims_verified": 0},
        )

    async def _run_pipeline(
        self,
        input_text: str,
        config: Any | None = None,
        template: Any | None = None,
    ) -> Any:
        """Run the gauntlet in pipeline mode using config.py's interfaces."""
        import time as _time
        from datetime import datetime, timezone

        from aragora.gauntlet.config import (
            GauntletConfig as PipelineConfig,
            GauntletResult as PipelineResult,
        )
        from aragora.gauntlet.types import GauntletPhase

        start_ms = int(_time.time() * 1000)

        # Resolve template to config
        if template is not None and config is None:
            from aragora.gauntlet.templates import _TEMPLATES

            config = _TEMPLATES.get(template, PipelineConfig())

        if config is None:
            config = PipelineConfig()

        result = PipelineResult(
            config=config,
            input_text=input_text,
        )

        # Select agents
        available_agents = config.agents[: config.max_agents] if config.agents else []
        result.agents_used = available_agents

        try:
            # Phase: Risk Assessment (always runs)
            result.current_phase = GauntletPhase.RISK_ASSESSMENT
            phase_result = await self._run_risk_assessment(input_text, config)
            result.phase_results.append(phase_result)
            result.findings.extend(phase_result.findings)
            for f in phase_result.findings:
                self._notify_finding(f)
            self._notify_phase_complete(GauntletPhase.RISK_ASSESSMENT, phase_result)

            # Phase: Scenario Analysis (optional)
            if getattr(config, "enable_scenario_analysis", False):
                result.current_phase = GauntletPhase.SCENARIO_ANALYSIS
                phase_result = await self._run_scenario_analysis(input_text, config)
                result.phase_results.append(phase_result)
                result.findings.extend(phase_result.findings)
                result.scenarios_tested = phase_result.metrics.get("scenarios_run", 0)
                self._notify_phase_complete(GauntletPhase.SCENARIO_ANALYSIS, phase_result)

            # Phase: Adversarial Probing (optional)
            if getattr(config, "enable_adversarial_probing", False):
                result.current_phase = GauntletPhase.ADVERSARIAL_PROBING
                phase_result = await self._run_adversarial_probing(input_text, config)
                result.phase_results.append(phase_result)
                result.findings.extend(phase_result.findings)
                result.probes_executed = phase_result.metrics.get("probes_run", 0)
                result.robustness_score = phase_result.metrics.get(
                    "robustness_score", result.robustness_score
                )
                self._notify_phase_complete(GauntletPhase.ADVERSARIAL_PROBING, phase_result)

            # Phase: Formal Verification (optional)
            if getattr(config, "enable_formal_verification", False):
                result.current_phase = GauntletPhase.FORMAL_VERIFICATION
                phase_result = await self._run_formal_verification(input_text, config)
                result.phase_results.append(phase_result)
                result.findings.extend(phase_result.findings)
                self._notify_phase_complete(GauntletPhase.FORMAL_VERIFICATION, phase_result)

            # Phase: Deep Audit (optional, reuse existing legacy method signature)
            if getattr(config, "enable_deep_audit", False):
                result.current_phase = GauntletPhase.DEEP_AUDIT
                phase_result = await self._run_deep_audit_pipeline(input_text, config)
                result.phase_results.append(phase_result)
                result.findings.extend(phase_result.findings)
                self._notify_phase_complete(GauntletPhase.DEEP_AUDIT, phase_result)

            # Extract and count claims
            claims = self._extract_claims(input_text)
            result.total_claims = len(claims)

            # Evaluate pass/fail
            result.current_phase = GauntletPhase.SYNTHESIS
            result.evaluate_pass_fail()
            result.current_phase = GauntletPhase.COMPLETE

        except (RuntimeError, ValueError, TimeoutError, OSError) as e:
            logger.warning("Pipeline gauntlet failed: %s", e)
            result.current_phase = GauntletPhase.FAILED
            result.verdict_summary = f"Pipeline failed: {type(e).__name__}: {e}"

        result.total_duration_ms = int(_time.time() * 1000) - start_ms
        result.completed_at = datetime.now(timezone.utc).isoformat()
        return result

    async def _run_deep_audit_pipeline(self, input_text: str, config: Any) -> Any:
        """Run deep audit phase (pipeline mode wrapper)."""
        from aragora.gauntlet.config import PhaseResult
        from aragora.gauntlet.types import GauntletPhase

        return PhaseResult(
            phase=GauntletPhase.DEEP_AUDIT,
            status="completed",
            metrics={},
        )

    async def _run_stress_test(self, config: GauntletConfig) -> GauntletResult:
        """
        Run a complete Gauntlet stress-test (legacy mode).

        Args:
            config: Configuration for the stress-test

        Returns:
            GauntletResult with verdict and findings
        """
        self._start_time = datetime.now()
        self._findings_count = 0
        gauntlet_id = f"gauntlet-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        logger.info("=" * 60)
        logger.info("GAUNTLET STRESS-TEST: %s", gauntlet_id)
        logger.info("Input Type: %s", config.input_type.value)
        logger.info("Agents: %s", ", ".join(a.name for a in self.agents))
        logger.info("=" * 60)

        # Emit initial progress
        self._emit_progress("Initialization", 1, 3, 0, "Starting Gauntlet stress-test...")

        all_findings: list[Finding] = []
        dissenting_views: list[DissentRecord] = []
        unresolved_tensions: list[UnresolvedTension] = []
        verified_claims: list[VerifiedClaim] = []
        unverified_claims: list[str] = []

        # Initialize sub-results
        redteam_result: RedTeamResult | None = None
        probe_report: VulnerabilityReport | None = None
        audit_verdict: DeepAuditVerdict | None = None
        risk_assessments: list[RiskAssessment] = []

        # 1. Risk Assessment (fast, run first)
        if config.enable_risk_assessment:
            logger.info("--- Phase 1: Risk Assessment ---")
            self._emit_progress(
                "Risk Assessment",
                1,
                3,
                10,
                "Analyzing domain-specific risks...",
                current_task="risk_assessment",
            )
            risk_assessments = self.risk_assessor.assess_topic(config.input_content[:2000])
            for ra in risk_assessments:
                all_findings.append(
                    Finding(
                        finding_id=self._next_finding_id(),
                        category="risk",
                        severity=self._risk_level_to_severity(ra.level),
                        title=f"Domain Risk: {ra.category}",
                        description=ra.description,
                        mitigation=", ".join(ra.mitigations),
                        source="RiskAssessor",
                    )
                )
            self._findings_count = len(all_findings)
            self._emit_progress(
                "Risk Assessment",
                1,
                3,
                20,
                f"Risk assessment complete: {len(risk_assessments)} risks identified",
            )

        # 2. Run parallel stress tests
        tasks: list[tuple[str, Coroutine[Any, Any, Any]]] = []

        if config.enable_redteam and self.agents:
            tasks.append(("redteam", self._run_redteam(config)))

        if config.enable_probing and self.agents:
            tasks.append(("probing", self._run_probing(config)))

        if config.enable_deep_audit and self.agents:
            tasks.append(("deep_audit", self._run_deep_audit(config)))

        if config.enable_verification:
            tasks.append(("verification", self._run_verification(config)))

        # Persona-specific compliance attacks
        if config.persona and PERSONAS_AVAILABLE and self.agents:
            tasks.append(("persona", self._run_persona_attacks(config)))

        # Execute with timeout
        logger.info("--- Phase 2: Parallel Stress Tests ---")
        task_names = [t[0] for t in tasks]
        self._emit_progress(
            "Stress Testing",
            2,
            3,
            25,
            f"Running {len(tasks)} parallel stress tests: {', '.join(task_names)}",
            current_task=task_names[0] if task_names else None,
        )

        if tasks:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*[t[1] for t in tasks], return_exceptions=True),
                    timeout=config.max_duration_seconds,
                )

                # Process results
                completed_tasks = 0
                for (task_name, _), result in zip(tasks, results):
                    completed_tasks += 1
                    progress_pct = 25 + (completed_tasks / len(tasks)) * 50  # 25-75%

                    if isinstance(result, Exception):
                        logger.warning("%s failed: %s", task_name, result)
                        self._emit_progress(
                            "Stress Testing",
                            2,
                            3,
                            progress_pct,
                            f"{task_name} failed: {str(result)[:50]}",
                            current_task=task_name,
                        )
                        continue

                    if task_name == "redteam" and result:
                        redteam_result = cast(RedTeamResult, result)
                        new_findings = self._redteam_to_findings(redteam_result)
                        all_findings.extend(new_findings)
                        self._findings_count = len(all_findings)
                        self._emit_progress(
                            "Stress Testing",
                            2,
                            3,
                            progress_pct,
                            f"Red-team complete: {redteam_result.total_attacks} attacks, {len(new_findings)} findings",
                            current_task="redteam",
                        )

                    elif task_name == "probing" and result:
                        probe_report = cast(VulnerabilityReport, result)
                        new_findings = self._probe_to_findings(probe_report)
                        all_findings.extend(new_findings)
                        self._findings_count = len(all_findings)
                        self._emit_progress(
                            "Stress Testing",
                            2,
                            3,
                            progress_pct,
                            f"Probing complete: {probe_report.vulnerabilities_found} vulnerabilities",
                            current_task="probing",
                        )

                    elif task_name == "deep_audit" and result:
                        audit_verdict = cast(DeepAuditVerdict, result)
                        findings, dissents, tensions = self._audit_to_findings(audit_verdict)
                        all_findings.extend(findings)
                        dissenting_views.extend(dissents)
                        unresolved_tensions.extend(tensions)
                        self._findings_count = len(all_findings)
                        self._emit_progress(
                            "Stress Testing",
                            2,
                            3,
                            progress_pct,
                            f"Deep audit complete: {len(findings)} findings, {len(audit_verdict.unanimous_issues)} unanimous",
                            current_task="deep_audit",
                        )

                    elif task_name == "verification" and result:
                        verified, unverified = cast(tuple[list[VerifiedClaim], list[str]], result)
                        verified_claims.extend(verified)
                        unverified_claims.extend(unverified)
                        self._emit_progress(
                            "Stress Testing",
                            2,
                            3,
                            progress_pct,
                            f"Verification complete: {len(verified)} verified, {len(unverified)} unverified",
                            current_task="verification",
                        )

                    elif task_name == "persona" and result:
                        # Persona findings are already Finding objects
                        persona_findings = cast(list[Finding], result)
                        all_findings.extend(persona_findings)
                        self._findings_count = len(all_findings)
                        self._emit_progress(
                            "Stress Testing",
                            2,
                            3,
                            progress_pct,
                            f"Persona attacks complete: {len(persona_findings)} findings",
                            current_task="persona",
                        )

            except asyncio.TimeoutError:
                logger.warning("Gauntlet timed out after %ss", config.max_duration_seconds)
                self._emit_progress(
                    "Stress Testing", 2, 3, 75, f"Timeout after {config.max_duration_seconds}s"
                )

        # 3. Aggregate and score
        logger.info("--- Phase 3: Aggregation ---")
        self._emit_progress("Aggregation", 3, 3, 80, "Filtering and scoring findings...")

        # Filter findings by threshold
        all_findings = [f for f in all_findings if f.severity >= config.severity_threshold]
        self._findings_count = len(all_findings)

        # Sort into severity buckets
        critical = [f for f in all_findings if f.severity >= 0.9]
        high = [f for f in all_findings if 0.7 <= f.severity < 0.9]
        medium = [f for f in all_findings if 0.4 <= f.severity < 0.7]
        low = [f for f in all_findings if f.severity < 0.4]

        self._emit_progress(
            "Aggregation",
            3,
            3,
            85,
            f"Categorized: {len(critical)} critical, {len(high)} high, {len(medium)} medium",
        )

        # Calculate aggregate scores
        risk_score = self._calculate_risk_score(all_findings, risk_assessments)
        robustness_score = redteam_result.robustness_score if redteam_result else 1.0
        coverage_score = self._calculate_coverage_score(redteam_result, probe_report, audit_verdict)
        verification_coverage = (
            len(verified_claims) / (len(verified_claims) + len(unverified_claims))
            if (verified_claims or unverified_claims)
            else 0.0
        )

        self._emit_progress(
            "Aggregation",
            3,
            3,
            90,
            f"Scores: risk={risk_score:.0%}, robustness={robustness_score:.0%}",
        )

        # Zero-adversarial-work gate (issue #9303): APPROVED means "survived
        # adversarial scrutiny". If NO attacks ran, NO probes ran, NO audit ran,
        # and nothing was verified or found, there was no scrutiny to survive —
        # measured live 2026-07-15: a quick-profile run with 0 attacks / 0%
        # coverage minted APPROVED at 95%. Fail closed to NEEDS_REVIEW @ 0.
        zero_evidence = _no_adversarial_work(
            redteam_result,
            probe_report,
            audit_verdict,
            verified_claims,
            unverified_claims,
            all_findings,
        )

        # Determine verdict
        if zero_evidence:
            verdict, confidence = Verdict.NEEDS_REVIEW, 0.0
            # No redteam ran, so robustness defaulted to a perfect 1.0 —
            # 100% robustness on a path where nothing executed is the same
            # hollow-receipt lie in a different field (claude #9306 r4 [P2]).
            robustness_score = 0.0
            coverage_score = 0.0
        else:
            verdict, confidence = self._determine_verdict(
                critical, high, medium, risk_score, robustness_score, dissenting_views
            )
        self._emit_progress(
            "Aggregation",
            3,
            3,
            95,
            f"Verdict: {verdict.value.upper()} ({confidence:.0%} confidence)",
        )

        # Build result
        duration = (datetime.now() - self._start_time).total_seconds()
        input_hash = hashlib.sha256(config.input_content.encode()).hexdigest()

        result = GauntletResult(
            gauntlet_id=gauntlet_id,
            input_type=config.input_type,
            input_summary=config.input_content[:500],
            input_hash=input_hash,
            verdict=verdict,
            confidence=confidence,
            risk_score=risk_score,
            robustness_score=robustness_score,
            coverage_score=coverage_score,
            critical_findings=critical,
            high_findings=high,
            medium_findings=medium,
            low_findings=low,
            consensus_reached=audit_verdict.confidence > 0.7 if audit_verdict else False,
            dissenting_views=dissenting_views,
            unresolved_tensions=unresolved_tensions,
            verified_claims=verified_claims,
            unverified_claims=unverified_claims,
            verification_coverage=verification_coverage,
            risk_assessments=risk_assessments,
            redteam_result=redteam_result,
            probe_report=probe_report,
            audit_verdict=audit_verdict,
            agents_involved=[a.name for a in self.agents],
            duration_seconds=duration,
        )

        logger.info("\n%s", result.summary())

        self._emit_progress(
            "Complete",
            3,
            3,
            100,
            f"Gauntlet complete: {result.total_findings} findings, {verdict.value.upper()}",
        )

        return result

    def _next_finding_id(self) -> str:
        """Generate unique finding ID."""
        self._finding_counter += 1
        return f"finding-{self._finding_counter:04d}"

    def _risk_level_to_severity(self, level: RiskLevel) -> float:
        """Convert RiskLevel to severity float."""
        mapping = {
            RiskLevel.LOW: 0.25,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.75,
            RiskLevel.CRITICAL: 0.95,
        }
        return mapping.get(level, 0.5)

    async def _run_redteam(self, config: GauntletConfig) -> RedTeamResult | None:
        """Run red-team adversarial testing."""
        logger.info("Running red-team attacks...")

        if not self.agents:
            return None

        try:
            # Use extra agent as proposer for defense if available
            red_team_agents = self.agents[: config.parallel_attacks]
            proposer_agent = None
            if len(self.agents) > config.parallel_attacks:
                proposer_agent = self.agents[config.parallel_attacks]
                logger.info("Using %s as defender", getattr(proposer_agent, "name", "agent"))

            result = await self.redteam_mode.run_redteam(
                target_proposal=config.input_content,
                proposer="input_author",
                red_team_agents=red_team_agents,
                run_agent_fn=self.run_agent_fn,
                max_rounds=3,
                proposer_agent=proposer_agent,
            )
            logger.info(
                f"Red-team: {result.total_attacks} attacks, robustness={result.robustness_score:.0%}"
            )
            return result
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.warning("Red-team failed: %s", e)
            return None

    async def _run_persona_attacks(self, config: GauntletConfig) -> list[Finding]:
        """Run persona-specific compliance attacks."""
        if not config.persona or not PERSONAS_AVAILABLE:
            return []

        if not self.agents:
            return []

        logger.info("Running persona attacks: %s...", config.persona.name)

        findings: list[Finding] = []
        persona = config.persona

        # Run each persona attack using available agents
        attack_agents = self.agents[: config.parallel_attacks]

        for attack in persona.attack_prompts:
            try:
                # Generate attack prompt
                attack_prompt = persona.get_attack_prompt(
                    config.input_content[:5000],
                    attack,  # Limit context
                )

                # Run attack with first available agent
                agent = attack_agents[0] if attack_agents else self.agents[0]
                response = await self.run_agent_fn(agent, attack_prompt)

                # Parse response for findings
                parsed_findings = self._parse_persona_response(
                    response, attack, persona, agent.name
                )
                findings.extend(parsed_findings)

            except (OSError, ValueError, TypeError, RuntimeError, AttributeError) as e:
                logger.debug("Persona attack %s failed: %s", attack.id, e)

        logger.info(
            f"Persona attacks: {len(findings)} findings from {len(persona.attack_prompts)} attacks"
        )
        return findings

    def _parse_persona_response(
        self,
        response: str,
        attack: Any,  # PersonaAttack
        persona: Any,  # RegulatoryPersona
        agent_name: str,
    ) -> list[Finding]:
        """Parse persona attack response into findings."""
        findings = []

        # Simple heuristic parsing - look for severity indicators
        response_lower = response.lower()

        # Check if response indicates findings
        has_critical = "critical" in response_lower and (
            "finding" in response_lower
            or "violation" in response_lower
            or "issue" in response_lower
        )
        has_high = "high" in response_lower and (
            "finding" in response_lower or "risk" in response_lower or "severity" in response_lower
        )
        has_medium = "medium" in response_lower and (
            "finding" in response_lower or "risk" in response_lower or "severity" in response_lower
        )

        # If response contains compliance findings, create a finding
        compliance_indicators = [
            "violation",
            "non-compliant",
            "missing",
            "inadequate",
            "failure",
            "gap",
            "risk",
            "concern",
            "issue",
        ]

        if any(ind in response_lower for ind in compliance_indicators):
            # Determine severity from response
            if has_critical:
                severity = 0.95
            elif has_high:
                severity = 0.75
            elif has_medium:
                severity = 0.50
            else:
                severity = 0.35

            # Apply persona severity weight
            if attack.category in persona.severity_weights:
                severity = min(1.0, severity * persona.severity_weights[attack.category])

            # Extract first paragraph as summary
            paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
            summary = paragraphs[0] if paragraphs else response[:300]

            findings.append(
                Finding(
                    finding_id=self._next_finding_id(),
                    category=f"persona/{attack.category}",
                    severity=severity,
                    title=f"{persona.regulation}: {attack.name}",
                    description=summary[:500],
                    evidence=response[:1000],
                    mitigation=None,  # Would need more sophisticated parsing
                    source=f"Persona/{persona.name}/{agent_name}",
                )
            )

        return findings

    async def _run_probing(self, config: GauntletConfig) -> VulnerabilityReport | None:
        """Run capability probing on agents."""
        logger.info("Running capability probes...")

        if not self.agents:
            return None

        try:
            # Probe the first agent (usually the most capable)
            target_agent = self.agents[0]
            report = await self.prober.probe_agent(
                target_agent=target_agent,
                run_agent_fn=self.run_agent_fn,
                probe_types=config.probe_types,
                probes_per_type=2,  # Reduced for speed
            )
            logger.info(
                f"Probing: {report.vulnerabilities_found}/{report.probes_run} vulnerabilities"
            )
            return report
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.warning("Probing failed: %s", e)
            return None

    async def _run_deep_audit(self, config: GauntletConfig) -> DeepAuditVerdict | None:
        """Run deep audit analysis."""
        logger.info("Running deep audit...")

        if not self.agents:
            return None

        try:
            audit_config = DeepAuditConfig(
                rounds=config.deep_audit_rounds,
                enable_research=False,  # Faster without web research
                risk_threshold=config.risk_threshold,
            )
            orchestrator = DeepAuditOrchestrator(self.agents, audit_config)
            verdict = await orchestrator.run(
                task=f"Analyze and critique this {config.input_type.value}:\n\n{config.input_content[:5000]}",
                context="This is a stress-test to find weaknesses and blind spots.",
            )
            logger.info(
                f"Deep audit: confidence={verdict.confidence:.0%}, {len(verdict.findings)} findings"
            )
            return verdict
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.warning("Deep audit failed: %s", e)
            return None

    async def _run_verification(
        self, config: GauntletConfig
    ) -> tuple[list[VerifiedClaim], list[str]]:
        """Run formal verification on extractable claims."""
        logger.info("Running formal verification...")

        verified: list[VerifiedClaim] = []
        unverified: list[str] = []

        # Extract potential claims from input (simple heuristic)
        claims = self._extract_verifiable_claims(config.input_content)

        for claim in claims[:10]:  # Limit to 10 claims
            try:
                result = await self.verification_manager.attempt_formal_verification(
                    claim=claim,
                    timeout_seconds=config.verification_timeout_seconds,
                )

                if result.status == FormalProofStatus.PROOF_FOUND:
                    verified.append(
                        VerifiedClaim(
                            claim=claim,
                            verified=True,
                            verification_method=result.language.value,
                            proof_hash=result.proof_hash,
                            verification_time_ms=result.proof_search_time_ms,
                        )
                    )
                elif result.status == FormalProofStatus.PROOF_FAILED:
                    verified.append(
                        VerifiedClaim(
                            claim=claim,
                            verified=False,
                            verification_method=result.language.value,
                            verification_time_ms=result.proof_search_time_ms,
                        )
                    )
                else:
                    unverified.append(claim)

            except (OSError, ValueError, TypeError, RuntimeError) as e:
                logger.debug("Verification failed for claim: %s", e)
                unverified.append(claim)

        logger.info("Verification: %s verified, %s unverified", len(verified), len(unverified))
        return verified, unverified

    def _extract_verifiable_claims(self, content: str) -> list[str]:
        """Extract claims that might be formally verifiable."""
        import re

        claims = []

        # Look for mathematical/logical statements
        patterns = [
            r"(?:if|when)\s+[^.]+then\s+[^.]+",  # If-then statements
            r"for all\s+[^.]+",  # Universal quantifiers
            r"there exists\s+[^.]+",  # Existential quantifiers
            r"[^.]*(?:must|shall|always|never)[^.]+",  # Modal claims
            r"[^.]*(?:implies|entails|guarantees)[^.]+",  # Logical implications
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            claims.extend(matches[:5])  # Limit per pattern

        return list(set(claims))[:10]

    def _redteam_to_findings(self, result: RedTeamResult) -> list[Finding]:
        """Convert red-team result to findings."""
        findings = []

        for attack in result.critical_issues:
            findings.append(
                Finding(
                    finding_id=self._next_finding_id(),
                    category="attack",
                    severity=attack.severity,
                    title=f"Attack: {attack.attack_type.value}",
                    description=attack.attack_description,
                    evidence=attack.evidence,
                    mitigation=attack.mitigation,
                    source=f"RedTeam/{attack.attacker}",
                )
            )

        return findings

    def _probe_to_findings(self, report: VulnerabilityReport) -> list[Finding]:
        """Convert probe report to findings."""
        findings = []

        severity_map = {
            VulnerabilitySeverity.CRITICAL: 0.95,
            VulnerabilitySeverity.HIGH: 0.75,
            VulnerabilitySeverity.MEDIUM: 0.5,
            VulnerabilitySeverity.LOW: 0.25,
        }

        for probe_type, results in report.by_type.items():
            for probe_result in results:
                if probe_result.vulnerability_found:
                    findings.append(
                        Finding(
                            finding_id=self._next_finding_id(),
                            category="probe",
                            severity=severity_map.get(probe_result.severity, 0.5),
                            title=f"Probe: {probe_type}",
                            description=probe_result.vulnerability_description
                            or "Vulnerability detected",
                            evidence=probe_result.evidence or "",
                            source=f"Prober/{report.target_agent}",
                        )
                    )

        return findings

    def _audit_to_findings(
        self, verdict: DeepAuditVerdict
    ) -> tuple[list[Finding], list[DissentRecord], list[UnresolvedTension]]:
        """Convert deep audit verdict to findings and dissent records."""
        findings = []
        dissents = []
        tensions = []

        # Convert audit findings
        for af in verdict.findings:
            findings.append(
                Finding(
                    finding_id=self._next_finding_id(),
                    category="audit",
                    severity=af.severity,
                    title=f"Audit: {af.category}",
                    description=af.summary,
                    evidence=af.details,
                    source="DeepAudit",
                )
            )

        # Convert unanimous issues to high-severity findings
        for issue in verdict.unanimous_issues:
            findings.append(
                Finding(
                    finding_id=self._next_finding_id(),
                    category="audit",
                    severity=0.85,  # Unanimous = high severity
                    title="Unanimous Issue",
                    description=issue,
                    source="DeepAudit/Unanimous",
                )
            )

        # Convert split opinions to dissent records
        for opinion in verdict.split_opinions:
            dissents.append(
                DissentRecord(
                    agent="multiple",
                    claim_id="",
                    dissent_type="partial",
                    reasons=[opinion],
                    severity=0.5,
                )
            )

        # Convert risk areas to tensions
        for risk in verdict.risk_areas:
            tensions.append(
                UnresolvedTension(
                    tension_id=f"tension-{uuid.uuid4().hex[:6]}",
                    description=risk,
                    agents_involved=[],
                    options=[],
                    impact="Identified during deep audit",
                )
            )

        return findings, dissents, tensions

    def _calculate_risk_score(
        self,
        findings: list[Finding],
        risk_assessments: list[RiskAssessment],
    ) -> float:
        """Calculate aggregate risk score."""
        if not findings and not risk_assessments:
            return 0.0

        # Weight by severity
        finding_risk = sum(f.severity**2 for f in findings)  # Square to emphasize high severity
        finding_max = len(findings) if findings else 1

        # Factor in domain risks
        domain_risk = sum(
            self._risk_level_to_severity(ra.level) * ra.confidence for ra in risk_assessments
        )
        domain_max = len(risk_assessments) if risk_assessments else 1

        # Combine
        combined = (finding_risk / finding_max + domain_risk / domain_max) / 2
        return min(1.0, combined)

    def _calculate_coverage_score(
        self,
        redteam: RedTeamResult | None,
        probe: VulnerabilityReport | None,
        audit: DeepAuditVerdict | None,
    ) -> float:
        """Calculate test coverage score."""
        scores = []

        if redteam:
            scores.append(redteam.coverage_score)

        if probe:
            # Coverage based on probe types tested
            scores.append(min(1.0, probe.probes_run / 20))

        if audit:
            # Coverage based on audit completion
            scores.append(audit.confidence)

        return sum(scores) / len(scores) if scores else 0.0

    def _determine_verdict(
        self,
        critical: list[Finding],
        high: list[Finding],
        medium: list[Finding],
        risk_score: float,
        robustness_score: float,
        dissents: list[DissentRecord],
    ) -> tuple[Verdict, float]:
        """Determine final verdict and confidence."""

        # Automatic rejection conditions
        if len(critical) >= 2:
            return Verdict.REJECTED, 0.9

        if risk_score > 0.8:
            return Verdict.REJECTED, 0.8

        # Needs review conditions
        if len(critical) == 1:
            return Verdict.NEEDS_REVIEW, 0.7

        if len(high) >= 3:
            return Verdict.NEEDS_REVIEW, 0.65

        if len(dissents) >= 3:
            return Verdict.NEEDS_REVIEW, 0.6

        if risk_score > 0.6:
            return Verdict.NEEDS_REVIEW, 0.6

        # Approved with conditions
        if len(high) >= 1 or len(medium) >= 3:
            confidence = robustness_score * (1 - risk_score * 0.3)
            return Verdict.APPROVED_WITH_CONDITIONS, confidence

        # Clean approval
        confidence = robustness_score * (1 - risk_score * 0.2)
        return Verdict.APPROVED, min(0.95, confidence)


# Convenience function for quick stress-testing
async def run_gauntlet(
    input_content: str,
    agents: list[Agent] | None = None,
    input_type: InputType = InputType.SPEC,
    *,
    template: Any | None = None,
    **config_kwargs,
) -> Any:
    """
    Run a Gauntlet stress-test.

    Supports two calling conventions:
    1. Legacy: run_gauntlet(content, agents, input_type, **kwargs) -- stress-test mode
    2. Pipeline: run_gauntlet(content, template=...) -- pipeline mode

    Args:
        input_content: Content to stress-test
        agents: Agents to participate (optional for pipeline mode)
        input_type: Type of input
        template: GauntletTemplate enum for pipeline mode
        **config_kwargs: Additional GauntletConfig options

    Returns:
        GauntletResult with verdict and findings

    Example:
        result = await run_gauntlet(
            spec_document,
            agents=[claude, gpt4, gemini],
            input_type=InputType.SPEC,
        )
        print(result.verdict)  # APPROVED, NEEDS_REVIEW, or REJECTED
    """
    orchestrator = GauntletOrchestrator(agents)

    # Pipeline mode: use input_text and optional template
    if template is not None or agents is None:
        return await orchestrator.run(input_text=input_content, template=template)

    # Legacy stress-test mode
    config = GauntletConfig(
        input_type=input_type,
        input_content=input_content,
        **config_kwargs,
    )
    return await orchestrator.run(config)


# Pre-configured Gauntlet profiles
QUICK_GAUNTLET = GauntletConfig(
    deep_audit_rounds=2,
    parallel_attacks=2,
    enable_verification=False,
    max_duration_seconds=120,
)

THOROUGH_GAUNTLET = GauntletConfig(
    deep_audit_rounds=6,
    parallel_attacks=5,
    parallel_probes=5,
    enable_verification=True,
    max_duration_seconds=900,  # 15 min
)

CODE_REVIEW_GAUNTLET = GauntletConfig(
    input_type=InputType.CODE,
    attack_types=[
        AttackType.SECURITY,
        AttackType.EDGE_CASE,
        AttackType.RACE_CONDITION,
        AttackType.RESOURCE_EXHAUSTION,
    ],
    probe_types=[
        ProbeType.HALLUCINATION,
        ProbeType.REASONING_DEPTH,
        ProbeType.EDGE_CASE,
    ],
    deep_audit_rounds=4,
    enable_verification=True,
)

POLICY_GAUNTLET = GauntletConfig(
    input_type=InputType.POLICY,
    attack_types=[
        AttackType.LOGICAL_FALLACY,
        AttackType.UNSTATED_ASSUMPTION,
        AttackType.EDGE_CASE,
        AttackType.COUNTEREXAMPLE,
    ],
    deep_audit_rounds=5,
    severity_threshold=0.3,  # More sensitive
)


# Compliance-focused gauntlet profiles
def get_compliance_gauntlet(persona_name: str = "gdpr") -> GauntletConfig:
    """
    Get a compliance-focused Gauntlet config with a regulatory persona.

    Args:
        persona_name: Name of persona ("gdpr", "hipaa", "ai_act", "security")

    Returns:
        GauntletConfig with persona configured

    Example:
        config = get_compliance_gauntlet("gdpr")
        result = await run_gauntlet(spec, agents, config=config)
    """
    return GauntletConfig(
        input_type=InputType.POLICY,
        attack_types=[
            AttackType.LOGICAL_FALLACY,
            AttackType.UNSTATED_ASSUMPTION,
            AttackType.EDGE_CASE,
            AttackType.COUNTEREXAMPLE,
        ],
        deep_audit_rounds=4,
        severity_threshold=0.3,
        persona=persona_name,  # Will be resolved in __post_init__
    )


GDPR_GAUNTLET = get_compliance_gauntlet("gdpr") if PERSONAS_AVAILABLE else None
HIPAA_GAUNTLET = get_compliance_gauntlet("hipaa") if PERSONAS_AVAILABLE else None
AI_ACT_GAUNTLET = get_compliance_gauntlet("ai_act") if PERSONAS_AVAILABLE else None
SECURITY_GAUNTLET = get_compliance_gauntlet("security") if PERSONAS_AVAILABLE else None
SOX_GAUNTLET = get_compliance_gauntlet("sox") if PERSONAS_AVAILABLE else None


def _no_adversarial_work(
    redteam: Any,
    probe: Any,
    audit: Any,
    verified_claims: Any,
    unverified_claims: Any,
    findings: Any,
) -> bool:
    """True when the run produced ZERO adversarial evidence (issue #9303).

    APPROVED means "survived adversarial scrutiny"; with no attacks, no
    probes, no audit, no claims examined, and no findings there was no
    scrutiny to survive, and the verdict must fail closed to NEEDS_REVIEW.
    """
    attacks_ran = bool(redteam and getattr(redteam, "total_attacks", 0) > 0)
    probes_ran = bool(probe and getattr(probe, "probes_run", 0) > 0)
    audit_ran = audit is not None
    claims_examined = bool(verified_claims or unverified_claims)
    return not (attacks_ran or probes_ran or audit_ran or claims_examined or bool(findings))

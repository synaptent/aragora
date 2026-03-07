"""
Gauntlet Runner - Main orchestrator for adversarial validation.

Chains together:
1. Red Team attacks
2. Capability probes
3. Scenario matrix testing
4. Risk aggregation
"""

from __future__ import annotations

__all__ = [
    "GauntletRunner",
    "run_gauntlet",
]

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Awaitable, Callable

from .config import AttackCategory, GauntletConfig, ProbeCategory
from .result import (
    AttackSummary,
    GauntletResult,
    ProbeSummary,
    ScenarioSummary,
    SeverityLevel,
    Vulnerability,
)

# Type-only imports for optional sandbox support
if TYPE_CHECKING:
    from aragora.core import DebateResult
    from aragora.modes.probes.models import ProbeResult
    from aragora.modes.redteam import Attack
    from aragora.sandbox.executor import ExecutionMode, SandboxConfig, SandboxExecutor

# Runtime imports for optional sandbox support
_sandbox_executor_cls: type[SandboxExecutor] | None = None
_sandbox_config_cls: type[SandboxConfig] | None = None
_execution_mode_cls: type[ExecutionMode] | None = None
_create_strict_policy_fn: Callable[[], Any] | None = None

try:
    from aragora.sandbox.executor import ExecutionMode as _ExecutionMode
    from aragora.sandbox.executor import SandboxConfig as _SandboxConfig
    from aragora.sandbox.executor import SandboxExecutor as _SandboxExecutor
    from aragora.sandbox.policies import create_strict_policy as _create_strict_policy_impl

    _sandbox_executor_cls = _SandboxExecutor
    _sandbox_config_cls = _SandboxConfig
    _execution_mode_cls = _ExecutionMode
    _create_strict_policy_fn = _create_strict_policy_impl
    SANDBOX_AVAILABLE = True
except ImportError:
    SANDBOX_AVAILABLE = False

logger = logging.getLogger(__name__)

ProgressReporter = Callable[[str, float], None]
RunAgentFn = Callable[[Any, str], Awaitable[str]]


@dataclass
class _ScenarioDebateFallbackResult:
    """Minimal debate result shape for scenario fallback paths."""

    final_answer: str
    confidence: float
    consensus_reached: bool
    key_claims: list[str] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    rounds: int = 0


class GauntletRunner:
    """
    Main orchestrator for Gauntlet adversarial validation.

    Runs attacks, probes, and scenarios against a target input,
    aggregating findings into a unified GauntletResult.
    """

    def __init__(
        self,
        config: GauntletConfig | None = None,
        agent_factory: Callable[[str], Any] | None = None,
        run_agent_fn: RunAgentFn | None = None,
        enable_sandbox: bool = False,
        sandbox_config: SandboxConfig | None = None,
        auto_improve: bool = False,
    ):
        """
        Initialize GauntletRunner.

        Args:
            config: Gauntlet configuration
            agent_factory: Factory function to create agents by name
            run_agent_fn: Function to run an agent with a prompt
            enable_sandbox: Enable sandboxed code execution for code-based scenarios
            sandbox_config: Optional custom sandbox configuration
            auto_improve: Enable automatic self-improvement feedback loop.
                When True, high/critical findings are automatically queued
                as Nomic Loop improvement goals after each run completes.
        """
        self.config = config or GauntletConfig()
        self.agent_factory = agent_factory
        self.run_agent_fn = run_agent_fn
        self._vulnerability_counter = 0
        self._auto_improve = auto_improve

        # Initialize sandbox for code execution scenarios (Clawdbot pattern)
        self._sandbox: SandboxExecutor | None = None
        self.enable_sandbox = enable_sandbox and SANDBOX_AVAILABLE

        if (
            self.enable_sandbox
            and _sandbox_config_cls
            and _sandbox_executor_cls
            and _execution_mode_cls
        ):
            policy = _create_strict_policy_fn() if _create_strict_policy_fn else None
            sandbox_cfg = sandbox_config or _sandbox_config_cls(
                mode=_execution_mode_cls.SUBPROCESS,
                policy=policy,
                network_enabled=False,
                cleanup_on_complete=True,
            )
            self._sandbox = _sandbox_executor_cls(sandbox_cfg)
            logger.info("[gauntlet] Sandbox executor initialized for code execution scenarios")

    async def run(
        self,
        input_content: str,
        context: str = "",
        on_progress: ProgressReporter | None = None,
    ) -> GauntletResult:
        """
        Run the full Gauntlet validation.

        Args:
            input_content: The content to validate (spec, policy, architecture)
            context: Additional context for the validation
            on_progress: Optional callback for progress updates (phase, percent)

        Returns:
            GauntletResult with all findings
        """
        # Initialize result
        gauntlet_id = f"gauntlet-{uuid.uuid4().hex[:12]}"
        input_hash = hashlib.sha256(input_content.encode()).hexdigest()
        started_at = datetime.now()

        result = GauntletResult(
            gauntlet_id=gauntlet_id,
            input_hash=input_hash,
            input_summary=input_content[:500],
            started_at=started_at.isoformat(),
            config_used=self.config.to_dict(),
            agents_used=self.config.agents,
        )

        def report_progress(phase: str, percent: float) -> None:
            if on_progress:
                on_progress(phase, percent)
            logger.info(f"[gauntlet] {phase}: {percent:.0%}")

        try:
            # Phase 1: Red Team Attacks
            report_progress("red_team", 0.0)
            attack_summary = await self._run_red_team(
                input_content, context, result, report_progress
            )
            result.attack_summary = attack_summary
            report_progress("red_team", 1.0)

            # Phase 2: Capability Probes
            report_progress("probes", 0.0)
            probe_summary = await self._run_probes(input_content, context, result, report_progress)
            result.probe_summary = probe_summary
            report_progress("probes", 1.0)

            # Phase 3: Scenario Matrix (if enabled)
            if self.config.run_scenario_matrix:
                report_progress("scenarios", 0.0)
                scenario_summary = await self._run_scenarios(
                    input_content, context, result, report_progress
                )
                result.scenario_summary = scenario_summary
                report_progress("scenarios", 1.0)

            # Phase 4: Calculate Verdict
            report_progress("verdict", 0.0)
            result.calculate_verdict(
                critical_threshold=self.config.critical_threshold,
                high_threshold=self.config.high_threshold,
                vulnerability_rate_threshold=self.config.vulnerability_rate_threshold,
                robustness_threshold=self.config.robustness_threshold,
            )
            report_progress("verdict", 1.0)

        except (RuntimeError, ValueError, TimeoutError, OSError) as e:
            logger.error("[gauntlet] Error during run: %s", e)
            result.verdict_reasoning = f"Error during validation: {str(e)}"

        # Finalize timing
        completed_at = datetime.now()
        result.completed_at = completed_at.isoformat()
        result.duration_seconds = (completed_at - started_at).total_seconds()

        # Write critical findings to ImprovementQueue for self-improvement
        if result.vulnerabilities:
            critical_count = sum(
                1 for v in result.vulnerabilities if v.severity == SeverityLevel.CRITICAL
            )
            if critical_count > 0:
                try:
                    from aragora.nomic.feedback_orchestrator import (
                        ImprovementGoal,
                        ImprovementQueue,
                    )

                    queue = ImprovementQueue()
                    queue.push(
                        ImprovementGoal(
                            goal=f"Fix {critical_count} critical gauntlet findings from {gauntlet_id}",
                            source="gauntlet",
                            priority=0.95,
                            context={"gauntlet_id": gauntlet_id, "critical_count": critical_count},
                        )
                    )
                    logger.info("Enqueued %d critical findings to ImprovementQueue", critical_count)
                except (ImportError, RuntimeError, ValueError, OSError) as e:
                    logger.debug("ImprovementQueue feedback skipped: %s", type(e).__name__)

        # Auto-improve: close the security-to-improvement feedback loop
        if self._auto_improve:
            try:
                from aragora.gauntlet.auto_improve import GauntletAutoImprove

                auto = GauntletAutoImprove(enabled=True)
                auto_result = auto.on_run_complete(result)
                if auto_result.goals_queued > 0:
                    logger.info(
                        "[gauntlet] Auto-improve queued %d goals from %s",
                        auto_result.goals_queued,
                        gauntlet_id,
                    )
            except (ImportError, RuntimeError, ValueError, OSError) as e:
                logger.debug("Auto-improve skipped: %s", type(e).__name__)

        return result

    async def _run_red_team(
        self,
        input_content: str,
        context: str,
        result: GauntletResult,
        report_progress: ProgressReporter,
    ) -> AttackSummary:
        """Run red team attacks."""
        summary = AttackSummary()

        # Import here to avoid circular imports
        try:
            from aragora.modes.redteam import AttackType, RedTeamMode, RedTeamProtocol
        except ImportError:
            logger.warning("[gauntlet] RedTeam mode not available")
            return summary

        # Map AttackCategory to AttackType
        category_to_types = {
            AttackCategory.SECURITY: [AttackType.SECURITY, AttackType.ADVERSARIAL_INPUT],
            AttackCategory.INJECTION: [AttackType.ADVERSARIAL_INPUT],
            AttackCategory.LOGIC: [AttackType.LOGICAL_FALLACY, AttackType.COUNTEREXAMPLE],
            AttackCategory.COMPLIANCE: [AttackType.UNSTATED_ASSUMPTION, AttackType.COUNTEREXAMPLE],
            AttackCategory.GDPR: [AttackType.UNSTATED_ASSUMPTION, AttackType.COUNTEREXAMPLE],
            AttackCategory.HIPAA: [AttackType.UNSTATED_ASSUMPTION, AttackType.COUNTEREXAMPLE],
            AttackCategory.AI_ACT: [AttackType.UNSTATED_ASSUMPTION, AttackType.COUNTEREXAMPLE],
            AttackCategory.REGULATORY_VIOLATION: [
                AttackType.UNSTATED_ASSUMPTION,
                AttackType.COUNTEREXAMPLE,
            ],
            AttackCategory.EDGE_CASES: [AttackType.EDGE_CASE],
            AttackCategory.EDGE_CASE: [AttackType.EDGE_CASE],
            AttackCategory.ASSUMPTIONS: [AttackType.UNSTATED_ASSUMPTION],
            AttackCategory.STAKEHOLDER_CONFLICT: [
                AttackType.UNSTATED_ASSUMPTION,
                AttackType.COUNTEREXAMPLE,
            ],
            AttackCategory.ARCHITECTURE: [AttackType.SCALABILITY],
            AttackCategory.SCALABILITY: [AttackType.SCALABILITY, AttackType.RESOURCE_EXHAUSTION],
            AttackCategory.PERFORMANCE: [AttackType.SCALABILITY, AttackType.RESOURCE_EXHAUSTION],
            AttackCategory.RESOURCE_EXHAUSTION: [AttackType.RESOURCE_EXHAUSTION],
            AttackCategory.OPERATIONAL: [AttackType.DEPENDENCY_FAILURE, AttackType.RACE_CONDITION],
            AttackCategory.DEPENDENCY_FAILURE: [AttackType.DEPENDENCY_FAILURE],
            AttackCategory.RACE_CONDITION: [AttackType.RACE_CONDITION],
            AttackCategory.RACE_CONDITIONS: [AttackType.RACE_CONDITION],
        }

        # Collect attack types to run
        attack_types = []
        for category in self.config.attack_categories:
            attack_types.extend(category_to_types.get(category, []))
        attack_types = list(set(attack_types))  # Deduplicate

        if not attack_types:
            return summary

        # Configure protocol
        protocol = RedTeamProtocol(
            attack_rounds=self.config.attack_rounds,
            defend_rounds=1,
            include_steelman=False,
            include_strawman=False,
        )
        protocol.ATTACK_CATEGORIES = attack_types

        mode = RedTeamMode(protocol)

        # Create agents if factory available
        agents = []
        if self.agent_factory:
            for agent_name in self.config.agents[:3]:  # Max 3 red team agents
                try:
                    agent = self.agent_factory(agent_name)
                    agents.append(agent)
                except (ValueError, RuntimeError, ImportError, OSError) as e:
                    logger.warning("[gauntlet] Could not create agent %s: %s", agent_name, e)

        if not agents:
            logger.warning("[gauntlet] No agents available for red team")
            return summary

        # Create proposer agent for defense if we have a 4th agent available
        proposer_agent = None
        if self.agent_factory and len(self.config.agents) > 3:
            try:
                # Use 4th agent as proposer/defender
                proposer_agent = self.agent_factory(self.config.agents[3])
                logger.info("[gauntlet] Using %s as defender", self.config.agents[3])
            except (ValueError, RuntimeError, ImportError, OSError) as e:
                logger.debug("[gauntlet] Could not create proposer agent: %s", e)

        # Run red team
        try:
            redteam_result = await mode.run_redteam(
                target_proposal=f"{input_content}\n\nContext:\n{context}",
                proposer="target",
                red_team_agents=agents,
                run_agent_fn=self.run_agent_fn or self._default_run_agent,
                max_rounds=self.config.attack_rounds,
                proposer_agent=proposer_agent,
            )

            # Convert attacks to vulnerabilities
            for attack in redteam_result.critical_issues:
                # Execute evidence code in sandbox if enabled
                sandbox_result = None
                if self.enable_sandbox and attack.evidence:
                    sandbox_result = await self._execute_attack_evidence(attack.evidence)
                self._add_attack_as_vulnerability(attack, result, sandbox_result)

            summary.total_attacks = redteam_result.total_attacks
            summary.successful_attacks = redteam_result.successful_attacks
            summary.robustness_score = redteam_result.robustness_score
            summary.coverage_score = redteam_result.coverage_score

            # Count by category
            for attack in redteam_result.critical_issues:
                cat = attack.attack_type.value
                summary.by_category[cat] = summary.by_category.get(cat, 0) + 1

        except (RuntimeError, ValueError, TimeoutError, OSError) as e:
            logger.error("[gauntlet] Red team error: %s", e)

        return summary

    async def _run_probes(
        self,
        input_content: str,
        context: str,
        result: GauntletResult,
        report_progress: ProgressReporter,
    ) -> ProbeSummary:
        """Run capability probes."""
        summary = ProbeSummary()

        try:
            from aragora.modes.prober import CapabilityProber, ProbeType
        except ImportError:
            logger.warning("[gauntlet] Prober not available")
            return summary

        # Map ProbeCategory to ProbeType
        category_to_type = {
            ProbeCategory.CONTRADICTION: ProbeType.CONTRADICTION,
            ProbeCategory.HALLUCINATION: ProbeType.HALLUCINATION,
            ProbeCategory.SYCOPHANCY: ProbeType.SYCOPHANCY,
            ProbeCategory.PERSISTENCE: ProbeType.PERSISTENCE,
            ProbeCategory.CALIBRATION: ProbeType.CONFIDENCE_CALIBRATION,
            ProbeCategory.REASONING_DEPTH: ProbeType.REASONING_DEPTH,
            ProbeCategory.EDGE_CASE: ProbeType.EDGE_CASE,
            ProbeCategory.INSTRUCTION_INJECTION: ProbeType.INSTRUCTION_INJECTION,
            ProbeCategory.CAPABILITY_EXAGGERATION: ProbeType.CAPABILITY_EXAGGERATION,
        }

        probe_types = []
        for category in self.config.probe_categories:
            if category in category_to_type:
                probe_types.append(category_to_type[category])

        if not probe_types:
            return summary

        prober = CapabilityProber()

        # Probe each agent
        total_probes = 0
        total_vulns = 0

        for agent_name in self.config.agents:
            if not self.agent_factory:
                continue

            try:
                agent = self.agent_factory(agent_name)
                report = await prober.probe_agent(
                    target_agent=agent,
                    run_agent_fn=self.run_agent_fn or self._default_run_agent,
                    probe_types=probe_types,
                    probes_per_type=self.config.probes_per_category,
                )

                total_probes += report.probes_run
                total_vulns += report.vulnerabilities_found

                # Convert to vulnerabilities
                for probe_type, results in report.by_type.items():
                    for probe_result in results:
                        if probe_result.vulnerability_found:
                            self._add_probe_as_vulnerability(probe_result, agent_name, result)
                            cat = probe_type
                            summary.by_category[cat] = summary.by_category.get(cat, 0) + 1

            except (RuntimeError, ValueError, TimeoutError, OSError) as e:
                logger.error("[gauntlet] Probe error for %s: %s", agent_name, e)

        summary.probes_run = total_probes
        summary.vulnerabilities_found = total_vulns
        summary.vulnerability_rate = total_vulns / total_probes if total_probes > 0 else 0

        return summary

    async def _run_scenarios(
        self,
        input_content: str,
        context: str,
        result: GauntletResult,
        report_progress: ProgressReporter,
    ) -> ScenarioSummary:
        """Run scenario matrix."""
        summary = ScenarioSummary()

        try:
            from aragora.debate.scenarios import (
                MatrixDebateRunner,
                ScenarioComparator,
                ScenarioMatrix,
            )
        except ImportError:
            logger.warning("[gauntlet] Scenario matrix not available")
            return summary

        # Create scenario matrix from preset
        preset = self.config.scenario_preset or "comprehensive"
        matrix = ScenarioMatrix.from_presets(preset)

        if not matrix.scenarios:
            return summary

        # Create debate function using real Arena
        async def debate_func(task: str, ctx: str) -> DebateResult | _ScenarioDebateFallbackResult:
            try:
                from aragora import Arena, DebateProtocol, Environment
                from aragora.debate.arena_config import ArenaConfig

                # Create environment for this scenario
                env = Environment(
                    task=task,
                    context=ctx,
                )

                # Get agents - use agent_factory if provided, else use default agent names
                agents = []
                if self.agent_factory:
                    for agent_name in self.config.agents[: self.config.max_agents]:
                        try:
                            agent = self.agent_factory(agent_name)
                            if agent:
                                agents.append(agent)
                        except (ValueError, RuntimeError, ImportError, OSError) as e:
                            logger.debug("Failed to create agent %s: %s", agent_name, e)

                # Fallback to creating agents from names
                if not agents:
                    from aragora.agents import get_agents_by_names

                    agents = get_agents_by_names(self.config.agents[: self.config.max_agents])

                if not agents:
                    # Return mock result if no agents available
                    logger.warning("[gauntlet] No agents available for scenario debate")
                    return _ScenarioDebateFallbackResult(
                        final_answer=f"Analysis of: {task[:50]}",
                        confidence=0.5,
                        consensus_reached=False,
                    )

                # Configure protocol for short scenario debates
                protocol = DebateProtocol(
                    rounds=2,
                    consensus="majority",
                    consensus_threshold=0.6,
                    convergence_detection=False,  # Faster without embedding checks
                    role_rotation=False,  # Faster without role rotation
                    enable_breakpoints=False,  # No human intervention needed
                )

                # Configure arena
                arena_config = ArenaConfig(
                    enable_prompt_evolution=False,  # No learning during scenarios
                )

                # Run the debate
                arena = Arena.from_config(env, agents, protocol, arena_config)
                result = cast(DebateResult, await arena.run())

                return result

            except ImportError as e:
                logger.warning("[gauntlet] Arena not available: %s", e)
                return _ScenarioDebateFallbackResult(
                    final_answer=f"Analysis of: {task[:50]}",
                    confidence=0.5,
                    consensus_reached=False,
                )
            except (RuntimeError, ValueError, TimeoutError, OSError) as e:
                logger.error("[gauntlet] Arena debate error: %s", e)
                return _ScenarioDebateFallbackResult(
                    final_answer=f"Error during analysis: {str(e)[:100]}",
                    confidence=0.3,
                    consensus_reached=False,
                )

        runner = MatrixDebateRunner(
            debate_func=debate_func,
            max_parallel=self.config.max_parallel_scenarios,
        )

        try:
            matrix_result = await runner.run_matrix(
                task=input_content[:500],
                matrix=matrix,
                base_context=context,
            )

            summary.scenarios_run = len(matrix_result.results)
            summary.outcome_category = matrix_result.outcome_category.value
            summary.universal_conclusions = matrix_result.universal_conclusions[:5]

            # Add dissenting views to result
            for scenario_result in matrix_result.results:
                result.dissenting_views.extend(scenario_result.dissenting_views[:2])

            # Analyze for conditional patterns
            comparator = ScenarioComparator()
            analysis = comparator.analyze_matrix(matrix_result)
            summary.avg_similarity = analysis.get("avg_similarity", 0)
            summary.conditional_patterns = analysis.get("conditional_patterns", {})

        except (RuntimeError, ValueError, TimeoutError, OSError) as e:
            logger.error("[gauntlet] Scenario matrix error: %s", e)

        return summary

    def _add_attack_as_vulnerability(
        self,
        attack: Attack,
        result: GauntletResult,
        sandbox_result: dict[str, Any] | None = None,
    ) -> None:
        """Convert red team attack to vulnerability.

        Args:
            attack: Red team attack result
            result: GauntletResult to add vulnerability to
            sandbox_result: Optional sandbox execution result for evidence code
        """
        self._vulnerability_counter += 1

        severity = SeverityLevel.MEDIUM
        if attack.severity >= 0.9:
            severity = SeverityLevel.CRITICAL
        elif attack.severity >= 0.7:
            severity = SeverityLevel.HIGH
        elif attack.severity >= 0.4:
            severity = SeverityLevel.MEDIUM
        else:
            severity = SeverityLevel.LOW

        # Build evidence with optional sandbox execution results
        evidence = attack.evidence or ""
        if sandbox_result and sandbox_result.get("executed"):
            evidence += "\n\n--- Sandbox Execution ---"
            evidence += f"\nStatus: {sandbox_result.get('status', 'unknown')}"
            if sandbox_result.get("stdout"):
                evidence += f"\nOutput:\n{sandbox_result['stdout'][:500]}"
            if sandbox_result.get("stderr"):
                evidence += f"\nErrors:\n{sandbox_result['stderr'][:500]}"
            if sandbox_result.get("policy_violations"):
                evidence += f"\nPolicy Violations: {sandbox_result['policy_violations']}"

        vuln = Vulnerability(
            id=f"vuln-{self._vulnerability_counter:04d}",
            title=f"[{attack.attack_type.value}] {attack.attack_description[:60]}",
            description=attack.attack_description,
            severity=severity,
            category=attack.attack_type.value,
            source="red_team",
            evidence=evidence,
            mitigation=attack.mitigation or "",
            exploitability=attack.exploitability,
            impact=attack.severity,
            agent_name=attack.attacker,
        )
        result.add_vulnerability(vuln)

    def _add_probe_as_vulnerability(
        self, probe_result: ProbeResult, agent_name: str, result: GauntletResult
    ) -> None:
        """Convert probe result to vulnerability."""
        self._vulnerability_counter += 1

        # Map probe severity
        severity_map = {
            "critical": SeverityLevel.CRITICAL,
            "high": SeverityLevel.HIGH,
            "medium": SeverityLevel.MEDIUM,
            "low": SeverityLevel.LOW,
        }
        severity = SeverityLevel.MEDIUM
        if hasattr(probe_result, "severity") and probe_result.severity:
            severity = severity_map.get(probe_result.severity.value.lower(), SeverityLevel.MEDIUM)

        vuln = Vulnerability(
            id=f"vuln-{self._vulnerability_counter:04d}",
            title=f"[{probe_result.probe_type.value}] {probe_result.vulnerability_description or 'Vulnerability detected'}",
            description=probe_result.vulnerability_description or "",
            severity=severity,
            category=probe_result.probe_type.value,
            source="capability_probe",
            evidence=probe_result.evidence if hasattr(probe_result, "evidence") else "",
            agent_name=agent_name,
        )
        result.add_vulnerability(vuln)

    async def _execute_attack_evidence(self, evidence: str) -> dict[str, Any] | None:
        """Execute code embedded in attack evidence.

        Detects and executes code blocks from attack evidence to validate
        attack feasibility and capture sandbox policy violations.

        Args:
            evidence: Attack evidence that may contain code

        Returns:
            Sandbox execution result or None if no executable code found
        """
        if not evidence or not self.enable_sandbox:
            return None

        # Detect code patterns in evidence
        code, language = self._extract_code_from_evidence(evidence)
        if not code:
            return None

        logger.debug("[gauntlet] Executing %s code from attack evidence", language)
        return await self.execute_code_sandboxed(code, language, timeout=30.0)

    def _extract_code_from_evidence(self, evidence: str) -> tuple[str | None, str]:
        """Extract executable code from attack evidence.

        Looks for code blocks or common code patterns.

        Args:
            evidence: Attack evidence text

        Returns:
            Tuple of (code, language) or (None, "") if no code found
        """
        import re

        # Check for markdown code blocks
        code_block_pattern = r"```(\w+)?\n(.*?)```"
        matches = re.findall(code_block_pattern, evidence, re.DOTALL)
        if matches:
            lang, code = matches[0]
            language = (lang or "python").lower()
            if language in ("python", "py"):
                return code.strip(), "python"
            elif language in ("javascript", "js", "node"):
                return code.strip(), "javascript"
            elif language in ("bash", "sh", "shell"):
                return code.strip(), "bash"
            return code.strip(), "python"

        # Check for inline code patterns (Python-style)
        python_patterns = [
            r"import\s+\w+",
            r"def\s+\w+\s*\(",
            r"exec\s*\(",
            r"eval\s*\(",
            r"os\.\w+\s*\(",
            r"subprocess\.\w+",
        ]

        for pattern in python_patterns:
            if re.search(pattern, evidence):
                lines = evidence.split("\n")
                code_lines = []
                in_code = False
                for line in lines:
                    stripped = line.strip()
                    if re.search(pattern, stripped) and not in_code:
                        in_code = True
                    if in_code:
                        if (
                            stripped
                            and not stripped.startswith("#")
                            and not any(
                                c.isalnum() or c in "()[]{}.,;:=+-*/<>!@#$%^&|~`'\" \t_"
                                for c in stripped
                            )
                        ):
                            break
                        code_lines.append(line)
                if code_lines:
                    return "\n".join(code_lines), "python"

        return None, ""

    async def execute_code_sandboxed(
        self,
        code: str,
        language: str = "python",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Execute code in sandbox for code-based scenarios.

        Provides safe code execution for:
        - Code review gauntlet scenarios
        - Adversarial code injection testing
        - Generated code validation

        Args:
            code: Code to execute
            language: Programming language (python, javascript, bash)
            timeout: Maximum execution time in seconds

        Returns:
            Dict with execution results (stdout, stderr, exit_code, status)
        """
        if not self.enable_sandbox or self._sandbox is None:
            return {
                "status": "sandbox_disabled",
                "stdout": "",
                "stderr": "Sandbox not enabled for this gauntlet run",
                "exit_code": -1,
                "executed": False,
            }

        try:
            result = await self._sandbox.execute(
                code=code,
                language=language,
                timeout=timeout,
            )
            return {
                "status": result.status.value,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "duration_seconds": result.duration_seconds,
                "policy_violations": result.policy_violations,
                "executed": True,
            }
        except (RuntimeError, ValueError, TimeoutError, OSError) as e:
            logger.error("[gauntlet] Sandbox execution error: %s", e)
            return {
                "status": "error",
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "executed": False,
            }

    async def _default_run_agent(self, agent: Any, prompt: str) -> str:
        """Default agent runner (placeholder)."""
        generate = getattr(agent, "generate", None)
        if callable(generate):
            return cast(str, await generate(prompt, []))
        run = getattr(agent, "run", None)
        if callable(run):
            return cast(str, await run(prompt))
        return f"[No response - agent {agent} not callable]"


async def run_gauntlet(
    input_content: str,
    config: GauntletConfig | None = None,
    context: str = "",
) -> GauntletResult:
    """
    Convenience function to run a gauntlet validation.

    Args:
        input_content: Content to validate
        config: Optional configuration
        context: Additional context

    Returns:
        GauntletResult with findings
    """
    runner = GauntletRunner(config)
    return await runner.run(input_content, context)

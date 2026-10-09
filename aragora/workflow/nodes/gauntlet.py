"""
Gauntlet Step for adversarial validation within workflows.

Wraps the GauntletRunner to enable:
- Security validation as a workflow step
- Compliance checking (GDPR, HIPAA, SOC2, etc.)
- Red team attack simulation
- Capability probing
"""

from __future__ import annotations

import logging
from typing import Any, cast

from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)


class GauntletStep(BaseStep):
    """
    Workflow step that executes Gauntlet adversarial validation.

    Runs red team attacks, capability probes, and compliance checks
    against input content to identify vulnerabilities and risks.

    Config options:
        input_key: str - Context key for input content (default: "content")
        context_key: str - Context key for additional context (default: "context")
        attack_categories: list[str] - Attack types to run (default: all)
            Options: prompt_injection, jailbreak, data_extraction,
                     hallucination, bias, privacy, safety
        probe_categories: list[str] - Probe types to run (default: all)
            Options: reasoning, factuality, consistency, boundaries
        compliance_frameworks: list[str] - Compliance checks to run
            Options: gdpr, hipaa, soc2, pci_dss, nist_csf, ai_act
        require_passing: bool - Fail workflow on findings (default: True)
        severity_threshold: str - Minimum severity to fail (default: "medium")
            Options: low, medium, high, critical
        max_findings: int - Maximum findings before abort (default: 100)
        timeout_seconds: float - Validation timeout (default: 300)
        parallel_attacks: int - Concurrent attack threads (default: 3)
        agents: list[str] - Agent types for validation (default: ["claude"])

    Usage:
        step = GauntletStep(
            name="Security Validation",
            config={
                "attack_categories": ["prompt_injection", "data_extraction"],
                "compliance_frameworks": ["gdpr", "hipaa"],
                "require_passing": True,
                "severity_threshold": "medium",
            }
        )
        result = await step.execute(context)
    """

    ATTACK_CATEGORIES = [
        "prompt_injection",
        "jailbreak",
        "data_extraction",
        "hallucination",
        "bias",
        "privacy",
        "safety",
    ]

    PROBE_CATEGORIES = [
        "reasoning",
        "factuality",
        "consistency",
        "boundaries",
    ]

    COMPLIANCE_FRAMEWORKS = [
        "gdpr",
        "hipaa",
        "soc2",
        "pci_dss",
        "nist_csf",
        "ai_act",
        "sox",
    ]

    SEVERITY_LEVELS = ["low", "medium", "high", "critical"]

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)
        self._findings_count = 0
        self._highest_severity: str | None = None

    async def execute(self, context: WorkflowContext) -> Any:
        """Execute the gauntlet validation step."""
        config = {**self._config, **context.current_step_config}

        # Extract configuration
        input_key = config.get("input_key", "content")
        context_key = config.get("context_key", "context")
        attack_categories = config.get("attack_categories", self.ATTACK_CATEGORIES)
        probe_categories = config.get("probe_categories", self.PROBE_CATEGORIES)
        compliance_frameworks = config.get("compliance_frameworks", [])
        require_passing = config.get("require_passing", True)
        severity_threshold = config.get("severity_threshold", "medium")
        max_findings = config.get("max_findings", 100)
        timeout_seconds = config.get("timeout_seconds", 300.0)
        parallel_attacks = config.get("parallel_attacks", 3)
        agents = config.get("agents", ["claude"])

        # Get input content from context
        input_content = context.get_input(input_key)
        if not input_content:
            # Try from previous step outputs
            input_content = context.get_state(input_key)
        if not input_content:
            # Try from step outputs
            for step_id, output in context.step_outputs.items():
                if isinstance(output, dict) and input_key in output:
                    input_content = output[input_key]
                    break

        if not input_content:
            logger.warning("No input content found for GauntletStep '%s'", self.name)
            return {
                "success": False,
                "error": f"No input content found at key '{input_key}'",
                "findings": [],
            }

        # Get additional context
        additional_context = context.get_input(context_key, "")

        logger.info(
            "GauntletStep '%s' starting: attacks=%s, probes=%s, compliance=%s",
            self.name,
            len(attack_categories),
            len(probe_categories),
            len(compliance_frameworks),
        )

        try:
            from aragora.gauntlet.runner import GauntletRunner
            from aragora.gauntlet.config import GauntletConfig, AttackCategory, ProbeCategory
            from aragora.gauntlet.result import SeverityLevel

            # Build gauntlet configuration
            gauntlet_config = GauntletConfig(
                attack_categories=[
                    AttackCategory(cat)
                    for cat in attack_categories
                    if cat in [c.value for c in AttackCategory]
                ],
                probe_categories=[
                    ProbeCategory(cat)
                    for cat in probe_categories
                    if cat in [c.value for c in ProbeCategory]
                ],
                max_parallel_scenarios=parallel_attacks,
                timeout_seconds=timeout_seconds,
            )

            # Create agent factory for gauntlet
            def agent_factory(agent_type: str):
                from aragora.agents import create_agent
                from aragora.agents.base import AgentType

                return create_agent(cast(AgentType, agent_type))

            # Create runner
            runner = GauntletRunner(
                config=gauntlet_config,
                agent_factory=agent_factory,
            )

            # Run gauntlet
            progress_updates = []

            def on_progress(phase: str, percent: float):
                progress_updates.append({"phase": phase, "percent": percent})
                logger.debug("Gauntlet progress: %s - %.1f%%", phase, percent * 100)

            result = await runner.run(
                input_content=input_content,
                context=additional_context,
                on_progress=on_progress,
            )

            # Run compliance checks if specified
            compliance_results = []
            if compliance_frameworks:
                compliance_results = await self._run_compliance_checks(
                    input_content=input_content,
                    frameworks=compliance_frameworks,
                    agents=agents,
                )

            # Aggregate findings
            all_findings = list(result.vulnerabilities) + compliance_results
            self._findings_count = len(all_findings)

            # Determine highest severity
            severity_order = {s: i for i, s in enumerate(self.SEVERITY_LEVELS)}
            for finding in all_findings:
                finding_severity = getattr(finding, "severity", "low")
                if isinstance(finding_severity, SeverityLevel):
                    finding_severity = finding_severity.value
                if self._highest_severity is None or severity_order.get(
                    finding_severity, 0
                ) > severity_order.get(self._highest_severity, 0):
                    self._highest_severity = finding_severity

            # Determine if validation passed
            threshold_idx = severity_order.get(severity_threshold, 1)
            highest_idx = (
                severity_order.get(self._highest_severity, 0) if self._highest_severity else 0
            )
            passed = highest_idx < threshold_idx

            # Check if we should fail the workflow
            if require_passing and not passed:
                logger.warning(
                    "Gauntlet validation failed: found %s issues, highest severity: %s",
                    self._findings_count,
                    self._highest_severity,
                )

            return {
                "success": passed or not require_passing,
                "passed": passed,
                "findings_count": self._findings_count,
                "highest_severity": self._highest_severity,
                "severity_threshold": severity_threshold,
                "attacks_run": len(attack_categories),
                "probes_run": len(probe_categories),
                "compliance_checks_run": len(compliance_frameworks),
                "attack_summary": {
                    "total": result.attack_summary.total_attacks if result.attack_summary else 0,
                    "successful": (
                        result.attack_summary.successful_attacks if result.attack_summary else 0
                    ),
                },
                "probe_summary": {
                    "total": result.probe_summary.probes_run if result.probe_summary else 0,
                    "passed": (
                        result.probe_summary.probes_run - result.probe_summary.vulnerabilities_found
                        if result.probe_summary
                        else 0
                    ),
                },
                "compliance_results": (
                    [
                        {"framework": r.get("framework"), "passed": r.get("passed")}
                        for r in compliance_results
                    ]
                    if compliance_results
                    else []
                ),
                "findings": [
                    {
                        "id": getattr(f, "id", str(i)),
                        "severity": getattr(f, "severity", "unknown"),
                        "category": getattr(f, "category", "unknown"),
                        "description": getattr(f, "description", str(f)),
                    }
                    for i, f in enumerate(all_findings[:max_findings])
                ],
                "risk_score": result.risk_score if hasattr(result, "risk_score") else None,
            }

        except ImportError as e:
            logger.error("Failed to import gauntlet module: %s", e)
            return {
                "success": False,
                "error": f"Gauntlet module not available: {e}",
                "findings": [],
            }

    async def _run_compliance_checks(
        self,
        input_content: str,
        frameworks: list[str],
        agents: list[str],
    ) -> list[dict[str, Any]]:
        """Run compliance framework checks."""
        results = []

        try:
            from aragora.gauntlet.personas import (
                GDPRPersona,
                HIPAAPersona,
                SOC2Persona,
                PCIDSSPersona,
                NISTCSFPersona,
                AIActPersona,
                SOXPersona,
            )

            persona_map = {
                "gdpr": GDPRPersona,
                "hipaa": HIPAAPersona,
                "soc2": SOC2Persona,
                "pci_dss": PCIDSSPersona,
                "nist_csf": NISTCSFPersona,
                "ai_act": AIActPersona,
                "sox": SOXPersona,
            }

            for framework in frameworks:
                persona_class = persona_map.get(framework.lower())
                if not persona_class:
                    logger.warning("Unknown compliance framework: %s", framework)
                    continue

                try:
                    persona = persona_class()
                    # Run compliance check
                    check_result = await persona.evaluate(input_content)
                    results.append(
                        {
                            "framework": framework,
                            "passed": check_result.get("compliant", False),
                            "findings": check_result.get("findings", []),
                            "score": check_result.get("score", 0.0),
                        }
                    )
                except (
                    ImportError,
                    RuntimeError,
                    ValueError,
                    TypeError,
                    OSError,
                    AttributeError,
                ) as e:
                    logger.error("Compliance check failed for %s: %s", framework, e)
                    results.append(
                        {
                            "framework": framework,
                            "passed": False,
                            "error": "Compliance check failed",
                        }
                    )

        except ImportError as e:
            logger.warning("Compliance personas not available: %s", e)

        return results

    async def checkpoint(self) -> dict[str, Any]:
        """Save gauntlet step state for checkpointing."""
        return {
            "findings_count": self._findings_count,
            "highest_severity": self._highest_severity,
        }

    async def restore(self, state: dict[str, Any]) -> None:
        """Restore gauntlet step state from checkpoint."""
        self._findings_count = state.get("findings_count", 0)
        self._highest_severity = state.get("highest_severity")

    def validate_config(self) -> bool:
        """Validate gauntlet step configuration."""
        severity = self._config.get("severity_threshold", "medium")
        if severity not in self.SEVERITY_LEVELS:
            logger.warning("Invalid severity threshold: %s", severity)
            return False
        return True

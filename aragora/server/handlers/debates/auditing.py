"""
Auditing and security analysis endpoint handlers.

Endpoints:
- POST /api/debates/capability-probe - Run capability probes on an agent
- POST /api/debates/deep-audit - Run deep audit on a task
- POST /api/debates/:id/red-team - Run red team analysis on a debate
"""

from __future__ import annotations

__all__ = [
    "AuditRequestParser",
    "AuditAgentFactory",
    "AuditResultRecorder",
    "AuditingHandler",
]

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    pass

from aragora.server.http_utils import run_async
from aragora.server.middleware.rate_limit import rate_limit
from aragora.server.validation import validate_agent_name, validate_id
from aragora.utils.optional_imports import try_import_class

from ..base import (
    SAFE_SLUG_PATTERN,
    HandlerResult,
    error_response,
    invalidate_leaderboard_cache,
    json_response,
    require_permission,
    safe_error_message,
)
from ..secure import SecureHandler

logger = logging.getLogger(__name__)

# Lazy imports for optional dependencies using centralized utility
CapabilityProber, PROBER_AVAILABLE = try_import_class("aragora.modes.prober", "CapabilityProber")
RedTeamMode, REDTEAM_AVAILABLE = try_import_class("aragora.modes.redteam", "RedTeamMode")
create_agent, DEBATE_AVAILABLE = try_import_class("aragora.debate", "create_agent")

from aragora.debate.sanitization import OutputSanitizer
from aragora.server.errors import safe_error_message as _safe_error_message

# =============================================================================
# Audit Request Utilities
# =============================================================================


class AuditRequestParser:
    """Parse and validate audit request JSON bodies."""

    @staticmethod
    def _read_json(
        handler: Any, read_json_fn: Any
    ) -> tuple[dict[str, Any] | None, HandlerResult | None]:
        """Read and validate JSON body."""
        data = read_json_fn(handler)
        if data is None:
            return None, error_response("Invalid JSON body", 400)
        return data, None

    @staticmethod
    def _require_field(
        data: dict[str, Any], field: str, validator: Any = None
    ) -> tuple[str | None, HandlerResult | None]:
        """Extract and validate a required string field."""
        value = data.get(field, "").strip()
        if not value:
            return None, error_response(f"Missing required field: {field}", 400)
        if validator:
            is_valid, err = validator(value)
            if not is_valid:
                return None, error_response(err, 400)
        return value, None

    @staticmethod
    def _parse_int(
        data: dict[str, Any], field: str, default: int, max_val: int
    ) -> tuple[int, HandlerResult | None]:
        """Parse and clamp an integer field."""
        try:
            return min(int(data.get(field, default)), max_val), None
        except (ValueError, TypeError):
            return 0, error_response(f"{field} must be an integer", 400)

    @staticmethod
    def parse_capability_probe(
        handler: Any, read_json_fn: Any
    ) -> tuple[dict[str, Any] | None, HandlerResult | None]:
        """Parse capability probe request."""
        data, err = AuditRequestParser._read_json(handler, read_json_fn)
        if err:
            return None, err
        data = cast(dict[str, Any], data)

        agent_name, err = AuditRequestParser._require_field(data, "agent_name", validate_agent_name)
        if err:
            return None, err

        probes_per_type, err = AuditRequestParser._parse_int(data, "probes_per_type", 3, 10)
        if err:
            return None, err

        return {
            "agent_name": agent_name,
            "probe_types": data.get(
                "probe_types", ["contradiction", "hallucination", "sycophancy", "persistence"]
            ),
            "probes_per_type": probes_per_type,
            "model_type": data.get("model_type", "anthropic-api"),
        }, None

    @staticmethod
    def parse_deep_audit(
        handler: Any, read_json_fn: Any
    ) -> tuple[dict[str, Any] | None, HandlerResult | None]:
        """Parse deep audit request."""
        data, err = AuditRequestParser._read_json(handler, read_json_fn)
        if err:
            return None, err
        data = cast(dict[str, Any], data)

        task, err = AuditRequestParser._require_field(data, "task")
        if err:
            return None, err

        config_data = data.get("config", {})
        rounds, err = AuditRequestParser._parse_int(config_data, "rounds", 6, 10)
        if err:
            return None, err
        cross_exam, err = AuditRequestParser._parse_int(
            config_data, "cross_examination_depth", 3, 10
        )
        if err:
            return None, err

        try:
            risk_threshold = float(config_data.get("risk_threshold", 0.7))
        except (ValueError, TypeError):
            return None, error_response("risk_threshold must be a number", 400)

        return {
            "task": task,
            "context": data.get("context", ""),
            "agent_names": data.get("agent_names", []),
            "model_type": data.get("model_type", "anthropic-api"),
            "audit_type": config_data.get("audit_type", ""),
            "rounds": rounds,
            "cross_examination_depth": cross_exam,
            "risk_threshold": risk_threshold,
            "enable_research": config_data.get("enable_research", True),
        }, None


class AuditAgentFactory:
    """Create and validate agents for auditing."""

    @staticmethod
    def create_single_agent(
        model_type: str, agent_name: str, role: str = "proposer"
    ) -> tuple[Any, HandlerResult | None]:
        """Create a single agent with validation.

        Returns:
            Tuple of (agent, error_response). If error_response is set, return it.
        """
        if not DEBATE_AVAILABLE or create_agent is None:
            return None, error_response("Agent system not available", 503)

        try:
            agent = create_agent(model_type, name=agent_name, role=role)
            return agent, None
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
            logger.warning("Agent creation failed: %s: %s", type(e).__name__, e)
            return None, error_response("Failed to create agent", 400)

    @staticmethod
    def create_multiple_agents(
        model_type: str, agent_names: list[str], default_names: list[str], max_agents: int = 5
    ) -> tuple[list, HandlerResult | None]:
        """Create multiple agents for auditing.

        Returns:
            Tuple of (agents_list, error_response).
        """
        if not DEBATE_AVAILABLE or create_agent is None:
            return [], error_response("Agent system not available", 503)

        if not agent_names:
            agent_names = default_names

        agents = []
        for name in agent_names[:max_agents]:
            is_valid, _ = validate_id(name, "agent name")
            if not is_valid:
                continue
            try:
                agent = create_agent(model_type, name=name, role="proposer")
                agents.append(agent)
            except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
                logger.debug("Failed to create audit agent %s: %s", name, e)

        if len(agents) < 2:
            return [], error_response("Need at least 2 agents for deep audit", 400)

        return agents, None


class AuditResultRecorder:
    """Record audit results to ELO system and storage."""

    @staticmethod
    def record_probe_elo(elo_system: Any, agent_name: str, report: Any, report_id: str) -> None:
        """Record capability probe results to ELO system."""
        if not elo_system or report.probes_run <= 0:
            return

        robustness_score = 1.0 - report.vulnerability_rate
        try:
            elo_system.record_redteam_result(
                agent_name=agent_name,
                robustness_score=robustness_score,
                successful_attacks=report.vulnerabilities_found,
                total_attacks=report.probes_run,
                critical_vulnerabilities=report.critical_count,
                session_id=report_id,
            )
            # Invalidate leaderboard cache after ELO update
            invalidate_leaderboard_cache()
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.warning("Failed to record ELO result for capability probe: %s", e)

    @staticmethod
    def calculate_audit_elo_adjustments(verdict: Any, elo_system: Any) -> dict[str, int]:
        """Calculate ELO adjustments from audit findings."""
        if not elo_system:
            return {}

        elo_adjustments: dict[str, int] = {}
        for finding in verdict.findings:
            for agent_name in finding.agents_agree:
                elo_adjustments[agent_name] = elo_adjustments.get(agent_name, 0) + 2
            for agent_name in finding.agents_disagree:
                elo_adjustments[agent_name] = elo_adjustments.get(agent_name, 0) - 1

        return elo_adjustments

    @staticmethod
    def save_probe_report(nomic_dir: Any, agent_name: str, report: Any) -> None:
        """Save capability probe report to storage."""
        if not nomic_dir:
            return

        try:
            probes_dir = nomic_dir / "probes" / agent_name
            probes_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now().strftime("%Y-%m-%d")
            probe_file = probes_dir / f"{date_str}_{report.report_id}.json"
            probe_file.write_text(json.dumps(report.to_dict(), indent=2, default=str))
        except (OSError, ValueError, TypeError, AttributeError) as e:
            logger.error("Failed to save probe report to %s: %s", nomic_dir, e)

    @staticmethod
    def save_audit_report(
        nomic_dir: Any,
        audit_id: str,
        task: str,
        context: str,
        agents: list[Any],
        verdict: Any,
        config: Any,
        duration_ms: float,
        elo_adjustments: dict[str, Any],
    ) -> None:
        """Save deep audit report to storage."""
        if not nomic_dir:
            return

        try:
            audits_dir = nomic_dir / "audits"
            audits_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now().strftime("%Y-%m-%d")
            audit_file = audits_dir / f"{date_str}_{audit_id}.json"
            audit_file.write_text(
                json.dumps(
                    {
                        "audit_id": audit_id,
                        "task": task,
                        "context": context[:1000],
                        "agents": [a.name for a in agents],
                        "recommendation": verdict.recommendation,
                        "confidence": verdict.confidence,
                        "unanimous_issues": verdict.unanimous_issues,
                        "split_opinions": verdict.split_opinions,
                        "risk_areas": verdict.risk_areas,
                        "findings": [
                            {
                                "category": f.category,
                                "summary": f.summary,
                                "details": f.details,
                                "agents_agree": f.agents_agree,
                                "agents_disagree": f.agents_disagree,
                                "confidence": f.confidence,
                                "severity": f.severity,
                                "citations": f.citations,
                            }
                            for f in verdict.findings
                        ],
                        "config": {
                            "rounds": config.rounds,
                            "enable_research": config.enable_research,
                            "cross_examination_depth": config.cross_examination_depth,
                            "risk_threshold": config.risk_threshold,
                        },
                        "duration_ms": duration_ms,
                        "elo_adjustments": elo_adjustments,
                        "created_at": datetime.now().isoformat(),
                    },
                    indent=2,
                    default=str,
                )
            )
        except (OSError, ValueError, TypeError, AttributeError) as e:
            logger.error("Failed to save deep audit report to %s: %s", nomic_dir, e)


class AuditingHandler(SecureHandler):
    """Handler for audit log access and management.

    Extends SecureHandler for JWT-based authentication and audit logging.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "audit"

    """Handler for security auditing and capability probing endpoints."""

    ROUTES = [
        "/api/v1/debates/capability-probe",
        "/api/v1/debates/deep-audit",
        "/api/v1/redteam/attack-types",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        # Handle /api/debates/:id/red-team pattern
        if path.startswith("/api/v1/debates/") and path.endswith("/red-team"):
            return True
        return False

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route auditing requests to appropriate methods.

        Note: These endpoints require POST with request body, which handler provides.
        """
        from aragora.rbac.decorators import PermissionDeniedError

        try:
            if path == "/api/v1/debates/capability-probe":
                return self._run_capability_probe(handler)

            if path == "/api/v1/debates/deep-audit":
                return self._run_deep_audit(handler)

            if path == "/api/v1/redteam/attack-types":
                return self._get_attack_types()

            if path.startswith("/api/v1/debates/") and path.endswith("/red-team"):
                debate_id, err = self.extract_path_param(path, 4, "debate_id", SAFE_SLUG_PATTERN)
                if err:
                    return err
                return self._run_red_team_analysis(debate_id, handler)

            return None
        except PermissionDeniedError as exc:
            return self.handle_security_error(exc, handler)

    def _get_attack_types(self) -> HandlerResult:
        """Get available red team attack types metadata.

        GET /api/redteam/attack-types

        Returns list of attack types with descriptions.
        """
        if not REDTEAM_AVAILABLE:
            return error_response("Red team module not available", 503)

        try:
            from aragora.modes.redteam import AttackType

            attack_types = []
            for attack_type in AttackType:
                attack_types.append(
                    {
                        "type": attack_type.value,
                        "name": attack_type.name.replace("_", " ").title(),
                        "category": self._get_attack_category(attack_type),
                    }
                )

            return json_response(
                {
                    "attack_types": attack_types,
                    "count": len(attack_types),
                }
            )

        except ImportError as e:
            logger.warning("Red team module not available: %s", e)
            return error_response("Red team module not available", 503)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Data error getting attack types: %s", e)
            return error_response(safe_error_message(e, "get attack types"), 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected error getting attack types: %s", e)
            return error_response(safe_error_message(e, "get attack types"), 500)

    def _get_attack_category(self, attack_type: Any) -> str:
        """Categorize attack types for easier filtering."""
        from aragora.modes.redteam import AttackType

        logic_attacks = {
            AttackType.LOGICAL_FALLACY,
            AttackType.UNSTATED_ASSUMPTION,
            AttackType.COUNTEREXAMPLE,
        }
        system_attacks = {
            AttackType.SECURITY,
            AttackType.RESOURCE_EXHAUSTION,
            AttackType.RACE_CONDITION,
            AttackType.DEPENDENCY_FAILURE,
        }
        if attack_type in logic_attacks:
            return "logic"
        elif attack_type in system_attacks:
            return "system"
        else:
            return "robustness"

    @require_permission("admin:audit")
    def _run_capability_probe(self, handler: Any, user: Any = None) -> HandlerResult:
        """Run capability probes on an agent to find vulnerabilities.

        Requires admin:audit permission (admin/owner only).

        POST body:
            agent_name: Name of agent to probe (required)
            probe_types: List of probe types (optional)
            probes_per_type: Number of probes per type (default: 3, max: 10)
            model_type: Agent model type (optional, default: anthropic-api)
        """
        if not PROBER_AVAILABLE:
            logger.warning("Capability probe requested but prober module not available")
            return error_response("Capability prober not available", 503)

        start_time = time.time()
        try:
            # Parse and validate request
            parsed, err = AuditRequestParser.parse_capability_probe(handler, self._read_json_body)
            if err:
                logger.info("Capability probe request validation failed")
                return err
            parsed = cast(dict[str, Any], parsed)

            agent_name = parsed["agent_name"]
            model_type = parsed["model_type"]
            logger.info(
                "Starting capability probe: agent=%s, model=%s, probe_types=%s, probes_per_type=%d",
                agent_name,
                model_type,
                parsed["probe_types"],
                parsed["probes_per_type"],
            )

            from aragora.modes.prober import CapabilityProber, ProbeType

            # Convert string probe types to enum
            probe_types = []
            for pt_str in parsed["probe_types"]:
                try:
                    probe_types.append(ProbeType(pt_str))
                except ValueError as e:
                    logger.debug("Skipping invalid probe type '%s': %s", pt_str, e)
            if not probe_types:
                return error_response("No valid probe types specified", 400)

            # Create agent
            agent, err = AuditAgentFactory.create_single_agent(model_type, agent_name)
            if err:
                return err

            # Create prober and run
            elo_system = self.ctx.get("elo_system")
            prober = CapabilityProber(elo_system=elo_system, elo_penalty_multiplier=5.0)
            report_id = f"probe-report-{uuid.uuid4().hex[:8]}"

            async def run_agent_fn(target_agent: Any, prompt: str) -> str:
                from aragora.server.stream.arena_hooks import streaming_task_context

                agent_name = getattr(target_agent, "name", "probe-agent")
                task_id = f"{agent_name}:audit_probe"
                try:
                    with streaming_task_context(task_id):
                        if asyncio.iscoroutinefunction(target_agent.generate):
                            raw_output = await target_agent.generate(prompt)
                        else:
                            raw_output = target_agent.generate(prompt)
                    return OutputSanitizer.sanitize_agent_output(raw_output, target_agent.name)
                except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
                    logger.debug("Agent generation failed: %s: %s", type(e).__name__, e)
                    return "[Agent Error: Generation failed]"

            try:
                report = run_async(
                    prober.probe_agent(
                        target_agent=agent,
                        run_agent_fn=run_agent_fn,
                        probe_types=probe_types,
                        probes_per_type=parsed["probes_per_type"],
                    )
                )
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                logger.error(
                    "Capability probe execution failed: agent=%s, error=%s",
                    agent_name,
                    e,
                    exc_info=True,
                )
                return error_response("Probe execution failed", 500)

            # Transform results for response
            by_type_transformed = self._transform_probe_results(report.by_type)

            # Record ELO and save report
            AuditResultRecorder.record_probe_elo(elo_system, agent_name, report, report_id)
            AuditResultRecorder.save_probe_report(self.ctx.get("nomic_dir"), agent_name, report)

            # Build response
            passed_count = report.probes_run - report.vulnerabilities_found
            pass_rate = passed_count / report.probes_run if report.probes_run > 0 else 1.0
            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                "Capability probe completed: agent=%s, probes=%d, vulnerabilities=%d, "
                "pass_rate=%.2f, duration_ms=%.1f",
                agent_name,
                report.probes_run,
                report.vulnerabilities_found,
                pass_rate,
                duration_ms,
            )

            return json_response(
                {
                    "report_id": report.report_id,
                    "target_agent": agent_name,
                    "probes_run": report.probes_run,
                    "vulnerabilities_found": report.vulnerabilities_found,
                    "vulnerability_rate": round(report.vulnerability_rate, 3),
                    "elo_penalty": round(report.elo_penalty, 1),
                    "by_type": by_type_transformed,
                    "summary": {
                        "total": report.probes_run,
                        "passed": passed_count,
                        "failed": report.vulnerabilities_found,
                        "pass_rate": round(pass_rate, 3),
                        "critical": report.critical_count,
                        "high": report.high_count,
                        "medium": report.medium_count,
                        "low": report.low_count,
                    },
                    "recommendations": report.recommendations,
                    "created_at": report.created_at,
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid capability probe request data: %s", e)
            return error_response(_safe_error_message(e, "capability_probe"), 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected capability probe error: %s", e)
            return error_response(_safe_error_message(e, "capability_probe"), 500)

    def _transform_probe_results(self, by_type: dict[str, Any]) -> dict[str, Any]:
        """Transform probe results for API response."""
        by_type_transformed = {}
        for probe_type_key, results in by_type.items():
            transformed_results = []
            for r in results:
                result_dict = r.to_dict() if hasattr(r, "to_dict") else r
                passed = not result_dict.get("vulnerability_found", False)
                transformed_results.append(
                    {
                        "probe_id": result_dict.get("probe_id", ""),
                        "type": result_dict.get("probe_type", probe_type_key),
                        "passed": passed,
                        "severity": (
                            str(result_dict.get("severity", "")).lower()
                            if result_dict.get("severity")
                            else None
                        ),
                        "description": result_dict.get("vulnerability_description", ""),
                        "details": result_dict.get("evidence", ""),
                        "response_time_ms": result_dict.get("response_time_ms", 0),
                    }
                )
            by_type_transformed[probe_type_key] = transformed_results
        return by_type_transformed

    @rate_limit(requests_per_minute=5, burst=2, limiter_name="deep_audit")
    @require_permission("admin:audit")
    def _run_deep_audit(self, handler: Any, user: Any = None) -> HandlerResult:
        """Run a deep audit (Heavy3-inspired intensive multi-round debate protocol).

        Requires admin:audit permission (admin/owner only).

        POST body:
            task: The question/decision to audit (required)
            context: Additional context/documents (optional)
            agent_names: List of agent names (optional)
            model_type: Agent model type (optional, default: anthropic-api)
            config: Optional configuration object
        """
        try:
            from aragora.modes.deep_audit import (
                CODE_ARCHITECTURE_AUDIT,
                CONTRACT_AUDIT,
                STRATEGY_AUDIT,
                DeepAuditConfig,
                DeepAuditOrchestrator,
            )
        except ImportError:
            logger.warning("Deep audit requested but module not available")
            return error_response("Deep audit module not available", 503)

        start_time = time.time()
        try:
            # Parse and validate request
            parsed, err = AuditRequestParser.parse_deep_audit(handler, self._read_json_body)
            if err:
                logger.info("Deep audit request validation failed")
                return err
            parsed = cast(dict[str, Any], parsed)

            task = parsed["task"]
            context = parsed["context"]
            logger.info(
                "Starting deep audit: task_len=%d, context_len=%d, audit_type=%s, rounds=%d",
                len(task),
                len(context),
                parsed["audit_type"] or "default",
                parsed["rounds"],
            )

            # Select config based on audit type or use parsed values
            config = self._get_audit_config(
                parsed["audit_type"],
                parsed,
                DeepAuditConfig,
                STRATEGY_AUDIT,
                CONTRACT_AUDIT,
                CODE_ARCHITECTURE_AUDIT,
            )

            # Create agents
            default_names = ["Claude-Analyst", "Claude-Skeptic", "Claude-Synthesizer"]
            agents, err = AuditAgentFactory.create_multiple_agents(
                parsed["model_type"], parsed["agent_names"], default_names
            )
            if err:
                logger.warning("Deep audit agent creation failed")
                return err

            audit_id = f"audit-{uuid.uuid4().hex[:8]}"
            agent_names = [a.name for a in agents]
            logger.debug("Deep audit agents created: %s", agent_names)

            # Run audit
            try:
                verdict = run_async(DeepAuditOrchestrator(agents, config).run(task, context))
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                logger.error(
                    "Deep audit execution failed: audit_id=%s, error=%s",
                    audit_id,
                    e,
                    exc_info=True,
                )
                return error_response(safe_error_message(e, "deep audit"), 500)

            duration_ms = (time.time() - start_time) * 1000

            # Calculate ELO and save report
            elo_system = self.ctx.get("elo_system")
            elo_adjustments = AuditResultRecorder.calculate_audit_elo_adjustments(
                verdict, elo_system
            )
            AuditResultRecorder.save_audit_report(
                self.ctx.get("nomic_dir"),
                audit_id,
                task,
                context,
                agents,
                verdict,
                config,
                duration_ms,
                elo_adjustments,
            )

            logger.info(
                "Deep audit completed: audit_id=%s, findings=%d, confidence=%.2f, "
                "unanimous=%d, split=%d, duration_ms=%.1f",
                audit_id,
                len(verdict.findings),
                verdict.confidence,
                len(verdict.unanimous_issues),
                len(verdict.split_opinions),
                duration_ms,
            )

            # Build response
            return json_response(
                {
                    "audit_id": audit_id,
                    "task": task,
                    "recommendation": verdict.recommendation,
                    "confidence": verdict.confidence,
                    "unanimous_issues": verdict.unanimous_issues,
                    "split_opinions": verdict.split_opinions,
                    "risk_areas": verdict.risk_areas,
                    "findings": [
                        {
                            "category": f.category,
                            "summary": f.summary,
                            "details": f.details[:500],
                            "agents_agree": f.agents_agree,
                            "agents_disagree": f.agents_disagree,
                            "confidence": f.confidence,
                            "severity": f.severity,
                        }
                        for f in verdict.findings
                    ],
                    "cross_examination_notes": verdict.cross_examination_notes[:2000],
                    "citations": verdict.citations[:20],
                    "rounds_completed": config.rounds,
                    "duration_ms": round(duration_ms, 1),
                    "agents": [a.name for a in agents],
                    "elo_adjustments": elo_adjustments,
                    "summary": {
                        "unanimous_count": len(verdict.unanimous_issues),
                        "split_count": len(verdict.split_opinions),
                        "risk_count": len(verdict.risk_areas),
                        "findings_count": len(verdict.findings),
                        "high_severity_count": sum(
                            1 for f in verdict.findings if f.severity >= 0.7
                        ),
                    },
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid deep audit request data: %s", e)
            return error_response(_safe_error_message(e, "deep_audit"), 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected deep audit error: %s", e)
            return error_response(_safe_error_message(e, "deep_audit"), 500)

    def _get_audit_config(
        self,
        audit_type: str,
        parsed: dict[str, Any],
        config_class: Any,
        strategy_preset: Any,
        contract_preset: Any,
        code_preset: Any,
    ) -> Any:
        """Get audit config from preset or parsed values."""
        if audit_type == "strategy":
            return strategy_preset
        elif audit_type == "contract":
            return contract_preset
        elif audit_type == "code_architecture":
            return code_preset
        else:
            return config_class(
                rounds=parsed["rounds"],
                enable_research=parsed["enable_research"],
                cross_examination_depth=parsed["cross_examination_depth"],
                risk_threshold=parsed["risk_threshold"],
            )

    def _analyze_proposal_for_redteam(
        self, proposal: str, attack_types: list[Any], debate_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Analyze a proposal for potential vulnerabilities."""
        try:
            from aragora.modes.redteam import AttackType
        except ImportError:
            logger.debug("RedTeam module not available for proposal analysis")
            return []

        findings = []
        proposal_lower = proposal.lower() if proposal else ""

        vulnerability_patterns = {
            "logical_fallacy": {
                "keywords": ["always", "never", "all", "none", "obviously", "clearly"],
                "description": "Absolute language suggests potential logical fallacy",
                "base_severity": 0.4,
            },
            "edge_case": {
                "keywords": ["usually", "most", "typical", "normal", "standard"],
                "description": "Generalization may miss edge cases",
                "base_severity": 0.5,
            },
            "unstated_assumption": {
                "keywords": ["should", "must", "need", "require"],
                "description": "Prescriptive language may hide unstated assumptions",
                "base_severity": 0.45,
            },
            "counterexample": {
                "keywords": ["best", "optimal", "superior", "only"],
                "description": "Strong claims may be vulnerable to counterexamples",
                "base_severity": 0.55,
            },
            "scalability": {
                "keywords": ["scale", "growth", "expand", "distributed"],
                "description": "Scalability claims require validation",
                "base_severity": 0.5,
            },
            "security": {
                "keywords": ["secure", "safe", "protected", "auth", "encrypt"],
                "description": "Security claims need rigorous testing",
                "base_severity": 0.6,
            },
        }

        for attack_type in attack_types:
            try:
                AttackType(attack_type)
            except ValueError:
                logger.debug("Skipping invalid attack type: %s", attack_type)
                continue

            pattern: dict[str, Any] = vulnerability_patterns.get(attack_type, {})
            keywords: list[str] = pattern.get("keywords") or []
            base_severity = float(pattern.get("base_severity") or 0.5)

            matches = sum(1 for kw in keywords if kw in proposal_lower)
            severity = min(0.9, base_severity + (matches * 0.1))

            if matches > 0:
                findings.append(
                    {
                        "attack_type": attack_type,
                        "description": pattern.get("description", f"Potential {attack_type} issue"),
                        "severity": round(severity, 2),
                        "exploitability": round(severity * 0.8, 2),
                        "keyword_matches": matches,
                        "requires_manual_review": severity > 0.6,
                    }
                )
            else:
                findings.append(
                    {
                        "attack_type": attack_type,
                        "description": f"No obvious {attack_type.replace('_', ' ')} patterns detected",
                        "severity": round(base_severity * 0.5, 2),
                        "exploitability": round(base_severity * 0.3, 2),
                        "keyword_matches": 0,
                        "requires_manual_review": False,
                    }
                )

        return findings

    @rate_limit(requests_per_minute=5, burst=2, limiter_name="red_team")
    @require_permission("admin:audit")
    def _run_red_team_analysis(
        self, debate_id: str, handler: Any, user: Any = None
    ) -> HandlerResult:
        """Run adversarial red-team analysis on a debate.

        Requires admin:audit permission (admin/owner only).

        POST body:
            attack_types: List of attack types (optional)
            max_rounds: Maximum attack/defend rounds (default: 3, max: 5)
            focus_proposal: Optional specific proposal to analyze
        """
        if not REDTEAM_AVAILABLE:
            logger.warning("Red team analysis requested but module not available")
            return error_response("Red team mode not available", 503)

        start_time = time.time()
        try:
            data = self._read_json_body(handler)
            if data is None:
                data = {}

            storage = self.ctx.get("storage")
            if not storage:
                logger.warning("Red team analysis failed: storage not configured")
                return error_response("Storage not configured", 500)

            debate_data = storage.get_by_slug(debate_id) or storage.get_by_id(debate_id)
            if not debate_data:
                logger.info("Red team analysis: debate not found: %s", debate_id)
                return error_response("Debate not found", 404)

            logger.info("Starting red team analysis: debate_id=%s", debate_id)

            attack_type_names = data.get(
                "attack_types",
                [
                    "logical_fallacy",
                    "edge_case",
                    "unstated_assumption",
                    "counterexample",
                    "scalability",
                    "security",
                ],
            )
            max_rounds = min(int(data.get("max_rounds", 3)), 5)

            focus_proposal = data.get("focus_proposal") or (
                debate_data.get("consensus_answer")
                or debate_data.get("final_answer")
                or debate_data.get("task", "")
            )

            session_id = f"redteam-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

            # Analyze proposal for potential weaknesses
            findings = self._analyze_proposal_for_redteam(
                focus_proposal, attack_type_names, debate_data
            )

            # Calculate robustness based on finding severity
            avg_severity = sum(f.get("severity", 0.5) for f in findings) / max(len(findings), 1)
            robustness_score = max(0.0, 1.0 - avg_severity)
            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                "Red team analysis completed: debate_id=%s, session_id=%s, findings=%d, "
                "robustness=%.2f, duration_ms=%.1f",
                debate_id,
                session_id,
                len(findings),
                robustness_score,
                duration_ms,
            )

            return json_response(
                {
                    "session_id": session_id,
                    "debate_id": debate_id,
                    "target_proposal": focus_proposal[:500] if focus_proposal else "",
                    "attack_types": attack_type_names,
                    "max_rounds": max_rounds,
                    "findings": findings,
                    "robustness_score": round(robustness_score, 2),
                    "status": "analysis_complete",
                    "created_at": datetime.now().isoformat(),
                }
            )

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid red team analysis request data for debate %s: %s", debate_id, e)
            return error_response(_safe_error_message(e, "red_team_analysis"), 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Unexpected red team analysis error for debate %s: %s", debate_id, e)
            return error_response(_safe_error_message(e, "red_team_analysis"), 500)

    # _read_json_body moved to BaseHandler.read_json_body
    def _read_json_body(self, handler: Any) -> dict[str, Any] | None:
        """Read and parse JSON body - delegates to base class."""
        return self.read_json_body(handler)

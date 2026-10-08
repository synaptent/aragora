"""
Context gathering phase for nomic loop.

Phase 0: Gather codebase understanding
- All agents explore codebase to gather context
- Each agent uses its native codebase exploration harness
- Prevents proposals for features that already exist
- (New) CodebaseAuditor identifies improvement opportunities
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
from collections.abc import Callable

from . import ContextResult, AuditFindingSummary

if TYPE_CHECKING:
    from aragora.audit.codebase_auditor import CodebaseAuditor

logger = logging.getLogger(__name__)

# Optional metrics recording (imported lazily to avoid circular imports)
_metrics_recorder: Callable[[str, str, float], None] | None = None
_agent_metrics_recorder: Callable[[str, str, float], None] | None = None


def set_metrics_recorder(
    phase_recorder: Callable[[str, str, float], None] | None = None,
    agent_recorder: Callable[[str, str, float], None] | None = None,
) -> None:
    """Set the metrics recorder callbacks for profiling.

    Args:
        phase_recorder: Callback(phase, outcome, duration_seconds)
        agent_recorder: Callback(phase, agent, duration_seconds)
    """
    global _metrics_recorder, _agent_metrics_recorder
    _metrics_recorder = phase_recorder
    _agent_metrics_recorder = agent_recorder


class ContextPhase:
    """
    Handles context gathering from multiple agents.

    Each agent uses its native codebase exploration harness:
    - Claude → Claude Code CLI (native codebase access)
    - Codex → Codex CLI (native codebase access)
    - Gemini → Kilo Code CLI (agentic codebase exploration)
    - Grok → Kilo Code CLI (agentic codebase exploration)
    """

    def __init__(
        self,
        aragora_path: Path,
        claude_agent: Any,
        codex_agent: Any,
        kilocode_available: bool = False,
        skip_kilocode: bool = False,
        kilocode_agent_factory: Callable[..., Any] | None = None,
        cycle_count: int = 0,
        log_fn: Callable[..., None] | None = None,
        stream_emit_fn: Callable[..., None] | None = None,
        get_features_fn: Callable[[], str] | None = None,
        codebase_auditor: Optional["CodebaseAuditor"] = None,
        enable_audit: bool = True,
    ):
        """
        Initialize the context gathering phase.

        Args:
            aragora_path: Path to the aragora project root
            claude_agent: Claude agent instance
            codex_agent: Codex agent instance
            kilocode_available: Whether KiloCode is available
            skip_kilocode: Whether to skip KiloCode for context gathering
            kilocode_agent_factory: Factory to create KiloCode agents
            cycle_count: Current cycle number
            log_fn: Function to log messages
            stream_emit_fn: Function to emit streaming events
            get_features_fn: Function to get current features as fallback
            codebase_auditor: Optional CodebaseAuditor for identifying issues
            enable_audit: Whether to run codebase audit (default True)
        """
        self.aragora_path = aragora_path
        self.claude = claude_agent
        self.codex = codex_agent
        self.kilocode_available = kilocode_available
        self.skip_kilocode = skip_kilocode
        self.kilocode_agent_factory = kilocode_agent_factory
        self.cycle_count = cycle_count
        self._log = log_fn or print
        self._stream_emit = stream_emit_fn or (lambda *args: None)
        self._get_features = get_features_fn or (lambda: "No features available")
        self.codebase_auditor = codebase_auditor
        self.enable_audit = enable_audit

    async def execute(self) -> ContextResult:
        """
        Execute the context gathering phase.

        Returns:
            ContextResult with gathered codebase context
        """
        phase_start = time.perf_counter()
        phase_start_dt = datetime.now()

        # Determine how many agents will participate
        use_kilocode = self.kilocode_available and not self.skip_kilocode
        self._log(
            "  [context] kilocode_available="
            f"{self.kilocode_available} skip_kilocode={self.skip_kilocode} "
            f"factory={'yes' if self.kilocode_agent_factory else 'no'}"
        )
        agents_count = 2  # Claude + Codex always
        if use_kilocode:
            agents_count = 4  # + Gemini + Grok via Kilo Code
            self._log("\n" + "=" * 70)
            self._log("PHASE 0: CONTEXT GATHERING (All 4 agents with codebase access)")
            self._log("  Claude → Claude Code | Codex → Codex CLI")
            self._log("  Gemini → Kilo Code  | Grok → Kilo Code")
            self._log("=" * 70)
        else:
            self._log("\n" + "=" * 70)
            self._log("PHASE 0: CONTEXT GATHERING (Claude + Codex)")
            if self.kilocode_available and self.skip_kilocode:
                self._log("  Note: KiloCode skipped (timeouts); Gemini/Grok join in debates")
            else:
                self._log("  Note: Install kilocode CLI to enable Gemini/Grok exploration")
            self._log("=" * 70)

        self._stream_emit("on_phase_start", "context", self.cycle_count, {"agents": agents_count})

        # Build exploration prompt
        explore_prompt = self._build_explore_prompt()

        # Build list of exploration tasks
        exploration_tasks = [
            self._gather_with_agent(self.claude, "claude", "Claude Code"),
            self._gather_with_agent(self.codex, "codex", "Codex CLI"),
        ]

        # Add Gemini and Grok via Kilo Code if available (and not skipped)
        if use_kilocode and self.kilocode_agent_factory:
            gemini_explorer = self.kilocode_agent_factory(
                name="gemini-explorer",
                provider_id="openrouter/google/gemini-3.1-pro-preview",
                model="openrouter/google/gemini-3.1-pro-preview",
                role="explorer",
                timeout=600,
                mode="architect",
            )
            grok_explorer = self.kilocode_agent_factory(
                name="grok-explorer",
                provider_id="openrouter/x-ai/grok-4.5",
                model="openrouter/x-ai/grok-4.5",
                role="explorer",
                timeout=600,
                mode="architect",
            )
            exploration_tasks.extend(
                [
                    self._gather_with_agent(gemini_explorer, "gemini", "Kilo Code"),
                    self._gather_with_agent(grok_explorer, "grok", "Kilo Code"),
                ]
            )

        # Run codebase audit in parallel with agent exploration (if enabled)
        audit_task = None
        if self.enable_audit and self.codebase_auditor:
            self._log("  [audit] Running codebase audit in parallel...")
            audit_task = asyncio.create_task(self._run_codebase_audit())

        # Run all agents in parallel
        results = await asyncio.gather(*exploration_tasks, return_exceptions=True)

        # Combine the context from all agents
        combined_context = []
        for result in results:
            if isinstance(result, BaseException):
                continue
            name, harness, content = result
            if content and "Error:" not in content:
                combined_context.append(
                    f"=== {name.upper()}'S CODEBASE ANALYSIS (via {harness}) ===\n{content}"
                )

        # If all failed, fall back to basic context
        if not combined_context:
            self._log("  Warning: Context gathering failed, using basic context")
            combined_context = [f"Current features (from docstring):\n{self._get_features()}"]

        gathered_context = "\n\n".join(combined_context)

        # Collect audit results
        audit_findings: list[AuditFindingSummary] = []
        audit_proposals: list[str] = []
        if audit_task:
            try:
                audit_findings, audit_proposals = await audit_task
                if audit_findings:
                    self._log(f"  [audit] Found {len(audit_findings)} audit findings")
                    # Add audit context to gathered context
                    audit_summary = self._format_audit_findings(audit_findings)
                    combined_context.append(audit_summary)
                    gathered_context = "\n\n".join(combined_context)
            except Exception as e:
                self._log(f"  [audit] Audit failed: {e}")
                logger.warning(f"Codebase audit failed: {e}")

        phase_duration = time.perf_counter() - phase_start
        success = len(combined_context) > 0
        self._log(
            f"  Context gathered from {len(combined_context)} agents in {phase_duration:.1f}s"
        )
        self._stream_emit(
            "on_phase_end",
            "context",
            self.cycle_count,
            success,
            phase_duration,
            {
                "agents": len(combined_context),
                "context_length": len(gathered_context),
                "audit_findings": len(audit_findings),
            },
        )

        # Record metrics if configured
        if _metrics_recorder:
            _metrics_recorder("context", "success" if success else "failure", phase_duration)

        return ContextResult(
            success=success,
            data={
                "agents_succeeded": len(combined_context),
                "audit_findings_count": len(audit_findings),
            },
            duration_seconds=phase_duration,
            codebase_summary=gathered_context,
            recent_changes="",  # Can be populated if needed
            open_issues=[],
            audit_findings=audit_findings,
            audit_proposals=audit_proposals,
        )

    def _build_explore_prompt(self) -> str:
        """Build the codebase exploration prompt."""
        return f"""Explore the aragora codebase and provide a comprehensive summary of EXISTING features.

Working directory: {self.aragora_path}

Your task:
1. Read key files: aragora/__init__.py, aragora/debate/orchestrator.py, aragora/server/stream.py
2. List ALL existing major features and capabilities
3. Note any features related to: streaming, real-time, visualization, spectator mode, WebSocket
4. Identify the project's current architecture and patterns

Output format:
## EXISTING FEATURES (DO NOT RECREATE)
- Feature 1: description
- Feature 2: description
...

## ARCHITECTURE OVERVIEW
Brief description of how the system is organized.

## RECENT FOCUS AREAS
What has been worked on recently (from git log).

## GAPS AND OPPORTUNITIES
What's genuinely missing (not already implemented).

CRITICAL: Be thorough. Features you miss here may be accidentally proposed for recreation."""

    async def _gather_with_agent(self, agent: Any, name: str, harness: str) -> tuple[str, str, str]:
        """Run exploration with one agent."""
        agent_start = time.perf_counter()
        try:
            self._log(f"  {name} ({harness}): exploring codebase...", agent=name)
            prompt = self._build_explore_prompt()
            result = await agent.generate(prompt, context=[])
            self._log(f"  {name}: complete ({len(result) if result else 0} chars)", agent=name)
            # Emit agent's full exploration result
            if not result:
                return (name, harness, "Error: empty response")
            if result:
                self._stream_emit(
                    "on_log_message", result, level="info", phase="context", agent=name
                )
            return (name, harness, result)
        except Exception as e:
            self._log(f"  {name}: error - {e}", agent=name)
            return (name, harness, f"Error: {e}")
        finally:
            # Record per-agent metrics
            if _agent_metrics_recorder:
                agent_duration = time.perf_counter() - agent_start
                _agent_metrics_recorder("context", name, agent_duration)

    async def _run_codebase_audit(self) -> tuple[list[AuditFindingSummary], list[str]]:
        """Run codebase audit and return findings with proposals.

        Returns:
            Tuple of (findings list, proposals list)
        """
        if not self.codebase_auditor:
            return [], []

        try:
            # Run the audit
            result = await self.codebase_auditor.audit_codebase()

            # Convert findings to summary format
            findings: list[AuditFindingSummary] = []
            for finding in result.findings[:10]:  # Limit to top 10
                findings.append(
                    AuditFindingSummary(
                        title=finding.title,
                        category=finding.category,
                        severity=(
                            finding.severity.value
                            if hasattr(finding.severity, "value")
                            else str(finding.severity)
                        ),
                        description=finding.description[:200],  # Truncate
                        file_path=finding.file_path,  # type: ignore[attr-defined]
                    )
                )

            # Convert findings to proposals
            proposals = self.codebase_auditor.findings_to_proposals(result.findings)
            proposal_texts = [
                f"[{p.severity.value}] {p.title}: {p.description[:100]}..."
                for p in proposals[:5]  # Limit to top 5 proposals
            ]

            return findings, proposal_texts

        except Exception as e:
            logger.warning(f"Codebase audit error: {e}")
            return [], []

    def _format_audit_findings(self, findings: list[AuditFindingSummary]) -> str:
        """Format audit findings for inclusion in context."""
        if not findings:
            return ""

        lines = ["=== CODEBASE AUDIT FINDINGS (Automated Analysis) ==="]
        lines.append("The following issues were identified by automated codebase scanning:\n")

        # Group by severity
        by_severity: dict = {}
        for f in findings:
            severity = f.get("severity", "medium")
            if severity not in by_severity:
                by_severity[severity] = []
            by_severity[severity].append(f)

        # Output in severity order
        for severity in ["critical", "high", "medium", "low"]:
            if severity in by_severity:
                lines.append(f"\n### {severity.upper()} Severity:")
                for f in by_severity[severity]:
                    lines.append(f"- [{f.get('category', 'unknown')}] {f.get('title', 'Unknown')}")
                    lines.append(f"  {f.get('description', '')}")
                    if f.get("file_path"):
                        lines.append(f"  File: {f.get('file_path')}")

        lines.append("\n" + "=" * 50)
        return "\n".join(lines)


__all__ = ["ContextPhase", "set_metrics_recorder"]

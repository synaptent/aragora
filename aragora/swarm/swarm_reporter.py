"""SwarmReport and SwarmReporter: plain-English reports of swarm runs for non-developer users.

``aragora.swarm.reporter`` re-exports both classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aragora.harnesses.base import AnalysisType
from aragora.swarm.spec import SwarmSpec

# Same logger name as before the move, so log routing and filters keep matching.
logger = logging.getLogger("aragora.swarm.reporter")


@dataclass
class SwarmReport:
    """Plain-English report of swarm execution for non-developer users."""

    success: bool = False
    summary: str = ""
    what_was_done: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    what_to_do_next: list[str] = field(default_factory=list)

    # Details (for developer review)
    spec: SwarmSpec | None = None
    result: Any = None
    receipts: list[Any] = field(default_factory=list)
    duration_seconds: float = 0.0
    budget_spent_usd: float = 0.0

    def to_plain_text(self) -> str:
        """Render as plain text for terminal output."""
        lines = []
        lines.append("=" * 60)
        lines.append("SWARM REPORT")
        lines.append("=" * 60)
        lines.append("")

        status = "SUCCESS" if self.success else "COMPLETED WITH ISSUES"
        lines.append(f"Status: {status}")
        lines.append("")

        if self.summary:
            lines.append(self.summary)
            lines.append("")

        if self.what_was_done:
            lines.append("What was done:")
            for item in self.what_was_done:
                lines.append(f"  - {item}")
            lines.append("")

        if self.what_failed:
            lines.append("What had issues:")
            for item in self.what_failed:
                lines.append(f"  - {item}")
            lines.append("")

        if self.what_to_do_next:
            lines.append("Suggested next steps:")
            for item in self.what_to_do_next:
                lines.append(f"  - {item}")
            lines.append("")

        lines.append("-" * 60)
        if self.duration_seconds > 0:
            mins = int(self.duration_seconds // 60)
            secs = int(self.duration_seconds % 60)
            lines.append(f"Duration: {mins}m {secs}s")
        if self.budget_spent_usd > 0:
            lines.append(f"Budget spent: ${self.budget_spent_usd:.2f}")
        lines.append("=" * 60)

        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Render as Markdown for docs/reports."""
        lines = []
        lines.append("# Swarm Report")
        lines.append("")

        status = "Success" if self.success else "Completed with issues"
        lines.append(f"**Status:** {status}")
        lines.append("")

        if self.summary:
            lines.append(f"> {self.summary}")
            lines.append("")

        if self.what_was_done:
            lines.append("## What was done")
            for item in self.what_was_done:
                lines.append(f"- {item}")
            lines.append("")

        if self.what_failed:
            lines.append("## Issues")
            for item in self.what_failed:
                lines.append(f"- {item}")
            lines.append("")

        if self.what_to_do_next:
            lines.append("## Next steps")
            for item in self.what_to_do_next:
                lines.append(f"- {item}")
            lines.append("")

        lines.append("---")
        details = []
        if self.duration_seconds > 0:
            mins = int(self.duration_seconds // 60)
            secs = int(self.duration_seconds % 60)
            details.append(f"Duration: {mins}m {secs}s")
        if self.budget_spent_usd > 0:
            details.append(f"Budget: ${self.budget_spent_usd:.2f}")
        if details:
            lines.append(" | ".join(details))

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage/API."""
        return {
            "success": self.success,
            "summary": self.summary,
            "what_was_done": self.what_was_done,
            "what_failed": self.what_failed,
            "what_to_do_next": self.what_to_do_next,
            "duration_seconds": self.duration_seconds,
            "budget_spent_usd": self.budget_spent_usd,
            "spec": self.spec.to_dict() if self.spec else None,
        }


class SwarmReporter:
    """Generates plain-language reports from orchestration results.

    Two modes:
    1. LLM-assisted: Claude translates OrchestrationResult into plain English
    2. Template fallback: structured templates (no LLM needed)
    """

    async def generate(
        self,
        spec: SwarmSpec,
        result: Any,
        duration_seconds: float = 0.0,
    ) -> SwarmReport:
        """Generate a SwarmReport from orchestration results.

        Args:
            spec: The SwarmSpec that drove the execution.
            result: OrchestrationResult from the orchestrator.
            duration_seconds: How long execution took.

        Returns:
            A plain-English SwarmReport.
        """
        # Try LLM-assisted report generation
        report = await self._try_llm_report(spec, result, duration_seconds)
        if report is not None:
            return report

        # Fall back to template-based generation
        return self._template_report(spec, result, duration_seconds)

    async def _try_llm_report(
        self,
        spec: SwarmSpec,
        result: Any,
        duration_seconds: float,
    ) -> SwarmReport | None:
        """Try to generate report using Claude. Returns None on failure."""
        try:
            from aragora.harnesses.claude_code import ClaudeCodeHarness

            harness = ClaudeCodeHarness()
            if not await harness.initialize():
                return None

            result_summary = self._summarize_result(result, spec=spec)
            prompt = (
                "You are a CTO giving a status update to your CEO.\n"
                "Explain what your engineering team accomplished in plain, "
                "simple language. Never use jargon. Be specific about what "
                "was done -- say 'We updated the login page to show your "
                "company logo' not 'Task 3 completed successfully'.\n\n"
                f"Goal: {spec.refined_goal or spec.raw_goal}\n\n"
                f"Results:\n{result_summary}\n\n"
                "Produce a JSON object with:\n"
                '- "summary": 2-3 sentence plain English overview\n'
                '- "what_was_done": Array of bullet points (plain language)\n'
                '- "what_failed": Array of failures (plain language, empty if none)\n'
                '- "what_to_do_next": Array of actionable next steps\n\n'
                "Respond with ONLY the JSON object."
            )

            llm_result = await harness.analyze_repository(
                repo_path=Path("."),
                analysis_type=AnalysisType.GENERAL,
                prompt=prompt,
            )
            raw = llm_result.raw_output if hasattr(llm_result, "raw_output") else str(llm_result)

            import json

            data = json.loads(raw)
            return SwarmReport(
                success=self._is_success(result),
                summary=data.get("summary", ""),
                what_was_done=data.get("what_was_done", []),
                what_failed=data.get("what_failed", []),
                what_to_do_next=data.get("what_to_do_next", []),
                spec=spec,
                result=result,
                duration_seconds=duration_seconds,
                budget_spent_usd=self._extract_budget(result),
            )
        except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
            logger.debug("LLM report generation failed, using template")
            return None

    def _template_report(
        self,
        spec: SwarmSpec,
        result: Any,
        duration_seconds: float,
    ) -> SwarmReport:
        """Template-based report generation (no LLM needed)."""
        total = getattr(result, "total_subtasks", 0)
        completed = getattr(result, "completed_subtasks", 0)
        failed = getattr(result, "failed_subtasks", 0)
        skipped = getattr(result, "skipped_subtasks", 0)
        success = self._is_success(result)

        goal = spec.refined_goal or spec.raw_goal

        if success:
            summary = (
                "Great news -- everything you asked for is done. "
                f"Your team finished all {total} tasks without any issues."
            )
        elif completed > 0:
            summary = (
                f'Your team made good progress on "{goal}". '
                f"They finished {completed} out of {total} tasks, "
                f"but {failed} had issues."
            )
        else:
            summary = (
                f"Your team wasn't able to complete '{goal}'. All {total} tasks ran into issues."
            )

        what_was_done = []
        what_failed = []
        assignments = getattr(result, "assignments", [])
        for assignment in assignments:
            task_title = getattr(assignment, "subtask_title", "Task")
            status = getattr(assignment, "status", "unknown")
            if status == "completed":
                what_was_done.append(task_title)
            elif status in ("failed", "error"):
                error_msg = getattr(assignment, "error", "Unknown error")
                what_failed.append(f"{task_title}: {error_msg}")

        if not what_was_done and completed > 0:
            what_was_done.append(f"{completed} tasks completed successfully")
        if not what_failed and failed > 0:
            what_failed.append(f"{failed} tasks encountered issues")

        what_to_do_next = []
        if failed > 0:
            what_to_do_next.append(
                "Some tasks had issues -- you might want to run the swarm again "
                "or have someone look into what went wrong"
            )
        if skipped > 0:
            what_to_do_next.append(
                f"{skipped} tasks were skipped and may need someone to handle them manually"
            )
        if success:
            what_to_do_next.append(
                "You might want to have someone do a quick review of the changes "
                "to make sure everything looks right"
            )

        # Add confidence level from epistemic scores if available (Phase 5)
        if hasattr(spec, "epistemic_scores") and spec.epistemic_scores:
            avg_score = spec.epistemic_scores.get("average", 0)
            if avg_score >= 0.7:
                confidence = "High"
            elif avg_score >= 0.4:
                confidence = "Medium"
            else:
                confidence = "Low"
            summary += f" Confidence level: {confidence}."

        return SwarmReport(
            success=success,
            summary=summary,
            what_was_done=what_was_done,
            what_failed=what_failed,
            what_to_do_next=what_to_do_next,
            spec=spec,
            result=result,
            duration_seconds=duration_seconds,
            budget_spent_usd=self._extract_budget(result),
        )

    def _is_success(self, result: Any) -> bool:
        """Determine if the orchestration succeeded."""
        failed = getattr(result, "failed_subtasks", 0)
        total = getattr(result, "total_subtasks", 0)
        if total == 0:
            return False
        return failed == 0

    def _extract_budget(self, result: Any) -> float:
        """Extract total cost from result."""
        return getattr(result, "total_cost_usd", 0.0)

    def _summarize_result(self, result: Any, spec: SwarmSpec | None = None) -> str:
        """Produce a text summary of OrchestrationResult for LLM consumption."""
        lines = []
        total = getattr(result, "total_subtasks", 0)
        completed = getattr(result, "completed_subtasks", 0)
        failed = getattr(result, "failed_subtasks", 0)
        skipped = getattr(result, "skipped_subtasks", 0)
        lines.append(f"Total tasks: {total}")
        lines.append(f"Completed: {completed}")
        lines.append(f"Failed: {failed}")
        lines.append(f"Skipped: {skipped}")

        assignments = getattr(result, "assignments", [])
        for assignment in assignments[:15]:
            title = getattr(assignment, "subtask_title", "Unknown")
            status = getattr(assignment, "status", "unknown")
            error = getattr(assignment, "error", "")
            line = f"  [{status}] {title}"
            if error:
                line += f" - {error}"
            lines.append(line)

        if spec and spec.proactive_suggestions:
            lines.append("\nProactive suggestions made during planning:")
            for suggestion in spec.proactive_suggestions:
                lines.append(f"  - {suggestion}")

        return "\n".join(lines)

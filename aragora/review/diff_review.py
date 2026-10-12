"""Multi-agent diff review helpers.

Shared by ``aragora review`` (``aragora.cli.review``, which re-exports the
public names) and the OpenClaw PR review runner.
"""

from __future__ import annotations

import re
from typing import Any

from aragora.core import DebateResult
from aragora.debate.disagreement import DisagreementReporter

__all__ = ["extract_review_findings"]

_LOCATION_HINT_RE = re.compile(
    r"(?P<path>[\w./-]+\.(?:py|pyi|ts|tsx|js|jsx|yml|yaml|json|md|sh))(?:[:#]L?(?P<line>\d+))?"
)
_META_REVIEW_PREFIXES = (
    "weak point:",
    "good catch:",
    "overstates ",
    "treat ",
    "state that ",
    "reframe ",
)
_META_REVIEW_MARKERS = (
    "agent-like target",
    "calling this **critical**",
    "calling this critical",
    "explicit meta-review language",
    "from the diff alone",
    "incomplete visibility",
    "not as a definite defect",
    "no concrete file/location hint",
    "not clearly a bug from the diff",
    "not shown in the diff",
    "not visible in the diff",
    "observation is reasonable but incomplete",
    "possible the guidance moved elsewhere",
    "plausible but somewhat speculative",
    "reasonable but incomplete",
    "regression risk, but not as a definite defect",
    "regression risk to validate",
    "review blocker due to incomplete visibility",
    "review blockers due to incomplete visibility",
    "should be framed as a regression risk",
    "somewhat speculative",
    "cannot assess installation changes",
    "cannot fully review",
    "not a definite bug",
    "not a confirmed vulnerability",
    "not a confirmed security bug",
    "not a useful review comment",
    "reframe the strongest findings",
    "since the diff is truncated",
    "since the diff may be truncated",
)


def _extract_location_hint(text: str) -> str | None:
    """Return a best-effort file/line hint from an issue string."""
    match = _LOCATION_HINT_RE.search(text)
    if not match:
        return None
    path = match.group("path")
    line = match.group("line")
    if not path:
        return None
    return f"{path}:{line}" if line else path


def _looks_like_agent_target(target: Any) -> bool:
    """Detect when a critique target is another reviewer rather than code."""
    if not isinstance(target, str):
        return False
    normalized = target.strip().lower()
    if not normalized:
        return False
    if "/" in normalized or "." in normalized or ":" in normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "_reviewer",
            "_critic",
            "_synthesizer",
            "_judge",
            "_analyst",
            "_implementer",
            "_planner",
        )
    )


def _is_meta_review_issue(issue: str, suggestions: list[str], raw_target: Any) -> bool:
    """Filter critique-of-review chatter out of blocking issue buckets."""
    normalized_issue = issue.strip().lower()
    if normalized_issue.startswith(("location**:", "location:**", "location:")):
        return True
    if normalized_issue.startswith(_META_REVIEW_PREFIXES):
        return True
    if any(marker in normalized_issue for marker in _META_REVIEW_MARKERS):
        return True

    normalized_suggestions = "\n".join(suggestions).lower()
    if any(marker in normalized_suggestions for marker in _META_REVIEW_MARKERS):
        return True

    return _looks_like_agent_target(raw_target) and _extract_location_hint(issue) is None


def extract_review_findings(result: DebateResult) -> dict:
    """Extract structured findings from debate result."""
    reporter = DisagreementReporter()
    report = reporter.generate_report(
        votes=result.votes,
        critiques=result.critiques,
        winner=result.final_answer[:100] if result.final_answer else None,
    )

    # Categorize critiques by severity
    critical_issues = []
    high_issues = []
    medium_issues = []
    low_issues = []
    meta_issues = []

    for critique in result.critiques:
        severity = critique.severity if hasattr(critique, "severity") else 0.5
        for issue in critique.issues:
            suggestions = list(getattr(critique, "suggestions", []) or [])
            raw_target = getattr(critique, "target_agent", None)
            normalized_target = raw_target
            if _looks_like_agent_target(raw_target):
                normalized_target = _extract_location_hint(issue)
            issue_data = {
                "agent": critique.agent,
                "issue": issue,
                "target": normalized_target,
                "suggestions": suggestions,
            }
            if _is_meta_review_issue(issue, suggestions, raw_target):
                issue_data["grounded"] = False
                meta_issues.append(issue_data)
                continue
            issue_data["grounded"] = True
            if severity >= 0.9:
                critical_issues.append(issue_data)
            elif severity >= 0.7:
                high_issues.append(issue_data)
            elif severity >= 0.4:
                medium_issues.append(issue_data)
            else:
                low_issues.append(issue_data)

    return {
        "unanimous_critiques": report.unanimous_critiques,
        "split_opinions": report.split_opinions,
        "risk_areas": report.risk_areas,
        "agreement_score": report.agreement_score,
        "agent_alignment": report.agent_alignment,
        "critical_issues": critical_issues,
        "high_issues": high_issues,
        "medium_issues": medium_issues,
        "low_issues": low_issues,
        "meta_issues": meta_issues,
        "all_critiques": result.critiques,
        "final_summary": result.final_answer,
        "agents_used": list(set(m.agent for m in result.messages)) if result.messages else [],
    }

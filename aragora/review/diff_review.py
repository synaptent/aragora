"""Multi-agent diff review helpers.

Shared by ``aragora review`` (``aragora.cli.review``, which re-exports the
public names) and the OpenClaw PR review runner.
"""

from __future__ import annotations

import re
from typing import Any, cast

from aragora.agents.base import AgentType, create_agent
from aragora.config.secrets import get_secret_presence
from aragora.config.settings import AgentSettings, DebateSettings
from aragora.core import Agent, DebateResult, Environment
from aragora.debate.disagreement import DisagreementReporter
from aragora.debate.orchestrator import Arena, DebateProtocol

__all__ = [
    "DEFAULT_REVIEW_AGENTS",
    "DEFAULT_ROUNDS",
    "MAX_DIFF_SIZE",
    "build_review_prompt",
    "extract_review_findings",
    "get_available_agents",
    "run_review_debate",
]


def _has_api_key(*names: str) -> bool:
    """Return API-key availability without exposing secret values."""
    return any(get_secret_presence(name).source in {"aws", "env"} for name in names)


# Default agents for code review (fast, diverse perspectives)
DEFAULT_REVIEW_AGENTS = AgentSettings().default_agents
DEFAULT_ROUNDS = DebateSettings().default_rounds
MAX_DIFF_SIZE = 50000  # 50KB max diff size
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


def get_available_agents() -> str:
    """Get available agents based on configured API keys.

    Falls back gracefully if not all providers are configured.
    """
    agents = []

    # Check Anthropic
    if _has_api_key("ANTHROPIC_API_KEY"):
        agents.append("anthropic-api")

    # Check OpenAI
    if _has_api_key("OPENAI_API_KEY"):
        agents.append("openai-api")

    # Check OpenRouter as fallback
    if _has_api_key("OPENROUTER_API_KEY"):
        if len(agents) < 2:
            agents.append("openrouter")

    # Check other providers
    if _has_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY") and len(agents) < 2:
        agents.append("gemini")

    if _has_api_key("MISTRAL_API_KEY") and len(agents) < 2:
        agents.append("mistral-api")

    if not agents:
        return ""

    return ",".join(agents)


def _parse_review_agents(agents_str: str) -> list[str]:
    """Parse a comma-separated review agent list."""
    return [spec.strip() for spec in agents_str.split(",") if spec.strip()]


def build_review_prompt(diff: str, focus_areas: list[str] | None = None) -> str:
    """Build a focused code review prompt."""
    focus = focus_areas or ["security", "performance", "quality"]

    focus_instructions = []
    if "security" in focus:
        focus_instructions.append("""
**Security** - Look for:
- SQL/NoSQL injection, XSS, CSRF
- Authentication/authorization bypass
- Secrets/credentials in code
- Insecure deserialization
- Path traversal""")

    if "performance" in focus:
        focus_instructions.append("""
**Performance** - Look for:
- N+1 query patterns
- O(n^2) or worse algorithms
- Memory leaks, unbounded collections
- Missing pagination
- Blocking operations in async code""")

    if "quality" in focus:
        focus_instructions.append("""
**Code Quality** - Look for:
- Missing error handling
- Edge cases not covered
- Unclear or complex logic
- Missing input validation
- Resource cleanup issues""")

    focus_text = "\n".join(focus_instructions)

    # Truncate diff if too large
    if len(diff) > MAX_DIFF_SIZE:
        diff = diff[:MAX_DIFF_SIZE] + "\n\n[... diff truncated ...]"

    return f"""You are reviewing a pull request. Analyze the diff carefully and identify issues.

## Review Focus
{focus_text}

## Diff to Review
```diff
{diff}
```

## Response Format
For each issue found, specify:
1. **Category**: Security, Performance, or Quality
2. **Severity**: CRITICAL, HIGH, MEDIUM, or LOW
3. **Location**: File and line number if identifiable
4. **Issue**: Clear description of the problem
5. **Suggestion**: How to fix it

If no issues found in a category, say "No issues found."

Be thorough but avoid false positives. Focus on real, actionable issues."""


async def run_review_debate(
    diff: str,
    agents_str: str = DEFAULT_REVIEW_AGENTS,
    rounds: int = DEFAULT_ROUNDS,
    focus_areas: list[str] | None = None,
) -> DebateResult:
    """Run a code review debate on the given diff."""

    agent_specs = _parse_review_agents(agents_str)

    if agents_str.strip() == DEFAULT_REVIEW_AGENTS.strip() or len(agent_specs) < 2:
        available_specs = _parse_review_agents(get_available_agents())
        if available_specs:
            agent_specs = available_specs

    if not agent_specs:
        agent_specs = _parse_review_agents(DEFAULT_REVIEW_AGENTS)

    # Create agents with reviewer roles
    agents: list[Agent] = []
    roles = ["security_reviewer", "performance_reviewer", "quality_reviewer"]
    for i, agent_type in enumerate(agent_specs):
        role = roles[i % len(roles)]
        agent = create_agent(
            model_type=cast(AgentType, agent_type),
            name=f"{agent_type}_{role}",
            role=role,
        )
        agents.append(agent)

    # Build review prompt
    task = build_review_prompt(diff, focus_areas)

    # Create environment and protocol
    env = Environment(task=task, max_rounds=rounds)
    protocol = DebateProtocol(rounds=rounds, consensus="majority")

    # Run debate
    arena = Arena(env, agents, protocol)
    result = await arena.run()

    return result


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

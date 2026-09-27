#!/usr/bin/env python3
"""
Aragora PR Review - Multi Agent Code Review

Run multi-agent code review debates on diffs/PRs:
    git diff main | aragora review
    aragora review https://github.com/owner/repo/pull/123
    aragora review --diff-file pr.diff --output-dir ./artifacts
    aragora review --demo  # Try without API keys
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from aragora.agents.base import AgentType, create_agent
from aragora.config.secrets import get_secret_presence, is_secret_presence_available
from aragora.core import Agent, DebateResult, Environment
from aragora.debate.disagreement import DisagreementReporter
from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.config.settings import DebateSettings, AgentSettings

logger = logging.getLogger(__name__)


def _has_api_key(*names: str) -> bool:
    """Return API-key availability without exposing secret values."""
    return any(is_secret_presence_available(get_secret_presence(name)) for name in names)


# Default agents for code review (fast, diverse perspectives)
DEFAULT_REVIEW_AGENTS = AgentSettings().default_agents
DEFAULT_ROUNDS = DebateSettings().default_rounds
MAX_DIFF_SIZE = 50000  # 50KB max diff size
REVIEWS_DIR = Path.home() / ".aragora" / "reviews"
SHARE_BASE_URL = "https://aragora.ai/reviews"
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


def generate_review_id(findings: dict, diff_hash: str) -> str:
    """Generate a short, unique review ID."""
    # Use first 8 chars of UUID combined with diff hash for uniqueness
    uid = uuid.uuid4().hex[:8]
    return f"{uid}"


def save_review_for_sharing(
    review_id: str,
    findings: dict,
    diff: str,
    agents: str,
    pr_url: str | None = None,
) -> Path:
    """Save review to local storage for sharing.

    Reviews are stored at ~/.aragora/reviews/{id}.json
    The server can serve these for shareable links.
    """
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    # Create review record
    review_data = {
        "id": review_id,
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "agents": agents.split(","),
        "pr_url": pr_url,
        "diff_preview": diff[:500] + "..." if len(diff) > 500 else diff,
        "diff_hash": hashlib.sha256(diff.encode()).hexdigest()[:16],
        "findings": {
            "unanimous_critiques": findings.get("unanimous_critiques", []),
            "split_opinions": [
                {"issue": d, "majority": m, "minority": mi}
                for d, m, mi in findings.get("split_opinions", [])
            ],
            "risk_areas": findings.get("risk_areas", []),
            "agreement_score": findings.get("agreement_score", 0),
            "critical_issues": findings.get("critical_issues", []),
            "high_issues": findings.get("high_issues", []),
            "medium_issues": findings.get("medium_issues", []),
            "low_issues": findings.get("low_issues", []),
            "meta_issues": findings.get("meta_issues", []),
            "summary": findings.get("final_summary", ""),
        },
    }

    # Save to file
    review_path = REVIEWS_DIR / f"{review_id}.json"
    review_path.write_text(json.dumps(review_data, indent=2))

    return review_path


def get_shareable_url(review_id: str) -> str:
    """Get the shareable URL for a review."""
    return f"{SHARE_BASE_URL}/{review_id}"


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


def get_demo_findings() -> dict:
    """Get demo review findings for trying without API keys."""
    return {
        "unanimous_critiques": [
            "SQL injection vulnerability in user search - query built with string concatenation",
            "Missing input validation on file upload endpoint",
        ],
        "split_opinions": [
            ("Add request rate limiting", ["anthropic-api", "openai-api"], ["gemini-api"]),
            ("Cache database queries", ["anthropic-api"], ["openai-api", "gemini-api"]),
        ],
        "risk_areas": [
            "Error handling in payment flow may expose sensitive data",
            "Session management needs manual review",
        ],
        "agreement_score": 0.75,
        "agent_alignment": {
            "anthropic-api": {"openai-api": 0.8, "gemini-api": 0.6},
            "openai-api": {"anthropic-api": 0.8, "gemini-api": 0.7},
        },
        "critical_issues": [
            {
                "agent": "anthropic-api",
                "issue": "SQL injection in search_users()",
                "target": "api/users.py:45",
                "grounded": True,
            },
        ],
        "high_issues": [
            {
                "agent": "openai-api",
                "issue": "Missing CSRF protection on POST endpoints",
                "target": "api/routes.py",
                "grounded": True,
            },
        ],
        "medium_issues": [
            {
                "agent": "gemini-api",
                "issue": "Unbounded query results - add pagination",
                "target": "api/products.py:102",
                "grounded": True,
            },
        ],
        "low_issues": [],
        "meta_issues": [],
        "all_critiques": [],
        "final_summary": """## Multi Agent Review Summary

This code review identified **2 critical security issues** that all AI models agree on.

**Unanimous Findings (High Confidence):**
1. SQL injection in `search_users()` - user input directly concatenated into query
2. Missing input validation on file upload - allows arbitrary file types

**Split Opinions:**
- Rate limiting: 2/3 models recommend adding, 1 suggests it's premature
- Query caching: Models disagree on whether caching adds complexity without benefit

**Recommendation:** Address the SQL injection immediately before merging.""",
        "agents_used": ["anthropic-api", "openai-api", "gemini-api"],
    }


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


def format_github_comment(result: DebateResult | None, findings: dict[str, Any]) -> str:
    """Format findings as a GitHub PR comment."""
    agents_used = findings.get("agents_used", [])
    agent_names = (
        ", ".join(set(a.split("_")[0] for a in agents_used)) if agents_used else "AI agents"
    )

    lines = [
        "## Multi Agent Code Review",
        "",
        f"**{len(agents_used)} agents reviewed this PR** ({agent_names})",
        "",
    ]

    # Unanimous issues (high confidence)
    unanimous = findings.get("unanimous_critiques", [])
    if unanimous:
        lines.extend(
            [
                "<details open>",
                "<summary><strong>Unanimous Issues</strong> - All AI models agree</summary>",
                "",
            ]
        )
        for issue in unanimous[:5]:  # Limit to top 5
            lines.append(f"- {issue}")
        lines.extend(["", "</details>", ""])

    # Critical/High issues
    critical = findings.get("critical_issues", [])
    high = findings.get("high_issues", [])
    if critical or high:
        count = len(critical) + len(high)
        lines.extend(
            [
                "<details open>",
                f"<summary><strong>Critical & High Severity Issues</strong> ({count} found)</summary>",
                "",
            ]
        )
        for issue in (critical + high)[:5]:
            severity = "CRITICAL" if issue in critical else "HIGH"
            lines.append(f"- **{severity}**: {issue['issue'][:200]}")
        lines.extend(["", "</details>", ""])

    # Split opinions
    split = findings.get("split_opinions", [])
    if split:
        lines.extend(
            [
                "<details>",
                "<summary><strong>Split Opinions</strong> - Agents disagree on these</summary>",
                "",
                "| Topic | For | Against |",
                "|-------|-----|---------|",
            ]
        )
        for desc, majority, minority in split[:3]:
            topic = desc[:50] + "..." if len(desc) > 50 else desc
            lines.append(f"| {topic} | {', '.join(majority)} | {', '.join(minority)} |")
        lines.extend(["", "</details>", ""])

    # Risk areas
    risks = findings.get("risk_areas", [])
    if risks:
        lines.extend(
            [
                "<details>",
                "<summary><strong>Risk Areas</strong> - Manual review recommended</summary>",
                "",
            ]
        )
        for risk in risks[:3]:
            lines.append(f"- {risk}")
        lines.extend(["", "</details>", ""])

    # Summary if available
    summary = findings.get("final_summary", "")
    if summary and len(summary) > 50:
        lines.extend(
            [
                "<details>",
                "<summary><strong>Summary</strong></summary>",
                "",
                summary[:500] + ("..." if len(summary) > 500 else ""),
                "",
                "</details>",
                "",
            ]
        )

    # Footer
    agreement = findings.get("agreement_score", 0)
    lines.extend(
        [
            "---",
            f"*Agreement score: {agreement:.0%} | Powered by [Aragora](https://github.com/synaptent/aragora) - Multi Agent Decision Making*",
        ]
    )

    return "\n".join(lines)


def findings_to_sarif(findings: dict, tool_name: str = "Aragora Review") -> dict:
    """Convert review findings to SARIF 2.1.0 format.

    Transforms the structured review findings into a SARIF document suitable
    for upload to GitHub Security tab, Azure DevOps, or other SARIF consumers.

    Args:
        findings: Review findings dict from extract_review_findings or get_demo_findings
        tool_name: Name of the tool for the SARIF driver entry

    Returns:
        SARIF 2.1.0 dictionary
    """
    sarif_level_map = {
        "CRITICAL": "error",
        "HIGH": "error",
        "MEDIUM": "warning",
        "LOW": "note",
    }

    sarif_severity_map = {
        "CRITICAL": "9.0",
        "HIGH": "7.0",
        "MEDIUM": "4.0",
        "LOW": "1.0",
    }

    rules: list[dict[str, Any]] = []
    rule_ids: dict[str, int] = {}
    results: list[dict[str, Any]] = []

    # Collect all issues across severity levels
    severity_buckets = [
        ("CRITICAL", findings.get("critical_issues", [])),
        ("HIGH", findings.get("high_issues", [])),
        ("MEDIUM", findings.get("medium_issues", [])),
        ("LOW", findings.get("low_issues", [])),
    ]

    for severity, issues in severity_buckets:
        for issue in issues:
            # Determine category from issue data
            agent = issue.get("agent", "unknown")
            issue_text = issue.get("issue", "")
            target = issue.get("target", "")

            # Create or reuse rule
            category = f"review/{severity.lower()}"
            if category not in rule_ids:
                rule_id = f"ARAGORA-REVIEW-{len(rule_ids) + 1:03d}"
                rule_ids[category] = len(rules)
                rules.append(
                    {
                        "id": rule_id,
                        "name": f"CodeReview{severity.title()}",
                        "shortDescription": {
                            "text": f"Aragora Review: {severity} severity finding"
                        },
                        "helpUri": "https://aragora.ai/docs/review",
                        "properties": {
                            "security-severity": sarif_severity_map.get(severity, "4.0"),
                            "tags": ["code-review", "aragora", severity.lower()],
                        },
                    }
                )

            rule_idx = rule_ids[category]
            rule_id = rules[rule_idx]["id"]

            # Build location from target if available
            location: dict[str, Any] = {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": target if target else "review-input",
                        "uriBaseId": "SRCROOT",
                    }
                }
            }

            result_entry: dict[str, Any] = {
                "ruleId": rule_id,
                "ruleIndex": rule_idx,
                "level": sarif_level_map.get(severity, "warning"),
                "message": {"text": issue_text},
                "locations": [location],
                "fingerprints": {
                    "aragora/v1": hashlib.sha256(
                        f"{severity}:{issue_text}:{target}".encode()
                    ).hexdigest()[:32]
                },
                "properties": {
                    "agent": agent,
                    "severity": severity,
                },
            }

            # Add suggestions if present
            suggestions = issue.get("suggestions", [])
            if suggestions:
                result_entry["fixes"] = [{"description": {"text": s}} for s in suggestions[:3]]

            results.append(result_entry)

    # Add unanimous critiques as results too
    for critique_text in findings.get("unanimous_critiques", []):
        category = "review/unanimous"
        if category not in rule_ids:
            rule_id = f"ARAGORA-REVIEW-{len(rule_ids) + 1:03d}"
            rule_ids[category] = len(rules)
            rules.append(
                {
                    "id": rule_id,
                    "name": "UnanimousFinding",
                    "shortDescription": {"text": "Aragora Review: Unanimous agent agreement"},
                    "helpUri": "https://aragora.ai/docs/review",
                    "properties": {
                        "security-severity": "7.0",
                        "tags": ["code-review", "aragora", "unanimous"],
                    },
                }
            )

        rule_idx = rule_ids[category]
        rule_id = rules[rule_idx]["id"]

        results.append(
            {
                "ruleId": rule_id,
                "ruleIndex": rule_idx,
                "level": "error",
                "message": {"text": critique_text},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": "review-input",
                                "uriBaseId": "SRCROOT",
                            }
                        }
                    }
                ],
                "fingerprints": {
                    "aragora/v1": hashlib.sha256(f"unanimous:{critique_text}".encode()).hexdigest()[
                        :32
                    ]
                },
                "properties": {
                    "unanimous": True,
                },
            }
        )

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": "1.0.0",
                        "informationUri": "https://aragora.ai/review",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }

    return sarif


async def run_gauntlet_on_diff(
    diff: str,
    findings: dict,
    agents_str: str = "anthropic-api,openai-api",
) -> dict:
    """Run gauntlet adversarial stress-test on the review content.

    Uses the CODE_REVIEW gauntlet template for adversarial validation
    of the code diff, then returns combined findings.

    Args:
        diff: The code diff content
        findings: Existing review findings to merge with
        agents_str: Comma-separated agent names

    Returns:
        Updated findings dict with gauntlet results merged in
    """
    from aragora.gauntlet.templates import GauntletTemplate, get_template
    from aragora.gauntlet.runner import GauntletRunner

    # Get the code review template config
    config = get_template(GauntletTemplate.CODE_REVIEW)

    # Override agents with what the user has configured
    config.agents = [a.strip() for a in agents_str.split(",") if a.strip()]

    # Run the gauntlet
    runner = GauntletRunner(config=config)
    gauntlet_result = await runner.run(
        input_content=diff,
        context="Code review diff - adversarial stress test",
    )

    # Merge gauntlet vulnerabilities into findings
    vuln_list: list[Any] = []
    gauntlet_findings: dict[str, Any] = {
        "gauntlet_id": gauntlet_result.gauntlet_id,
        "gauntlet_verdict": gauntlet_result.verdict.value
        if hasattr(gauntlet_result.verdict, "value")
        else str(gauntlet_result.verdict),
        "gauntlet_robustness": gauntlet_result.attack_summary.robustness_score
        if gauntlet_result.attack_summary
        else 0.0,
        "gauntlet_vulnerabilities": vuln_list,
    }

    for vuln in gauntlet_result.vulnerabilities:
        severity = (
            vuln.severity.value.upper()
            if hasattr(vuln.severity, "value")
            else str(vuln.severity).upper()
        )
        vuln_data = {
            "agent": vuln.agent_name or vuln.source,
            "issue": vuln.description,
            "target": vuln.category,
            "suggestions": [vuln.mitigation] if vuln.mitigation else [],
        }

        gauntlet_findings["gauntlet_vulnerabilities"].append(vuln.to_dict())

        # Merge into appropriate severity bucket
        if severity == "CRITICAL":
            findings.setdefault("critical_issues", []).append(vuln_data)
        elif severity == "HIGH":
            findings.setdefault("high_issues", []).append(vuln_data)
        elif severity == "MEDIUM":
            findings.setdefault("medium_issues", []).append(vuln_data)
        else:
            findings.setdefault("low_issues", []).append(vuln_data)

    findings["gauntlet"] = gauntlet_findings
    return findings


def _persist_review_to_km(
    result: DebateResult,
    findings: dict[str, Any],
    *,
    pr_url: str | None = None,
) -> bool:
    """Persist review findings to Knowledge Mound as a decision receipt.

    Creates a DecisionReceipt from the review findings and ingests it
    into the Knowledge Mound via the ReceiptAdapter, following the same
    pattern as PostDebateCoordinator._step_persist_receipt().

    Args:
        result: The DebateResult from the review debate.
        findings: Structured findings dict from extract_review_findings().
        pr_url: Optional GitHub PR URL for provenance metadata.

    Returns:
        True if persistence succeeded, False otherwise.
    """
    try:
        from aragora.gauntlet.receipt_models import DecisionReceipt
        from aragora.knowledge.mound.adapters.receipt_adapter import get_receipt_adapter

        # from_review_result takes the findings dict (not DebateResult)
        # plus optional pr_url and reviewer_agents keyword args
        agents_used = list(findings.get("agents_used", []))
        receipt = DecisionReceipt.from_review_result(
            findings,
            pr_url=pr_url,
            reviewer_agents=agents_used or None,
        )

        adapter = get_receipt_adapter()
        adapter.ingest(receipt.to_dict())
        logger.info("Review findings persisted to Knowledge Mound")
        return True
    except ImportError:
        logger.debug("KM persistence unavailable: missing dependencies")
        return False
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.debug("KM persistence failed: %s", e)
        return False


def _write_review_odr(
    findings: dict[str, Any],
    *,
    pr_url: str | None,
    output_dir: Path | None,
    output_path: str,
    demo: bool = False,
) -> Path:
    """Export review findings as an Open Decision Receipt."""
    from aragora.gauntlet.odr_export import decision_receipt_to_odr, sign_odr_if_configured
    from aragora.gauntlet.receipt_models import DecisionReceipt

    if demo:
        # Mark demo receipts before hashing so the marker is tamper-evident and
        # the artifact can never pass for a real review's receipt.
        findings = {
            **findings,
            "final_summary": "[DEMO MODE] Fabricated sample findings, not a real review. "
            + str(findings.get("final_summary", "")),
        }

    agents_used = list(findings.get("agents_used", []))
    receipt = DecisionReceipt.from_review_result(
        findings,
        pr_url=pr_url,
        reviewer_agents=agents_used or None,
    )
    odr = decision_receipt_to_odr(receipt)
    if not demo:
        # Never sign fabricated demo findings; demo receipts stay explicitly unsigned.
        odr = sign_odr_if_configured(odr)

    path = Path(output_path) if output_path else (output_dir or Path.cwd()) / "review.odr.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(odr, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _emit_requested_odr(
    args: argparse.Namespace,
    findings: dict[str, Any],
    output_dir: Path | None,
) -> bool:
    """Write the requested ODR artifact and report failures to the CLI caller."""
    output_path = getattr(args, "emit_odr", None)
    if output_path is None:
        return True

    from aragora.gauntlet.odr_signing import OdrSigningError

    try:
        path = _write_review_odr(
            findings,
            pr_url=getattr(args, "pr_url", None),
            output_dir=output_dir,
            output_path=output_path,
            demo=getattr(args, "demo", False),
        )
    except (
        AttributeError,
        ImportError,
        KeyError,
        OdrSigningError,
        OSError,
        TypeError,
        ValueError,
    ) as e:
        logger.warning("ODR export failed: %s", e)
        print(f"Error: Could not emit review ODR: {e}", file=sys.stderr)
        return False

    print(f"ODR receipt written to: {path}", file=sys.stderr)
    return True


def cmd_review(args: argparse.Namespace) -> int:
    """Handle 'review' command."""

    # Fail fast if --emit-odr swallowed the PR URL positional (nargs="?" footgun):
    # otherwise the receipt would be written under a literal "https:/..." directory.
    emit_odr_path = getattr(args, "emit_odr", None)
    if emit_odr_path and (
        emit_odr_path.lower().startswith(("http://", "https://", "git@"))
        or emit_odr_path.lower().lstrip("/").startswith(("github.com/", "www.github.com/"))
    ):
        print(
            f"Error: --emit-odr received a URL ({emit_odr_path}) instead of a file path. "
            "Place --emit-odr after the PR URL, or pass an explicit PATH.",
            file=sys.stderr,
        )
        return 1

    # Demo mode - show sample output without API keys
    if getattr(args, "demo", False):
        print("Running in demo mode (no API calls)...", file=sys.stderr)
        findings = get_demo_findings()

        output_dir = Path(args.output_dir) if args.output_dir else None

        if args.output_format == "github":
            comment = format_github_comment(None, findings)
            comment = "**[DEMO MODE]** " + comment
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "comment.md").write_text(comment)
            print(comment)
        elif args.output_format == "json":
            output = {
                "demo_mode": True,
                "unanimous_critiques": findings["unanimous_critiques"],
                "split_opinions": [(d, m, mi) for d, m, mi in findings["split_opinions"]],
                "risk_areas": findings["risk_areas"],
                "agreement_score": findings["agreement_score"],
                "critical_issues": findings["critical_issues"],
                "high_issues": findings["high_issues"],
                "summary": findings["final_summary"],
            }
            json_output = json.dumps(output, indent=2)
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "review.json").write_text(json_output)
            print(json_output)
        else:
            print("Demo mode only supports github and json output formats", file=sys.stderr)
            return 1

        # Generate SARIF output in demo mode if requested
        sarif_output = getattr(args, "sarif", None)
        if sarif_output is not None:
            sarif_path = Path(sarif_output) if sarif_output else Path("review-results.sarif")
            try:
                sarif_data = findings_to_sarif(findings)
                sarif_json = json.dumps(sarif_data, indent=2)
                sarif_path.parent.mkdir(parents=True, exist_ok=True)
                sarif_path.write_text(sarif_json)
                print(f"SARIF output written to: {sarif_path}", file=sys.stderr)
            except (OSError, ValueError, KeyError) as e:
                print(f"Warning: SARIF export failed: {e}", file=sys.stderr)

        odr_ok = _emit_requested_odr(args, findings, output_dir)

        print("\n---", file=sys.stderr)
        print("This was a demo. To run a real review, configure API keys:", file=sys.stderr)
        print("  export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
        print("  export OPENAI_API_KEY=sk-...", file=sys.stderr)
        return 0 if odr_ok else 3

    # Get diff content
    diff = ""

    if args.diff_file:
        # Read from file
        diff_path = Path(args.diff_file)
        if not diff_path.exists():
            print(f"Error: Diff file not found: {args.diff_file}", file=sys.stderr)
            return 1
        diff = diff_path.read_text()
    elif args.pr_url:
        # Fetch from GitHub PR
        print(f"Fetching PR diff from: {args.pr_url}", file=sys.stderr)
        try:
            # Extract owner/repo/number from URL
            # Supports: https://github.com/owner/repo/pull/123
            parts = args.pr_url.rstrip("/").split("/")
            if len(parts) >= 5 and parts[-2] == "pull":
                pr_number = parts[-1]
                # Extract owner/repo for cross-repo support
                try:
                    # Find github.com index and extract owner/repo
                    gh_idx = next(i for i, p in enumerate(parts) if "github.com" in p)
                    owner = parts[gh_idx + 1]
                    repo = parts[gh_idx + 2]
                    repo_arg: str | None = f"{owner}/{repo}"
                except (StopIteration, IndexError):
                    repo_arg = None

                # Build gh command with repo context if available
                gh_cmd = ["gh", "pr", "diff", pr_number]
                if repo_arg:
                    gh_cmd.extend(["--repo", repo_arg])

                gh_result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                    gh_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    shell=False,
                )
                if gh_result.returncode == 0:
                    diff = gh_result.stdout
                else:
                    print(f"Error fetching PR: {gh_result.stderr}", file=sys.stderr)
                    return 1
            else:
                print(f"Invalid PR URL format: {args.pr_url}", file=sys.stderr)
                print("Expected: https://github.com/owner/repo/pull/123", file=sys.stderr)
                return 1
        except subprocess.TimeoutExpired:
            print("Timeout fetching PR diff", file=sys.stderr)
            return 1
        except FileNotFoundError:
            print("Error: 'gh' CLI not found. Install GitHub CLI.", file=sys.stderr)
            return 1
    elif not sys.stdin.isatty():
        # Read from stdin
        diff = sys.stdin.read()
    else:
        print(
            "Error: No diff provided. Use --diff-file, PR URL, or pipe diff to stdin.",
            file=sys.stderr,
        )
        return 1

    if not diff.strip():
        print("Error: Empty diff — no changes to review.", file=sys.stderr)
        print("  Make some code changes first, then run:", file=sys.stderr)
        print("    aragora review                    # Review unstaged changes", file=sys.stderr)
        print("    aragora review --diff-file d.patch # Review a diff file", file=sys.stderr)
        print("    aragora review <PR-URL>           # Review a GitHub PR", file=sys.stderr)
        return 1

    # Determine which agents to use
    agents_str = args.agents
    if agents_str == DEFAULT_REVIEW_AGENTS:
        # Check if default agents are available, fall back if not
        available = get_available_agents()
        if not available:
            print("Error: No API keys configured.", file=sys.stderr)
            print(
                "Set at least one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY",
                file=sys.stderr,
            )
            print("\nTry demo mode instead: aragora review --demo", file=sys.stderr)
            return 1
        if available != DEFAULT_REVIEW_AGENTS:
            print(f"Note: Using available agents: {available}", file=sys.stderr)
            agents_str = available

    # Run review debate
    print(f"Running AI code review ({agents_str}, {args.rounds} rounds)...", file=sys.stderr)

    try:
        result = asyncio.run(
            run_review_debate(
                diff=diff,
                agents_str=agents_str,
                rounds=args.rounds,
                focus_areas=args.focus.split(",") if args.focus else None,
            )
        )
    except (OSError, ConnectionError, RuntimeError, ValueError) as e:
        print(f"Error running review: {e}", file=sys.stderr)
        return 1

    # Extract findings
    findings = extract_review_findings(result)

    # Persist review findings to Knowledge Mound
    _persist_review_to_km(result, findings, pr_url=getattr(args, "pr_url", None))

    # Generate shareable link if requested
    share_url = None
    if getattr(args, "share", False):
        diff_hash = hashlib.sha256(diff.encode()).hexdigest()[:16]
        review_id = generate_review_id(findings, diff_hash)
        save_review_for_sharing(
            review_id=review_id,
            findings=findings,
            diff=diff,
            agents=agents_str,
            pr_url=getattr(args, "pr_url", None),
        )
        share_url = get_shareable_url(review_id)
        print(f"\nShareable link: {share_url}", file=sys.stderr)
        print(f"Review ID: {review_id}", file=sys.stderr)

    # Output based on format
    output_dir = Path(args.output_dir) if args.output_dir else None

    if args.output_format == "github":
        comment = format_github_comment(result, findings)
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "comment.md").write_text(comment)
            print(f"Comment saved to: {output_dir / 'comment.md'}", file=sys.stderr)
        print(comment)

    elif args.output_format == "json":
        # Convert to JSON-serializable format
        output = {
            "unanimous_critiques": findings["unanimous_critiques"],
            "split_opinions": [(d, m, mi) for d, m, mi in findings["split_opinions"]],
            "risk_areas": findings["risk_areas"],
            "agreement_score": findings["agreement_score"],
            "critical_issues": findings["critical_issues"],
            "high_issues": findings["high_issues"],
            "medium_issues": findings["medium_issues"],
            "low_issues": findings["low_issues"],
            "meta_issues": findings.get("meta_issues", []),
            "summary": findings["final_summary"],
        }
        json_output = json.dumps(output, indent=2)
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "review.json").write_text(json_output)
        print(json_output)

    elif args.output_format == "html":
        # Use existing static HTML exporter
        try:
            from aragora.export.artifact import ArtifactBuilder
            from aragora.export.static_html import StaticHTMLExporter

            artifact = ArtifactBuilder().from_result(result).build()
            exporter = StaticHTMLExporter(artifact)
            html = exporter.generate()
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "review.html").write_text(html)
                print(f"HTML report saved to: {output_dir / 'review.html'}", file=sys.stderr)
            else:
                print(html)
        except ImportError:
            print("Error: HTML export not available", file=sys.stderr)
            return 1

    # Run gauntlet adversarial stress-test if requested
    if getattr(args, "gauntlet", False):
        print("Running gauntlet adversarial stress-test...", file=sys.stderr)
        try:
            findings = asyncio.run(
                run_gauntlet_on_diff(
                    diff=diff,
                    findings=findings,
                    agents_str=agents_str,
                )
            )
            gauntlet_info = findings.get("gauntlet", {})
            gauntlet_verdict = gauntlet_info.get("gauntlet_verdict", "unknown")
            gauntlet_vulns = len(gauntlet_info.get("gauntlet_vulnerabilities", []))
            print(
                f"Gauntlet complete: verdict={gauntlet_verdict}, vulnerabilities={gauntlet_vulns}",
                file=sys.stderr,
            )
            # Re-persist with gauntlet enrichment so findings include vulnerabilities
            _persist_review_to_km(result, findings, pr_url=getattr(args, "pr_url", None))
        except (OSError, ConnectionError, RuntimeError, ValueError) as e:
            print(f"Warning: Gauntlet stress-test failed: {e}", file=sys.stderr)
            logger.debug("Gauntlet error details", exc_info=True)

    # Generate SARIF output if requested
    sarif_output = getattr(args, "sarif", None)
    if sarif_output is not None:
        sarif_path = Path(sarif_output) if sarif_output else Path("review-results.sarif")
        try:
            sarif_data = findings_to_sarif(findings)
            sarif_json = json.dumps(sarif_data, indent=2)
            sarif_path.parent.mkdir(parents=True, exist_ok=True)
            sarif_path.write_text(sarif_json)
            print(f"SARIF output written to: {sarif_path}", file=sys.stderr)
        except (OSError, ValueError, KeyError) as e:
            print(f"Warning: SARIF export failed: {e}", file=sys.stderr)
            logger.debug("SARIF export error details", exc_info=True)

    # Post review as PR comment if requested
    if getattr(args, "post_comment", False):
        pr_url = getattr(args, "pr_url", None)
        if not pr_url:
            print("Error: --post-comment requires a PR URL as the first argument", file=sys.stderr)
            return 1
        try:
            # Extract PR number from URL
            parts = pr_url.rstrip("/").split("/")
            if len(parts) >= 2 and parts[-2] == "pull":
                pr_number = parts[-1]
            else:
                print(f"Error: Cannot extract PR number from: {pr_url}", file=sys.stderr)
                return 1

            # Extract repo for cross-repo support
            gh_cmd = ["gh", "pr", "comment", pr_number]
            try:
                gh_idx = next(i for i, p in enumerate(parts) if "github.com" in p)
                owner = parts[gh_idx + 1]
                repo = parts[gh_idx + 2]
                gh_cmd.extend(["--repo", f"{owner}/{repo}"])
            except (StopIteration, IndexError):
                pass  # Use default repo context

            comment_body = format_github_comment(result, findings)
            gh_cmd.extend(["--body", comment_body])

            gh_result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                gh_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            if gh_result.returncode == 0:
                print(f"Review comment posted to PR #{pr_number}", file=sys.stderr)
            else:
                print(f"Warning: Failed to post comment: {gh_result.stderr}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print("Warning: Timeout posting PR comment", file=sys.stderr)
        except FileNotFoundError:
            print(
                "Warning: 'gh' CLI not found. Install GitHub CLI to use --post-comment.",
                file=sys.stderr,
            )

    # Emit the receipt after the other artifact steps so an emit failure cannot
    # suppress SARIF/comment output.
    odr_ok = _emit_requested_odr(args, findings, output_dir)

    # CI mode exit codes — findings verdicts take priority over artifact-IO errors
    if getattr(args, "ci", False):
        critical = len(findings.get("critical_issues", []))
        high = len(findings.get("high_issues", []))
        if critical > 0:
            print(f"CI: {critical} critical issues found", file=sys.stderr)
            return 1
        if high > 0:
            print(f"CI: {high} high severity issues found", file=sys.stderr)
            return 2

    # Exit 3 keeps emit failure distinct from the --ci findings verdicts (1=critical, 2=high).
    return 0 if odr_ok else 3


def create_review_parser(subparsers) -> None:
    """Add review subcommand to argument parser."""
    parser = subparsers.add_parser(
        "review",
        help="Run AI code review on a diff or PR",
        description="Multi-agent AI code review for pull requests",
    )

    parser.add_argument(
        "pr_url",
        nargs="?",
        help="GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)",
    )

    parser.add_argument(
        "--diff-file",
        help="Path to diff file (alternative to PR URL or stdin)",
    )

    parser.add_argument(
        "--agents",
        default=DEFAULT_REVIEW_AGENTS,
        help=f"Comma-separated list of agents (default: {DEFAULT_REVIEW_AGENTS})",
    )

    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help=f"Number of debate rounds (default: {DEFAULT_ROUNDS})",
    )

    parser.add_argument(
        "--focus",
        default="security,performance,quality",
        help="Focus areas: security,performance,quality (default: all)",
    )

    parser.add_argument(
        "--output-format",
        choices=["github", "json", "html"],
        default="github",
        help="Output format (default: github)",
    )

    parser.add_argument(
        "--output-dir",
        help="Directory to save output artifacts",
    )

    parser.add_argument(
        "--emit-odr",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="Emit a verifiable Open Decision Receipt (default: review.odr.json, "
        "or inside --output-dir when set); place after the PR URL or pass an explicit "
        "PATH; a failed receipt write exits 3",
    )

    parser.add_argument(
        "--sarif",
        nargs="?",
        const="review-results.sarif",
        default=None,
        metavar="PATH",
        help="Export findings as SARIF 2.1.0 (default: review-results.sarif). "
        "Integrates with GitHub Security tab when used in CI.",
    )

    parser.add_argument(
        "--gauntlet",
        action="store_true",
        default=False,
        help="Run adversarial gauntlet stress-test after review debate. "
        "Uses the CODE_REVIEW gauntlet template for deeper vulnerability analysis.",
    )

    parser.add_argument(
        "--ci",
        action="store_true",
        default=False,
        help="CI mode: exit with non-zero code based on findings severity. "
        "Exit 1 if critical issues, exit 2 if high issues found "
        "(exit 3 = --emit-odr write failure, not a findings verdict).",
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode (no API keys required, shows sample output)",
    )

    parser.add_argument(
        "--share",
        action="store_true",
        help="Generate a shareable link for this review",
    )

    parser.add_argument(
        "--post-comment",
        action="store_true",
        default=False,
        help="Post review findings as a comment on the GitHub PR. "
        "Requires a PR URL as the first argument and the 'gh' CLI installed.",
    )

    parser.set_defaults(func=cmd_review)


# For direct module execution
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aragora PR Review")
    subparsers = parser.add_subparsers(dest="command")
    create_review_parser(subparsers)
    args = parser.parse_args()

    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()
        sys.exit(1)

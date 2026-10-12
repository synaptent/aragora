"""Tests for the multi-agent diff review home in ``aragora.review.diff_review``.

The helpers moved from ``aragora.cli.review``, which re-exports the public
names. Every public function is called at both paths with fixed inputs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import aragora.cli.review as cli_review
import aragora.review.diff_review as diff_review
from aragora.core import Critique, DebateResult, Message, Vote

REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_NAMES = ("extract_review_findings",)
BOTH_PATHS = pytest.mark.parametrize("module", [cli_review, diff_review], ids=["cli", "home"])


def test_public_names_are_the_same_objects_at_both_paths() -> None:
    assert sorted(diff_review.__all__) == sorted(PUBLIC_NAMES)
    for name in PUBLIC_NAMES:
        assert getattr(cli_review, name) is getattr(diff_review, name), name


@pytest.mark.parametrize("name", ["extract_review_findings"])
def test_functions_are_defined_in_the_review_home(name: str) -> None:
    assert getattr(cli_review, name).__module__ == "aragora.review.diff_review"


def _fixed_debate_result() -> DebateResult:
    security = "anthropic-api_security_reviewer"
    performance = "openai-api_performance_reviewer"
    return DebateResult(
        task="review",
        final_answer="Fix the SQL injection before merging.",
        critiques=[
            Critique(
                agent=security,
                target_agent=performance,
                target_content="",
                issues=["SQL injection in api/users.py:45"],
                suggestions=["Use bound parameters"],
                severity=0.95,
                reasoning="",
            ),
            Critique(
                agent=performance,
                target_agent="api/products.py",
                target_content="",
                issues=["Unbounded query in list_products"],
                suggestions=[],
                severity=0.5,
                reasoning="",
            ),
            Critique(
                agent=performance,
                target_agent=security,
                target_content="",
                issues=["Weak point: overstates the risk"],
                suggestions=[],
                severity=0.8,
                reasoning="",
            ),
        ],
        votes=[
            Vote(agent=security, choice="block", reasoning=""),
            Vote(agent=performance, choice="block", reasoning=""),
        ],
        messages=[
            Message(role="proposer", agent=security, content="Found an injection."),
            Message(role="critic", agent=performance, content="Found an unbounded query."),
        ],
    )


@BOTH_PATHS
def test_extract_review_findings_fixed_input(module) -> None:
    findings = module.extract_review_findings(_fixed_debate_result())

    assert findings["critical_issues"] == [
        {
            "agent": "anthropic-api_security_reviewer",
            "issue": "SQL injection in api/users.py:45",
            "target": "api/users.py:45",
            "suggestions": ["Use bound parameters"],
            "grounded": True,
        }
    ]
    assert findings["high_issues"] == []
    assert findings["medium_issues"] == [
        {
            "agent": "openai-api_performance_reviewer",
            "issue": "Unbounded query in list_products",
            "target": "api/products.py",
            "suggestions": [],
            "grounded": True,
        }
    ]
    assert findings["low_issues"] == []
    assert findings["meta_issues"] == [
        {
            "agent": "openai-api_performance_reviewer",
            "issue": "Weak point: overstates the risk",
            "target": None,
            "suggestions": [],
            "grounded": False,
        }
    ]
    assert findings["final_summary"] == "Fix the SQL injection before merging."
    assert sorted(findings["agents_used"]) == [
        "anthropic-api_security_reviewer",
        "openai-api_performance_reviewer",
    ]
    assert len(findings["all_critiques"]) == 3


def _cli_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
            if node.module == "aragora":
                modules = [f"aragora.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            continue
        for module in modules:
            if module == "aragora.cli" or module.startswith("aragora.cli."):
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {module}")
    return found


def test_diff_review_does_not_import_the_cli_package() -> None:
    assert _cli_imports(REPO_ROOT / "aragora" / "review" / "diff_review.py") == []

"""Tests for the multi-agent diff review home in ``aragora.review.diff_review``.

The helpers moved from ``aragora.cli.review``, which re-exports the public
names. Every public function is called at both paths with fixed inputs.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import aragora.cli.review as cli_review
import aragora.review.diff_review as diff_review
from aragora.compat.openclaw.pr_review_runner import PRReviewRunner
from aragora.core import Critique, DebateResult, Message, Vote

REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_NAMES = (
    "DEFAULT_REVIEW_AGENTS",
    "DEFAULT_ROUNDS",
    "MAX_DIFF_SIZE",
    "build_review_prompt",
    "extract_review_findings",
    "get_available_agents",
    "run_review_debate",
)
BOTH_PATHS = pytest.mark.parametrize("module", [cli_review, diff_review], ids=["cli", "home"])


def test_public_names_are_the_same_objects_at_both_paths() -> None:
    assert sorted(diff_review.__all__) == sorted(PUBLIC_NAMES)
    for name in PUBLIC_NAMES:
        assert getattr(cli_review, name) is getattr(diff_review, name), name


@pytest.mark.parametrize(
    "name",
    ["build_review_prompt", "extract_review_findings", "get_available_agents", "run_review_debate"],
)
def test_functions_are_defined_in_the_review_home(name: str) -> None:
    assert getattr(cli_review, name).__module__ == "aragora.review.diff_review"


@BOTH_PATHS
def test_constants_keep_their_values(module) -> None:
    assert module.MAX_DIFF_SIZE == 50000
    assert isinstance(module.DEFAULT_REVIEW_AGENTS, str)
    assert isinstance(module.DEFAULT_ROUNDS, int)


@BOTH_PATHS
def test_build_review_prompt_fixed_input(module) -> None:
    prompt = module.build_review_prompt("diff --git a/x.py b/x.py\n+x = 1\n", ["security"])

    assert prompt.startswith("You are reviewing a pull request.")
    assert "**Security** - Look for:" in prompt
    assert "**Performance**" not in prompt
    assert "**Code Quality**" not in prompt
    assert "```diff\ndiff --git a/x.py b/x.py\n+x = 1\n\n```" in prompt


@BOTH_PATHS
def test_build_review_prompt_truncates_large_diffs(module) -> None:
    prompt = module.build_review_prompt("y" * (module.MAX_DIFF_SIZE + 5))

    assert "y" * module.MAX_DIFF_SIZE + "\n\n[... diff truncated ...]" in prompt
    assert "y" * (module.MAX_DIFF_SIZE + 1) not in prompt


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


@BOTH_PATHS
def test_get_available_agents_fixed_input(module, monkeypatch: pytest.MonkeyPatch) -> None:
    present = {"ANTHROPIC_API_KEY", "MISTRAL_API_KEY"}
    monkeypatch.setattr(
        diff_review,
        "get_secret_presence",
        lambda name: SimpleNamespace(source="env" if name in present else "missing"),
    )
    assert module.get_available_agents() == "anthropic-api,mistral-api"

    present.clear()
    assert module.get_available_agents() == ""


@pytest.mark.asyncio
@BOTH_PATHS
async def test_run_review_debate_builds_reviewers_in_the_home(module) -> None:
    debate_result = Mock(final_answer="ok")
    arena = Mock()
    arena.run = AsyncMock(return_value=debate_result)

    with (
        patch.object(diff_review, "get_available_agents", return_value=""),
        patch.object(
            diff_review,
            "create_agent",
            side_effect=lambda **kwargs: Mock(name=kwargs["name"]),
        ) as create_agent_mock,
        patch.object(diff_review, "Arena", return_value=arena) as arena_cls,
    ):
        result = await module.run_review_debate(
            "diff --git a/a.py b/a.py", agents_str="anthropic-api,openai-api", rounds=1
        )

    assert result is debate_result
    assert [call.kwargs["name"] for call in create_agent_mock.call_args_list] == [
        "anthropic-api_security_reviewer",
        "openai-api_performance_reviewer",
    ]
    env, agents, protocol = arena_cls.call_args.args
    assert env.max_rounds == 1
    assert len(agents) == 2
    assert protocol.rounds == 1
    assert protocol.consensus == "majority"


@pytest.mark.asyncio
async def test_openclaw_runner_reviews_through_the_home() -> None:
    runner = PRReviewRunner(dry_run=True)
    debate_result = Mock(final_answer="ok")
    findings = {"critical_issues": []}

    with (
        patch.object(
            diff_review, "run_review_debate", AsyncMock(return_value=debate_result)
        ) as run_mock,
        patch.object(diff_review, "extract_review_findings", return_value=findings) as extract,
        patch.object(
            runner,
            "_run_review_subprocess",
            side_effect=AssertionError("subprocess fallback used"),
        ),
    ):
        result, error = await runner._run_review("diff --git a/x b/x")

    assert (result, error) == (findings, None)
    run_mock.assert_awaited_once_with(
        diff="diff --git a/x b/x",
        agents_str=runner.agents,
        rounds=runner.rounds,
        focus_areas=["security", "quality", "performance"],
    )
    extract.assert_called_once_with(debate_result)


def _cli_imports(path: Path, root: Path = REPO_ROOT) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # For both modules and __init__.py files this is the package that relative imports start from.
    package = list(path.relative_to(root).with_suffix("").parts[:-1])
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            parent = ".".join(base + ([node.module] if node.module else []))
            modules = [parent] + [f"{parent}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            continue
        hits = [m for m in modules if m == "aragora.cli" or m.startswith("aragora.cli.")]
        if hits:
            found.append(f"{path.relative_to(root)}:{node.lineno}: {hits[0]}")
    return found


def test_cli_import_guard_resolves_absolute_and_relative_imports(tmp_path: Path) -> None:
    module = tmp_path / "aragora" / "compat" / "sample.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from aragora.cli.review import run_review_debate\n"
        "from aragora import cli\n"
        "import aragora.cli.main\n"
        "from ..cli import review\n"
        "from .. import cli as cli_package\n"
        "from ..review import diff_review\n"
        "from . import openclaw\n",
        encoding="utf-8",
    )

    found = _cli_imports(module, root=tmp_path)

    assert [line.split(": ", 1)[1] for line in found] == [
        "aragora.cli.review",
        "aragora.cli",
        "aragora.cli.main",
        "aragora.cli",
        "aragora.cli",
    ]
    assert [line.split(":")[1] for line in found] == ["1", "2", "3", "4", "5"]


def test_compat_and_diff_review_do_not_import_the_cli_package() -> None:
    files = sorted((REPO_ROOT / "aragora" / "compat").rglob("*.py"))
    files.append(REPO_ROOT / "aragora" / "review" / "diff_review.py")

    offenders = [line for path in files for line in _cli_imports(path)]

    assert offenders == []

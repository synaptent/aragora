"""Tests for aragora.skills.builtin.pr_reviewer.

The review runs through the ``aragora review`` CLI as a subprocess. The skills
package sits below the CLI in the import-layer contract, so the module must not
import ``aragora.cli`` at any scope.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.skills.base import SkillContext
from aragora.skills.builtin import pr_reviewer
from aragora.skills.builtin.pr_reviewer import PRReviewerSkill

MODULE_PATH = Path(pr_reviewer.__file__)


def _imported_modules(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def test_module_never_imports_the_cli_package() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    cli_imports = [
        name
        for name in _imported_modules(tree)
        if name == "aragora.cli" or name.startswith("aragora.cli.")
    ]
    assert cli_imports == []
    dynamic = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("aragora.cli")
    ]
    assert dynamic == []


@pytest.mark.asyncio
async def test_run_review_uses_the_cli_subprocess() -> None:
    skill = PRReviewerSkill(demo=True)
    expected = ({"issues": []}, None)
    with patch.object(
        PRReviewerSkill, "_run_review_subprocess", new=AsyncMock(return_value=expected)
    ) as runner:
        assert await skill._run_review("diff --git a/x b/x") == expected
    runner.assert_awaited_once_with("diff --git a/x b/x")


@pytest.mark.asyncio
async def test_subprocess_review_passes_the_diff_and_parses_json() -> None:
    skill = PRReviewerSkill(demo=True)
    completed = MagicMock(returncode=0, stdout='log line\n{"issues": [1]}\n', stderr="")
    with patch.object(pr_reviewer.subprocess, "run", return_value=completed) as run:
        assert await skill._run_review("the diff") == ({"issues": [1]}, None)
    args, kwargs = run.call_args
    assert args[0] == ["aragora", "review", "--format", "json", "--demo"]
    assert kwargs["input"] == "the diff"


@pytest.mark.asyncio
async def test_subprocess_review_reports_a_missing_cli() -> None:
    skill = PRReviewerSkill()
    with patch.object(pr_reviewer.subprocess, "run", side_effect=FileNotFoundError):
        assert await skill._run_review("the diff") == (None, "aragora CLI not found")


@pytest.mark.asyncio
async def test_subprocess_review_reports_a_timeout() -> None:
    skill = PRReviewerSkill()
    timeout = subprocess.TimeoutExpired(cmd="aragora", timeout=120)
    with patch.object(pr_reviewer.subprocess, "run", side_effect=timeout):
        assert await skill._run_review("the diff") == (None, "Review timed out")


@pytest.mark.asyncio
async def test_execute_with_diff_returns_subprocess_findings() -> None:
    skill = PRReviewerSkill(post_comment=False)
    completed = MagicMock(returncode=0, stdout='{"issues": []}\n', stderr="")
    with patch.object(pr_reviewer.subprocess, "run", return_value=completed):
        result = await skill.execute({"diff": "the diff"}, SkillContext(user_id="u1"))
    assert result.success
    assert result.data["findings"] == {"issues": []}
    assert result.data["comment_posted"] is False

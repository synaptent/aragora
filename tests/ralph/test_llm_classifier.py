"""Tests for LLM-powered blocker classification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_type_hints
from unittest.mock import AsyncMock, patch

import pytest

from aragora.agents.base import AgentType
from aragora.ralph.classifier import BlockerKind
from aragora.ralph.llm_classifier import (
    CapacityVerdict,
    ClassificationVerdict,
    LLMBlockerClassifier,
    MergeVerdict,
    RunOutcomeVerdict,
    ScopeVerdict,
    SpecInferenceVerdict,
)


class TestClassificationVerdict:
    def test_verdict_fields(self) -> None:
        v = ClassificationVerdict(
            kind=BlockerKind.SCOPE_FALSE_POSITIVE,
            confidence=0.95,
            reasoning="Test file edits are expected companions.",
        )
        assert v.kind == BlockerKind.SCOPE_FALSE_POSITIVE
        assert v.confidence == 0.95
        assert "companions" in v.reasoning


class TestScopeVerdict:
    def test_verdict_fields(self) -> None:
        v = ScopeVerdict(
            justified_paths=["tests/test_foo.py"],
            rejected_paths=[],
            reasoning="Test file corresponds to implementation.",
        )
        assert v.justified_paths == ["tests/test_foo.py"]
        assert v.rejected_paths == []


class TestMergeVerdict:
    def test_verdict_fields(self) -> None:
        v = MergeVerdict(
            ready=True,
            blocking_issues=[],
            advisory_issues=["Consider adding docstring"],
            reasoning="All acceptance criteria met.",
        )
        assert v.ready is True
        assert len(v.advisory_issues) == 1


class TestLLMClassifyBlocker:
    def test_constructor_type_hints_resolve(self) -> None:
        hints = get_type_hints(LLMBlockerClassifier.__init__)

        assert hints["model"] == AgentType

    @pytest.mark.asyncio
    async def test_classify_scope_false_positive(self) -> None:
        llm_response = json.dumps(
            {
                "kind": "scope_false_positive",
                "confidence": 0.92,
                "reasoning": "Worker edited test files that correspond to implementation scope.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_blocker(
                manifest_dict={
                    "projects": [
                        {
                            "project_id": "B-3",
                            "status": "blocked",
                            "last_run_outcome": "needs_human",
                            "review": {
                                "status": "changes_requested",
                                "findings": [
                                    "scope violation: tests/swarm/test_campaign.py outside declared scope"
                                ],
                            },
                            "attempt_history": [
                                {
                                    "failure_detail": "worker edited files outside permitted scope: tests/swarm/test_campaign.py"
                                }
                            ],
                        }
                    ]
                },
                stop_reason="campaign_blocked",
            )
        assert verdict.kind == BlockerKind.SCOPE_FALSE_POSITIVE
        assert verdict.confidence > 0.8

    @pytest.mark.asyncio
    async def test_classify_auth_failure(self) -> None:
        llm_response = json.dumps(
            {
                "kind": "reviewer_auth_or_billing_failure",
                "confidence": 0.99,
                "reasoning": "Credit balance exhausted.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_blocker(
                manifest_dict={
                    "projects": [
                        {
                            "project_id": "B-1",
                            "status": "blocked",
                            "last_run_outcome": "deliverable_created",
                            "review": {
                                "status": "blocked_nonreviewable",
                                "findings": ["Credit balance is too low"],
                            },
                        }
                    ]
                },
                stop_reason="campaign_blocked",
            )
        assert verdict.kind == BlockerKind.REVIEWER_AUTH_OR_BILLING

    @pytest.mark.asyncio
    async def test_classify_falls_back_on_malformed_response(self) -> None:
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value="not json at all")

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_blocker(
                manifest_dict={"projects": []},
                stop_reason="campaign_blocked",
            )
        # Should return UNKNOWN with low confidence on parse failure
        assert verdict.kind == BlockerKind.UNKNOWN
        assert verdict.confidence < 0.5

    @pytest.mark.asyncio
    async def test_classify_falls_back_on_agent_error(self) -> None:
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_blocker(
                manifest_dict={"projects": []},
                stop_reason="campaign_blocked",
            )
        assert verdict.kind == BlockerKind.UNKNOWN
        assert verdict.confidence == 0.0


class TestLLMAdjudicateScope:
    @pytest.mark.asyncio
    async def test_justifies_test_file_companion(self) -> None:
        llm_response = json.dumps(
            {
                "justified_paths": ["tests/swarm/test_campaign.py"],
                "rejected_paths": [],
                "reasoning": "Test file directly tests the implementation in declared scope.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.adjudicate_scope(
                task_description="Implement budget cap validation in campaign executor",
                declared_scope=["aragora/swarm/campaign.py"],
                changed_paths=["aragora/swarm/campaign.py", "tests/swarm/test_campaign.py"],
                violations=[
                    {
                        "type": "out_of_scope",
                        "path": "tests/swarm/test_campaign.py",
                        "allowed_scope": ["aragora/swarm/campaign.py"],
                    }
                ],
            )
        assert "tests/swarm/test_campaign.py" in verdict.justified_paths
        assert verdict.rejected_paths == []

    @pytest.mark.asyncio
    async def test_rejects_unrelated_file(self) -> None:
        llm_response = json.dumps(
            {
                "justified_paths": [],
                "rejected_paths": ["aragora/billing/cost_tracker.py"],
                "reasoning": "Billing module is unrelated to swarm campaign work.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.adjudicate_scope(
                task_description="Fix campaign reviewer diff",
                declared_scope=["aragora/swarm/campaign.py"],
                changed_paths=["aragora/swarm/campaign.py", "aragora/billing/cost_tracker.py"],
                violations=[
                    {
                        "type": "out_of_scope",
                        "path": "aragora/billing/cost_tracker.py",
                        "allowed_scope": ["aragora/swarm/campaign.py"],
                    }
                ],
            )
        assert verdict.rejected_paths == ["aragora/billing/cost_tracker.py"]

    @pytest.mark.asyncio
    async def test_fail_closed_on_error(self) -> None:
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("timeout"))

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.adjudicate_scope(
                task_description="Any task",
                declared_scope=["src/foo.py"],
                changed_paths=["src/foo.py", "src/bar.py"],
                violations=[
                    {"type": "out_of_scope", "path": "src/bar.py", "allowed_scope": ["src/foo.py"]}
                ],
            )
        # Fail closed: all violation paths stay rejected
        assert verdict.rejected_paths == ["src/bar.py"]
        assert verdict.justified_paths == []


class TestLLMEvaluateMergeReadiness:
    @pytest.mark.asyncio
    async def test_ready_despite_cosmetic_test_noise(self) -> None:
        llm_response = json.dumps(
            {
                "ready": True,
                "blocking_issues": [],
                "advisory_issues": ["Test output includes deprecation warning"],
                "reasoning": "All acceptance criteria met. Test failure is a pre-existing deprecation warning, not caused by this change.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.evaluate_merge_readiness(
                acceptance_criteria=["Budget caps enforced", "Tests pass"],
                verification_results=[
                    {
                        "command": "pytest tests/swarm -q",
                        "passed": False,
                        "exit_code": 1,
                        "stderr": "DeprecationWarning: old API",
                    },
                ],
                changed_paths=["aragora/swarm/campaign.py"],
                diff_summary="Added budget cap validation to campaign executor",
            )
        assert verdict.ready is True
        assert len(verdict.advisory_issues) > 0

    @pytest.mark.asyncio
    async def test_not_ready_real_failure(self) -> None:
        llm_response = json.dumps(
            {
                "ready": False,
                "blocking_issues": ["Test assertion failure in budget validation"],
                "advisory_issues": [],
                "reasoning": "The budget cap test fails with AssertionError, indicating the implementation has a bug.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.evaluate_merge_readiness(
                acceptance_criteria=["Budget caps enforced"],
                verification_results=[
                    {
                        "command": "pytest tests/swarm -q",
                        "passed": False,
                        "exit_code": 1,
                        "stderr": "AssertionError: expected 75.0 got None",
                    },
                ],
                changed_paths=["aragora/swarm/campaign.py"],
                diff_summary="Added budget cap field",
            )
        assert verdict.ready is False
        assert len(verdict.blocking_issues) > 0

    @pytest.mark.asyncio
    async def test_fail_closed_on_error(self) -> None:
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("timeout"))

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.evaluate_merge_readiness(
                acceptance_criteria=["Tests pass"],
                verification_results=[{"command": "pytest", "passed": False, "exit_code": 1}],
                changed_paths=["src/foo.py"],
                diff_summary="changes",
            )
        # Fail closed: not ready
        assert verdict.ready is False


class TestRunOutcomeVerdict:
    def test_verdict_fields(self) -> None:
        v = RunOutcomeVerdict(outcome="crash", reasoning="Non-zero exit code.")
        assert v.outcome == "crash"
        assert "exit" in v.reasoning


class TestCapacityVerdict:
    def test_verdict_fields(self) -> None:
        v = CapacityVerdict(
            is_capacity=True, detail="credit balance is too low", reasoning="Billing."
        )
        assert v.is_capacity is True
        assert "credit" in v.detail


class TestSpecInferenceVerdict:
    def test_verdict_fields(self) -> None:
        v = SpecInferenceVerdict(
            track_hints=["qa", "developer"],
            constraints=["Do not modify the database schema"],
            acceptance_criteria=["Tests pass"],
            reasoning="Extracted from user messages.",
        )
        assert "qa" in v.track_hints
        assert len(v.constraints) == 1


class TestLLMClassifyRunOutcome:
    @pytest.mark.asyncio
    async def test_classify_timeout(self) -> None:
        llm_response = json.dumps({"outcome": "timeout", "reasoning": "Run exceeded time limit."})
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_run_outcome(
                run_dict={"status": "failed", "error": "timeout after 300s"}
            )
        assert verdict.outcome == "timeout"

    @pytest.mark.asyncio
    async def test_classify_crash(self) -> None:
        llm_response = json.dumps(
            {"outcome": "crash", "reasoning": "Non-zero exit code with traceback."}
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_run_outcome(
                run_dict={"status": "failed", "exit_code": 1, "traceback": "..."}
            )
        assert verdict.outcome == "crash"

    @pytest.mark.asyncio
    async def test_classify_invalid_outcome_falls_back(self) -> None:
        llm_response = json.dumps({"outcome": "something_weird", "reasoning": "huh"})
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_run_outcome(run_dict={"status": "unknown"})
        assert verdict.outcome == "blocked"

    @pytest.mark.asyncio
    async def test_fail_closed_on_error(self) -> None:
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.classify_run_outcome(run_dict={})
        assert verdict.outcome == "blocked"


class TestLLMDetectCapacityFailure:
    @pytest.mark.asyncio
    async def test_detects_billing_issue(self) -> None:
        llm_response = json.dumps({"is_capacity": True, "reasoning": "Credit balance depleted."})
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.detect_capacity_failure(
                stdout="", stderr="Error: credit balance is too low", agent_name="claude"
            )
        assert verdict.is_capacity is True
        assert verdict.detail  # non-empty when is_capacity=True

    @pytest.mark.asyncio
    async def test_not_capacity_on_regular_error(self) -> None:
        llm_response = json.dumps(
            {"is_capacity": False, "reasoning": "This is a crash, not billing."}
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.detect_capacity_failure(
                stdout="", stderr="Traceback: IndexError", agent_name="codex"
            )
        assert verdict.is_capacity is False

    @pytest.mark.asyncio
    async def test_empty_output_returns_not_capacity(self) -> None:
        classifier = LLMBlockerClassifier()
        verdict = await classifier.detect_capacity_failure(
            stdout="", stderr="", agent_name="claude"
        )
        assert verdict.is_capacity is False

    @pytest.mark.asyncio
    async def test_fail_closed_on_error(self) -> None:
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("timeout"))

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.detect_capacity_failure(
                stdout="credit balance", stderr="", agent_name="claude"
            )
        assert verdict.is_capacity is False


class TestLLMInferSpecFields:
    @pytest.mark.asyncio
    async def test_infers_tracks_and_criteria(self) -> None:
        llm_response = json.dumps(
            {
                "track_hints": ["qa", "developer"],
                "constraints": ["Do not modify the database"],
                "acceptance_criteria": ["All tests pass", "Coverage above 80%"],
                "reasoning": "Goal involves testing and API work.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.infer_spec_fields(
                user_messages=["Add unit tests for the API endpoint"],
                raw_goal="Add test coverage for API",
            )
        assert "qa" in verdict.track_hints
        assert "developer" in verdict.track_hints
        assert len(verdict.acceptance_criteria) == 2

    @pytest.mark.asyncio
    async def test_filters_invalid_tracks(self) -> None:
        llm_response = json.dumps(
            {
                "track_hints": ["qa", "bogus_track", "security"],
                "constraints": [],
                "acceptance_criteria": [],
                "reasoning": "Filtered.",
            }
        )
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(return_value=llm_response)

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.infer_spec_fields(
                user_messages=["Fix security audit findings"],
                raw_goal="Security fix",
            )
        assert "qa" in verdict.track_hints
        assert "security" in verdict.track_hints
        assert "bogus_track" not in verdict.track_hints

    @pytest.mark.asyncio
    async def test_fail_closed_on_error(self) -> None:
        mock_agent = AsyncMock()
        mock_agent.generate = AsyncMock(side_effect=RuntimeError("timeout"))

        with patch("aragora.agents.base.create_agent", return_value=mock_agent):
            classifier = LLMBlockerClassifier()
            verdict = await classifier.infer_spec_fields(
                user_messages=["anything"], raw_goal="goal"
            )
        assert verdict.track_hints == []
        assert verdict.constraints == []
        assert verdict.acceptance_criteria == []


# ---------------------------------------------------------------------------
# Tests for improved scope adjudication prompt content
# ---------------------------------------------------------------------------


class TestScopePromptContent:
    """Verify the _build_scope_prompt includes dependency-aware patterns,
    test companion patterns, and optional repository structure context."""

    def test_prompt_mentions_dependency_files(self) -> None:
        prompt = LLMBlockerClassifier._build_scope_prompt(
            task_description="Update React to v19",
            declared_scope=["src/components/**"],
            changed_paths=["src/components/App.tsx", "package.json"],
            out_of_scope_paths=["package.json"],
        )
        # Dependency file patterns should be in the prompt
        assert "package.json" in prompt
        assert "requirements.txt" in prompt
        assert "Cargo.lock" in prompt
        assert "pyproject.toml" in prompt
        assert "setup.cfg" in prompt
        assert "go.mod" in prompt

    def test_prompt_mentions_lock_files(self) -> None:
        prompt = LLMBlockerClassifier._build_scope_prompt(
            task_description="Add new dependency",
            declared_scope=["aragora/server/**"],
            changed_paths=["aragora/server/app.py", "poetry.lock"],
            out_of_scope_paths=["poetry.lock"],
        )
        assert "package-lock.json" in prompt
        assert "yarn.lock" in prompt
        assert "poetry.lock" in prompt
        assert "Pipfile.lock" in prompt

    def test_prompt_mentions_test_companion_pattern(self) -> None:
        prompt = LLMBlockerClassifier._build_scope_prompt(
            task_description="Fix consensus detection",
            declared_scope=["aragora/debate/**"],
            changed_paths=["aragora/debate/consensus.py", "tests/debate/test_consensus.py"],
            out_of_scope_paths=["tests/debate/test_consensus.py"],
        )
        # Should mention the test companion pattern
        assert "test_bar.py" in prompt or "test file" in prompt.lower()
        assert "tests/" in prompt

    def test_prompt_mentions_init_files(self) -> None:
        prompt = LLMBlockerClassifier._build_scope_prompt(
            task_description="Add new module",
            declared_scope=["aragora/new_module/**"],
            changed_paths=["aragora/new_module/core.py", "aragora/__init__.py"],
            out_of_scope_paths=["aragora/__init__.py"],
        )
        assert "__init__.py" in prompt

    def test_prompt_includes_repo_structure_when_provided(self, tmp_path: Path) -> None:
        """When repo_root is given, top-level dirs appear in the prompt."""
        (tmp_path / "aragora").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "scripts").mkdir()

        prompt = LLMBlockerClassifier._build_scope_prompt(
            task_description="Fix bug",
            declared_scope=["aragora/**"],
            changed_paths=["aragora/foo.py", "docs/bar.md"],
            out_of_scope_paths=["docs/bar.md"],
            repo_root=str(tmp_path),
        )
        assert "Repository top-level directories" in prompt
        assert "aragora" in prompt
        assert "tests" in prompt
        assert "docs" in prompt

    def test_prompt_omits_repo_structure_when_not_provided(self) -> None:
        """Without repo_root, no repository structure section appears."""
        prompt = LLMBlockerClassifier._build_scope_prompt(
            task_description="Fix bug",
            declared_scope=["aragora/**"],
            changed_paths=["aragora/foo.py"],
            out_of_scope_paths=[],
        )
        assert "Repository top-level directories" not in prompt

    def test_prompt_omits_hidden_dirs_from_repo_structure(self, tmp_path: Path) -> None:
        """Dotfiles/dotdirs should be filtered out of repo structure."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".env").write_text("SECRET=x\n")
        (tmp_path / "aragora").mkdir()

        prompt = LLMBlockerClassifier._build_scope_prompt(
            task_description="Fix bug",
            declared_scope=["aragora/**"],
            changed_paths=["aragora/foo.py"],
            out_of_scope_paths=[],
            repo_root=str(tmp_path),
        )
        assert ".git" not in prompt
        assert ".env" not in prompt

"""E2E test: debate result -> spec extraction -> task creation -> execution -> receipt.

Tests the full OpenClaw E2E loop with a mocked ClaudeCodeHarness so no
real subprocess calls are made. Validates that data flows correctly through
each stage and that the final receipt contains execution metadata.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal debate result stub
# ---------------------------------------------------------------------------


@dataclass
class _StubDebateResult:
    """Minimal DebateResult duck-type for test use."""

    debate_id: str = "debate-test-001"
    task: str = "Add rate limiting to the API endpoint"
    final_answer: str = (
        "1. Create a `rate_limiter.py` module in `aragora/server/`\n"
        "2. Implement token-bucket algorithm with configurable limits\n"
        "3. Add middleware integration in `aragora/server/middleware.py`\n"
        "4. Write unit tests in `tests/server/test_rate_limiter.py`\n"
        "\n"
        "Rollback plan: revert the middleware change if latency increases > 50ms.\n"
    )
    confidence: float = 0.85
    consensus_reached: bool = True
    consensus_strength: str = "strong"
    participants: list[str] = field(default_factory=lambda: ["claude", "gpt-4"])
    messages: list[Any] = field(default_factory=list)
    critiques: list[Any] = field(default_factory=list)
    votes: list[Any] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    debate_cruxes: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    per_agent_similarity: dict[str, float] = field(default_factory=dict)
    convergence_status: str = "converged"
    consensus_variance: float = 0.3
    winner: str = ""
    rounds_used: int = 3
    status: str = "consensus_reached"
    total_cost_usd: float = 0.05
    proposals: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSpecExtraction:
    """Test the ImplementationSpecExtractor."""

    def test_extract_files_from_final_answer(self) -> None:
        from aragora.pipeline.spec_extractor import extract_implementation_spec

        result = _StubDebateResult()
        spec = extract_implementation_spec(result)

        # Should find files mentioned in backticks
        assert "rate_limiter.py" in spec.files_to_modify or any(
            "rate_limiter.py" in f for f in spec.files_to_modify
        )
        assert len(spec.files_to_modify) >= 1

    def test_extract_rollback_plan(self) -> None:
        from aragora.pipeline.spec_extractor import extract_implementation_spec

        result = _StubDebateResult()
        spec = extract_implementation_spec(result)

        # Should capture the rollback line
        assert "revert" in spec.rollback_plan.lower() or "rollback" in spec.rollback_plan.lower()

    def test_extract_implementation_prompt(self) -> None:
        from aragora.pipeline.spec_extractor import extract_implementation_spec

        result = _StubDebateResult()
        spec = extract_implementation_spec(result)

        # Should contain the task and implementation steps
        assert "rate limit" in spec.implementation_prompt.lower()
        assert len(spec.implementation_prompt) > 50

    def test_empty_final_answer_fallback(self) -> None:
        from aragora.pipeline.spec_extractor import extract_implementation_spec

        result = _StubDebateResult(final_answer="", task="Do something")
        spec = extract_implementation_spec(result)

        assert "Do something" in spec.implementation_prompt
        assert spec.files_to_modify == []

    def test_spec_to_dict_roundtrip(self) -> None:
        from aragora.pipeline.spec_extractor import ImplementationSpec

        spec = ImplementationSpec(
            implementation_prompt="test prompt",
            files_to_modify=["foo.py"],
            rollback_plan="revert commit",
        )
        data = spec.to_dict()
        restored = ImplementationSpec.from_dict(data)
        assert restored.implementation_prompt == spec.implementation_prompt
        assert restored.files_to_modify == spec.files_to_modify
        assert restored.rollback_plan == spec.rollback_plan


class TestComputerUseActionBundle:
    """Test the ComputerUseActionBundle backbone contract."""

    def test_from_execution_result(self) -> None:
        from aragora.pipeline.backbone_contracts import ComputerUseActionBundle

        exec_result = {
            "stdout": "Created file rate_limiter.py\nModified middleware.py",
            "stderr": "",
            "exit_code": 0,
            "duration_seconds": 45.2,
            "files_changed": 2,
            "success": True,
        }

        bundle = ComputerUseActionBundle.from_execution_result(
            exec_result,
            harness_name="claude-code",
            action_type="implementation",
            input_prompt="Add rate limiting",
        )

        assert bundle.harness_name == "claude-code"
        assert bundle.action_type == "implementation"
        assert bundle.exit_code == 0
        assert bundle.execution_time_seconds == pytest.approx(45.2)
        assert "rate_limiter.py" in bundle.stdout_summary

    def test_to_dict_roundtrip(self) -> None:
        from aragora.pipeline.backbone_contracts import ComputerUseActionBundle

        bundle = ComputerUseActionBundle(
            harness_name="claude-code",
            action_type="implementation",
            input_prompt="test",
            output_files=["a.py"],
            execution_time_seconds=10.0,
            exit_code=0,
            stdout_summary="done",
            policy_violations=[],
        )
        data = bundle.to_dict()
        restored = ComputerUseActionBundle.from_dict(data)
        assert restored.harness_name == bundle.harness_name
        assert restored.exit_code == bundle.exit_code
        assert restored.stdout_summary == bundle.stdout_summary

    def test_stdout_truncation(self) -> None:
        from aragora.pipeline.backbone_contracts import ComputerUseActionBundle

        long_stdout = "x" * 5000
        bundle = ComputerUseActionBundle.from_dict(
            {
                "harness_name": "codex",
                "action_type": "analysis",
                "input_prompt": "",
                "stdout_summary": long_stdout,
            }
        )
        assert len(bundle.stdout_summary) <= 2000


class TestReceiptLinkage:
    """Test receipt update after execution."""

    def test_update_receipt_with_execution_success(self) -> None:
        from aragora.pipeline.backbone_contracts import ReceiptEnvelope
        from aragora.pipeline.receipt_generator import update_receipt_with_execution

        envelope = ReceiptEnvelope(
            receipt_id="receipt-abc123",
            artifact_hash="oldhash",
            verdict="unknown",
            confidence=0.8,
        )

        outcome = {
            "status": "succeeded",
            "tests_passed": 10,
            "tests_failed": 0,
            "files_changed": 3,
            "duration_s": 42.5,
        }

        action_data = {
            "harness_name": "claude-code",
            "action_type": "implementation",
            "exit_code": 0,
        }

        updated = update_receipt_with_execution(envelope, outcome, action_data)

        assert updated.verdict == "pass"
        assert updated.extras["execution_outcome"]["tests_passed"] == 10
        assert updated.extras["action_bundle"]["harness_name"] == "claude-code"
        # Hash should have changed
        assert updated.artifact_hash != "oldhash"

    def test_update_receipt_with_execution_failure(self) -> None:
        from aragora.pipeline.backbone_contracts import ReceiptEnvelope
        from aragora.pipeline.receipt_generator import update_receipt_with_execution

        envelope = ReceiptEnvelope(
            receipt_id="receipt-def456",
            artifact_hash="oldhash",
            verdict="unknown",
        )

        outcome = {
            "status": "failed",
            "tests_passed": 5,
            "tests_failed": 3,
            "files_changed": 1,
        }

        updated = update_receipt_with_execution(envelope, outcome)

        assert updated.verdict == "fail"
        assert updated.extras["execution_outcome"]["tests_failed"] == 3
        assert "action_bundle" not in updated.extras

    def test_update_receipt_hash_covers_provenance_and_taint(self) -> None:
        from aragora.pipeline.backbone_contracts import ReceiptEnvelope
        from aragora.pipeline.receipt_generator import update_receipt_with_execution

        outcome = {
            "status": "succeeded",
            "tests_passed": 1,
            "tests_failed": 0,
            "files_changed": 1,
            "duration_s": 1.0,
        }

        base = ReceiptEnvelope(
            receipt_id="receipt-hash-001",
            artifact_hash="oldhash",
            verdict="unknown",
            confidence=0.8,
            provenance_chain=[{"stage": "ideas", "id": "n1"}],
            taint_summary={"blocked": False},
        )
        changed = ReceiptEnvelope(
            receipt_id="receipt-hash-001",
            artifact_hash="oldhash",
            verdict="unknown",
            confidence=0.8,
            provenance_chain=[{"stage": "ideas", "id": "n1"}, {"stage": "actions", "id": "n2"}],
            taint_summary={"blocked": True},
        )

        hash_base = update_receipt_with_execution(base, outcome).artifact_hash
        hash_changed = update_receipt_with_execution(changed, outcome).artifact_hash

        assert hash_base != hash_changed


class TestCodeImplementationTask:
    """Test the CodeImplementationTask workflow node with mocked harness."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        from aragora.workflow.nodes.code_implementation import CodeImplementationTask
        from aragora.workflow.step import WorkflowContext

        node = CodeImplementationTask(
            "test-impl",
            config={
                "repo_path": "/tmp/test-repo",
                "implementation_prompt": "Add rate limiting",
                "files_to_modify": ["rate_limiter.py"],
                "timeout_seconds": 60,
            },
        )

        ctx = WorkflowContext(
            workflow_id="wf-1",
            definition_id="def-1",
        )

        mock_harness = AsyncMock()
        mock_harness.initialize = AsyncMock(return_value=True)
        mock_harness.execute_implementation = AsyncMock(
            return_value=("Created file rate_limiter.py\nDone.", "")
        )

        with patch.object(
            CodeImplementationTask,
            "_create_harness",
            return_value=mock_harness,
        ):
            result = await node.execute(ctx)

        assert result["success"] is True
        assert result["exit_code"] == 0
        assert result["files_changed"] >= 1
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_execution_failure(self) -> None:
        from aragora.workflow.nodes.code_implementation import CodeImplementationTask
        from aragora.workflow.step import WorkflowContext

        node = CodeImplementationTask(
            "test-impl-fail",
            config={
                "repo_path": "/tmp/test-repo",
                "implementation_prompt": "Bad instruction",
                "timeout_seconds": 10,
            },
        )

        ctx = WorkflowContext(workflow_id="wf-2", definition_id="def-2")

        mock_harness = AsyncMock()
        mock_harness.initialize = AsyncMock(return_value=True)
        mock_harness.execute_implementation = AsyncMock(
            return_value=("", "Error: compilation failed")
        )

        with patch.object(
            CodeImplementationTask,
            "_create_harness",
            return_value=mock_harness,
        ):
            result = await node.execute(ctx)

        assert result["success"] is False
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_no_prompt(self) -> None:
        from aragora.workflow.nodes.code_implementation import CodeImplementationTask
        from aragora.workflow.step import WorkflowContext

        node = CodeImplementationTask(
            "test-no-prompt",
            config={"repo_path": "/tmp/test-repo"},
        )

        ctx = WorkflowContext(workflow_id="wf-3", definition_id="def-3")
        result = await node.execute(ctx)

        assert result["success"] is False
        assert "No implementation_prompt" in result["error"]

    @pytest.mark.asyncio
    async def test_harness_timeout(self) -> None:
        from aragora.workflow.nodes.code_implementation import CodeImplementationTask
        from aragora.workflow.step import WorkflowContext

        node = CodeImplementationTask(
            "test-timeout",
            config={
                "repo_path": "/tmp/test-repo",
                "implementation_prompt": "Slow task",
                "timeout_seconds": 1,
            },
        )

        ctx = WorkflowContext(workflow_id="wf-4", definition_id="def-4")

        mock_harness = AsyncMock()
        mock_harness.initialize = AsyncMock(return_value=True)
        mock_harness.execute_implementation = AsyncMock(side_effect=TimeoutError("timed out"))

        with patch.object(
            CodeImplementationTask,
            "_create_harness",
            return_value=mock_harness,
        ):
            result = await node.execute(ctx)

        assert result["success"] is False
        assert "TimeoutError" in result["error"]


class TestFullE2ELoop:
    """End-to-end: debate result -> spec -> task -> execution -> receipt."""

    @pytest.mark.asyncio
    async def test_debate_to_receipt(self) -> None:
        """Full loop with mocked harness execution."""
        from aragora.pipeline.backbone_contracts import (
            ComputerUseActionBundle,
            ReceiptEnvelope,
        )
        from aragora.pipeline.receipt_generator import update_receipt_with_execution
        from aragora.pipeline.spec_extractor import extract_implementation_spec
        from aragora.workflow.nodes.code_implementation import CodeImplementationTask
        from aragora.workflow.step import WorkflowContext

        # Step 1: Start with a debate result
        debate_result = _StubDebateResult()

        # Step 2: Extract implementation spec
        spec = extract_implementation_spec(debate_result)
        assert spec.implementation_prompt
        assert len(spec.files_to_modify) >= 1

        # Step 3: Create and execute the task (mocked harness)
        node = CodeImplementationTask(
            "e2e-impl",
            config={
                "repo_path": "/tmp/e2e-repo",
                "implementation_prompt": spec.implementation_prompt,
                "files_to_modify": spec.files_to_modify,
            },
        )

        ctx = WorkflowContext(workflow_id="wf-e2e", definition_id="def-e2e")

        mock_harness = AsyncMock()
        mock_harness.initialize = AsyncMock(return_value=True)
        mock_harness.execute_implementation = AsyncMock(
            return_value=(
                "Created file aragora/server/rate_limiter.py\n"
                "Modified aragora/server/middleware.py\n"
                "All tests passing.",
                "",
            )
        )

        with patch.object(
            CodeImplementationTask,
            "_create_harness",
            return_value=mock_harness,
        ):
            exec_result = await node.execute(ctx)

        assert exec_result["success"] is True

        # Step 4: Create action bundle from execution result
        action_bundle = ComputerUseActionBundle.from_execution_result(
            exec_result,
            harness_name="claude-code",
            action_type="implementation",
            input_prompt=spec.implementation_prompt,
        )
        assert action_bundle.exit_code == 0

        # Step 5: Create and update receipt
        envelope = ReceiptEnvelope(
            receipt_id="receipt-e2e-001",
            artifact_hash="initial",
            verdict="unknown",
            confidence=debate_result.confidence,
        )

        plan_outcome = {
            "status": "succeeded",
            "tests_passed": 10,
            "tests_failed": 0,
            "files_changed": exec_result["files_changed"],
            "duration_s": exec_result["duration_seconds"],
        }

        updated = update_receipt_with_execution(
            envelope,
            plan_outcome,
            action_bundle.to_dict(),
        )

        # Verify the full chain
        assert updated.verdict == "pass"
        assert updated.artifact_hash != "initial"
        assert updated.extras["execution_outcome"]["status"] == "succeeded"
        assert updated.extras["action_bundle"]["harness_name"] == "claude-code"
        assert updated.confidence == debate_result.confidence

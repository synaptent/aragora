"""
Tests for Nomic Loop Commit Phase.

Phase 5: Commit changes if verified
- Tests human approval workflow
- Tests auto-commit mode
- Tests git operations (add, commit)
- Tests commit hash tracking
- Tests CommitGate integration
- Tests error handling
- Tests CommitResult TypedDict
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.nomic.phases.commit import CommitPhase
from aragora.nomic.phases import CommitResult


class TestCommitPhaseInitialization:
    """Tests for CommitPhase initialization."""

    def test_init_with_required_args(self, mock_aragora_path):
        """Should initialize with required arguments."""
        phase = CommitPhase(aragora_path=mock_aragora_path)
        assert phase.aragora_path == mock_aragora_path
        assert phase.require_human_approval is True
        assert phase.auto_commit is False
        assert phase.cycle_count == 0

    def test_init_with_all_optional_args(self, mock_aragora_path, mock_log_fn, mock_stream_emit_fn):
        """Should initialize with all optional arguments."""
        gate = MagicMock()
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            cycle_count=5,
            log_fn=mock_log_fn,
            stream_emit_fn=mock_stream_emit_fn,
            commit_gate=gate,
        )
        assert phase.require_human_approval is False
        assert phase.auto_commit is True
        assert phase.cycle_count == 5
        assert phase._commit_gate is gate

    def test_init_default_log_fn(self, mock_aragora_path):
        """Default log function should be print."""
        phase = CommitPhase(aragora_path=mock_aragora_path)
        assert phase._log is not None

    def test_init_default_stream_emit_fn(self, mock_aragora_path):
        """Default stream emit function should be a no-op."""
        phase = CommitPhase(aragora_path=mock_aragora_path)
        # Should not raise
        phase._stream_emit("test_event", "arg1", "arg2")


class TestCommitPhaseExecution:
    """Tests for CommitPhase execution."""

    @pytest.mark.asyncio
    async def test_execute_with_auto_commit(self, mock_aragora_path, mock_log_fn):
        """Should commit without approval when auto_commit is True."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
        )

        with patch("subprocess.run") as mock_run:
            # Mock git diff --name-only (for _get_changed_files)
            mock_diff_name = MagicMock()
            mock_diff_name.returncode = 0
            mock_diff_name.stdout = "file.py"
            # Mock git add
            mock_add = MagicMock()
            mock_add.returncode = 0
            # Mock git commit
            mock_commit = MagicMock()
            mock_commit.returncode = 0
            mock_commit.stdout = ""
            mock_commit.stderr = ""
            # Mock git rev-parse
            mock_rev_parse = MagicMock()
            mock_rev_parse.returncode = 0
            mock_rev_parse.stdout = "abc1234"
            # Mock git diff --stat
            mock_stat = MagicMock()
            mock_stat.returncode = 0
            mock_stat.stdout = "file.py | 5 +++--"

            mock_run.side_effect = [
                mock_diff_name,
                mock_add,
                mock_commit,
                mock_rev_parse,
                mock_stat,
            ]

            result = await phase.execute("Test improvement")

            assert result["success"] is True
            assert result["committed"] is True
            assert result["commit_hash"] == "abc1234"

    @pytest.mark.asyncio
    async def test_execute_commit_failure(self, mock_aragora_path, mock_log_fn):
        """Should handle commit failure gracefully."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
        )

        with patch("subprocess.run") as mock_run:
            # Mock git add success
            mock_add = MagicMock()
            mock_add.returncode = 0
            # Mock git commit failure
            mock_commit = MagicMock()
            mock_commit.returncode = 1
            mock_commit.stderr = "nothing to commit"

            mock_run.side_effect = [mock_add, mock_commit]

            result = await phase.execute("Test improvement")

            assert result["success"] is False
            assert result["committed"] is False

    @pytest.mark.asyncio
    async def test_execute_with_gate_approved(self, mock_aragora_path, mock_log_fn):
        """Should use CommitGate when provided and approved."""
        from aragora.nomic.gates import ApprovalStatus

        gate = MagicMock()
        gate_decision = MagicMock()
        gate_decision.status = ApprovalStatus.APPROVED
        gate_decision.approver = "auto"
        gate.require_approval = AsyncMock(return_value=gate_decision)

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
            log_fn=mock_log_fn,
            commit_gate=gate,
        )

        with patch("subprocess.run") as mock_run:
            # Mock git diff --stat for gate context
            mock_diff_stat = MagicMock()
            mock_diff_stat.returncode = 0
            mock_diff_stat.stdout = "file.py | 2 ++"
            # Mock git diff --name-only for changed files
            mock_diff_name = MagicMock()
            mock_diff_name.returncode = 0
            mock_diff_name.stdout = "file.py"
            # Mock git add
            mock_add = MagicMock()
            mock_add.returncode = 0
            # Mock git commit
            mock_commit = MagicMock()
            mock_commit.returncode = 0
            mock_commit.stdout = ""
            mock_commit.stderr = ""
            # Mock git rev-parse
            mock_rev_parse = MagicMock()
            mock_rev_parse.returncode = 0
            mock_rev_parse.stdout = "def5678"
            # Mock git diff --stat for files changed count
            mock_stat = MagicMock()
            mock_stat.returncode = 0
            mock_stat.stdout = "file.py | 2 ++"

            mock_run.side_effect = [
                mock_diff_name,  # _get_changed_files
                mock_diff_stat,  # gate context
                mock_add,
                mock_commit,
                mock_rev_parse,
                mock_stat,
            ]

            result = await phase.execute("Test improvement")

            assert result["success"] is True
            gate.require_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_gate_skipped(self, mock_aragora_path, mock_log_fn):
        """Should handle skipped gate status."""
        from aragora.nomic.gates import ApprovalStatus

        gate = MagicMock()
        gate_decision = MagicMock()
        gate_decision.status = ApprovalStatus.SKIPPED
        gate.require_approval = AsyncMock(return_value=gate_decision)

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
            log_fn=mock_log_fn,
            commit_gate=gate,
        )

        with patch("subprocess.run") as mock_run:
            # Mock git diff --name-only
            mock_diff_name = MagicMock()
            mock_diff_name.returncode = 0
            mock_diff_name.stdout = "file.py"
            # Mock git diff --stat
            mock_diff_stat = MagicMock()
            mock_diff_stat.returncode = 0
            mock_diff_stat.stdout = ""

            mock_run.side_effect = [mock_diff_name, mock_diff_stat]

            # The gate returns SKIPPED, which should fall through to legacy approval
            # Since require_human_approval is True and auto_commit is False,
            # and we can't simulate interactive input, let's patch _get_approval
            with patch.object(phase, "_get_approval", return_value=True):
                with patch("subprocess.run") as mock_run_inner:
                    mock_add = MagicMock()
                    mock_add.returncode = 0
                    mock_commit = MagicMock()
                    mock_commit.returncode = 0
                    mock_commit.stdout = ""
                    mock_commit.stderr = ""
                    mock_rev_parse = MagicMock()
                    mock_rev_parse.returncode = 0
                    mock_rev_parse.stdout = "xyz789"
                    mock_stat = MagicMock()
                    mock_stat.returncode = 0
                    mock_stat.stdout = ""

                    mock_run_inner.side_effect = [mock_add, mock_commit, mock_rev_parse, mock_stat]

                    result = await phase.execute("Test improvement")

                    assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_with_gate_declined(self, mock_aragora_path, mock_log_fn):
        """Should fail when gate denies approval."""
        from aragora.nomic.gates import ApprovalRequired

        gate = MagicMock()
        gate.require_approval = AsyncMock(side_effect=ApprovalRequired("commit", "Not allowed"))

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
            log_fn=mock_log_fn,
            commit_gate=gate,
        )

        with patch("subprocess.run") as mock_run:
            mock_diff_name = MagicMock()
            mock_diff_name.returncode = 0
            mock_diff_name.stdout = ""
            mock_diff_stat = MagicMock()
            mock_diff_stat.returncode = 0
            mock_diff_stat.stdout = ""

            mock_run.side_effect = [mock_diff_name, mock_diff_stat]

            result = await phase.execute("Test improvement")

            assert result["success"] is False
            assert result["committed"] is False
            assert "gate_declined" in str(result.get("data", {}))

    @pytest.mark.asyncio
    async def test_execute_records_duration(self, mock_aragora_path, mock_log_fn):
        """Should record execution duration."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
        )

        with patch("subprocess.run") as mock_run:
            mock_add = MagicMock()
            mock_add.returncode = 0
            mock_commit = MagicMock()
            mock_commit.returncode = 0
            mock_commit.stdout = ""
            mock_commit.stderr = ""
            mock_rev_parse = MagicMock()
            mock_rev_parse.returncode = 0
            mock_rev_parse.stdout = "abc123"
            mock_stat = MagicMock()
            mock_stat.returncode = 0
            mock_stat.stdout = ""

            mock_run.side_effect = [mock_add, mock_commit, mock_rev_parse, mock_stat]

            result = await phase.execute("Test")

            assert "duration_seconds" in result
            assert result["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_execute_emits_stream_events(self, mock_aragora_path, mock_stream_emit_fn):
        """Should emit streaming events during execution."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            stream_emit_fn=mock_stream_emit_fn,
        )

        with patch("subprocess.run") as mock_run:
            mock_add = MagicMock()
            mock_add.returncode = 0
            mock_commit = MagicMock()
            mock_commit.returncode = 0
            mock_commit.stdout = ""
            mock_commit.stderr = ""
            mock_rev_parse = MagicMock()
            mock_rev_parse.returncode = 0
            mock_rev_parse.stdout = "abc"
            mock_stat = MagicMock()
            mock_stat.returncode = 0
            mock_stat.stdout = ""

            mock_run.side_effect = [mock_add, mock_commit, mock_rev_parse, mock_stat]

            await phase.execute("Test")

            # Check that stream events were emitted
            assert mock_stream_emit_fn.call_count >= 2  # phase_start and phase_end

    @pytest.mark.asyncio
    async def test_execute_subprocess_exception(self, mock_aragora_path, mock_log_fn):
        """Should handle subprocess exceptions gracefully."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Git not found")

            result = await phase.execute("Test")

            assert result["success"] is False
            assert "error" in result
            assert result["committed"] is False


class TestCommitPhaseApproval:
    """Tests for human approval workflow."""

    def test_get_approval_with_auto_commit_env(self, mock_aragora_path, monkeypatch):
        """Should auto-approve when NOMIC_AUTO_COMMIT=1."""
        monkeypatch.setenv("NOMIC_AUTO_COMMIT", "1")

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
        )

        with patch("subprocess.run"):  # Mock git diff --stat
            result = phase._get_approval()
            assert result is True

    def test_get_approval_non_interactive(self, mock_aragora_path, monkeypatch):
        """Should return False in non-interactive mode without NOMIC_AUTO_COMMIT."""
        monkeypatch.setenv("NOMIC_AUTO_COMMIT", "0")

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
        )

        with patch("subprocess.run"):  # Mock git diff --stat
            with patch("sys.stdin.isatty", return_value=False):
                result = phase._get_approval()
                assert result is False

    def test_get_approval_interactive_yes(self, mock_aragora_path, monkeypatch):
        """Should return True when user enters 'y'."""
        monkeypatch.setenv("NOMIC_AUTO_COMMIT", "0")

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
        )

        with patch("subprocess.run"):  # Mock git diff --stat
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="y"):
                    result = phase._get_approval()
                    assert result is True

    def test_get_approval_interactive_no(self, mock_aragora_path, monkeypatch):
        """Should return False when user enters 'n'."""
        monkeypatch.setenv("NOMIC_AUTO_COMMIT", "0")

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
        )

        with patch("subprocess.run"):  # Mock git diff --stat
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="n"):
                    result = phase._get_approval()
                    assert result is False


class TestCommitPhaseGitOperations:
    """Tests for git operations."""

    def test_get_changed_files_success(self, mock_aragora_path):
        """Should return list of changed files."""
        phase = CommitPhase(aragora_path=mock_aragora_path)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "aragora/core.py\naragora/utils.py\n"
            mock_run.return_value = mock_result

            files = phase._get_changed_files()

            assert files == ["aragora/core.py", "aragora/utils.py"]

    def test_get_changed_files_empty(self, mock_aragora_path):
        """Should return empty list when no changes."""
        phase = CommitPhase(aragora_path=mock_aragora_path)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            files = phase._get_changed_files()

            assert files == []

    def test_get_changed_files_git_error(self, mock_aragora_path, mock_log_fn):
        """Should return empty list on git error."""
        phase = CommitPhase(aragora_path=mock_aragora_path, log_fn=mock_log_fn)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 128
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            files = phase._get_changed_files()

            assert files == []

    def test_get_changed_files_exception(self, mock_aragora_path, mock_log_fn):
        """Should return empty list on exception."""
        phase = CommitPhase(aragora_path=mock_aragora_path, log_fn=mock_log_fn)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Git failed")

            files = phase._get_changed_files()

            assert files == []


class TestCommitResult:
    """Tests for CommitResult TypedDict."""

    def test_commit_result_success(self):
        """Should create CommitResult with success values."""
        result = CommitResult(
            success=True,
            data={"message": "feat: add feature"},
            duration_seconds=1.5,
            commit_hash="abc1234",
            committed=True,
        )

        assert result["success"] is True
        assert result["commit_hash"] == "abc1234"
        assert result["committed"] is True
        assert result["duration_seconds"] == 1.5

    def test_commit_result_failure(self):
        """Should create CommitResult with failure values."""
        result = CommitResult(
            success=False,
            data={"reason": "Human declined"},
            duration_seconds=0.5,
            commit_hash=None,
            committed=False,
        )

        assert result["success"] is False
        assert result["commit_hash"] is None
        assert result["committed"] is False

    def test_commit_result_with_error(self):
        """Should support error field."""
        result = CommitResult(
            success=False,
            error="Git command failed",
            data={},
            duration_seconds=0.1,
            commit_hash=None,
            committed=False,
        )

        assert result["error"] == "Git command failed"

    def test_commit_result_is_dict(self):
        """CommitResult should be usable as a regular dict."""
        result = CommitResult(
            success=True,
            data={},
            duration_seconds=1.0,
            commit_hash="xyz",
            committed=True,
        )
        assert isinstance(result, dict)
        assert "success" in result


class TestCommitPhaseIntegration:
    """Integration tests for commit phase."""

    @pytest.mark.asyncio
    async def test_full_commit_flow_success(
        self, mock_aragora_path, mock_log_fn, mock_stream_emit_fn
    ):
        """Should complete full commit flow successfully."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
            stream_emit_fn=mock_stream_emit_fn,
        )

        with patch("subprocess.run") as mock_run:
            # Mock all git commands
            mock_add = MagicMock()
            mock_add.returncode = 0
            mock_commit = MagicMock()
            mock_commit.returncode = 0
            mock_commit.stdout = ""
            mock_commit.stderr = ""
            mock_rev_parse = MagicMock()
            mock_rev_parse.returncode = 0
            mock_rev_parse.stdout = "abc1234"
            mock_stat = MagicMock()
            mock_stat.returncode = 0
            mock_stat.stdout = "file1.py | 10 +++++++---\nfile2.py | 5 ++---"

            mock_run.side_effect = [mock_add, mock_commit, mock_rev_parse, mock_stat]

            result = await phase.execute("Add new feature")

            assert result["success"] is True
            assert result["committed"] is True
            assert result["commit_hash"] == "abc1234"
            assert "duration_seconds" in result

    @pytest.mark.asyncio
    async def test_commit_flow_with_human_decline(self, mock_aragora_path, mock_log_fn):
        """Should handle human declining commit."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
            log_fn=mock_log_fn,
        )

        with patch.object(phase, "_get_approval", return_value=False):
            with patch.object(phase, "_get_changed_files", return_value=[]):
                result = await phase.execute("Test improvement")

                assert result["success"] is False
                assert result["committed"] is False
                assert result["data"]["reason"] == "Human declined"

    @pytest.mark.asyncio
    async def test_commit_message_formatting(self, mock_aragora_path):
        """Should format commit message correctly."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
        )

        commit_message = None

        def capture_commit(*args, **kwargs):
            nonlocal commit_message
            if args[0][1] == "commit":
                commit_message = args[0][3]  # -m argument
            result = MagicMock()
            result.returncode = 0
            result.stdout = "abc123" if args[0][1] == "rev-parse" else ""
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=capture_commit):
            await phase.execute("Implement feature X with improvements")

        assert commit_message is not None
        assert "feat(nomic):" in commit_message
        assert "Implement feature X with improvements" in commit_message
        assert "Auto-generated by aragora nomic loop" in commit_message

    @pytest.mark.asyncio
    async def test_multiline_improvement_flattened(self, mock_aragora_path):
        """Should flatten multiline improvement descriptions."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
        )

        commit_message = None

        def capture_commit(*args, **kwargs):
            nonlocal commit_message
            if args[0][1] == "commit":
                commit_message = args[0][3]
            result = MagicMock()
            result.returncode = 0
            result.stdout = "abc" if args[0][1] == "rev-parse" else ""
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=capture_commit):
            await phase.execute("Line one\nLine two\nLine three")

        assert commit_message is not None
        # Newlines should be replaced with spaces in the summary line
        assert "\n" not in commit_message.split("\n")[0]


class TestCommitPhaseGateError:
    """Tests for gate error handling."""

    @pytest.mark.asyncio
    async def test_gate_error_falls_back_to_legacy(self, mock_aragora_path, mock_log_fn):
        """Should fall back to legacy approval when gate errors."""
        gate = MagicMock()
        gate.require_approval = AsyncMock(side_effect=RuntimeError("Gate unavailable"))

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=True,
            auto_commit=False,
            log_fn=mock_log_fn,
            commit_gate=gate,
        )

        # Since gate failed, it should fall back to legacy approval
        with patch.object(phase, "_get_changed_files", return_value=[]):
            with patch("subprocess.run"):  # For gate diff
                with patch.object(phase, "_get_approval", return_value=True):
                    with patch("subprocess.run") as mock_run:
                        mock_add = MagicMock()
                        mock_add.returncode = 0
                        mock_commit = MagicMock()
                        mock_commit.returncode = 0
                        mock_commit.stdout = ""
                        mock_commit.stderr = ""
                        mock_rev_parse = MagicMock()
                        mock_rev_parse.returncode = 0
                        mock_rev_parse.stdout = "xyz"
                        mock_stat = MagicMock()
                        mock_stat.returncode = 0
                        mock_stat.stdout = ""

                        mock_run.side_effect = [mock_add, mock_commit, mock_rev_parse, mock_stat]

                        result = await phase.execute("Test")

                        # Should still succeed via legacy path
                        assert result["success"] is True


class TestCommitKMPersistence:
    """Tests for Knowledge Mound persistence from CommitPhase (Gap 5)."""

    def _make_subprocess_mocks(self, commit_hash: str = "abc1234"):
        """Create standard subprocess mock side effects for a successful commit."""
        mock_add = MagicMock()
        mock_add.returncode = 0
        mock_commit = MagicMock()
        mock_commit.returncode = 0
        mock_commit.stdout = ""
        mock_commit.stderr = ""
        mock_rev_parse = MagicMock()
        mock_rev_parse.returncode = 0
        mock_rev_parse.stdout = commit_hash
        mock_stat = MagicMock()
        mock_stat.returncode = 0
        mock_stat.stdout = "file.py | 5 +++--"
        return [mock_add, mock_commit, mock_rev_parse, mock_stat]

    def _make_cycle_outcome(self):
        """Create a mock cycle outcome with required attributes."""
        outcome = MagicMock()
        outcome.metadata = {}
        outcome.completed_at = None
        return outcome

    @pytest.mark.asyncio
    async def test_commit_persists_to_km(self, mock_aragora_path, mock_log_fn):
        """Should call ingest_cycle_outcome on the KM adapter after commit."""
        outcome = self._make_cycle_outcome()
        mock_adapter = MagicMock()
        mock_ingest_result = MagicMock()
        mock_ingest_result.items_ingested = 3
        mock_ingest_result.cycle_id = "cycle-001"
        mock_adapter.ingest_cycle_outcome = AsyncMock(return_value=mock_ingest_result)

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
            cycle_outcome=outcome,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._make_subprocess_mocks()

            with patch(
                "aragora.nomic.phases.commit.CommitPhase._persist_to_km",
                wraps=phase._persist_to_km,
            ):
                with patch(
                    "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                    return_value=mock_adapter,
                ):
                    result = await phase.execute("Test improvement")

        assert result["success"] is True
        assert result["committed"] is True
        mock_adapter.ingest_cycle_outcome.assert_called_once_with(outcome)

    @pytest.mark.asyncio
    async def test_commit_sets_commit_hash_in_metadata(self, mock_aragora_path, mock_log_fn):
        """Should set commit_hash in cycle_outcome.metadata before persisting."""
        outcome = self._make_cycle_outcome()
        mock_adapter = MagicMock()
        mock_ingest_result = MagicMock()
        mock_ingest_result.items_ingested = 1
        mock_ingest_result.cycle_id = "cycle-002"
        mock_adapter.ingest_cycle_outcome = AsyncMock(return_value=mock_ingest_result)

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
            cycle_outcome=outcome,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._make_subprocess_mocks("def5678")

            with patch(
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                return_value=mock_adapter,
            ):
                result = await phase.execute("Set hash test")

        assert result["success"] is True
        assert outcome.metadata["commit_hash"] == "def5678"

    @pytest.mark.asyncio
    async def test_commit_km_failure_non_fatal(self, mock_aragora_path, mock_log_fn):
        """KM persistence failure should not prevent commit from succeeding."""
        outcome = self._make_cycle_outcome()
        mock_adapter = MagicMock()
        mock_adapter.ingest_cycle_outcome = AsyncMock(
            side_effect=RuntimeError("KM store unavailable")
        )

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
            cycle_outcome=outcome,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._make_subprocess_mocks()

            with patch(
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                return_value=mock_adapter,
            ):
                result = await phase.execute("KM failure test")

        assert result["success"] is True
        assert result["committed"] is True
        assert result["commit_hash"] == "abc1234"

    @pytest.mark.asyncio
    async def test_commit_km_import_error_graceful(self, mock_aragora_path, mock_log_fn):
        """ImportError from KM adapter should be logged, not raised."""
        outcome = self._make_cycle_outcome()

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
            cycle_outcome=outcome,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._make_subprocess_mocks()

            with patch(
                "builtins.__import__",
                side_effect=lambda name, *args, **kwargs: (
                    (_ for _ in ()).throw(ImportError("no nomic_cycle_adapter"))
                    if "nomic_cycle_adapter" in name
                    else __builtins__.__import__(name, *args, **kwargs)
                    if hasattr(__builtins__, "__import__")
                    else __import__(name, *args, **kwargs)
                ),
            ):
                result = await phase.execute("Import error test")

        assert result["success"] is True
        assert result["committed"] is True
        # Verify the log captured the import error message
        log_messages = " ".join(str(c) for c in mock_log_fn.call_args_list)
        assert "KM adapter not available" in log_messages

    @pytest.mark.asyncio
    async def test_commit_without_outcome_skips_km(self, mock_aragora_path, mock_log_fn):
        """When cycle_outcome is None, KM persistence should be skipped entirely."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
            cycle_outcome=None,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._make_subprocess_mocks()

            with patch("aragora.nomic.phases.commit.CommitPhase._persist_to_km") as mock_persist:
                result = await phase.execute("No outcome test")

        assert result["success"] is True
        assert result["committed"] is True
        mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_to_km_without_outcome_is_noop(self, mock_aragora_path, mock_log_fn):
        """Calling _persist_to_km with no cycle_outcome returns before touching KM."""
        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            log_fn=mock_log_fn,
            cycle_outcome=None,
        )

        with patch(
            "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter"
        ) as mock_get_adapter:
            await phase._persist_to_km("abc1234")

        mock_get_adapter.assert_not_called()
        mock_log_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_commit_sets_completed_at(self, mock_aragora_path, mock_log_fn):
        """Should set completed_at on cycle_outcome before persisting if not already set."""
        outcome = self._make_cycle_outcome()
        assert outcome.completed_at is None

        mock_adapter = MagicMock()
        mock_ingest_result = MagicMock()
        mock_ingest_result.items_ingested = 1
        mock_ingest_result.cycle_id = "cycle-003"
        mock_adapter.ingest_cycle_outcome = AsyncMock(return_value=mock_ingest_result)

        phase = CommitPhase(
            aragora_path=mock_aragora_path,
            require_human_approval=False,
            auto_commit=True,
            log_fn=mock_log_fn,
            cycle_outcome=outcome,
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._make_subprocess_mocks()

            with patch(
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter.get_nomic_cycle_adapter",
                return_value=mock_adapter,
            ):
                result = await phase.execute("Completed at test")

        assert result["success"] is True
        assert outcome.completed_at is not None
        # Verify it was set to a UTC datetime
        from datetime import timezone

        assert outcome.completed_at.tzinfo == timezone.utc

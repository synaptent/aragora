"""
Extended tests for Incremental Consensus Checkpointing.

Tests cover gaps not in test_debate_checkpoint.py:
- Advanced path security (URL-encoded, null bytes, symlinks)
- Corruption handling (bad gzip, truncated, missing fields)
- Resume flow (multiple resumes, status transitions)
- Cleanup lifecycle (concurrent, expiry)
- S3CheckpointStore (boto3 mocking)
- GitCheckpointStore (subprocess mocking)
- Webhook URL posting
"""

import asyncio
import gzip
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

import pytest

from aragora.debate.checkpoint import (
    AgentState,
    CheckpointConfig,
    CheckpointManager,
    CheckpointStatus,
    CheckpointWebhook,
    DatabaseCheckpointStore,
    DebateCheckpoint,
    FileCheckpointStore,
    GitCheckpointStore,
    ResumedDebate,
    S3CheckpointStore,
    SAFE_CHECKPOINT_ID,
)
from aragora.core import Message, Vote


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_checkpoint_dir(tmp_path):
    """Create a temporary directory for checkpoints."""
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    return checkpoint_dir


@pytest.fixture
def sample_checkpoint():
    """Create a sample checkpoint for testing."""
    return DebateCheckpoint(
        checkpoint_id="cp-test-001-abc",
        debate_id="debate-123",
        task="Test debate task",
        current_round=3,
        total_rounds=5,
        phase="critique",
        messages=[
            {
                "agent": "claude",
                "content": "Hello",
                "role": "assistant",
                "round": 1,
                "timestamp": "2026-01-06T12:00:00",
            }
        ],
        critiques=[],
        votes=[
            {
                "agent": "claude",
                "choice": "A",
                "confidence": 0.8,
                "reasoning": "Good",
                "continue_debate": True,
            }
        ],
        agent_states=[
            AgentState(
                agent_name="claude",
                agent_model="claude-3-opus",
                agent_role="proposer",
                system_prompt="Be helpful",
                stance="pro",
            )
        ],
    )


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    agent = Mock()
    agent.name = "claude"
    agent.model = "claude-3-opus"
    agent.role = "proposer"
    agent.system_prompt = "Be helpful"
    agent.stance = "neutral"
    return agent


# =============================================================================
# Path Security Tests (Extended)
# =============================================================================


class TestPathSecurityExtended:
    """Extended path security tests for FileCheckpointStore."""

    @pytest.fixture
    def store(self, temp_checkpoint_dir):
        return FileCheckpointStore(base_dir=str(temp_checkpoint_dir), compress=False)

    def test_url_encoded_path_traversal(self, store):
        """URL-encoded path traversal should be sanitized."""
        malicious_ids = [
            "%2e%2e%2f%2e%2e%2fetc/passwd",  # ../
            "%2e%2e%5c%2e%2e%5cwindows",  # ..\
            "..%252f..%252fetc%252fpasswd",  # Double encoded
            "checkpoint%00.json",  # Null byte
        ]
        for malicious_id in malicious_ids:
            sanitized = store._sanitize_checkpoint_id(malicious_id)
            assert ".." not in sanitized
            assert "/" not in sanitized
            assert "\\" not in sanitized
            assert "\x00" not in sanitized

    def test_null_byte_injection(self, store):
        """Null byte injection should be sanitized."""
        malicious = "checkpoint\x00.json"
        sanitized = store._sanitize_checkpoint_id(malicious)
        assert "\x00" not in sanitized

    def test_double_dot_variations(self, store):
        """Various double-dot patterns should be sanitized."""
        variations = [
            "....//....//etc/passwd",
            "..../..../etc/passwd",
            "..%c0%af..%c0%afetc/passwd",  # UTF-8 overlong encoding
            "..%252f..%252f",
        ]
        for v in variations:
            sanitized = store._sanitize_checkpoint_id(v)
            path = store._get_path(sanitized)
            assert path.resolve().is_relative_to(store.base_dir)

    def test_windows_style_paths(self, store):
        """Windows-style path separators should be sanitized."""
        windows_paths = [
            "..\\..\\..\\windows\\system32",
            "checkpoint\\..\\..\\secret",
            "C:\\Windows\\System32",
        ]
        for wp in windows_paths:
            sanitized = store._sanitize_checkpoint_id(wp)
            assert "\\" not in sanitized
            assert ":" not in sanitized

    def test_unicode_normalization_attack(self, store):
        """Unicode normalization attacks should be handled."""
        # Various Unicode representations of dots and slashes
        unicode_attacks = [
            "checkpoint\u2024\u2024/etc",  # ONE DOT LEADER
            "checkpoint\uff0e\uff0e/etc",  # FULLWIDTH FULL STOP
        ]
        for ua in unicode_attacks:
            sanitized = store._sanitize_checkpoint_id(ua)
            # Should only contain safe characters after sanitization
            assert all(c.isalnum() or c in "_-" for c in sanitized)

    @pytest.mark.asyncio
    async def test_path_outside_base_dir_rejected(self, store, temp_checkpoint_dir):
        """Paths resolving outside base_dir should be rejected."""
        # This tests the defense-in-depth check in _get_path
        # After sanitization, path should always be within base_dir
        checkpoint = DebateCheckpoint(
            checkpoint_id="safe-id",
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agent_states=[],
        )
        path = await store.save(checkpoint)
        assert str(temp_checkpoint_dir) in path

    def test_special_characters_replaced(self, store):
        """Special shell characters should be replaced."""
        dangerous_chars = [
            "checkpoint;rm -rf /",
            "checkpoint$(whoami)",
            "checkpoint`id`",
            "checkpoint|cat /etc/passwd",
            "checkpoint&& malicious",
        ]
        for dc in dangerous_chars:
            sanitized = store._sanitize_checkpoint_id(dc)
            assert ";" not in sanitized
            assert "$" not in sanitized
            assert "`" not in sanitized
            assert "|" not in sanitized
            assert "&" not in sanitized


# =============================================================================
# Integrity & Corruption Tests
# =============================================================================


class TestCorruptionHandling:
    """Tests for handling corrupted checkpoint data."""

    @pytest.fixture
    def store(self, temp_checkpoint_dir):
        return FileCheckpointStore(base_dir=str(temp_checkpoint_dir), compress=True)

    @pytest.mark.asyncio
    async def test_bad_gzip_file(self, store, temp_checkpoint_dir):
        """Bad gzip file should return None, not crash."""
        # Write invalid gzip data
        bad_path = temp_checkpoint_dir / "bad-checkpoint.json.gz"
        bad_path.write_bytes(b"not valid gzip data")

        loaded = await store.load("bad-checkpoint")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_truncated_gzip_file(self, store, temp_checkpoint_dir, sample_checkpoint):
        """Truncated gzip file should raise EOFError (current behavior).

        Note: The implementation catches BadGzipFile but not EOFError.
        This test documents the current behavior.
        """
        # Save a valid checkpoint first
        await store.save(sample_checkpoint)

        # Truncate the file
        path = store._get_path(sample_checkpoint.checkpoint_id)
        content = path.read_bytes()
        path.write_bytes(content[: len(content) // 2])  # Cut in half

        # Current implementation raises EOFError for truncated gzip
        with pytest.raises(EOFError):
            await store.load(sample_checkpoint.checkpoint_id)

    @pytest.mark.asyncio
    async def test_invalid_json_structure(self, store, temp_checkpoint_dir):
        """Invalid JSON structure should return None."""
        # Write valid gzip with invalid JSON
        path = temp_checkpoint_dir / "invalid-json.json.gz"
        with gzip.open(path, "wt") as f:
            f.write("not valid json {{{")

        loaded = await store.load("invalid-json")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, store, temp_checkpoint_dir):
        """Checkpoint missing required fields should return None."""
        incomplete_data = {
            "checkpoint_id": "incomplete",
            "debate_id": "debate-1",
            # Missing: task, current_round, etc.
        }
        path = temp_checkpoint_dir / "incomplete.json.gz"
        with gzip.open(path, "wt") as f:
            json.dump(incomplete_data, f)

        loaded = await store.load("incomplete")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_wrong_data_types_loaded_without_validation(self, store, temp_checkpoint_dir):
        """Wrong data types are loaded without strict validation (current behavior).

        Note: The implementation uses dataclass without type enforcement.
        This test documents that wrong types pass through.
        """
        wrong_types = {
            "checkpoint_id": "wrong-types",
            "debate_id": "debate-1",
            "task": "Test",
            "current_round": "not a number",  # Should be int
            "total_rounds": 5,
            "phase": "proposal",
            "messages": "not a list",  # Should be list
            "critiques": [],
            "votes": [],
            "agent_states": [],
            "status": "complete",
            "created_at": "2026-01-06T12:00:00",
            "checksum": "abc123",
        }
        path = temp_checkpoint_dir / "wrong-types.json.gz"
        with gzip.open(path, "wt") as f:
            json.dump(wrong_types, f)

        # Current behavior: wrong types are accepted without validation
        loaded = await store.load("wrong-types")
        assert loaded is not None
        assert loaded.current_round == "not a number"  # String instead of int

    def test_checksum_mismatch_detection(self, sample_checkpoint):
        """Modified checkpoint should fail integrity check."""
        # Modify data after creation
        sample_checkpoint.messages.append({"agent": "attacker", "content": "injected"})

        # Checksum was computed on original data
        assert sample_checkpoint.verify_integrity() is False

    def test_checksum_computation_deterministic(self, sample_checkpoint):
        """Checksum computation should be deterministic."""
        checksum1 = sample_checkpoint._compute_checksum()
        checksum2 = sample_checkpoint._compute_checksum()
        assert checksum1 == checksum2


# =============================================================================
# Resume Flow Tests
# =============================================================================


class TestResumeFlowExtended:
    """Extended tests for checkpoint resume functionality."""

    @pytest.fixture
    def manager(self, temp_checkpoint_dir):
        store = FileCheckpointStore(base_dir=str(temp_checkpoint_dir), compress=False)
        config = CheckpointConfig(interval_rounds=1, max_checkpoints=10)
        return CheckpointManager(store=store, config=config)

    @pytest.mark.asyncio
    async def test_resume_increments_count(self, manager, mock_agent):
        """Resume should increment resume_count."""
        checkpoint = await manager.create_checkpoint(
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agents=[mock_agent],
        )

        # Resume multiple times
        for i in range(3):
            resumed = await manager.resume_from_checkpoint(checkpoint.checkpoint_id)
            assert resumed is not None

        # Load and check count
        loaded = await manager.store.load(checkpoint.checkpoint_id)
        assert loaded.resume_count == 3

    @pytest.mark.asyncio
    async def test_resume_updates_status(self, manager, mock_agent):
        """Resume should update status to RESUMING."""
        checkpoint = await manager.create_checkpoint(
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agents=[mock_agent],
        )

        await manager.resume_from_checkpoint(checkpoint.checkpoint_id)

        loaded = await manager.store.load(checkpoint.checkpoint_id)
        assert loaded.status == CheckpointStatus.RESUMING

    @pytest.mark.asyncio
    async def test_resume_records_timestamp(self, manager, mock_agent):
        """Resume should record last_resumed_at timestamp."""
        checkpoint = await manager.create_checkpoint(
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agents=[mock_agent],
        )

        before_resume = datetime.now().isoformat()
        await manager.resume_from_checkpoint(checkpoint.checkpoint_id, resumed_by="test-user")

        loaded = await manager.store.load(checkpoint.checkpoint_id)
        assert loaded.last_resumed_at is not None
        assert loaded.resumed_by == "test-user"

    @pytest.mark.asyncio
    async def test_resume_restores_messages_with_timestamps(self, manager, mock_agent):
        """Resume should correctly restore message timestamps."""
        messages = [
            Message(
                role="assistant",
                agent="claude",
                content="Test message",
                timestamp=datetime(2026, 1, 6, 12, 0, 0),
                round=1,
            )
        ]

        checkpoint = await manager.create_checkpoint(
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=messages,
            critiques=[],
            votes=[],
            agents=[mock_agent],
        )

        resumed = await manager.resume_from_checkpoint(checkpoint.checkpoint_id)

        assert resumed is not None
        assert len(resumed.messages) == 1
        assert isinstance(resumed.messages[0].timestamp, datetime)

    @pytest.mark.asyncio
    async def test_resume_restores_votes(self, manager, mock_agent):
        """Resume should correctly restore votes."""
        votes = [
            Vote(
                agent="claude",
                choice="Option A",
                confidence=0.85,
                reasoning="Best approach",
                continue_debate=False,
            )
        ]

        checkpoint = await manager.create_checkpoint(
            debate_id="debate-1",
            task="Test",
            current_round=2,
            total_rounds=5,
            phase="vote",
            messages=[],
            critiques=[],
            votes=votes,
            agents=[mock_agent],
        )

        resumed = await manager.resume_from_checkpoint(checkpoint.checkpoint_id)

        assert resumed is not None
        assert len(resumed.votes) == 1
        assert resumed.votes[0].choice == "Option A"
        assert resumed.votes[0].confidence == 0.85
        assert resumed.votes[0].continue_debate is False

    @pytest.mark.asyncio
    async def test_resume_corrupted_checkpoint_returns_none(self, manager, mock_agent):
        """Resume of corrupted checkpoint should return None."""
        checkpoint = await manager.create_checkpoint(
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agents=[mock_agent],
        )

        # Corrupt the checkpoint by modifying stored data
        loaded = await manager.store.load(checkpoint.checkpoint_id)
        loaded.current_round = 999  # Modify without updating checksum
        # Save corrupted version
        path = manager.store._get_path(checkpoint.checkpoint_id)
        path.write_text(json.dumps(loaded.to_dict()))

        # Resume should detect corruption
        resumed = await manager.resume_from_checkpoint(checkpoint.checkpoint_id)
        assert resumed is None


# =============================================================================
# Cleanup & Lifecycle Tests
# =============================================================================


class TestCleanupLifecycle:
    """Tests for checkpoint cleanup and lifecycle management."""

    @pytest.fixture
    def manager(self, temp_checkpoint_dir):
        store = FileCheckpointStore(base_dir=str(temp_checkpoint_dir), compress=False)
        config = CheckpointConfig(interval_rounds=1, max_checkpoints=3, auto_cleanup=True)
        return CheckpointManager(store=store, config=config)

    @pytest.mark.asyncio
    async def test_cleanup_removes_oldest(self, manager, mock_agent):
        """Cleanup should remove oldest checkpoints beyond limit."""
        # Create 5 checkpoints (limit is 3)
        checkpoint_ids = []
        for i in range(5):
            cp = await manager.create_checkpoint(
                debate_id="debate-1",
                task="Test",
                current_round=i,
                total_rounds=10,
                phase="proposal",
                messages=[],
                critiques=[],
                votes=[],
                agents=[mock_agent],
            )
            checkpoint_ids.append(cp.checkpoint_id)
            await asyncio.sleep(0.01)  # Ensure different timestamps

        # Should only have 3 checkpoints left
        remaining = await manager.store.list_checkpoints(debate_id="debate-1")
        assert len(remaining) <= 3

    @pytest.mark.asyncio
    async def test_cleanup_per_debate(self, manager, mock_agent):
        """Cleanup should be per-debate, not global."""
        # Create checkpoints for two different debates
        for i in range(4):
            await manager.create_checkpoint(
                debate_id="debate-1",
                task="Test 1",
                current_round=i,
                total_rounds=10,
                phase="proposal",
                messages=[],
                critiques=[],
                votes=[],
                agents=[mock_agent],
            )

        for i in range(4):
            await manager.create_checkpoint(
                debate_id="debate-2",
                task="Test 2",
                current_round=i,
                total_rounds=10,
                phase="proposal",
                messages=[],
                critiques=[],
                votes=[],
                agents=[mock_agent],
            )

        debate_1 = await manager.store.list_checkpoints(debate_id="debate-1")
        debate_2 = await manager.store.list_checkpoints(debate_id="debate-2")

        # Each debate should have at most 3 checkpoints
        assert len(debate_1) <= 3
        assert len(debate_2) <= 3

    @pytest.mark.asyncio
    async def test_auto_cleanup_disabled(self, temp_checkpoint_dir, mock_agent):
        """Disabled auto_cleanup should not remove old checkpoints."""
        store = FileCheckpointStore(base_dir=str(temp_checkpoint_dir), compress=False)
        config = CheckpointConfig(interval_rounds=1, max_checkpoints=2, auto_cleanup=False)
        manager = CheckpointManager(store=store, config=config)

        # Create 5 checkpoints
        for i in range(5):
            await manager.create_checkpoint(
                debate_id="debate-1",
                task="Test",
                current_round=i,
                total_rounds=10,
                phase="proposal",
                messages=[],
                critiques=[],
                votes=[],
                agents=[mock_agent],
            )

        # All 5 should still exist
        remaining = await manager.store.list_checkpoints(debate_id="debate-1")
        assert len(remaining) == 5

    @pytest.mark.asyncio
    async def test_expiry_time_set(self, manager, mock_agent):
        """Checkpoint should have expiry time set based on config."""
        checkpoint = await manager.create_checkpoint(
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agents=[mock_agent],
        )

        assert checkpoint.expires_at is not None
        expiry = datetime.fromisoformat(checkpoint.expires_at)
        assert expiry > datetime.now()

    def test_should_checkpoint_time_interval(self, manager):
        """should_checkpoint should trigger on time interval."""
        debate_id = "debate-time"

        # First call should not trigger (no previous checkpoint)
        manager._last_checkpoint_time[debate_id] = datetime.now() - timedelta(seconds=400)

        # Should trigger because interval_seconds (300) has passed
        assert manager.should_checkpoint(debate_id, current_round=1) is True


# =============================================================================
# S3CheckpointStore Tests
# =============================================================================


class TestS3CheckpointStore:
    """Tests for S3CheckpointStore with mocked boto3."""

    @pytest.fixture
    def mock_boto3_client(self):
        """Create a mock boto3 S3 client."""
        client = MagicMock()
        return client

    def test_boto3_import_error(self):
        """Missing boto3 should raise RuntimeError."""
        with patch.dict("sys.modules", {"boto3": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'boto3'")):
                store = S3CheckpointStore(bucket="test-bucket")
                with pytest.raises(RuntimeError, match="boto3 required"):
                    store._get_client()

    @pytest.mark.asyncio
    async def test_save_compresses_and_uploads(self, sample_checkpoint):
        """Save should gzip compress and upload to S3."""
        mock_client = MagicMock()

        with patch("boto3.client", return_value=mock_client):
            store = S3CheckpointStore(bucket="test-bucket", prefix="checkpoints/")

            path = await store.save(sample_checkpoint)

            assert path == f"s3://test-bucket/checkpoints/{sample_checkpoint.checkpoint_id}.json.gz"
            mock_client.put_object.assert_called_once()
            call_kwargs = mock_client.put_object.call_args.kwargs
            assert call_kwargs["Bucket"] == "test-bucket"
            assert call_kwargs["ContentEncoding"] == "gzip"

    @pytest.mark.asyncio
    async def test_load_success(self, sample_checkpoint):
        """Load should decompress and parse checkpoint."""
        mock_client = MagicMock()
        compressed_data = gzip.compress(json.dumps(sample_checkpoint.to_dict()).encode())
        mock_client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=compressed_data))
        }

        with patch("boto3.client", return_value=mock_client):
            store = S3CheckpointStore(bucket="test-bucket")

            loaded = await store.load(sample_checkpoint.checkpoint_id)

            assert loaded is not None
            assert loaded.checkpoint_id == sample_checkpoint.checkpoint_id

    @pytest.mark.asyncio
    async def test_load_corrupted_data(self, sample_checkpoint):
        """Load should handle corrupted S3 data gracefully."""
        mock_client = MagicMock()
        mock_client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"not valid gzip"))
        }

        with patch("boto3.client", return_value=mock_client):
            store = S3CheckpointStore(bucket="test-bucket")

            loaded = await store.load(sample_checkpoint.checkpoint_id)
            assert loaded is None

    @pytest.mark.asyncio
    async def test_load_connection_error(self, sample_checkpoint):
        """Load should handle S3 connection errors gracefully."""
        mock_client = MagicMock()
        mock_client.get_object.side_effect = OSError("Connection refused")

        with patch("boto3.client", return_value=mock_client):
            store = S3CheckpointStore(bucket="test-bucket")

            loaded = await store.load(sample_checkpoint.checkpoint_id)
            assert loaded is None

    @pytest.mark.asyncio
    async def test_list_checkpoints_pagination(self, sample_checkpoint):
        """list_checkpoints should handle S3 pagination."""
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "checkpoints/cp-1.json.gz"}, {"Key": "checkpoints/cp-2.json.gz"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator

        # Mock load to return sample checkpoints
        compressed_data = gzip.compress(json.dumps(sample_checkpoint.to_dict()).encode())
        mock_client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=compressed_data))
        }

        with patch("boto3.client", return_value=mock_client):
            store = S3CheckpointStore(bucket="test-bucket", prefix="checkpoints/")

            checkpoints = await store.list_checkpoints(limit=10)

            mock_client.get_paginator.assert_called_with("list_objects_v2")

    @pytest.mark.asyncio
    async def test_delete_success(self, sample_checkpoint):
        """Delete should remove object from S3."""
        mock_client = MagicMock()

        with patch("boto3.client", return_value=mock_client):
            store = S3CheckpointStore(bucket="test-bucket")

            result = await store.delete(sample_checkpoint.checkpoint_id)

            assert result is True
            mock_client.delete_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_connection_error(self, sample_checkpoint):
        """Delete should handle connection errors gracefully."""
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = OSError("Connection refused")

        with patch("boto3.client", return_value=mock_client):
            store = S3CheckpointStore(bucket="test-bucket")

            result = await store.delete(sample_checkpoint.checkpoint_id)
            assert result is False


# =============================================================================
# GitCheckpointStore Tests
# =============================================================================


class TestGitCheckpointStore:
    """Tests for GitCheckpointStore with mocked subprocess."""

    @pytest.fixture
    def store(self, temp_checkpoint_dir):
        return GitCheckpointStore(repo_path=str(temp_checkpoint_dir))

    @pytest.mark.asyncio
    async def test_run_git_success(self, store):
        """_run_git should return success for valid git command."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"branch-name\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            success, output = await store._run_git(["branch", "--show-current"])

            assert success is True
            assert output == "branch-name"

    @pytest.mark.asyncio
    async def test_run_git_failure(self, store):
        """_run_git should return failure for failed git command."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            success, output = await store._run_git(["checkout", "nonexistent"])

            assert success is False

    @pytest.mark.asyncio
    async def test_run_git_timeout(self, store):
        """_run_git should handle timeout."""
        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            success, output = await store._run_git(["status"])

            assert success is False
            assert "timed out" in output

    @pytest.mark.asyncio
    async def test_run_git_exception(self, store):
        """_run_git should handle exceptions."""
        with patch("asyncio.create_subprocess_exec", side_effect=OSError("Unexpected error")):
            success, output = await store._run_git(["status"])

            assert success is False
            assert "git_os_error" in output

    @pytest.mark.asyncio
    async def test_save_validates_checkpoint_id(self, store):
        """Save should reject invalid checkpoint IDs."""
        invalid_checkpoint = DebateCheckpoint(
            checkpoint_id="../../../etc/passwd",  # Invalid
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agent_states=[],
        )

        with pytest.raises(ValueError, match="Invalid checkpoint ID format"):
            await store.save(invalid_checkpoint)

    @pytest.mark.asyncio
    async def test_save_creates_branch(self, store, sample_checkpoint):
        """Save should create git branch for checkpoint."""
        # Make checkpoint ID valid for git
        sample_checkpoint.checkpoint_id = "cp-test-001"

        with patch.object(store, "_run_git") as mock_git:
            mock_git.return_value = (True, "")

            await store.save(sample_checkpoint)

            # Should have called git commands
            calls = mock_git.call_args_list
            assert any("checkout" in str(c) and "-b" in str(c) for c in calls)
            assert any("commit" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_load_validates_checkpoint_id(self, store):
        """Load should reject invalid checkpoint IDs."""
        loaded = await store.load("../../../etc/passwd")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_from_file(self, store, sample_checkpoint):
        """Load should read from checkpoint file if it exists."""
        # Make checkpoint ID valid for git
        sample_checkpoint.checkpoint_id = "cp-test-001"

        # Write checkpoint to file
        path = store.checkpoint_dir / f"{sample_checkpoint.checkpoint_id}.json"
        path.write_text(json.dumps(sample_checkpoint.to_dict()))

        loaded = await store.load(sample_checkpoint.checkpoint_id)

        assert loaded is not None
        assert loaded.checkpoint_id == sample_checkpoint.checkpoint_id

    @pytest.mark.asyncio
    async def test_delete_removes_branch(self, store):
        """Delete should remove git branch."""
        with patch.object(store, "_run_git") as mock_git:
            mock_git.return_value = (True, "")

            result = await store.delete("cp-test-001")

            assert result is True
            mock_git.assert_called()


# =============================================================================
# Webhook Tests (Extended)
# =============================================================================


class TestWebhookExtended:
    """Extended tests for CheckpointWebhook."""

    @pytest.mark.asyncio
    async def test_webhook_url_posting(self):
        """Webhook should post to URL when configured."""
        webhook = CheckpointWebhook(webhook_url="https://example.com/webhook")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.get_session = MagicMock(return_value=mock_session_ctx)

        with patch(
            "aragora.observability.http_client_pool.get_http_pool",
            return_value=mock_pool,
        ):
            await webhook.emit("on_checkpoint", {"test": "data"})

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[1]["json"]["event"] == "on_checkpoint"

    @pytest.mark.asyncio
    async def test_webhook_url_failure_handled(self):
        """Webhook URL failure should not crash."""
        webhook = CheckpointWebhook(webhook_url="https://example.com/webhook")

        with patch("aiohttp.ClientSession") as MockSession:
            MockSession.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("Connection failed")
            )
            MockSession.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should not raise
            await webhook.emit("on_checkpoint", {"test": "data"})

    @pytest.mark.asyncio
    async def test_multiple_handlers_all_called(self):
        """All handlers for an event should be called."""
        webhook = CheckpointWebhook()
        results = []

        @webhook.on_checkpoint
        def handler1(data):
            results.append("handler1")

        @webhook.on_checkpoint
        def handler2(data):
            results.append("handler2")

        @webhook.on_checkpoint
        async def handler3(data):
            results.append("handler3")

        await webhook.emit("on_checkpoint", {})

        assert len(results) == 3
        assert "handler1" in results
        assert "handler2" in results
        assert "handler3" in results

    @pytest.mark.asyncio
    async def test_intervention_handler(self):
        """on_intervention handler should be called."""
        webhook = CheckpointWebhook()
        called = []

        @webhook.on_intervention
        def handler(data):
            called.append(data)

        await webhook.emit("on_intervention", {"note": "Please review"})

        assert len(called) == 1
        assert called[0]["note"] == "Please review"


# =============================================================================
# Agent State Tests (Extended)
# =============================================================================


class TestAgentStateExtended:
    """Extended tests for AgentState serialization."""

    def test_agent_state_with_complex_memory(self):
        """Agent state should handle complex memory snapshots."""
        complex_memory = {
            "conversation": [{"role": "user", "content": "Hello"}],
            "context": {"topic": "AI", "depth": 3},
            "scores": [0.1, 0.5, 0.9],
        }

        state = AgentState(
            agent_name="claude",
            agent_model="claude-3-opus",
            agent_role="proposer",
            system_prompt="Be helpful",
            stance="neutral",
            memory_snapshot=complex_memory,
        )

        assert state.memory_snapshot["conversation"][0]["content"] == "Hello"
        assert state.memory_snapshot["scores"] == [0.1, 0.5, 0.9]

    def test_agent_state_serialization_roundtrip(self):
        """Agent state should survive to_dict/from_dict roundtrip in checkpoint."""
        state = AgentState(
            agent_name="claude",
            agent_model="claude-3-opus",
            agent_role="proposer",
            system_prompt="Be helpful and concise",
            stance="pro",
            memory_snapshot={"key": "value"},
        )

        checkpoint = DebateCheckpoint(
            checkpoint_id="cp-test",
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agent_states=[state],
        )

        d = checkpoint.to_dict()
        restored = DebateCheckpoint.from_dict(d)

        assert len(restored.agent_states) == 1
        assert restored.agent_states[0].agent_name == "claude"
        assert restored.agent_states[0].system_prompt == "Be helpful and concise"
        assert restored.agent_states[0].memory_snapshot == {"key": "value"}


# =============================================================================
# Compression Tests (Extended)
# =============================================================================


class TestCompressionExtended:
    """Extended tests for checkpoint compression."""

    @pytest.mark.asyncio
    async def test_large_checkpoint_compression(self, temp_checkpoint_dir):
        """Large checkpoint should compress significantly."""
        store = FileCheckpointStore(base_dir=str(temp_checkpoint_dir), compress=True)

        # Create checkpoint with large content
        large_messages = [
            {
                "agent": "claude",
                "content": "A" * 10000,
                "role": "assistant",
                "round": i,
                "timestamp": "2026-01-06T12:00:00",
            }
            for i in range(100)
        ]

        checkpoint = DebateCheckpoint(
            checkpoint_id="cp-large",
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=large_messages,
            critiques=[],
            votes=[],
            agent_states=[],
        )

        path = await store.save(checkpoint)

        # Compressed file should be much smaller than uncompressed
        file_size = Path(path).stat().st_size
        uncompressed_size = len(json.dumps(checkpoint.to_dict()))
        compression_ratio = file_size / uncompressed_size

        assert compression_ratio < 0.1  # Should compress to less than 10%

    @pytest.mark.asyncio
    async def test_compression_flag_respected(self, temp_checkpoint_dir):
        """Compress flag should control file extension."""
        compressed_store = FileCheckpointStore(
            base_dir=str(temp_checkpoint_dir / "compressed"), compress=True
        )
        uncompressed_store = FileCheckpointStore(
            base_dir=str(temp_checkpoint_dir / "uncompressed"), compress=False
        )

        checkpoint = DebateCheckpoint(
            checkpoint_id="cp-test",
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agent_states=[],
        )

        compressed_path = await compressed_store.save(checkpoint)
        checkpoint.checkpoint_id = "cp-test-2"  # Different ID
        uncompressed_path = await uncompressed_store.save(checkpoint)

        assert compressed_path.endswith(".json.gz")
        assert uncompressed_path.endswith(".json")


# =============================================================================
# DatabaseCheckpointStore Tests (G2)
# =============================================================================


class TestDatabaseCheckpointStore:
    """Tests for SQLite-based checkpoint storage."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a DatabaseCheckpointStore in a temp directory."""
        db_path = tmp_path / "checkpoints" / "test.db"
        return DatabaseCheckpointStore(db_path=str(db_path), compress=True)

    @pytest.fixture
    def sample_checkpoint(self):
        """Create a sample checkpoint for testing."""
        return DebateCheckpoint(
            checkpoint_id="db-cp-001",
            debate_id="debate-db-test",
            task="Test database checkpoint storage",
            current_round=3,
            total_rounds=5,
            phase="critique",
            messages=[{"role": "agent", "content": "Test message"}],
            critiques=[],
            votes=[],
            agent_states=[],
        )

    @pytest.mark.asyncio
    async def test_save_and_load(self, store, sample_checkpoint):
        """Should save and load checkpoint correctly."""
        path = await store.save(sample_checkpoint)
        assert path.startswith("db:")

        loaded = await store.load(sample_checkpoint.checkpoint_id)
        assert loaded is not None
        assert loaded.checkpoint_id == sample_checkpoint.checkpoint_id
        assert loaded.debate_id == sample_checkpoint.debate_id
        assert loaded.current_round == sample_checkpoint.current_round

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, store):
        """Loading nonexistent checkpoint should return None."""
        loaded = await store.load("nonexistent-checkpoint")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_checkpoints_empty(self, store):
        """List on empty store should return empty list."""
        checkpoints = await store.list_checkpoints()
        assert checkpoints == []

    @pytest.mark.asyncio
    async def test_list_checkpoints_filtered_by_debate(self, store, sample_checkpoint):
        """Should filter checkpoints by debate_id."""
        # Save first checkpoint
        await store.save(sample_checkpoint)

        # Save second checkpoint with different debate_id
        other_checkpoint = DebateCheckpoint(
            checkpoint_id="db-cp-002",
            debate_id="other-debate",
            task="Other task",
            current_round=1,
            total_rounds=3,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agent_states=[],
        )
        await store.save(other_checkpoint)

        # Filter by first debate
        filtered = await store.list_checkpoints(debate_id=sample_checkpoint.debate_id)
        assert len(filtered) == 1
        assert filtered[0]["debate_id"] == sample_checkpoint.debate_id

        # List all
        all_checkpoints = await store.list_checkpoints()
        assert len(all_checkpoints) == 2

    @pytest.mark.asyncio
    async def test_delete(self, store, sample_checkpoint):
        """Should delete checkpoint successfully."""
        await store.save(sample_checkpoint)

        # Verify it exists
        loaded = await store.load(sample_checkpoint.checkpoint_id)
        assert loaded is not None

        # Delete it
        result = await store.delete(sample_checkpoint.checkpoint_id)
        assert result is True

        # Verify it's gone
        loaded = await store.load(sample_checkpoint.checkpoint_id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        """Deleting nonexistent checkpoint should return False."""
        result = await store.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, store):
        """Should cleanup expired checkpoints."""
        # Create checkpoint with past expiry
        expired = DebateCheckpoint(
            checkpoint_id="expired-cp",
            debate_id="debate-1",
            task="Expired task",
            current_round=1,
            total_rounds=3,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agent_states=[],
            expires_at=(datetime.now() - timedelta(hours=1)).isoformat(),
        )
        await store.save(expired)

        # Create checkpoint with future expiry
        valid = DebateCheckpoint(
            checkpoint_id="valid-cp",
            debate_id="debate-2",
            task="Valid task",
            current_round=1,
            total_rounds=3,
            phase="proposal",
            messages=[],
            critiques=[],
            votes=[],
            agent_states=[],
            expires_at=(datetime.now() + timedelta(hours=1)).isoformat(),
        )
        await store.save(valid)

        # Run cleanup
        deleted = await store.cleanup_expired()
        assert deleted == 1

        # Verify expired is gone
        assert await store.load("expired-cp") is None
        # Verify valid remains
        assert await store.load("valid-cp") is not None

    @pytest.mark.asyncio
    async def test_get_stats(self, store, sample_checkpoint):
        """Should return correct statistics."""
        await store.save(sample_checkpoint)

        stats = await store.get_stats()
        assert stats["total_checkpoints"] == 1
        assert stats["unique_debates"] == 1
        assert stats["total_bytes"] > 0

    @pytest.mark.asyncio
    async def test_compression(self, store, sample_checkpoint):
        """Should compress data when enabled."""
        # Add more data to see compression effect
        sample_checkpoint.messages = [{"role": "agent", "content": "A" * 1000} for _ in range(10)]

        await store.save(sample_checkpoint)

        stats = await store.get_stats()
        # Compressed data should be smaller than raw JSON
        raw_size = len(json.dumps(sample_checkpoint.to_dict()))
        assert stats["total_bytes"] < raw_size

    @pytest.mark.asyncio
    async def test_upsert_replaces_existing(self, store, sample_checkpoint):
        """Save should update existing checkpoint."""
        await store.save(sample_checkpoint)

        # Modify and save again
        sample_checkpoint.current_round = 4
        await store.save(sample_checkpoint)

        # Should only have one checkpoint
        checkpoints = await store.list_checkpoints()
        assert len(checkpoints) == 1

        # Should have updated round
        loaded = await store.load(sample_checkpoint.checkpoint_id)
        assert loaded.current_round == 4

    @pytest.mark.asyncio
    async def test_uncompressed_store(self, tmp_path):
        """Should work without compression."""
        db_path = tmp_path / "uncompressed" / "test.db"
        store = DatabaseCheckpointStore(db_path=str(db_path), compress=False)

        checkpoint = DebateCheckpoint(
            checkpoint_id="uncompressed-cp",
            debate_id="debate-1",
            task="Test",
            current_round=1,
            total_rounds=3,
            phase="proposal",
            messages=[{"role": "test", "content": "data"}],
            critiques=[],
            votes=[],
            agent_states=[],
        )

        await store.save(checkpoint)
        loaded = await store.load("uncompressed-cp")

        assert loaded is not None
        assert loaded.messages == checkpoint.messages


# =============================================================================
# Connection Pooling Tests (Phase 10F)
# =============================================================================


class TestDatabaseCheckpointStorePooling:
    """Tests for connection pooling in DatabaseCheckpointStore (Phase 10F)."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a DatabaseCheckpointStore with custom pool size."""
        db_path = tmp_path / "pooled" / "test.db"
        return DatabaseCheckpointStore(db_path=str(db_path), compress=True, pool_size=3)

    @pytest.fixture
    def sample_checkpoint(self):
        """Create a sample checkpoint for testing."""
        return DebateCheckpoint(
            checkpoint_id="pool-cp-001",
            debate_id="debate-pool-test",
            task="Test connection pooling",
            current_round=1,
            total_rounds=5,
            phase="proposal",
            messages=[{"role": "agent", "content": "Test"}],
            critiques=[],
            votes=[],
            agent_states=[],
        )

    def test_pool_initialization(self, store):
        """Pool stats should report managed_by_sqlitestore after migration."""
        stats = store.get_pool_stats()
        assert stats["available_connections"] == "managed_by_sqlitestore"
        assert stats["max_pool_size"] == 3

    @pytest.mark.asyncio
    async def test_connection_returned_to_pool(self, store, sample_checkpoint):
        """Connections should be managed by SQLiteStore after operations."""
        await store.save(sample_checkpoint)

        stats = store.get_pool_stats()
        # Connections are now managed by SQLiteStore context manager
        assert stats["available_connections"] == "managed_by_sqlitestore"

    @pytest.mark.asyncio
    async def test_connection_reused_from_pool(self, store, sample_checkpoint):
        """Multiple operations should work via SQLiteStore connection management."""
        await store.save(sample_checkpoint)

        # Load should work using SQLiteStore connection management
        loaded = await store.load(sample_checkpoint.checkpoint_id)
        assert loaded is not None
        assert loaded.checkpoint_id == sample_checkpoint.checkpoint_id

    @pytest.mark.asyncio
    async def test_pool_size_limit(self, store, sample_checkpoint):
        """Pool size parameter should be stored for backward compatibility."""
        # _pool_size is kept for API compatibility but actual pooling
        # is handled by SQLiteStore
        assert store._pool_size == 3

        # Operations should still work correctly
        await store.save(sample_checkpoint)
        loaded = await store.load(sample_checkpoint.checkpoint_id)
        assert loaded is not None

    def test_close_pool(self, store):
        """Pool stats should reflect SQLiteStore management."""
        stats = store.get_pool_stats()
        assert stats["available_connections"] == "managed_by_sqlitestore"
        assert "db_path" in stats

    @pytest.mark.asyncio
    async def test_stats_include_pool_info(self, store, sample_checkpoint):
        """get_stats should include pool statistics."""
        await store.save(sample_checkpoint)

        stats = await store.get_stats()
        assert "pool" in stats
        assert "available_connections" in stats["pool"]
        assert "max_pool_size" in stats["pool"]

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, store):
        """SQLiteStore should handle concurrent operations safely."""
        import asyncio

        checkpoints = []
        for i in range(10):
            cp = DebateCheckpoint(
                checkpoint_id=f"concurrent-cp-{i:03d}",
                debate_id="debate-concurrent",
                task=f"Concurrent test {i}",
                current_round=i,
                total_rounds=10,
                phase="proposal",
                messages=[{"role": "test", "content": f"Message {i}"}],
                critiques=[],
                votes=[],
                agent_states=[],
            )
            checkpoints.append(cp)

        # Save all concurrently
        await asyncio.gather(*[store.save(cp) for cp in checkpoints])

        # Verify all saved
        all_cps = await store.list_checkpoints(debate_id="debate-concurrent")
        assert len(all_cps) == 10

        # Pool stats should report managed_by_sqlitestore
        stats = store.get_pool_stats()
        assert stats["available_connections"] == "managed_by_sqlitestore"

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, store, sample_checkpoint):
        """WAL mode should be enabled for better concurrency."""
        await store.save(sample_checkpoint)

        # Check WAL mode via SQLiteStore's connection context manager
        with store._db.connection() as conn:
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0].lower()
            assert mode == "wal"

    @pytest.mark.asyncio
    async def test_default_pool_size(self, tmp_path):
        """Default pool size should be 5."""
        db_path = tmp_path / "default" / "test.db"
        store = DatabaseCheckpointStore(db_path=str(db_path))

        assert store._pool_size == 5

    @pytest.mark.asyncio
    async def test_custom_pool_size(self, tmp_path):
        """Custom pool size should be respected."""
        db_path = tmp_path / "custom" / "test.db"
        store = DatabaseCheckpointStore(db_path=str(db_path), pool_size=10)

        assert store._pool_size == 10
        assert store.get_pool_stats()["max_pool_size"] == 10

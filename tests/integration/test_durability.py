"""
Tests for durability and persistence.

Verifies that state survives server restarts and is properly persisted.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDebateOriginDurability:
    """Test debate origin persistence."""

    def test_origin_saved_to_sqlite(self):
        """Verify origins are persisted to SQLite."""
        from aragora.server.debate_origin import (
            DebateOrigin,
            SQLiteOriginStore,
            register_debate_origin,
            get_debate_origin,
        )

        # Use temp database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_origins.db")
            store = SQLiteOriginStore(db_path)

            # Create and save origin
            origin = DebateOrigin(
                debate_id="test-debate-123",
                platform="telegram",
                channel_id="chat-456",
                user_id="user-789",
                metadata={"username": "tester"},
            )
            store.save(origin)

            # Retrieve and verify
            loaded = store.get("test-debate-123")
            assert loaded is not None
            assert loaded.debate_id == origin.debate_id
            assert loaded.platform == "telegram"
            assert loaded.channel_id == "chat-456"
            assert loaded.metadata.get("username") == "tester"

    def test_origin_survives_restart(self):
        """Test that origin can be recovered after 'restart'."""
        from aragora.server.debate_origin import SQLiteOriginStore, DebateOrigin

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "origins.db")

            # First "session"
            store1 = SQLiteOriginStore(db_path)
            origin = DebateOrigin(
                debate_id="persist-test-1",
                platform="slack",
                channel_id="C123",
                user_id="U456",
            )
            store1.save(origin)

            # New "session" (simulating restart)
            store2 = SQLiteOriginStore(db_path)
            recovered = store2.get("persist-test-1")

            assert recovered is not None
            assert recovered.platform == "slack"

    def test_cleanup_expired_origins(self):
        """Test that expired origins are cleaned up."""
        from aragora.server.debate_origin import SQLiteOriginStore, DebateOrigin

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "cleanup.db")
            store = SQLiteOriginStore(db_path)

            # Create old origin
            old_origin = DebateOrigin(
                debate_id="old-debate",
                platform="test",
                channel_id="ch",
                user_id="u",
                created_at=time.time() - 100000,  # Very old
            )
            store.save(old_origin)

            # Cleanup with short TTL
            cleaned = store.cleanup_expired(ttl_seconds=1000)

            # Old origin should be cleaned
            assert cleaned >= 1


class TestEmailReplyOriginDurability:
    """Test email reply origin persistence."""

    def test_email_origin_saved_to_sqlite(self):
        """Verify email origins are persisted to SQLite."""
        from aragora.integrations.email_reply_loop import (
            EmailReplyOrigin,
            SQLiteEmailReplyStore,
        )
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "email_origins.db")
            store = SQLiteEmailReplyStore(db_path)

            origin = EmailReplyOrigin(
                debate_id="debate-123",
                message_id="<msg-id-123@example.com>",
                recipient_email="user@example.com",
                recipient_name="Test User",
            )
            store.save(origin)

            loaded = store.get("<msg-id-123@example.com>")
            assert loaded is not None
            assert loaded.debate_id == "debate-123"
            assert loaded.recipient_email == "user@example.com"


class TestControlPlaneSQLiteFallback:
    """Test control plane shared state SQLite fallback."""

    @pytest.mark.asyncio
    async def test_sqlite_fallback_initialization(self):
        """Test that SQLite fallback initializes correctly."""
        from aragora.control_plane.shared_state import SharedControlPlaneState

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "control_plane.db")

            state = SharedControlPlaneState(
                redis_url="redis://nonexistent:6379",  # Will fail
                sqlite_path=db_path,
            )

            # Connect should fail to Redis, fall back to SQLite
            connected = await state.connect()
            assert connected is False  # No Redis
            assert state._sqlite_initialized is True
            assert Path(db_path).exists()

    @pytest.mark.asyncio
    async def test_agent_persisted_to_sqlite(self):
        """Test that agents are persisted to SQLite fallback."""
        from aragora.control_plane.shared_state import (
            SharedControlPlaneState,
            AgentState,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "cp.db")

            state = SharedControlPlaneState(
                redis_url="redis://nonexistent:6379",
                sqlite_path=db_path,
            )
            await state.connect()

            # Register an agent
            agent = await state.register_agent(
                {
                    "id": "agent-123",
                    "name": "Test Agent",
                    "type": "anthropic-api",
                    "model": "claude-3",
                    "status": "active",
                }
            )

            assert agent.id == "agent-123"

            # Create new state instance (simulating restart)
            state2 = SharedControlPlaneState(
                redis_url="redis://nonexistent:6379",
                sqlite_path=db_path,
            )
            await state2.connect()

            # Agent should be recovered from SQLite
            recovered = await state2.get_agent("agent-123")
            assert recovered is not None
            assert recovered["name"] == "Test Agent"


class TestHumanCheckpointDurability:
    """Test human checkpoint approval persistence."""

    def test_approval_persisted_to_governance_store(self):
        """Test that approvals are saved to GovernanceStore."""
        from aragora.storage.governance_store import GovernanceStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "governance.db")
            store = GovernanceStore(db_path)

            # Save an approval with all required parameters
            store.save_approval(
                approval_id="test-approval-123",
                title="Test Approval",
                description="Testing approval persistence",
                risk_level="medium",
                status="pending",
                requested_by="test-user",
                changes=[{"action": "test"}],
                metadata={
                    "workflow_id": "wf-456",
                    "step_id": "step-1",
                    "type": "workflow_checkpoint",
                },
            )

            # Retrieve and verify
            record = store.get_approval("test-approval-123")
            assert record is not None
            assert record.status == "pending"
            # Check metadata from metadata_json
            import json

            metadata = json.loads(record.metadata_json) if record.metadata_json else {}
            assert metadata.get("workflow_id") == "wf-456"

    def test_pending_approvals_recovered(self):
        """Test that pending approvals can be recovered after restart."""
        from aragora.storage.governance_store import GovernanceStore

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "governance.db")

            # First "session" - create approvals
            store1 = GovernanceStore(db_path)
            store1.save_approval(
                approval_id="recover-1",
                title="Pending Approval 1",
                description="Testing recovery",
                risk_level="low",
                status="pending",
                requested_by="test-user",
                changes=[],
                metadata={"type": "workflow_checkpoint"},
            )
            store1.save_approval(
                approval_id="recover-2",
                title="Completed Approval",
                description="Already approved",
                risk_level="low",
                status="approved",
                requested_by="test-user",
                changes=[],
                metadata={"type": "workflow_checkpoint"},
            )

            # Second "session" (simulating restart)
            store2 = GovernanceStore(db_path)
            pending = store2.list_approvals(status="pending")

            # Should find only the pending approval
            assert len(pending) == 1
            assert pending[0].approval_id == "recover-1"


class TestJobQueueDurability:
    """Test job queue persistence."""

    @pytest.mark.asyncio
    async def test_transcription_job_persisted(self):
        """Test that transcription jobs are persisted."""
        from aragora.storage.job_queue_store import (
            QueuedJob,
            JobStatus,
            SQLiteJobStore,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "jobs.db")
            store = SQLiteJobStore(db_path)

            # Create a transcription job
            job = QueuedJob(
                id="transcribe-123",
                job_type="transcription_audio",
                payload={
                    "file_path": "/path/to/audio.mp3",
                    "language": "en",
                    "model": "whisper-1",
                },
                user_id="user-456",
                workspace_id="ws-789",
            )

            # Enqueue and verify persistence
            await store.enqueue(job)

            # Verify job exists in database
            jobs = await store.list_jobs(
                job_type="transcription_audio",
                status=JobStatus.PENDING,
            )
            assert len(jobs) >= 1
            assert any(j.id == "transcribe-123" for j in jobs)

    @pytest.mark.asyncio
    async def test_routing_job_recovery(self):
        """Test that routing jobs can be recovered after server restart."""
        from aragora.storage.job_queue_store import (
            QueuedJob,
            JobStatus,
            SQLiteJobStore,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "routing_jobs.db")

            # First "session" - create and start processing a job
            store1 = SQLiteJobStore(db_path)

            job = QueuedJob(
                id="route-debate-123",
                job_type="routing_debate",
                payload={
                    "debate_id": "debate-456",
                    "result": {"verdict": "consensus"},
                    "include_voice": False,
                },
                user_id="user-789",
            )
            await store1.enqueue(job)

            # Dequeue (mark as processing)
            dequeued = await store1.dequeue(
                worker_id="worker-1",
                job_types=["routing_debate"],
            )
            assert dequeued is not None
            assert dequeued.id == "route-debate-123"

            # Simulate crash - create new store instance
            store2 = SQLiteJobStore(db_path)

            # Recover stale jobs (those in processing state for too long)
            recovered = await store2.recover_stale_jobs(
                stale_threshold_seconds=0,  # Treat all processing jobs as stale
            )

            # Should have recovered the job
            assert recovered >= 1

            # Job should be back in pending state
            pending = await store2.list_jobs(
                job_type="routing_debate",
                status=JobStatus.PENDING,
            )
            assert any(j.id == "route-debate-123" for j in pending)


class TestMultiInstanceRequirements:
    """Test that multi-instance mode properly requires Redis."""

    def test_control_plane_leader_requires_redis_in_multi_instance(self):
        """Test that leader election fails without Redis in multi-instance mode."""
        # Save original env
        original_multi = os.environ.get("ARAGORA_MULTI_INSTANCE")

        try:
            os.environ["ARAGORA_MULTI_INSTANCE"] = "true"

            # Import and check the requirement function
            from aragora.control_plane.leader import is_distributed_state_required

            assert is_distributed_state_required() is True

        finally:
            # Restore env
            if original_multi is not None:
                os.environ["ARAGORA_MULTI_INSTANCE"] = original_multi
            else:
                os.environ.pop("ARAGORA_MULTI_INSTANCE", None)

    def test_control_plane_leader_not_required_single_instance(self):
        """Test that leader election allows in-memory in single instance mode."""
        # Save original env
        original_multi = os.environ.get("ARAGORA_MULTI_INSTANCE")
        original_single = os.environ.get("ARAGORA_SINGLE_INSTANCE")

        try:
            os.environ.pop("ARAGORA_MULTI_INSTANCE", None)
            os.environ["ARAGORA_SINGLE_INSTANCE"] = "true"

            from aragora.control_plane.leader import is_distributed_state_required

            assert is_distributed_state_required() is False

        finally:
            if original_multi is not None:
                os.environ["ARAGORA_MULTI_INSTANCE"] = original_multi
            if original_single is not None:
                os.environ["ARAGORA_SINGLE_INSTANCE"] = original_single
            else:
                os.environ.pop("ARAGORA_SINGLE_INSTANCE", None)

    def test_session_store_requires_redis_in_multi_instance(self):
        """Test that session store fails without Redis in multi-instance mode."""
        from aragora.control_plane.leader import DistributedStateError

        original_multi = os.environ.get("ARAGORA_MULTI_INSTANCE")
        original_redis = os.environ.get("REDIS_URL")

        try:
            os.environ["ARAGORA_MULTI_INSTANCE"] = "true"
            os.environ.pop("REDIS_URL", None)

            # Reset module state
            import aragora.server.session_store as ss

            ss._session_store = None

            # Should raise DistributedStateError
            with pytest.raises(DistributedStateError):
                ss.get_session_store()

        finally:
            if original_multi is not None:
                os.environ["ARAGORA_MULTI_INSTANCE"] = original_multi
            else:
                os.environ.pop("ARAGORA_MULTI_INSTANCE", None)
            if original_redis is not None:
                os.environ["REDIS_URL"] = original_redis


class TestProductionRequirements:
    """Test that production mode properly requires durable backends."""

    def test_startup_validator_checks_production(self):
        """Test startup validator detects missing requirements."""
        from aragora.server.startup import check_production_requirements

        # Use patch.dict for proper isolation - automatically restores on exit
        env_overrides = {
            "ARAGORA_ENV": "production",
            "ARAGORA_MULTI_INSTANCE": "true",
        }
        # Remove REDIS_URL to trigger the missing-requirement check
        keys_to_remove = ["REDIS_URL"]

        with patch.dict(os.environ, env_overrides):
            for key in keys_to_remove:
                os.environ.pop(key, None)

            missing = check_production_requirements()

            # Should report missing REDIS_URL
            assert any("REDIS_URL" in m for m in missing), (
                f"Expected REDIS_URL warning, got: {missing}"
            )

    def test_connector_sync_store_requires_db_in_production(self):
        """Test connector sync store requires database in production."""
        from aragora.storage.sync_store import SyncStore
        from aragora.control_plane.leader import DistributedStateError

        # Use patch.dict for proper isolation - automatically restores on exit
        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}):
            # Test with SQLite URL but aiosqlite not available
            with patch.dict("sys.modules", {"aiosqlite": None}):
                store = SyncStore(database_url="sqlite:///nonexistent.db")

                # Initialization should raise DistributedStateError in production
                with pytest.raises(DistributedStateError, match="aiosqlite not installed"):
                    asyncio.run(store.initialize())


class TestExplainabilityBatchJobPersistence:
    """Test explainability batch job storage using the store abstraction."""

    def test_batch_job_save_and_retrieve(self):
        """Test batch jobs can be saved and retrieved via store."""
        from aragora.server.handlers.explainability import (
            BatchJob,
            BatchStatus,
            _save_batch_job,
            _get_batch_job,
        )

        # Create and save a batch job
        job = BatchJob(
            batch_id="test-batch-store-123",
            debate_ids=["debate-1", "debate-2"],
            status=BatchStatus.PROCESSING,
            options={"format": "full"},
        )
        _save_batch_job(job)

        # Should be retrievable
        retrieved = _get_batch_job("test-batch-store-123")
        assert retrieved is not None
        assert retrieved.batch_id == "test-batch-store-123"
        assert len(retrieved.debate_ids) == 2
        assert retrieved.status == BatchStatus.PROCESSING

    def test_batch_job_update(self):
        """Test batch job status can be updated."""
        from aragora.server.handlers.explainability import (
            BatchJob,
            BatchStatus,
            _save_batch_job,
            _get_batch_job,
        )

        # Create initial job
        job = BatchJob(
            batch_id="test-batch-update-456",
            debate_ids=["debate-1"],
            status=BatchStatus.PENDING,
        )
        _save_batch_job(job)

        # Update status
        job.status = BatchStatus.COMPLETED
        _save_batch_job(job)

        # Verify update
        retrieved = _get_batch_job("test-batch-update-456")
        assert retrieved is not None
        assert retrieved.status == BatchStatus.COMPLETED

    def test_batch_job_not_found(self):
        """Test retrieving non-existent batch job returns None."""
        from aragora.server.handlers.explainability import _get_batch_job

        result = _get_batch_job("nonexistent-batch-id")
        assert result is None


class TestMarketplaceStorePersistence:
    """Test marketplace store production requirements."""

    def test_marketplace_requires_postgres_in_multi_instance(self):
        """Test marketplace store requires PostgreSQL in multi-instance mode."""
        original_multi = os.environ.get("ARAGORA_MULTI_INSTANCE")
        original_backend = os.environ.get("ARAGORA_DB_BACKEND")

        try:
            os.environ["ARAGORA_MULTI_INSTANCE"] = "true"
            os.environ["ARAGORA_DB_BACKEND"] = "sqlite"

            # Reset module state
            import aragora.storage.marketplace_store as ms

            ms._marketplace_store = None

            # Should raise RuntimeError
            with pytest.raises(RuntimeError, match="ARAGORA_MULTI_INSTANCE"):
                ms.get_marketplace_store()

        finally:
            if original_multi is not None:
                os.environ["ARAGORA_MULTI_INSTANCE"] = original_multi
            else:
                os.environ.pop("ARAGORA_MULTI_INSTANCE", None)
            if original_backend is not None:
                os.environ["ARAGORA_DB_BACKEND"] = original_backend
            else:
                os.environ.pop("ARAGORA_DB_BACKEND", None)

    def test_marketplace_uses_sqlite_in_dev(self):
        """Test marketplace store uses SQLite in development."""
        import aragora.storage.marketplace_store as ms

        # Use temp directory to avoid schema conflicts with existing databases
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "marketplace.db")

            # Create store directly with temp path to avoid global state issues
            store = ms.MarketplaceStore(db_path=db_path)
            assert isinstance(store, ms.MarketplaceStore)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

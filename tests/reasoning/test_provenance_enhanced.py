"""
Tests for aragora/reasoning/provenance_enhanced.py

Comprehensive tests for the enhanced evidence provenance system including:
- Staleness detection for Git and Web sources
- Revalidation triggers
- Living document support
- Provenance validation
"""

import asyncio
import hashlib
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

from aragora.reasoning.provenance_enhanced import (
    StalenessStatus,
    GitSourceInfo,
    WebSourceInfo,
    StalenessCheck,
    RevalidationTrigger,
    GitProvenanceTracker,
    WebProvenanceTracker,
    EnhancedProvenanceManager,
    ProvenanceValidator,
)
from aragora.reasoning.provenance import SourceType


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_git_info():
    """Create sample GitSourceInfo."""
    return GitSourceInfo(
        repo_path="/path/to/repo",
        file_path="src/main.py",
        line_start=10,
        line_end=20,
        commit_sha="abc123def456789012345678901234567890abcd",
        branch="main",
        commit_timestamp="2024-01-15T10:30:00",
        commit_author="Test Author",
        commit_message="Test commit",
    )


@pytest.fixture
def sample_web_info():
    """Create sample WebSourceInfo."""
    return WebSourceInfo(
        url="https://example.com/doc",
        fetch_timestamp="2024-01-15T10:30:00",
        content_hash="abc123def456",
        http_status=200,
        content_type="text/html",
        last_modified="2024-01-14T00:00:00",
        etag='"abc123"',
    )


@pytest.fixture
def sample_staleness_check():
    """Create sample StalenessCheck."""
    return StalenessCheck(
        evidence_id="test-evidence-001",
        status=StalenessStatus.STALE,
        checked_at="2024-01-15T10:30:00",
        reason="Code changed in 3 commits",
        original_hash="abc123",
        current_hash="def456",
        change_summary="2 lines modified",
        commits_behind=3,
        changed_lines=[(15, "new code")],
    )


@pytest.fixture
def mock_git_tracker():
    """Create a mock GitProvenanceTracker."""
    tracker = MagicMock(spec=GitProvenanceTracker)
    tracker.get_current_commit.return_value = "abc123"
    return tracker


@pytest.fixture
def mock_web_tracker():
    """Create a mock WebProvenanceTracker."""
    tracker = MagicMock(spec=WebProvenanceTracker)
    return tracker


# =============================================================================
# Test StalenessStatus Enum
# =============================================================================


class TestStalenessStatus:
    """Tests for StalenessStatus enum."""

    def test_fresh_value(self):
        """Test FRESH enum value."""
        assert StalenessStatus.FRESH.value == "fresh"

    def test_stale_value(self):
        """Test STALE enum value."""
        assert StalenessStatus.STALE.value == "stale"

    def test_unknown_value(self):
        """Test UNKNOWN enum value."""
        assert StalenessStatus.UNKNOWN.value == "unknown"

    def test_error_value(self):
        """Test ERROR enum value."""
        assert StalenessStatus.ERROR.value == "error"

    def test_expired_value(self):
        """Test EXPIRED enum value."""
        assert StalenessStatus.EXPIRED.value == "expired"

    def test_all_values_unique(self):
        """Test all enum values are unique."""
        values = [s.value for s in StalenessStatus]
        assert len(values) == len(set(values))


# =============================================================================
# Test GitSourceInfo Dataclass
# =============================================================================


class TestGitSourceInfo:
    """Tests for GitSourceInfo dataclass."""

    def test_creation_with_required_fields(self):
        """Test creating GitSourceInfo with required fields."""
        info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=10,
            commit_sha="abc123",
        )
        assert info.repo_path == "/repo"
        assert info.file_path == "file.py"
        assert info.line_start == 1
        assert info.line_end == 10
        assert info.commit_sha == "abc123"

    def test_default_branch(self):
        """Test default branch is 'main'."""
        info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=10,
            commit_sha="abc123",
        )
        assert info.branch == "main"

    def test_optional_fields_default_none(self):
        """Test optional fields default to None."""
        info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=10,
            commit_sha="abc123",
        )
        assert info.commit_timestamp is None
        assert info.commit_author is None
        assert info.commit_message is None

    def test_ref_property(self, sample_git_info):
        """Test ref property generates correct reference string."""
        ref = sample_git_info.ref
        assert "src/main.py" in ref
        assert "10-20" in ref
        assert "abc123de" in ref  # First 8 chars of sha

    def test_ref_truncates_sha(self):
        """Test ref truncates SHA to 8 characters."""
        info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=10,
            commit_sha="abcdef1234567890",
        )
        assert "@abcdef12" in info.ref

    def test_to_dict_contains_all_fields(self, sample_git_info):
        """Test to_dict includes all fields."""
        data = sample_git_info.to_dict()
        assert data["repo_path"] == "/path/to/repo"
        assert data["file_path"] == "src/main.py"
        assert data["line_start"] == 10
        assert data["line_end"] == 20
        assert data["commit_sha"] == "abc123def456789012345678901234567890abcd"
        assert data["branch"] == "main"
        assert data["commit_timestamp"] == "2024-01-15T10:30:00"
        assert data["commit_author"] == "Test Author"
        assert data["commit_message"] == "Test commit"
        assert "ref" in data

    def test_to_dict_includes_ref(self, sample_git_info):
        """Test to_dict includes the ref property."""
        data = sample_git_info.to_dict()
        assert data["ref"] == sample_git_info.ref


# =============================================================================
# Test WebSourceInfo Dataclass
# =============================================================================


class TestWebSourceInfo:
    """Tests for WebSourceInfo dataclass."""

    def test_creation_with_required_fields(self):
        """Test creating WebSourceInfo with required fields."""
        info = WebSourceInfo(
            url="https://example.com",
            fetch_timestamp="2024-01-15T10:00:00",
            content_hash="abc123",
        )
        assert info.url == "https://example.com"
        assert info.fetch_timestamp == "2024-01-15T10:00:00"
        assert info.content_hash == "abc123"

    def test_default_http_status(self):
        """Test default http_status is 200."""
        info = WebSourceInfo(
            url="https://example.com",
            fetch_timestamp="2024-01-15T10:00:00",
            content_hash="abc123",
        )
        assert info.http_status == 200

    def test_default_content_type(self):
        """Test default content_type is 'text/html'."""
        info = WebSourceInfo(
            url="https://example.com",
            fetch_timestamp="2024-01-15T10:00:00",
            content_hash="abc123",
        )
        assert info.content_type == "text/html"

    def test_optional_etag(self):
        """Test optional etag field."""
        info = WebSourceInfo(
            url="https://example.com",
            fetch_timestamp="2024-01-15T10:00:00",
            content_hash="abc123",
            etag='"etag-value"',
        )
        assert info.etag == '"etag-value"'

    def test_optional_last_modified(self):
        """Test optional last_modified field."""
        info = WebSourceInfo(
            url="https://example.com",
            fetch_timestamp="2024-01-15T10:00:00",
            content_hash="abc123",
            last_modified="2024-01-14T00:00:00",
        )
        assert info.last_modified == "2024-01-14T00:00:00"

    def test_to_dict_contains_all_fields(self, sample_web_info):
        """Test to_dict includes all fields."""
        data = sample_web_info.to_dict()
        assert data["url"] == "https://example.com/doc"
        assert data["fetch_timestamp"] == "2024-01-15T10:30:00"
        assert data["content_hash"] == "abc123def456"
        assert data["http_status"] == 200
        assert data["content_type"] == "text/html"
        assert data["last_modified"] == "2024-01-14T00:00:00"
        assert data["etag"] == '"abc123"'


# =============================================================================
# Test StalenessCheck Dataclass
# =============================================================================


class TestStalenessCheck:
    """Tests for StalenessCheck dataclass."""

    def test_creation_with_required_fields(self):
        """Test creating StalenessCheck with required fields."""
        check = StalenessCheck(
            evidence_id="test-001",
            status=StalenessStatus.FRESH,
            checked_at="2024-01-15T10:00:00",
            reason="Content unchanged",
        )
        assert check.evidence_id == "test-001"
        assert check.status == StalenessStatus.FRESH
        assert check.checked_at == "2024-01-15T10:00:00"
        assert check.reason == "Content unchanged"

    def test_default_optional_fields(self):
        """Test default values for optional fields."""
        check = StalenessCheck(
            evidence_id="test-001",
            status=StalenessStatus.FRESH,
            checked_at="2024-01-15T10:00:00",
            reason="Content unchanged",
        )
        assert check.original_hash is None
        assert check.current_hash is None
        assert check.change_summary is None
        assert check.commits_behind == 0
        assert check.changed_lines == []

    def test_commits_behind_field(self, sample_staleness_check):
        """Test commits_behind field."""
        assert sample_staleness_check.commits_behind == 3

    def test_changed_lines_field(self, sample_staleness_check):
        """Test changed_lines field."""
        assert len(sample_staleness_check.changed_lines) == 1
        assert sample_staleness_check.changed_lines[0] == (15, "new code")

    def test_to_dict_contains_all_fields(self, sample_staleness_check):
        """Test to_dict includes all fields."""
        data = sample_staleness_check.to_dict()
        assert data["evidence_id"] == "test-evidence-001"
        assert data["status"] == "stale"
        assert data["checked_at"] == "2024-01-15T10:30:00"
        assert data["reason"] == "Code changed in 3 commits"
        assert data["original_hash"] == "abc123"
        assert data["current_hash"] == "def456"
        assert data["change_summary"] == "2 lines modified"
        assert data["commits_behind"] == 3
        assert data["changed_lines"] == [(15, "new code")]

    def test_to_dict_status_is_string(self, sample_staleness_check):
        """Test to_dict converts status enum to string."""
        data = sample_staleness_check.to_dict()
        assert isinstance(data["status"], str)
        assert data["status"] == "stale"


# =============================================================================
# Test RevalidationTrigger Dataclass
# =============================================================================


class TestRevalidationTrigger:
    """Tests for RevalidationTrigger dataclass."""

    def test_creation_with_required_fields(self, sample_staleness_check):
        """Test creating RevalidationTrigger with required fields."""
        trigger = RevalidationTrigger(
            trigger_id="trigger-001",
            claim_id="claim-001",
            evidence_ids=["ev-001", "ev-002"],
            staleness_checks=[sample_staleness_check],
            severity="warning",
            recommendation="Review changes",
        )
        assert trigger.trigger_id == "trigger-001"
        assert trigger.claim_id == "claim-001"
        assert trigger.evidence_ids == ["ev-001", "ev-002"]
        assert len(trigger.staleness_checks) == 1
        assert trigger.severity == "warning"
        assert trigger.recommendation == "Review changes"

    def test_default_created_at(self, sample_staleness_check):
        """Test created_at has default value."""
        trigger = RevalidationTrigger(
            trigger_id="trigger-001",
            claim_id="claim-001",
            evidence_ids=["ev-001"],
            staleness_checks=[sample_staleness_check],
            severity="info",
            recommendation="Review",
        )
        assert trigger.created_at is not None
        # Should be a valid ISO timestamp
        datetime.fromisoformat(trigger.created_at)

    def test_severity_levels(self, sample_staleness_check):
        """Test different severity levels."""
        for severity in ["info", "warning", "critical"]:
            trigger = RevalidationTrigger(
                trigger_id=f"trigger-{severity}",
                claim_id="claim-001",
                evidence_ids=["ev-001"],
                staleness_checks=[sample_staleness_check],
                severity=severity,
                recommendation="Review",
            )
            assert trigger.severity == severity

    def test_to_dict_contains_all_fields(self, sample_staleness_check):
        """Test to_dict includes all fields."""
        trigger = RevalidationTrigger(
            trigger_id="trigger-001",
            claim_id="claim-001",
            evidence_ids=["ev-001", "ev-002"],
            staleness_checks=[sample_staleness_check],
            severity="warning",
            recommendation="Review changes",
        )
        data = trigger.to_dict()
        assert data["trigger_id"] == "trigger-001"
        assert data["claim_id"] == "claim-001"
        assert data["evidence_ids"] == ["ev-001", "ev-002"]
        assert len(data["staleness_checks"]) == 1
        assert data["severity"] == "warning"
        assert data["recommendation"] == "Review changes"
        assert "created_at" in data

    def test_to_dict_serializes_staleness_checks(self, sample_staleness_check):
        """Test to_dict serializes staleness_checks."""
        trigger = RevalidationTrigger(
            trigger_id="trigger-001",
            claim_id="claim-001",
            evidence_ids=["ev-001"],
            staleness_checks=[sample_staleness_check],
            severity="info",
            recommendation="Review",
        )
        data = trigger.to_dict()
        assert isinstance(data["staleness_checks"][0], dict)
        assert data["staleness_checks"][0]["status"] == "stale"


# =============================================================================
# Test GitProvenanceTracker
# =============================================================================


class TestGitProvenanceTracker:
    """Tests for GitProvenanceTracker class."""

    def test_init_default_repo_path(self):
        """Test initialization with default repo path."""
        with patch("os.getcwd", return_value="/current/dir"):
            tracker = GitProvenanceTracker()
            assert tracker.repo_path == "/current/dir"

    def test_init_custom_repo_path(self):
        """Test initialization with custom repo path."""
        tracker = GitProvenanceTracker(repo_path="/custom/repo")
        assert tracker.repo_path == "/custom/repo"

    def test_run_git_success(self):
        """Test _run_git with successful command."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output\n")
            success, output = tracker._run_git(["status"])
            assert success is True
            assert output == "output"

    def test_run_git_failure(self):
        """Test _run_git with failed command."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            success, output = tracker._run_git(["invalid"])
            assert success is False

    def test_run_git_exception(self):
        """Test _run_git handles exceptions."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch("subprocess.run", side_effect=OSError("Command failed")):
            success, output = tracker._run_git(["status"])
            assert success is False
            assert "Command failed" in output

    def test_get_current_commit_success(self):
        """Test get_current_commit returns SHA."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch.object(tracker, "_run_git", return_value=(True, "abc123")):
            commit = tracker.get_current_commit()
            assert commit == "abc123"

    def test_get_current_commit_failure(self):
        """Test get_current_commit returns None on failure."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch.object(tracker, "_run_git", return_value=(False, "")):
            commit = tracker.get_current_commit()
            assert commit is None

    def test_get_file_at_commit_success(self):
        """Test get_file_at_commit returns content."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch.object(tracker, "_run_git", return_value=(True, "file content")):
            content = tracker.get_file_at_commit("file.py", "abc123")
            assert content == "file content"

    def test_get_file_at_commit_failure(self):
        """Test get_file_at_commit returns None on failure."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch.object(tracker, "_run_git", return_value=(False, "")):
            content = tracker.get_file_at_commit("file.py", "abc123")
            assert content is None

    def test_get_blame_parses_output(self):
        """Test get_blame parses porcelain output correctly."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        blame_output = """abc123def456789012345678901234567890abcd 1 1 1
author Test Author
author-time 1234567890
	line content"""

        with patch.object(tracker, "_run_git", return_value=(True, blame_output)):
            blame = tracker.get_blame("file.py", 1, 1)
            assert len(blame) == 1
            assert blame[0]["sha"] == "abc123def456789012345678901234567890abcd"
            assert blame[0]["author"] == "Test Author"
            assert blame[0]["content"] == "line content"

    def test_get_blame_failure(self):
        """Test get_blame returns empty list on failure."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch.object(tracker, "_run_git", return_value=(False, "")):
            blame = tracker.get_blame("file.py", 1, 10)
            assert blame == []

    def test_record_code_evidence(self):
        """Test record_code_evidence creates GitSourceInfo."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch.object(tracker, "get_current_commit", return_value="abc123"):
            with patch.object(tracker, "_run_git") as mock_run:
                # Mock commit info and branch
                mock_run.side_effect = [
                    (True, "abc123|Author|2024-01-15|Commit msg"),
                    (True, "main"),
                ]
                info = tracker.record_code_evidence(
                    file_path="src/main.py",
                    line_start=10,
                    line_end=20,
                    content="test code",
                )
                assert isinstance(info, GitSourceInfo)
                assert info.file_path == "src/main.py"
                assert info.commit_sha == "abc123"
                assert info.commit_author == "Author"
                assert info.branch == "main"

    def test_record_code_evidence_unknown_commit(self):
        """Test record_code_evidence handles unknown commit."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        with patch.object(tracker, "get_current_commit", return_value=None):
            with patch.object(tracker, "_run_git", return_value=(False, "")):
                info = tracker.record_code_evidence(
                    file_path="file.py",
                    line_start=1,
                    line_end=10,
                    content="code",
                )
                assert info.commit_sha == "unknown"

    def test_check_staleness_fresh(self):
        """Test check_staleness returns FRESH when content unchanged."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        source_info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=2,
            commit_sha="abc123",
        )

        file_content = "line1\nline2\nline3"
        with patch.object(tracker, "get_file_at_commit", return_value=file_content):
            with patch.object(tracker, "get_current_commit", return_value="def456"):
                check = tracker.check_staleness(source_info)
                assert check.status == StalenessStatus.FRESH
                assert "unchanged" in check.reason.lower()

    def test_check_staleness_stale(self):
        """Test check_staleness returns STALE when content changed."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        source_info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=2,
            commit_sha="abc123",
        )

        original_content = "line1\nline2\nline3"
        current_content = "modified\nline2\nline3"

        with patch.object(tracker, "get_file_at_commit") as mock_get:
            mock_get.side_effect = [original_content, current_content]
            with patch.object(tracker, "get_current_commit", return_value="def456"):
                with patch.object(tracker, "_run_git", return_value=(True, "5")):
                    check = tracker.check_staleness(source_info)
                    assert check.status == StalenessStatus.STALE
                    assert check.commits_behind == 5

    def test_check_staleness_error_cannot_retrieve(self):
        """Test check_staleness returns ERROR when file not found at commit."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        source_info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=2,
            commit_sha="abc123",
        )

        with patch.object(tracker, "get_file_at_commit", return_value=None):
            check = tracker.check_staleness(source_info)
            assert check.status == StalenessStatus.ERROR

    def test_check_staleness_unknown_file_deleted(self):
        """Test check_staleness returns UNKNOWN when file no longer exists."""
        tracker = GitProvenanceTracker(repo_path="/repo")
        source_info = GitSourceInfo(
            repo_path="/repo",
            file_path="file.py",
            line_start=1,
            line_end=2,
            commit_sha="abc123",
        )

        with patch.object(tracker, "get_file_at_commit") as mock_get:
            mock_get.side_effect = ["original content", None]
            with patch.object(tracker, "get_current_commit", return_value="def456"):
                check = tracker.check_staleness(source_info)
                assert check.status == StalenessStatus.UNKNOWN
                assert "no longer exists" in check.reason.lower()


# =============================================================================
# Test WebProvenanceTracker
# =============================================================================


def _mock_http_pool_response(status_code: int = 200, text: str = ""):
    response = MagicMock(status_code=status_code, text=text)
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=client)
    session_ctx.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.get_session.return_value = session_ctx
    return pool, session_ctx


class TestWebProvenanceTracker:
    """Tests for WebProvenanceTracker class."""

    def test_init_default_cache_dir(self):
        """Test initialization creates default cache directory."""
        with patch.object(Path, "mkdir"):
            tracker = WebProvenanceTracker()
            assert tracker.cache_dir == Path(".web_cache")

    def test_init_custom_cache_dir(self, temp_dir):
        """Test initialization with custom cache directory."""
        cache_path = os.path.join(temp_dir, "custom_cache")
        tracker = WebProvenanceTracker(cache_dir=cache_path)
        assert tracker.cache_dir == Path(cache_path)
        assert tracker.cache_dir.exists()

    @pytest.mark.asyncio
    async def test_record_url_evidence(self):
        """Test record_url_evidence creates WebSourceInfo."""
        with patch.object(Path, "mkdir"):
            tracker = WebProvenanceTracker()
            content = "test content"
            info = await tracker.record_url_evidence(
                url="https://example.com",
                content=content,
            )
            assert isinstance(info, WebSourceInfo)
            assert info.url == "https://example.com"
            assert info.content_hash == hashlib.sha256(content.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_check_staleness_fresh(self):
        """Test check_staleness returns FRESH when content unchanged."""
        with patch.object(Path, "mkdir"):
            tracker = WebProvenanceTracker()
            content = "test content"
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            source_info = WebSourceInfo(
                url="https://example.com",
                fetch_timestamp="2024-01-15T10:00:00",
                content_hash=content_hash,
            )

            mock_pool, _ = _mock_http_pool_response(status_code=200, text=content)

            with patch(
                "aragora.observability.http_client_pool.get_http_pool", return_value=mock_pool
            ):
                check = await tracker.check_staleness(source_info)
                assert check.status == StalenessStatus.FRESH

    @pytest.mark.asyncio
    async def test_check_staleness_stale(self):
        """Test check_staleness returns STALE when content changed."""
        with patch.object(Path, "mkdir"):
            tracker = WebProvenanceTracker()

            source_info = WebSourceInfo(
                url="https://example.com",
                fetch_timestamp="2024-01-15T10:00:00",
                content_hash="original_hash",
            )

            mock_pool, _ = _mock_http_pool_response(status_code=200, text="different content")

            with patch(
                "aragora.observability.http_client_pool.get_http_pool", return_value=mock_pool
            ):
                check = await tracker.check_staleness(source_info)
                assert check.status == StalenessStatus.STALE
                assert "changed" in check.reason.lower()

    @pytest.mark.asyncio
    async def test_check_staleness_http_error(self):
        """Test check_staleness returns ERROR on HTTP error."""
        with patch.object(Path, "mkdir"):
            tracker = WebProvenanceTracker()

            source_info = WebSourceInfo(
                url="https://example.com",
                fetch_timestamp="2024-01-15T10:00:00",
                content_hash="abc123",
            )

            mock_pool, _ = _mock_http_pool_response(status_code=404)

            with patch(
                "aragora.observability.http_client_pool.get_http_pool", return_value=mock_pool
            ):
                check = await tracker.check_staleness(source_info)
                assert check.status == StalenessStatus.ERROR
                assert "404" in check.reason

    @pytest.mark.asyncio
    async def test_check_staleness_import_error(self):
        """Test check_staleness handles HTTP pool unavailability gracefully."""
        with patch.object(Path, "mkdir"):
            tracker = WebProvenanceTracker()

            source_info = WebSourceInfo(
                url="https://example.com",
                fetch_timestamp="2024-01-15T10:00:00",
                content_hash="abc123",
            )

            with patch(
                "aragora.observability.http_client_pool.get_http_pool",
                side_effect=ImportError("http pool not available"),
            ):
                check = await tracker.check_staleness(source_info)
                assert check.status == StalenessStatus.UNKNOWN
                assert "http pool not available" in check.reason

    @pytest.mark.asyncio
    async def test_check_staleness_network_exception(self):
        """Test check_staleness handles network exceptions."""
        with patch.object(Path, "mkdir"):
            tracker = WebProvenanceTracker()

            source_info = WebSourceInfo(
                url="https://example.com",
                fetch_timestamp="2024-01-15T10:00:00",
                content_hash="abc123",
            )

            mock_pool, session_ctx = _mock_http_pool_response()
            session_ctx.__aenter__.side_effect = OSError("Network error")

            with patch(
                "aragora.observability.http_client_pool.get_http_pool", return_value=mock_pool
            ):
                check = await tracker.check_staleness(source_info)
                assert check.status == StalenessStatus.ERROR
                assert "Network error" in check.reason


# =============================================================================
# Test EnhancedProvenanceManager
# =============================================================================


class TestEnhancedProvenanceManager:
    """Tests for EnhancedProvenanceManager class."""

    def test_init_creates_trackers(self):
        """Test initialization creates git and web trackers."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            assert isinstance(manager.git_tracker, GitProvenanceTracker)
            assert isinstance(manager.web_tracker, WebProvenanceTracker)

    def test_init_custom_debate_id(self):
        """Test initialization with custom debate_id."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager(debate_id="test-debate")
            assert manager.debate_id == "test-debate"

    def test_init_custom_repo_path(self):
        """Test initialization with custom repo_path."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager(repo_path="/custom/repo")
            assert manager.git_tracker.repo_path == "/custom/repo"

    def test_init_custom_staleness_threshold(self):
        """Test initialization with custom staleness threshold."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager(staleness_threshold_hours=48.0)
            assert manager.staleness_threshold == timedelta(hours=48.0)

    def test_init_empty_state(self):
        """Test initialization starts with empty state."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            assert manager.git_sources == {}
            assert manager.web_sources == {}
            assert manager.staleness_checks == {}
            assert manager.triggers == []

    def test_record_code_evidence(self):
        """Test record_code_evidence creates provenance record."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            git_info = GitSourceInfo(
                repo_path="/repo",
                file_path="file.py",
                line_start=1,
                line_end=10,
                commit_sha="abc123",
            )

            with patch.object(manager.git_tracker, "record_code_evidence", return_value=git_info):
                record = manager.record_code_evidence(
                    file_path="file.py",
                    line_start=1,
                    line_end=10,
                    content="test code",
                )
                assert record is not None
                assert record.id in manager.git_sources

    def test_record_code_evidence_with_claim(self):
        """Test record_code_evidence creates citation when claim_id provided."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            git_info = GitSourceInfo(
                repo_path="/repo",
                file_path="file.py",
                line_start=1,
                line_end=10,
                commit_sha="abc123",
            )

            with patch.object(manager.git_tracker, "record_code_evidence", return_value=git_info):
                record = manager.record_code_evidence(
                    file_path="file.py",
                    line_start=1,
                    line_end=10,
                    content="test code",
                    claim_id="claim-001",
                )
                # Check citation was created
                citations = manager.graph.get_claim_evidence("claim-001")
                assert len(citations) == 1

    @pytest.mark.asyncio
    async def test_record_web_evidence(self):
        """Test record_web_evidence creates provenance record."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()

            record = await manager.record_web_evidence(
                url="https://example.com",
                content="web content",
            )
            assert record is not None
            assert record.id in manager.web_sources

    @pytest.mark.asyncio
    async def test_check_all_staleness(self):
        """Test check_all_staleness checks all sources."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()

            # Add mock sources
            git_info = GitSourceInfo(
                repo_path="/repo",
                file_path="file.py",
                line_start=1,
                line_end=10,
                commit_sha="abc123",
            )
            manager.git_sources["git-001"] = git_info

            web_info = WebSourceInfo(
                url="https://example.com",
                fetch_timestamp="2024-01-15T10:00:00",
                content_hash="abc123",
            )
            manager.web_sources["web-001"] = web_info

            fresh_check = StalenessCheck(
                evidence_id="test",
                status=StalenessStatus.FRESH,
                checked_at=datetime.now().isoformat(),
                reason="Unchanged",
            )

            with patch.object(manager.git_tracker, "check_staleness", return_value=fresh_check):
                with patch.object(
                    manager.web_tracker,
                    "check_staleness",
                    new=AsyncMock(return_value=fresh_check),
                ):
                    checks = await manager.check_all_staleness()
                    assert len(checks) == 2

    def test_generate_recommendation_critical(self):
        """Test _generate_recommendation for critical changes."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            # Need total_changes > 20 for critical
            checks = [
                StalenessCheck(
                    evidence_id="test",
                    status=StalenessStatus.STALE,
                    checked_at=datetime.now().isoformat(),
                    reason="Changed",
                    commits_behind=25,
                )
            ]
            recommendation = manager._generate_recommendation(checks)
            assert "Critical" in recommendation
            assert "re-debate" in recommendation.lower()

    def test_generate_recommendation_warning(self):
        """Test _generate_recommendation for warning level."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            checks = [
                StalenessCheck(
                    evidence_id="test",
                    status=StalenessStatus.STALE,
                    checked_at=datetime.now().isoformat(),
                    reason="Changed",
                    commits_behind=8,
                )
            ]
            recommendation = manager._generate_recommendation(checks)
            assert "Warning" in recommendation

    def test_generate_recommendation_info(self):
        """Test _generate_recommendation for info level."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            checks = [
                StalenessCheck(
                    evidence_id="test",
                    status=StalenessStatus.STALE,
                    checked_at=datetime.now().isoformat(),
                    reason="Changed",
                    commits_behind=2,
                )
            ]
            recommendation = manager._generate_recommendation(checks)
            assert "Info" in recommendation

    def test_get_living_document_status_healthy(self):
        """Test get_living_document_status for healthy state."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            manager.staleness_checks["check-1"] = StalenessCheck(
                evidence_id="test-1",
                status=StalenessStatus.FRESH,
                checked_at=datetime.now().isoformat(),
                reason="Unchanged",
            )
            status = manager.get_living_document_status()
            assert status["overall_status"] == "healthy"
            assert status["freshness_ratio"] == 1.0

    def test_get_living_document_status_stale(self):
        """Test get_living_document_status for stale state."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            # Add mostly stale checks
            for i in range(4):
                manager.staleness_checks[f"check-{i}"] = StalenessCheck(
                    evidence_id=f"test-{i}",
                    status=StalenessStatus.STALE,
                    checked_at=datetime.now().isoformat(),
                    reason="Changed",
                )
            manager.staleness_checks["check-4"] = StalenessCheck(
                evidence_id="test-4",
                status=StalenessStatus.FRESH,
                checked_at=datetime.now().isoformat(),
                reason="Unchanged",
            )
            status = manager.get_living_document_status()
            assert status["overall_status"] == "stale"
            assert status["counts"]["stale"] == 4
            assert status["counts"]["fresh"] == 1

    def test_export_enhanced(self):
        """Test export_enhanced includes all enhanced data."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager(debate_id="test-debate")

            # Add some sources
            git_info = GitSourceInfo(
                repo_path="/repo",
                file_path="file.py",
                line_start=1,
                line_end=10,
                commit_sha="abc123",
            )
            manager.git_sources["git-001"] = git_info

            exported = manager.export_enhanced()
            assert "git_sources" in exported
            assert "web_sources" in exported
            assert "staleness_checks" in exported
            assert "triggers" in exported
            assert "living_document_status" in exported
            assert "git-001" in exported["git_sources"]


# =============================================================================
# Test ProvenanceValidator
# =============================================================================


class TestProvenanceValidator:
    """Tests for ProvenanceValidator class."""

    def test_init(self):
        """Test initialization with manager."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)
            assert validator.manager == manager

    @pytest.mark.asyncio
    async def test_full_validation(self):
        """Test full_validation returns complete results."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager(debate_id="test-debate")
            validator = ProvenanceValidator(manager)

            with patch.object(manager, "check_all_staleness", return_value=[]):
                results = await validator.full_validation()
                assert "validation_time" in results
                assert "debate_id" in results
                assert results["debate_id"] == "test-debate"
                assert "chain_integrity" in results
                assert "evidence_coverage" in results
                assert "circular_dependencies" in results
                assert "staleness" in results
                assert "passed" in results

    def test_validate_chain_valid(self):
        """Test _validate_chain for valid chain."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            # Empty chain is valid
            result = validator._validate_chain()
            assert result["valid"] is True
            assert result["errors"] == []

    def test_validate_coverage_no_claims(self):
        """Test _validate_coverage with no claims."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            result = validator._validate_coverage()
            assert result["total_claims"] == 0
            assert result["ratio"] == 0

    def test_validate_coverage_with_evidence(self):
        """Test _validate_coverage with claims having evidence."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            # Add a claim with evidence
            manager.graph.add_citation(
                claim_id="claim-1",
                evidence_id="evidence-1",
                relevance=1.0,
            )

            result = validator._validate_coverage()
            assert result["total_claims"] == 1
            assert result["claims_with_evidence"] == 1
            assert result["ratio"] == 1.0

    def test_check_circular_no_cycles(self):
        """Test _check_circular with no cycles."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            result = validator._check_circular()
            assert result == []

    @pytest.mark.asyncio
    async def test_check_staleness_empty(self):
        """Test _check_staleness with no sources."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            result = await validator._check_staleness()
            assert result["total_checked"] == 0
            assert result["freshness_ratio"] == 1.0

    @pytest.mark.asyncio
    async def test_check_staleness_with_sources(self):
        """Test _check_staleness with sources."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            fresh_check = StalenessCheck(
                evidence_id="test",
                status=StalenessStatus.FRESH,
                checked_at=datetime.now().isoformat(),
                reason="Unchanged",
            )
            stale_check = StalenessCheck(
                evidence_id="test2",
                status=StalenessStatus.STALE,
                checked_at=datetime.now().isoformat(),
                reason="Changed",
            )

            with patch.object(
                manager, "check_all_staleness", return_value=[fresh_check, stale_check]
            ):
                result = await validator._check_staleness()
                assert result["total_checked"] == 2
                assert result["fresh_count"] == 1
                assert result["stale_count"] == 1
                assert result["freshness_ratio"] == 0.5

    @pytest.mark.asyncio
    async def test_full_validation_passes(self):
        """Test full_validation passes with good data."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            # Set up passing conditions
            manager.graph.add_citation("claim-1", "ev-1")
            fresh_check = StalenessCheck(
                evidence_id="test",
                status=StalenessStatus.FRESH,
                checked_at=datetime.now().isoformat(),
                reason="Unchanged",
            )

            with patch.object(manager, "check_all_staleness", return_value=[fresh_check]):
                results = await validator.full_validation()
                assert results["passed"] is True

    @pytest.mark.asyncio
    async def test_full_validation_fails_on_staleness(self):
        """Test full_validation fails when too stale."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()
            validator = ProvenanceValidator(manager)

            manager.graph.add_citation("claim-1", "ev-1")

            # All stale
            stale_checks = [
                StalenessCheck(
                    evidence_id=f"test-{i}",
                    status=StalenessStatus.STALE,
                    checked_at=datetime.now().isoformat(),
                    reason="Changed",
                )
                for i in range(3)
            ]

            with patch.object(manager, "check_all_staleness", return_value=stale_checks):
                results = await validator.full_validation()
                assert results["passed"] is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestProvenanceIntegration:
    """Integration tests for the enhanced provenance system."""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Test complete provenance workflow."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager(debate_id="integration-test")

            # Record code evidence
            git_info = GitSourceInfo(
                repo_path="/repo",
                file_path="src/main.py",
                line_start=10,
                line_end=20,
                commit_sha="abc123",
            )

            with patch.object(manager.git_tracker, "record_code_evidence", return_value=git_info):
                code_record = manager.record_code_evidence(
                    file_path="src/main.py",
                    line_start=10,
                    line_end=20,
                    content="def main():\n    pass",
                    claim_id="claim-main-function",
                )

            # Record web evidence
            web_record = await manager.record_web_evidence(
                url="https://docs.example.com/api",
                content="API documentation",
                claim_id="claim-api-docs",
            )

            # Check staleness - use proper async mock
            fresh_check = StalenessCheck(
                evidence_id="test",
                status=StalenessStatus.FRESH,
                checked_at=datetime.now().isoformat(),
                reason="Unchanged",
            )

            async def mock_web_check(*args, **kwargs):
                return fresh_check

            with patch.object(manager.git_tracker, "check_staleness", return_value=fresh_check):
                with patch.object(
                    manager.web_tracker, "check_staleness", side_effect=mock_web_check
                ):
                    checks = await manager.check_all_staleness()

            # Validate
            validator = ProvenanceValidator(manager)

            async def mock_check_all():
                return [fresh_check, fresh_check]

            with patch.object(manager, "check_all_staleness", side_effect=mock_check_all):
                results = await validator.full_validation()
                assert results["evidence_coverage"]["total_claims"] == 2

            # Export - staleness_checks was populated by check_all_staleness
            # Clear any coroutine objects that might have been stored
            manager.staleness_checks = {
                k: v for k, v in manager.staleness_checks.items() if isinstance(v, StalenessCheck)
            }
            exported = manager.export_enhanced()
            assert exported["debate_id"] == "integration-test"
            assert len(exported["git_sources"]) >= 1
            assert len(exported["web_sources"]) >= 1

    def test_revalidation_trigger_generation(self):
        """Test revalidation trigger generation for stale evidence."""
        with patch.object(Path, "mkdir"):
            manager = EnhancedProvenanceManager()

            # Set up claim with stale evidence
            manager.graph.add_citation("claim-1", "ev-1")
            stale_check = StalenessCheck(
                evidence_id="ev-1",
                status=StalenessStatus.STALE,
                checked_at=datetime.now().isoformat(),
                reason="Changed in 5 commits",
                commits_behind=5,
            )
            manager.staleness_checks["ev-1"] = stale_check

            with patch.object(
                manager, "check_claim_evidence_staleness", return_value=[stale_check]
            ):
                triggers = manager.generate_revalidation_triggers(["claim-1"])
                assert len(triggers) == 1
                assert triggers[0].claim_id == "claim-1"
                assert triggers[0].severity == "warning"

    def test_staleness_check_serialization(self, sample_staleness_check):
        """Test staleness check can be serialized and deserialized."""
        data = sample_staleness_check.to_dict()

        # Verify all fields are JSON-serializable
        import json

        json_str = json.dumps(data)
        parsed = json.loads(json_str)

        assert parsed["evidence_id"] == sample_staleness_check.evidence_id
        assert parsed["status"] == sample_staleness_check.status.value
        assert parsed["commits_behind"] == sample_staleness_check.commits_behind

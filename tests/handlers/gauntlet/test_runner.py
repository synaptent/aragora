"""
Tests for GauntletRunnerMixin (aragora/server/handlers/gauntlet/runner.py).

Covers:
- _start_gauntlet: quota checks, body parsing, validation, gauntlet ID generation,
  in-memory storage, persistent storage, durable queue, fire-and-forget, response shape
- _run_gauntlet_async: agent creation, orchestrator execution, progress callbacks,
  emitter events, result storage, receipt persistence, failure handling, storage errors
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.gauntlet.runner import GauntletRunnerMixin
from aragora.server.handlers.gauntlet.storage import get_gauntlet_runs
from aragora.server.handlers.utils.responses import HandlerResult

from aragora.tenancy.record_scope import OrgScope as _OrgScope

TEST_ORG = "test-org-001"
TEST_SCOPE = _OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: HandlerResult) -> dict[str, Any]:
    """Decode a HandlerResult body into a dict."""
    return json.loads(result.body.decode("utf-8"))


def _status(result: HandlerResult) -> int:
    """Extract status code from a HandlerResult."""
    return result.status_code


# ---------------------------------------------------------------------------
# Fake / stub objects
# ---------------------------------------------------------------------------


@dataclass
class FakeUserCtx:
    """Mimics the user context from extract_user_from_request."""

    is_authenticated: bool = True
    org_id: str = "org-001"


@dataclass
class FakeOrg:
    """Mimics an organization object from user_store."""

    is_at_limit: bool = False
    debates_used_this_month: int = 5
    tier: Any = None
    limits: Any = None

    def __post_init__(self):
        if self.tier is None:
            self.tier = type("Tier", (), {"value": "professional"})()
        if self.limits is None:
            self.limits = type("Limits", (), {"debates_per_month": 100})()


@dataclass
class FakeFinding:
    """Mimics a gauntlet finding."""

    finding_id: str = "f-001"
    category: str = "auth"
    severity: str = "high"
    severity_level: str = "high"
    title: str = "Weak auth"
    description: str = "Uses basic auth"


@dataclass
class FakeGauntletResult:
    """Mimics a GauntletResult from the gauntlet orchestrator."""

    verdict: Any = None
    confidence: float = 0.95
    risk_score: float = 0.2
    robustness_score: float = 0.85
    coverage_score: float = 0.9
    total_findings: int = 2
    duration_seconds: float = 12.5
    critical_findings: list = field(default_factory=list)
    high_findings: list = field(default_factory=lambda: [FakeFinding()])
    medium_findings: list = field(
        default_factory=lambda: [FakeFinding(finding_id="f-002", severity_level="medium")]
    )
    low_findings: list = field(default_factory=list)
    all_findings: list = field(
        default_factory=lambda: [FakeFinding(), FakeFinding(finding_id="f-002")]
    )

    def __post_init__(self):
        if self.verdict is None:
            self.verdict = type("Verdict", (), {"value": "APPROVED"})()


class FakeValidationResult:
    """Mimics a ValidationResult."""

    def __init__(self, is_valid=True, error=None):
        self.is_valid = is_valid
        self.error = error


# ---------------------------------------------------------------------------
# Stub mixin class
# ---------------------------------------------------------------------------


class _Stub(GauntletRunnerMixin):
    """Minimal concrete class that mixes in GauntletRunnerMixin.

    Provides stubs for methods the mixin expects from other mixins/base.
    """

    def __init__(self):
        self._auto_persist_called = False
        self._auto_persist_args = None

    def read_json_body(self, handler):
        """Stub: return body from handler."""
        return getattr(handler, "_parsed_body", None)

    async def _auto_persist_receipt(self, result, gauntlet_id, *, scope):
        """Stub for receipt persistence."""
        self._auto_persist_called = True
        self._auto_persist_args = (result, gauntlet_id)
        self._auto_persist_scope = scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mixin():
    return _Stub()


@pytest.fixture(autouse=True)
def _clear_runs():
    """Ensure in-memory runs are empty before/after every test."""
    runs = get_gauntlet_runs()
    runs.clear()
    yield
    runs.clear()


@pytest.fixture
def mock_storage():
    """Return a MagicMock that acts as GauntletStorage."""
    s = MagicMock()
    s.save_inflight = MagicMock()
    s.update_inflight_status = MagicMock()
    s.save = MagicMock()
    s.delete_inflight = MagicMock()
    return s


@pytest.fixture(autouse=True)
def _patch_storage(mock_storage):
    """Patch _get_storage_proxy to return mock_storage for every test."""
    with patch(
        "aragora.server.handlers.gauntlet.runner._get_storage_proxy",
        return_value=mock_storage,
    ):
        yield


@pytest.fixture
def mock_handler():
    """Create a mock HTTP handler with a parsed body for read_json_body."""

    def _create(body=None, user_store=None):
        handler = MagicMock()
        handler._parsed_body = body
        if user_store is not None:
            handler.user_store = user_store
        else:
            # Remove user_store attribute so hasattr returns False
            del handler.user_store
        return handler

    return _create


@pytest.fixture
def valid_body():
    """A valid request body for _start_gauntlet."""
    return {
        "input_content": "Design a rate limiter for the API gateway",
        "input_type": "spec",
        "agents": ["anthropic-api"],
        "profile": "default",
    }


# ============================================================================
# _start_gauntlet - Success cases
# ============================================================================


class TestStartGauntletSuccess:
    """Tests for successful _start_gauntlet invocations."""

    @pytest.mark.asyncio
    async def test_returns_202_with_gauntlet_id(self, mixin, mock_handler, valid_body):
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ) as mock_task,
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202
        body = _body(result)
        assert body["status"] == "pending"
        assert "gauntlet_id" in body
        assert body["gauntlet_id"].startswith("gauntlet-")
        assert body["message"] == "Gauntlet stress-test started"

    @pytest.mark.asyncio
    async def test_stores_run_in_memory(self, mixin, mock_handler, valid_body):
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        gauntlet_id = _body(result)["gauntlet_id"]
        runs = get_gauntlet_runs()
        assert gauntlet_id in runs
        assert runs[gauntlet_id]["status"] == "pending"
        assert runs[gauntlet_id]["input_type"] == "spec"
        assert runs[gauntlet_id]["profile"] == "default"

    @pytest.mark.asyncio
    async def test_persists_to_storage(self, mixin, mock_handler, valid_body, mock_storage):
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        mock_storage.save_inflight.assert_called_once()
        call_kwargs = mock_storage.save_inflight.call_args[1]
        assert call_kwargs["status"] == "pending"
        assert call_kwargs["input_type"] == "spec"
        assert call_kwargs["org_id"] == TEST_ORG

    @pytest.mark.asyncio
    async def test_uses_fire_and_forget_when_durable_disabled(
        self, mixin, mock_handler, valid_body
    ):
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ) as mock_task,
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202
        mock_task.assert_called_once()
        assert _body(result)["durable_queue"] is False

    @pytest.mark.asyncio
    async def test_uses_durable_queue_when_enabled(self, mixin, mock_handler, valid_body):
        handler = mock_handler(body=valid_body)
        mock_enqueue = AsyncMock()
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=True,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ) as mock_task,
            patch.dict(
                "sys.modules",
                {
                    "aragora.server.workers.gauntlet_worker": MagicMock(
                        enqueue_gauntlet_job=mock_enqueue,
                    ),
                },
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202
        assert _body(result)["durable_queue"] is True
        mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_durable_queue_fallback_on_import_error(self, mixin, mock_handler, valid_body):
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=True,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ) as mock_task,
            patch.dict(
                "sys.modules",
                {"aragora.server.workers.gauntlet_worker": None},
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        # Should still return 202 and fall back to fire-and-forget
        assert _status(result) == 202
        # create_tracked_task called for the fallback path
        assert mock_task.call_count >= 1

    @pytest.mark.asyncio
    async def test_input_summary_truncated_at_200(self, mixin, mock_handler, mock_storage):
        long_body = {
            "input_content": "x" * 500,
            "input_type": "spec",
        }
        handler = mock_handler(body=long_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        gauntlet_id = _body(result)["gauntlet_id"]
        runs = get_gauntlet_runs()
        summary = runs[gauntlet_id]["input_summary"]
        assert summary.endswith("...")
        assert len(summary) == 203  # 200 chars + "..."

    @pytest.mark.asyncio
    async def test_short_input_not_truncated(self, mixin, mock_handler, mock_storage):
        body = {
            "input_content": "Short input",
            "input_type": "spec",
        }
        handler = mock_handler(body=body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        gauntlet_id = _body(result)["gauntlet_id"]
        runs = get_gauntlet_runs()
        assert runs[gauntlet_id]["input_summary"] == "Short input"

    @pytest.mark.asyncio
    async def test_input_hash_is_sha256(self, mixin, mock_handler, mock_storage):
        body = {
            "input_content": "Hash me",
            "input_type": "spec",
        }
        handler = mock_handler(body=body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        gauntlet_id = _body(result)["gauntlet_id"]
        runs = get_gauntlet_runs()
        import hashlib

        expected = hashlib.sha256(b"Hash me").hexdigest()
        assert runs[gauntlet_id]["input_hash"] == expected

    @pytest.mark.asyncio
    async def test_default_agents_when_not_provided(self, mixin, mock_handler, mock_storage):
        body = {
            "input_content": "Test content",
        }
        handler = mock_handler(body=body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        # agents defaults to ["anthropic-api"] in the code
        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_cleanup_called_before_store(self, mixin, mock_handler, valid_body):
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner._cleanup_gauntlet_runs",
            ) as mock_cleanup,
        ):
            await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        mock_cleanup.assert_called_once()


# ============================================================================
# _start_gauntlet - Error cases
# ============================================================================


class TestStartGauntletErrors:
    """Tests for _start_gauntlet error handling."""

    @pytest.mark.asyncio
    async def test_returns_400_on_null_body(self, mixin, mock_handler):
        handler = mock_handler(body=None)
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=None,
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 400
        assert "Invalid" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_returns_400_on_validation_failure(self, mixin, mock_handler):
        handler = mock_handler(body={"input_content": "test"})
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=False, error="input_type is invalid"),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 400
        assert "input_type" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_storage_persist_failure_doesnt_block(
        self, mixin, mock_handler, valid_body, mock_storage
    ):
        """If save_inflight fails, the run should still proceed."""
        mock_storage.save_inflight.side_effect = OSError("disk full")
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        # Should still succeed despite storage failure
        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_storage_persist_runtime_error_doesnt_block(
        self, mixin, mock_handler, valid_body, mock_storage
    ):
        mock_storage.save_inflight.side_effect = RuntimeError("connection lost")
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_storage_persist_value_error_doesnt_block(
        self, mixin, mock_handler, valid_body, mock_storage
    ):
        mock_storage.save_inflight.side_effect = ValueError("bad data")
        handler = mock_handler(body=valid_body)
        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202


# ============================================================================
# _start_gauntlet - Quota checks
# ============================================================================


class TestStartGauntletQuota:
    """Tests for quota enforcement in _start_gauntlet."""

    @pytest.mark.asyncio
    async def test_returns_429_when_at_quota_limit(self, mixin, mock_handler, valid_body):
        org = FakeOrg(is_at_limit=True)
        user_store = MagicMock()
        user_store.get_organization_by_id.return_value = org

        user_ctx = FakeUserCtx(is_authenticated=True, org_id="org-001")
        handler = mock_handler(body=valid_body, user_store=user_store)

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=user_ctx,
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 429
        body = _body(result)
        assert body["code"] == "quota_exceeded"
        assert body["remaining"] == 0
        assert "upgrade_url" in body

    @pytest.mark.asyncio
    async def test_increments_usage_when_under_limit(self, mixin, mock_handler, valid_body):
        org = FakeOrg(is_at_limit=False)
        user_store = MagicMock()
        user_store.get_organization_by_id.return_value = org
        user_store.increment_usage = MagicMock()

        user_ctx = FakeUserCtx(is_authenticated=True, org_id="org-001")
        handler = mock_handler(body=valid_body, user_store=user_store)

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=user_ctx,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202
        user_store.increment_usage.assert_called_once_with("org-001", 1)

    @pytest.mark.asyncio
    async def test_usage_increment_failure_doesnt_block(self, mixin, mock_handler, valid_body):
        """If increment_usage fails, the gauntlet should still start."""
        org = FakeOrg(is_at_limit=False)
        user_store = MagicMock()
        user_store.get_organization_by_id.return_value = org
        user_store.increment_usage = MagicMock(side_effect=RuntimeError("db error"))

        user_ctx = FakeUserCtx(is_authenticated=True, org_id="org-001")
        handler = mock_handler(body=valid_body, user_store=user_store)

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=user_ctx,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_no_quota_check_without_user_store(self, mixin, mock_handler, valid_body):
        handler = mock_handler(body=valid_body, user_store=None)
        # Remove user_store explicitly
        if hasattr(handler, "user_store"):
            del handler.user_store

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_no_quota_check_for_unauthenticated_user(self, mixin, mock_handler, valid_body):
        user_store = MagicMock()
        user_ctx = FakeUserCtx(is_authenticated=False, org_id="org-001")
        handler = mock_handler(body=valid_body, user_store=user_store)

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=user_ctx,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202
        # Should not try to check org quota
        user_store.get_organization_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_quota_check_when_org_not_found(self, mixin, mock_handler, valid_body):
        user_store = MagicMock()
        user_store.get_organization_by_id.return_value = None
        user_ctx = FakeUserCtx(is_authenticated=True, org_id="org-001")
        handler = mock_handler(body=valid_body, user_store=user_store)

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=user_ctx,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_quota_429_includes_tier_info(self, mixin, mock_handler, valid_body):
        org = FakeOrg(is_at_limit=True, debates_used_this_month=50)
        org.tier = type("Tier", (), {"value": "starter"})()
        org.limits = type("Limits", (), {"debates_per_month": 50})()
        user_store = MagicMock()
        user_store.get_organization_by_id.return_value = org

        user_ctx = FakeUserCtx(is_authenticated=True, org_id="org-001")
        handler = mock_handler(body=valid_body, user_store=user_store)

        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=user_ctx,
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        body = _body(result)
        assert body["tier"] == "starter"
        assert body["limit"] == 50
        assert body["used"] == 50
        assert "starter" in body["message"]

    @pytest.mark.asyncio
    async def test_user_store_on_class_attr(self, mixin, mock_handler, valid_body):
        """Test that user_store is found via handler.__class__.user_store."""
        user_store = MagicMock()
        user_store.get_organization_by_id.return_value = FakeOrg(is_at_limit=False)
        user_store.increment_usage = MagicMock()

        user_ctx = FakeUserCtx(is_authenticated=True, org_id="org-001")
        handler = mock_handler(body=valid_body)
        # Remove instance attr, set on class
        if hasattr(handler, "user_store"):
            del handler.user_store
        handler.__class__.user_store = user_store

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.validate_against_schema",
                return_value=FakeValidationResult(is_valid=True),
            ),
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=user_ctx,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.is_durable_queue_enabled",
                return_value=False,
            ),
            patch(
                "aragora.server.handlers.gauntlet.runner.create_tracked_task",
            ),
        ):
            result = await mixin._start_gauntlet(handler, scope=TEST_SCOPE)

        assert _status(result) == 202
        user_store.increment_usage.assert_called_once()

        # Clean up class attr
        del handler.__class__.user_store


# ============================================================================
# _run_gauntlet_async - Success cases
# ============================================================================


class TestRunGauntletAsyncSuccess:
    """Tests for _run_gauntlet_async execution."""

    @pytest.mark.asyncio
    async def test_successful_run_stores_completed_result(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-test-001"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "test content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "completed"
        assert runs[gid]["result"]["verdict"] == "APPROVED"
        assert runs[gid]["result"]["confidence"] == 0.95
        assert runs[gid]["result"]["total_findings"] == 2

    @pytest.mark.asyncio
    async def test_successful_run_persists_to_storage(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-test-persist"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "test content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        mock_storage.save.assert_called_once_with(fake_result, org_id=TEST_ORG)
        mock_storage.delete_inflight.assert_called_once_with(gid)

    @pytest.mark.asyncio
    async def test_auto_persist_receipt_called(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-test-receipt"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "test content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert mixin._auto_persist_called is True
        assert mixin._auto_persist_args[1] == gid
        assert mixin._auto_persist_scope == TEST_SCOPE

    @pytest.mark.asyncio
    async def test_result_findings_limited_to_20(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-test-findings"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        many_findings = [
            FakeFinding(finding_id=f"f-{i:03d}", title=f"Finding {i}") for i in range(30)
        ]
        fake_result = FakeGauntletResult(all_findings=many_findings, total_findings=30)
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "test content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert len(runs[gid]["result"]["findings"]) == 20

    @pytest.mark.asyncio
    async def test_finding_description_truncated_to_500(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-test-desc"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        long_finding = FakeFinding(description="D" * 1000)
        fake_result = FakeGauntletResult(all_findings=[long_finding], total_findings=1)
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "test content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        desc = runs[gid]["result"]["findings"][0]["description"]
        assert len(desc) == 500


# ============================================================================
# _run_gauntlet_async - Input type mapping
# ============================================================================


class TestRunGauntletInputTypes:
    """Tests for input type mapping in _run_gauntlet_async."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "input_type_str,expected_attr",
        [
            ("spec", "SPEC"),
            ("architecture", "ARCHITECTURE"),
            ("policy", "POLICY"),
            ("code", "CODE"),
            ("strategy", "STRATEGY"),
            ("contract", "CONTRACT"),
            ("unknown_type", "SPEC"),  # Falls back to SPEC
        ],
    )
    async def test_input_type_mapping(self, mixin, mock_storage, input_type_str, expected_attr):
        runs = get_gauntlet_runs()
        gid = f"gauntlet-type-{input_type_str}"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        # Create proper InputType mock with all attrs
        mock_input_type = MagicMock()
        for attr in ["SPEC", "ARCHITECTURE", "POLICY", "CODE", "STRATEGY", "CONTRACT"]:
            setattr(mock_input_type, attr, MagicMock(name=attr))

        mock_config_cls = MagicMock()

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=mock_input_type,
                        OrchestratorConfig=mock_config_cls,
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", input_type_str, None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "completed"


# ============================================================================
# _run_gauntlet_async - Failure cases
# ============================================================================


class TestRunGauntletAsyncFailures:
    """Tests for _run_gauntlet_async error handling."""

    @pytest.mark.asyncio
    async def test_no_agents_created_marks_failed(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-no-agents"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(side_effect=ValueError("No such agent")),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["bad-agent"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "failed"
        assert runs[gid]["error"] == "No agents could be created"

    @pytest.mark.asyncio
    async def test_orchestrator_runtime_error_marks_failed(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-orch-fail"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.side_effect = RuntimeError("orchestrator crashed")

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "failed"
        assert runs[gid]["error"] == "Gauntlet run failed"

    @pytest.mark.asyncio
    async def test_orchestrator_os_error_marks_failed(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-os-fail"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.side_effect = OSError("disk full")

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_import_error_marks_failed(self, mixin, mock_storage):
        """When gauntlet modules cannot be imported, run should fail gracefully."""
        runs = get_gauntlet_runs()
        gid = "gauntlet-import-fail"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": None,  # Force ImportError
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancelled_error_marks_failed(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-cancel"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.side_effect = asyncio.CancelledError()

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_failure_updates_persistent_status(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-persist-fail"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.side_effect = RuntimeError("fail")

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        # Should have been called at least twice: once for "running", once for "failed"
        calls = mock_storage.update_inflight_status.call_args_list
        # Find the "failed" call
        failed_calls = [c for c in calls if c[0][1] == "failed" or c[1].get("status") == "failed"]
        assert len(failed_calls) >= 1 or any("failed" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_storage_save_error_doesnt_crash(self, mixin, mock_storage):
        """If storage.save() fails after orchestrator success, run still completes."""
        runs = get_gauntlet_runs()
        gid = "gauntlet-save-fail"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        mock_storage.save.side_effect = OSError("disk full")

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        # Run should still be completed in memory
        assert runs[gid]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_partial_agent_creation_continues(self, mixin, mock_storage):
        """If some agents fail to create, run proceeds with the ones that succeed."""
        runs = get_gauntlet_runs()
        gid = "gauntlet-partial"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_agent = MagicMock()
        fake_agent.name = "good_agent"

        def create_agent_side_effect(model_type, name, role):
            if "bad" in str(model_type):
                raise ValueError("No such agent")
            return fake_agent

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(side_effect=create_agent_side_effect),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid,
                "content",
                "spec",
                None,
                ["good-agent", "bad-agent"],
                "default",
                scope=TEST_SCOPE,
            )

        assert runs[gid]["status"] == "completed"


# ============================================================================
# _run_gauntlet_async - Emitter / streaming
# ============================================================================


class TestRunGauntletAsyncEmitter:
    """Tests for streaming emitter integration in _run_gauntlet_async."""

    @pytest.mark.asyncio
    async def test_emitter_start_called_when_broadcast_fn_set(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-emit-start"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        mock_emitter_cls = MagicMock()
        mock_emitter_instance = MagicMock()
        mock_emitter_cls.return_value = mock_emitter_instance

        broadcast_fn = MagicMock()

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=broadcast_fn,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(
                        GauntletStreamEmitter=mock_emitter_cls,
                    ),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        mock_emitter_instance.emit_start.assert_called_once()
        mock_emitter_instance.emit_verdict.assert_called_once()
        mock_emitter_instance.emit_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_emitter_when_no_broadcast_fn(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-no-emit"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        # Should complete without errors (no emitter calls)
        assert runs[gid]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_emitter_verdict_includes_severity_counts(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-emit-verdict"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult(
            critical_findings=[FakeFinding(severity_level="critical")],
            high_findings=[FakeFinding(), FakeFinding()],
            medium_findings=[],
            low_findings=[FakeFinding(severity_level="low")],
        )
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        mock_emitter_cls = MagicMock()
        mock_emitter_instance = MagicMock()
        mock_emitter_cls.return_value = mock_emitter_instance

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=MagicMock(),
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(
                        GauntletStreamEmitter=mock_emitter_cls,
                    ),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        call_kwargs = mock_emitter_instance.emit_verdict.call_args[1]
        assert call_kwargs["critical_count"] == 1
        assert call_kwargs["high_count"] == 2
        assert call_kwargs["medium_count"] == 0
        assert call_kwargs["low_count"] == 1


# ============================================================================
# _run_gauntlet_async - Status update / running state
# ============================================================================


class TestRunGauntletAsyncStatusUpdates:
    """Tests for status transitions during _run_gauntlet_async."""

    @pytest.mark.asyncio
    async def test_sets_running_status_before_execution(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-status-running"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        statuses_seen = []

        original_run = AsyncMock()

        async def capture_status(config):
            statuses_seen.append(runs[gid]["status"])
            return FakeGauntletResult()

        original_run.side_effect = capture_status

        mock_orchestrator = MagicMock()
        mock_orchestrator.run = original_run

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        # When orchestrator.run was called, status should have been "running"
        assert "running" in statuses_seen

    @pytest.mark.asyncio
    async def test_updates_persistent_status_to_running(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-persist-running"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        # First call should be for "running" status
        first_call = mock_storage.update_inflight_status.call_args_list[0]
        assert first_call[0] == (gid, "running")

    @pytest.mark.asyncio
    async def test_update_inflight_status_error_doesnt_crash(self, mixin, mock_storage):
        """If update_inflight_status fails, run continues."""
        runs = get_gauntlet_runs()
        gid = "gauntlet-inflight-err"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        mock_storage.update_inflight_status.side_effect = OSError("db down")

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["status"] == "completed"


# ============================================================================
# _run_gauntlet_async - Result dict shape
# ============================================================================


class TestRunGauntletResultShape:
    """Tests for the shape of result_dict stored in memory."""

    @pytest.mark.asyncio
    async def test_result_dict_has_all_fields(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-shape"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        result_dict = runs[gid]["result"]
        expected_keys = {
            "gauntlet_id",
            "verdict",
            "confidence",
            "risk_score",
            "robustness_score",
            "coverage_score",
            "total_findings",
            "critical_count",
            "high_count",
            "medium_count",
            "low_count",
            "findings",
        }
        assert expected_keys.issubset(set(result_dict.keys()))
        assert result_dict["gauntlet_id"] == gid

    @pytest.mark.asyncio
    async def test_completed_at_is_set(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-completed-at"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert "completed_at" in runs[gid]
        # Should be a valid ISO timestamp
        datetime.fromisoformat(runs[gid]["completed_at"])

    @pytest.mark.asyncio
    async def test_result_obj_stored_in_memory(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-result-obj"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        fake_result = FakeGauntletResult()
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        assert runs[gid]["result_obj"] is fake_result

    @pytest.mark.asyncio
    async def test_finding_fields_in_result(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        gid = "gauntlet-finding-fields"
        runs[gid] = {"org_id": TEST_ORG, "gauntlet_id": gid, "status": "pending"}

        finding = FakeFinding(
            finding_id="f-test",
            category="auth",
            severity="high",
            severity_level="high",
            title="Weak Token",
            description="Token has no expiry",
        )
        fake_result = FakeGauntletResult(all_findings=[finding], total_findings=1)
        mock_orchestrator = AsyncMock()
        mock_orchestrator.run.return_value = fake_result

        fake_agent = MagicMock()
        fake_agent.name = "test_agent"

        with (
            patch(
                "aragora.server.handlers.gauntlet.runner.get_gauntlet_broadcast_fn",
                return_value=None,
            ),
            patch.dict(
                "sys.modules",
                {
                    "aragora.agents.base": MagicMock(
                        create_agent=MagicMock(return_value=fake_agent),
                        AgentType=MagicMock(),
                    ),
                    "aragora.gauntlet": MagicMock(
                        GauntletOrchestrator=MagicMock(return_value=mock_orchestrator),
                        GauntletProgress=MagicMock,
                        InputType=MagicMock(SPEC=MagicMock()),
                        OrchestratorConfig=MagicMock(),
                    ),
                    "aragora.server.stream.gauntlet_emitter": MagicMock(),
                },
            ),
        ):
            await mixin._run_gauntlet_async(
                gid, "content", "spec", None, ["anthropic-api"], "default", scope=TEST_SCOPE
            )

        f = runs[gid]["result"]["findings"][0]
        assert f["id"] == "f-test"
        assert f["category"] == "auth"
        assert f["severity"] == "high"
        assert f["severity_level"] == "high"
        assert f["title"] == "Weak Token"
        assert f["description"] == "Token has no expiry"

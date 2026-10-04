"""
Tests for GauntletResultsMixin (aragora/server/handlers/gauntlet/results.py).

Covers:
- _list_personas: persona listing, import errors
- _get_status: in-memory lookup, persistent storage, inflight, not found, storage errors
- _list_results: pagination, filtering, clamping, storage errors
- _compare_results: success, not found, storage errors
- _delete_result: in-memory + persistent, not found, storage errors
- _export_report: JSON/HTML/full_html formats, findings, heatmap, enhanced data,
                  not completed, not found, storage errors, unsupported format, XSS escaping
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.gauntlet.results import GauntletResultsMixin
from aragora.server.handlers.gauntlet.storage import get_gauntlet_runs
from aragora.server.handlers.utils.responses import HandlerResult

from aragora.tenancy.record_scope import OrgScope as _OrgScope

TEST_ORG = "test-org-001"
TEST_SCOPE = _OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(result: HandlerResult) -> dict[str, Any]:
    """Decode a HandlerResult body into a dict."""
    return json.loads(result.body.decode("utf-8"))


@dataclass
class FakeInflight:
    """Mimics an inflight record returned by storage.get_inflight()."""

    gauntlet_id: str
    status: str = "running"
    progress: float = 0.5
    org_id: str | None = TEST_ORG

    def to_dict(self) -> dict[str, Any]:
        return {
            "gauntlet_id": self.gauntlet_id,
            "status": self.status,
            "progress": self.progress,
        }


@dataclass
class FakeResultRow:
    """Mimics a row returned by storage.list_recent()."""

    gauntlet_id: str = "g-001"
    input_hash: str = "abc123"
    input_summary: str = "Test input"
    verdict: str = "APPROVED"
    confidence: float = 0.95
    robustness_score: float = 0.88
    critical_count: int = 0
    high_count: int = 1
    total_findings: int = 3
    created_at: datetime = field(default_factory=datetime.now)
    duration_seconds: float = 12.5


@dataclass
class FakePersona:
    name: str = "GDPR Auditor"
    description: str = "Tests GDPR compliance"
    regulation: str = "GDPR"
    attack_prompts: list = field(
        default_factory=lambda: [
            type("AP", (), {"category": "data_retention"})(),
            type("AP", (), {"category": "consent"})(),
        ]
    )


# ---------------------------------------------------------------------------
# Fixture: mixin instance with RBAC auto-bypassed via conftest
# ---------------------------------------------------------------------------


class _Stub(GauntletResultsMixin):
    """Minimal concrete class that mixes in GauntletResultsMixin."""

    pass


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


# ---------------------------------------------------------------------------
# Mock storage factory
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage():
    """Return a MagicMock that acts as GauntletStorage."""
    s = MagicMock()
    s.get.return_value = None
    s.get_inflight.return_value = None
    s.list_recent.return_value = []
    s.count.return_value = 0
    s.compare.return_value = None
    s.delete.return_value = False
    return s


@pytest.fixture(autouse=True)
def _patch_storage(mock_storage):
    """Patch _get_storage_proxy to return mock_storage for every test."""
    with patch(
        "aragora.server.handlers.gauntlet.results._get_storage_proxy",
        return_value=mock_storage,
    ):
        yield


# ============================================================================
# _list_personas
# ============================================================================


class TestListPersonas:
    """Tests for _list_personas endpoint."""

    def test_returns_personas_list(self, mixin):
        with (
            patch(
                "aragora.server.handlers.gauntlet.results.list_personas",
                return_value=["gdpr"],
                create=True,
            ),
            patch(
                "aragora.server.handlers.gauntlet.results.get_persona",
                return_value=FakePersona(),
                create=True,
            ),
        ):
            # The import is inside the method so we patch at the import site
            with patch.dict(
                "sys.modules",
                {
                    "aragora.gauntlet.personas": MagicMock(
                        list_personas=MagicMock(return_value=["gdpr"]),
                        get_persona=MagicMock(return_value=FakePersona()),
                    )
                },
            ):
                result = mixin._list_personas()

        assert result.status_code == 200
        data = _parse(result)
        assert data["count"] == 1
        assert data["personas"][0]["id"] == "gdpr"
        assert data["personas"][0]["name"] == "GDPR Auditor"
        assert "data_retention" in data["personas"][0]["categories"]

    def test_returns_multiple_personas(self, mixin):
        p1 = FakePersona(name="GDPR", regulation="GDPR")
        p2 = FakePersona(name="SOX", regulation="SOX")
        mod = MagicMock(
            list_personas=MagicMock(return_value=["gdpr", "sox"]),
            get_persona=MagicMock(side_effect=[p1, p2]),
        )
        with patch.dict("sys.modules", {"aragora.gauntlet.personas": mod}):
            result = mixin._list_personas()
        data = _parse(result)
        assert data["count"] == 2

    def test_returns_empty_on_import_error(self, mixin):
        """When personas module is unavailable, return empty list with error."""
        with patch.dict("sys.modules", {"aragora.gauntlet.personas": None}):
            result = mixin._list_personas()
        assert result.status_code == 200
        data = _parse(result)
        assert data["count"] == 0
        assert data["personas"] == []
        assert "error" in data

    def test_persona_attack_count(self, mixin):
        persona = FakePersona()
        persona.attack_prompts = [
            type("AP", (), {"category": "c1"})(),
            type("AP", (), {"category": "c2"})(),
            type("AP", (), {"category": "c1"})(),
        ]
        mod = MagicMock(
            list_personas=MagicMock(return_value=["test"]),
            get_persona=MagicMock(return_value=persona),
        )
        with patch.dict("sys.modules", {"aragora.gauntlet.personas": mod}):
            result = mixin._list_personas()
        data = _parse(result)
        assert data["personas"][0]["attack_count"] == 3
        # Categories deduplicated via set
        assert sorted(data["personas"][0]["categories"]) == ["c1", "c2"]

    def test_persona_with_no_attacks(self, mixin):
        persona = FakePersona()
        persona.attack_prompts = []
        mod = MagicMock(
            list_personas=MagicMock(return_value=["empty"]),
            get_persona=MagicMock(return_value=persona),
        )
        with patch.dict("sys.modules", {"aragora.gauntlet.personas": mod}):
            result = mixin._list_personas()
        data = _parse(result)
        assert data["personas"][0]["attack_count"] == 0
        assert data["personas"][0]["categories"] == []


# ============================================================================
# _get_status
# ============================================================================


class TestGetStatus:
    """Tests for _get_status endpoint."""

    @pytest.mark.asyncio
    async def test_returns_in_memory_run(self, mixin):
        runs = get_gauntlet_runs()
        runs["run-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "run-1",
            "status": "running",
            "result_obj": "SHOULD_BE_EXCLUDED",
        }
        result = await mixin._get_status("run-1", scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["gauntlet_id"] == "run-1"
        assert data["status"] == "running"
        assert "result_obj" not in data

    @pytest.mark.asyncio
    async def test_returns_inflight_from_storage(self, mixin, mock_storage):
        mock_storage.get_inflight.return_value = FakeInflight("run-2")
        result = await mixin._get_status("run-2", scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["gauntlet_id"] == "run-2"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("owner", ["org-other", None])
    async def test_inflight_of_another_or_no_org_is_not_found(self, mixin, mock_storage, owner):
        mock_storage.get_inflight.return_value = FakeInflight("run-2", org_id=owner)
        result = await mixin._get_status("run-2", scope=TEST_SCOPE)
        assert result.status_code == 404
        assert _parse(result) == {"error": "Gauntlet run not found", "code": "not_found"}
        mock_storage.get.assert_called_once_with("run-2", TEST_ORG)

    @pytest.mark.asyncio
    async def test_returns_completed_from_storage(self, mixin, mock_storage):
        mock_storage.get_inflight.return_value = None
        mock_storage.get.return_value = {"verdict": "APPROVED", "confidence": 0.9}
        result = await mixin._get_status("run-3", scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["status"] == "completed"
        assert data["result"]["verdict"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_not_found(self, mixin, mock_storage):
        mock_storage.get_inflight.return_value = None
        mock_storage.get.return_value = None
        result = await mixin._get_status("nonexistent", scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_storage_error_returns_404(self, mixin, mock_storage):
        mock_storage.get_inflight.side_effect = RuntimeError("db down")
        result = await mixin._get_status("err-1", scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_storage_os_error_returns_404(self, mixin, mock_storage):
        mock_storage.get_inflight.side_effect = OSError("disk error")
        result = await mixin._get_status("err-2", scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_storage_value_error_returns_404(self, mixin, mock_storage):
        mock_storage.get_inflight.side_effect = ValueError("bad data")
        result = await mixin._get_status("err-3", scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_in_memory_takes_precedence_over_storage(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        runs["dup-1"] = {"org_id": TEST_ORG, "gauntlet_id": "dup-1", "status": "pending"}
        mock_storage.get.return_value = {"verdict": "APPROVED"}
        result = await mixin._get_status("dup-1", scope=TEST_SCOPE)
        data = _parse(result)
        assert data["status"] == "pending"
        # Storage should NOT be called because in-memory matched first
        mock_storage.get_inflight.assert_not_called()

    @pytest.mark.asyncio
    async def test_strips_result_obj_from_response(self, mixin):
        runs = get_gauntlet_runs()
        runs["strip-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "strip-1",
            "status": "completed",
            "result_obj": MagicMock(),
            "result": {"verdict": "PASS"},
        }
        result = await mixin._get_status("strip-1", scope=TEST_SCOPE)
        data = _parse(result)
        assert "result_obj" not in data
        assert "result" in data


# ============================================================================
# _list_results
# ============================================================================


class TestListResults:
    """Tests for _list_results endpoint."""

    def test_empty_results(self, mixin, mock_storage):
        result = mixin._list_results({}, scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["results"] == []
        assert data["total"] == 0
        assert data["limit"] == 20
        assert data["offset"] == 0

    def test_with_results(self, mixin, mock_storage):
        mock_storage.list_recent.return_value = [FakeResultRow()]
        mock_storage.count.return_value = 1
        result = mixin._list_results({}, scope=TEST_SCOPE)
        data = _parse(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["gauntlet_id"] == "g-001"
        assert data["results"][0]["verdict"] == "APPROVED"
        assert data["total"] == 1

    def test_custom_limit_and_offset(self, mixin, mock_storage):
        mock_storage.list_recent.return_value = []
        result = mixin._list_results({"limit": "5", "offset": "10"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["limit"] == 5
        assert data["offset"] == 10
        mock_storage.list_recent.assert_called_once_with(
            limit=5,
            offset=10,
            verdict=None,
            min_severity=None,
            org_id=TEST_ORG,
        )

    def test_limit_clamped_to_max_100(self, mixin, mock_storage):
        mock_storage.list_recent.return_value = []
        result = mixin._list_results({"limit": "500"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["limit"] == 100

    def test_limit_clamped_to_min_1(self, mixin, mock_storage):
        mock_storage.list_recent.return_value = []
        result = mixin._list_results({"limit": "0"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["limit"] == 1

    def test_negative_offset_clamped_to_zero(self, mixin, mock_storage):
        mock_storage.list_recent.return_value = []
        result = mixin._list_results({"offset": "-5"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["offset"] == 0

    def test_verdict_filter(self, mixin, mock_storage):
        mock_storage.list_recent.return_value = []
        mixin._list_results({"verdict": "APPROVED"}, scope=TEST_SCOPE)
        mock_storage.list_recent.assert_called_once_with(
            limit=20,
            offset=0,
            verdict="APPROVED",
            min_severity=None,
            org_id=TEST_ORG,
        )
        mock_storage.count.assert_called_once_with(org_id=TEST_ORG, verdict="APPROVED")

    def test_min_severity_filter(self, mixin, mock_storage):
        mock_storage.list_recent.return_value = []
        mixin._list_results({"min_severity": "high"}, scope=TEST_SCOPE)
        mock_storage.list_recent.assert_called_once_with(
            limit=20,
            offset=0,
            verdict=None,
            min_severity="high",
            org_id=TEST_ORG,
        )

    def test_input_summary_truncation(self, mixin, mock_storage):
        row = FakeResultRow(input_summary="A" * 200)
        mock_storage.list_recent.return_value = [row]
        mock_storage.count.return_value = 1
        result = mixin._list_results({}, scope=TEST_SCOPE)
        data = _parse(result)
        summary = data["results"][0]["input_summary"]
        assert summary.endswith("...")
        assert len(summary) == 103  # 100 chars + "..."

    def test_short_summary_not_truncated(self, mixin, mock_storage):
        row = FakeResultRow(input_summary="Short")
        mock_storage.list_recent.return_value = [row]
        mock_storage.count.return_value = 1
        result = mixin._list_results({}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["results"][0]["input_summary"] == "Short"

    def test_storage_error_returns_500(self, mixin, mock_storage):
        mock_storage.list_recent.side_effect = RuntimeError("db down")
        result = mixin._list_results({}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_storage_os_error_returns_500(self, mixin, mock_storage):
        mock_storage.list_recent.side_effect = OSError("disk")
        result = mixin._list_results({}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_storage_type_error_returns_500(self, mixin, mock_storage):
        mock_storage.list_recent.side_effect = TypeError("bad type")
        result = mixin._list_results({}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_storage_value_error_returns_500(self, mixin, mock_storage):
        mock_storage.list_recent.side_effect = ValueError("bad val")
        result = mixin._list_results({}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_created_at_serialized_as_iso(self, mixin, mock_storage):
        dt = datetime(2025, 6, 15, 12, 0, 0)
        row = FakeResultRow(created_at=dt)
        mock_storage.list_recent.return_value = [row]
        mock_storage.count.return_value = 1
        result = mixin._list_results({}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["results"][0]["created_at"] == "2025-06-15T12:00:00"

    def test_multiple_results(self, mixin, mock_storage):
        rows = [
            FakeResultRow(gauntlet_id="g-001", verdict="APPROVED"),
            FakeResultRow(gauntlet_id="g-002", verdict="REJECTED"),
            FakeResultRow(gauntlet_id="g-003", verdict="APPROVED"),
        ]
        mock_storage.list_recent.return_value = rows
        mock_storage.count.return_value = 3
        result = mixin._list_results({}, scope=TEST_SCOPE)
        data = _parse(result)
        assert len(data["results"]) == 3
        assert data["total"] == 3


# ============================================================================
# _compare_results
# ============================================================================


class TestCompareResults:
    """Tests for _compare_results endpoint."""

    def test_compare_success(self, mixin, mock_storage):
        mock_storage.compare.return_value = {"id1": "a", "id2": "b", "diff": {"score_delta": 0.1}}
        result = mixin._compare_results("a", "b", {}, scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["id1"] == "a"
        assert data["diff"]["score_delta"] == 0.1

    def test_compare_not_found(self, mixin, mock_storage):
        mock_storage.compare.return_value = None
        result = mixin._compare_results("a", "b", {}, scope=TEST_SCOPE)
        assert result.status_code == 404

    def test_compare_runtime_error(self, mixin, mock_storage):
        mock_storage.compare.side_effect = RuntimeError("fail")
        result = mixin._compare_results("a", "b", {}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_compare_os_error(self, mixin, mock_storage):
        mock_storage.compare.side_effect = OSError("disk")
        result = mixin._compare_results("a", "b", {}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_compare_type_error(self, mixin, mock_storage):
        mock_storage.compare.side_effect = TypeError("bad")
        result = mixin._compare_results("a", "b", {}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_compare_value_error(self, mixin, mock_storage):
        mock_storage.compare.side_effect = ValueError("bad")
        result = mixin._compare_results("a", "b", {}, scope=TEST_SCOPE)
        assert result.status_code == 500


# ============================================================================
# _delete_result
# ============================================================================


class TestDeleteResult:
    """Tests for _delete_result endpoint."""

    def test_delete_success_from_storage(self, mixin, mock_storage):
        mock_storage.delete.return_value = True
        result = mixin._delete_result("del-1", {}, scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["deleted"] is True
        assert data["gauntlet_id"] == "del-1"

    def test_delete_removes_from_memory(self, mixin, mock_storage):
        runs = get_gauntlet_runs()
        runs["del-2"] = {"org_id": TEST_ORG, "gauntlet_id": "del-2", "status": "completed"}
        mock_storage.delete.return_value = True
        result = mixin._delete_result("del-2", {}, scope=TEST_SCOPE)
        assert result.status_code == 200
        assert "del-2" not in runs

    def test_delete_not_found(self, mixin, mock_storage):
        mock_storage.delete.return_value = False
        result = mixin._delete_result("missing", {}, scope=TEST_SCOPE)
        assert result.status_code == 404

    def test_delete_runtime_error(self, mixin, mock_storage):
        mock_storage.delete.side_effect = RuntimeError("fail")
        result = mixin._delete_result("err", {}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_delete_os_error(self, mixin, mock_storage):
        mock_storage.delete.side_effect = OSError("disk")
        result = mixin._delete_result("err", {}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_delete_key_error(self, mixin, mock_storage):
        mock_storage.delete.side_effect = KeyError("missing")
        result = mixin._delete_result("err", {}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_delete_value_error(self, mixin, mock_storage):
        mock_storage.delete.side_effect = ValueError("bad")
        result = mixin._delete_result("err", {}, scope=TEST_SCOPE)
        assert result.status_code == 500

    def test_delete_memory_only_then_storage_not_found(self, mixin, mock_storage):
        """Deleting from memory succeeds but storage says not found."""
        runs = get_gauntlet_runs()
        runs["mem-only"] = {"org_id": TEST_ORG, "gauntlet_id": "mem-only", "status": "pending"}
        mock_storage.delete.return_value = False
        result = mixin._delete_result("mem-only", {}, scope=TEST_SCOPE)
        # Storage returned False so handler returns 404
        assert result.status_code == 404
        # But it was removed from memory
        assert "mem-only" not in runs


# ============================================================================
# _export_report - JSON format
# ============================================================================


class TestExportReportJSON:
    """Tests for _export_report with format=json."""

    @pytest.mark.asyncio
    async def test_export_in_memory_completed(self, mixin):
        runs = get_gauntlet_runs()
        runs["exp-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "exp-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.95,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.85,
                "total_findings": 2,
                "critical_count": 0,
                "high_count": 1,
                "medium_count": 1,
                "low_count": 0,
                "findings": [
                    {"category": "auth", "severity_level": "high", "title": "Weak auth"},
                ],
            },
            "input_summary": "Test input",
            "input_type": "text",
            "input_hash": "hash123",
            "created_at": "2025-01-01T00:00:00",
            "completed_at": "2025-01-01T00:05:00",
        }
        result = await mixin._export_report("exp-1", {}, scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["gauntlet_id"] == "exp-1"
        assert data["summary"]["verdict"] == "APPROVED"
        assert data["summary"]["confidence"] == 0.95
        assert data["findings_summary"]["total"] == 2
        assert "findings" in data
        assert "heatmap" in data

    @pytest.mark.asyncio
    async def test_export_not_completed_returns_400(self, mixin):
        runs = get_gauntlet_runs()
        runs["exp-2"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "exp-2",
            "status": "running",
            "result": None,
        }
        result = await mixin._export_report("exp-2", {}, scope=TEST_SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_export_from_storage(self, mixin, mock_storage):
        mock_storage.get.return_value = {
            "verdict": "REJECTED",
            "confidence": 0.7,
            "robustness_score": 0.5,
            "risk_score": 0.4,
            "coverage_score": 0.6,
            "total_findings": 1,
            "critical_count": 1,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
        }
        result = await mixin._export_report("stored-1", {"format": "json"}, scope=TEST_SCOPE)
        assert result.status_code == 200
        data = _parse(result)
        assert data["summary"]["verdict"] == "REJECTED"

    @pytest.mark.asyncio
    async def test_export_not_found(self, mixin, mock_storage):
        mock_storage.get.return_value = None
        result = await mixin._export_report("missing", {}, scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_export_storage_error_returns_404(self, mixin, mock_storage):
        mock_storage.get.side_effect = RuntimeError("db down")
        result = await mixin._export_report("err-1", {}, scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_export_storage_os_error(self, mixin, mock_storage):
        mock_storage.get.side_effect = OSError("disk")
        result = await mixin._export_report("err-2", {}, scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_export_storage_value_error(self, mixin, mock_storage):
        mock_storage.get.side_effect = ValueError("bad")
        result = await mixin._export_report("err-3", {}, scope=TEST_SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_export_without_findings(self, mixin):
        runs = get_gauntlet_runs()
        runs["nf-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "nf-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.99,
                "robustness_score": 0.99,
                "risk_score": 0.01,
                "coverage_score": 0.99,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
        }
        result = await mixin._export_report("nf-1", {"include_findings": "false"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert "findings" not in data

    @pytest.mark.asyncio
    async def test_export_without_heatmap(self, mixin):
        runs = get_gauntlet_runs()
        runs["nh-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "nh-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.99,
                "robustness_score": 0.99,
                "risk_score": 0.01,
                "coverage_score": 0.99,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
        }
        result = await mixin._export_report("nh-1", {"include_heatmap": "false"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert "heatmap" not in data

    @pytest.mark.asyncio
    async def test_export_defaults_missing_result_fields(self, mixin):
        runs = get_gauntlet_runs()
        runs["def-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "def-1",
            "status": "completed",
            "result": {},
        }
        result = await mixin._export_report("def-1", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["summary"]["verdict"] == "UNKNOWN"
        assert data["summary"]["confidence"] == 0
        assert data["findings_summary"]["total"] == 0


# ============================================================================
# _export_report - heatmap generation
# ============================================================================


class TestExportReportHeatmap:
    """Tests for heatmap generation within _export_report."""

    @pytest.mark.asyncio
    async def test_heatmap_cells(self, mixin):
        runs = get_gauntlet_runs()
        runs["hm-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "hm-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.8,
                "risk_score": 0.2,
                "coverage_score": 0.9,
                "total_findings": 2,
                "critical_count": 1,
                "high_count": 1,
                "medium_count": 0,
                "low_count": 0,
                "findings": [
                    {"category": "auth", "severity_level": "critical"},
                    {"category": "auth", "severity_level": "high"},
                ],
            },
        }
        result = await mixin._export_report("hm-1", {}, scope=TEST_SCOPE)
        data = _parse(result)
        heatmap = data["heatmap"]
        assert "auth" in heatmap["categories"]
        assert heatmap["severities"] == ["critical", "high", "medium", "low"]
        # auth x 4 severities = 4 cells
        assert len(heatmap["cells"]) == 4
        crit_cell = next(c for c in heatmap["cells"] if c["severity"] == "critical")
        assert crit_cell["count"] == 1

    @pytest.mark.asyncio
    async def test_heatmap_multiple_categories(self, mixin):
        runs = get_gauntlet_runs()
        runs["hm-2"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "hm-2",
            "status": "completed",
            "result": {
                "verdict": "REJECTED",
                "confidence": 0.5,
                "robustness_score": 0.3,
                "risk_score": 0.7,
                "coverage_score": 0.4,
                "total_findings": 3,
                "critical_count": 1,
                "high_count": 1,
                "medium_count": 1,
                "low_count": 0,
                "findings": [
                    {"category": "auth", "severity_level": "critical"},
                    {"category": "data", "severity_level": "high"},
                    {"category": "data", "severity_level": "medium"},
                ],
            },
        }
        result = await mixin._export_report("hm-2", {}, scope=TEST_SCOPE)
        data = _parse(result)
        heatmap = data["heatmap"]
        assert sorted(heatmap["categories"]) == ["auth", "data"]
        # 2 categories x 4 severities = 8 cells
        assert len(heatmap["cells"]) == 8

    @pytest.mark.asyncio
    async def test_heatmap_uses_vulnerabilities_fallback(self, mixin):
        """When findings key is missing, use vulnerabilities."""
        runs = get_gauntlet_runs()
        runs["hm-3"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "hm-3",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 1,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 1,
                "low_count": 0,
                "vulnerabilities": [
                    {"category": "config", "severity": "medium"},
                ],
            },
        }
        result = await mixin._export_report("hm-3", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert "config" in data["heatmap"]["categories"]

    @pytest.mark.asyncio
    async def test_heatmap_empty_findings(self, mixin):
        runs = get_gauntlet_runs()
        runs["hm-4"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "hm-4",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.99,
                "robustness_score": 0.99,
                "risk_score": 0.01,
                "coverage_score": 0.99,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
        }
        result = await mixin._export_report("hm-4", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["heatmap"]["cells"] == []
        assert data["heatmap"]["categories"] == []

    @pytest.mark.asyncio
    async def test_heatmap_finding_severity_fallback(self, mixin):
        """If severity_level is missing, falls back to severity field."""
        runs = get_gauntlet_runs()
        runs["hm-5"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "hm-5",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 1,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 1,
                "findings": [
                    {"category": "net", "severity": "low"},
                ],
            },
        }
        result = await mixin._export_report("hm-5", {}, scope=TEST_SCOPE)
        data = _parse(result)
        low_cell = next(
            c for c in data["heatmap"]["cells"] if c["severity"] == "low" and c["category"] == "net"
        )
        assert low_cell["count"] == 1


# ============================================================================
# _export_report - HTML format
# ============================================================================


class TestExportReportHTML:
    """Tests for _export_report with format=html and full_html."""

    def _make_run(self, gauntlet_id="html-1", verdict="APPROVED"):
        return {
            "org_id": TEST_ORG,
            "gauntlet_id": gauntlet_id,
            "status": "completed",
            "result": {
                "verdict": verdict,
                "confidence": 0.95,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.85,
                "total_findings": 1,
                "critical_count": 0,
                "high_count": 1,
                "medium_count": 0,
                "low_count": 0,
                "findings": [
                    {
                        "category": "auth",
                        "severity_level": "high",
                        "title": "Weak auth",
                        "description": "Uses basic auth",
                    },
                ],
            },
            "input_summary": "Test input",
            "input_type": "text",
            "input_hash": "hash123",
            "created_at": "2025-01-01T00:00:00",
            "completed_at": "2025-01-01T00:05:00",
        }

    @pytest.mark.asyncio
    async def test_html_format(self, mixin):
        runs = get_gauntlet_runs()
        runs["html-1"] = self._make_run()
        result = await mixin._export_report("html-1", {"format": "html"}, scope=TEST_SCOPE)
        assert result.status_code == 200
        assert result.content_type == "text/html"
        body = result.body.decode("utf-8")
        assert "<!DOCTYPE html>" in body
        assert "APPROVED" in body

    @pytest.mark.asyncio
    async def test_full_html_format(self, mixin):
        runs = get_gauntlet_runs()
        runs["html-2"] = self._make_run("html-2")
        result = await mixin._export_report("html-2", {"format": "full_html"}, scope=TEST_SCOPE)
        assert result.status_code == 200
        assert result.content_type == "text/html"

    @pytest.mark.asyncio
    async def test_html_verdict_color_approved(self, mixin):
        runs = get_gauntlet_runs()
        runs["vc-1"] = self._make_run("vc-1", "APPROVED")
        result = await mixin._export_report("vc-1", {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        assert "#22c55e" in body  # green for APPROVED

    @pytest.mark.asyncio
    async def test_html_verdict_color_rejected(self, mixin):
        runs = get_gauntlet_runs()
        runs["vc-2"] = self._make_run("vc-2", "REJECTED")
        result = await mixin._export_report("vc-2", {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        assert "#ef4444" in body  # red for REJECTED

    @pytest.mark.asyncio
    async def test_html_verdict_color_pass(self, mixin):
        runs = get_gauntlet_runs()
        runs["vc-3"] = self._make_run("vc-3", "PASS")
        result = await mixin._export_report("vc-3", {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        assert "#22c55e" in body  # green for PASS

    @pytest.mark.asyncio
    async def test_html_verdict_color_fail(self, mixin):
        runs = get_gauntlet_runs()
        runs["vc-4"] = self._make_run("vc-4", "FAIL")
        result = await mixin._export_report("vc-4", {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        assert "#ef4444" in body  # red for FAIL

    @pytest.mark.asyncio
    async def test_html_verdict_color_unknown(self, mixin):
        runs = get_gauntlet_runs()
        runs["vc-5"] = self._make_run("vc-5", "PENDING")
        result = await mixin._export_report("vc-5", {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        assert "#eab308" in body  # yellow for unknown

    @pytest.mark.asyncio
    async def test_html_xss_escape_gauntlet_id(self, mixin):
        malicious_id = '<script>alert("xss")</script>'
        runs = get_gauntlet_runs()
        runs[malicious_id] = self._make_run(malicious_id)
        result = await mixin._export_report(malicious_id, {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        # The raw script tag must NOT appear in the output
        assert "<script>" not in body

    @pytest.mark.asyncio
    async def test_html_xss_escape_verdict(self, mixin):
        runs = get_gauntlet_runs()
        run = self._make_run("xss-v")
        run["result"]["verdict"] = '<img onerror="alert(1)" src=x>'
        runs["xss-v"] = run
        result = await mixin._export_report("xss-v", {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        assert '<img onerror="alert(1)"' not in body

    @pytest.mark.asyncio
    async def test_html_findings_limit_to_20(self, mixin):
        """HTML report limits findings to 20."""
        runs = get_gauntlet_runs()
        run = self._make_run("many-f")
        run["result"]["findings"] = [
            {
                "category": f"cat-{i}",
                "severity_level": "medium",
                "title": f"F{i}",
                "description": "d",
            }
            for i in range(30)
        ]
        run["result"]["total_findings"] = 30
        runs["many-f"] = run
        result = await mixin._export_report("many-f", {"format": "html"}, scope=TEST_SCOPE)
        body = result.body.decode("utf-8")
        # Count finding divs - should be 20 max
        assert body.count('class="finding ') <= 20

    @pytest.mark.asyncio
    async def test_html_no_findings_section_when_excluded(self, mixin):
        runs = get_gauntlet_runs()
        runs["nfh-1"] = self._make_run("nfh-1")
        result = await mixin._export_report(
            "nfh-1", {"format": "html", "include_findings": "false"}, scope=TEST_SCOPE
        )
        body = result.body.decode("utf-8")
        assert "Findings Detail" not in body

    @pytest.mark.asyncio
    async def test_unsupported_format(self, mixin):
        runs = get_gauntlet_runs()
        runs["uf-1"] = self._make_run("uf-1")
        result = await mixin._export_report("uf-1", {"format": "xml"}, scope=TEST_SCOPE)
        assert result.status_code == 400
        data = _parse(result)
        assert "Unsupported format" in data.get("error", "")


# ============================================================================
# _export_report - enhanced data from GauntletResult object
# ============================================================================


class TestExportReportEnhanced:
    """Tests for enhanced report data from in-memory result_obj."""

    @pytest.mark.asyncio
    async def test_enhanced_verdict_reasoning(self, mixin):
        result_obj = MagicMock()
        result_obj.verdict_reasoning = "Strong compliance."
        result_obj.attack_summary = None
        result_obj.probe_summary = None
        result_obj.scenario_summary = None
        del result_obj.attack_summary
        del result_obj.probe_summary
        del result_obj.scenario_summary

        runs = get_gauntlet_runs()
        runs["enh-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "enh-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
            "result_obj": result_obj,
        }
        result = await mixin._export_report("enh-1", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["enhanced"]["verdict_reasoning"] == "Strong compliance."

    @pytest.mark.asyncio
    async def test_enhanced_attack_summary_dict(self, mixin):
        class AttackSummary:
            def __init__(self):
                self.total = 10
                self.passed = 8

        class ResultObj:
            def __init__(self):
                self.verdict_reasoning = None
                self.attack_summary = AttackSummary()

        result_obj = ResultObj()

        runs = get_gauntlet_runs()
        runs["enh-2"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "enh-2",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
            "result_obj": result_obj,
        }
        result = await mixin._export_report("enh-2", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["enhanced"]["attack_summary"]["total"] == 10

    @pytest.mark.asyncio
    async def test_enhanced_probe_summary_str(self, mixin):
        """When probe_summary has no __dict__, it falls back to str()."""

        class NoDict:
            __slots__ = ()

            def __str__(self):
                return "probe-info"

        result_obj = MagicMock(spec=["probe_summary"])
        result_obj.probe_summary = NoDict()

        runs = get_gauntlet_runs()
        runs["enh-3"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "enh-3",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
            "result_obj": result_obj,
        }
        result = await mixin._export_report("enh-3", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["enhanced"]["probe_summary"] == "probe-info"

    @pytest.mark.asyncio
    async def test_no_enhanced_when_no_result_obj(self, mixin, mock_storage):
        """When loading from storage, no result_obj exists so no enhanced data."""
        mock_storage.get.return_value = {
            "verdict": "APPROVED",
            "confidence": 0.9,
            "robustness_score": 0.9,
            "risk_score": 0.1,
            "coverage_score": 0.9,
            "total_findings": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
        }
        result = await mixin._export_report("no-enh", {"format": "json"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert "enhanced" not in data

    @pytest.mark.asyncio
    async def test_no_enhanced_when_result_obj_empty(self, mixin):
        """When result_obj has no enhanced attributes, no enhanced section."""
        result_obj = MagicMock(spec=[])  # empty spec = no enhanced attrs

        runs = get_gauntlet_runs()
        runs["enh-4"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "enh-4",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
            "result_obj": result_obj,
        }
        result = await mixin._export_report("enh-4", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert "enhanced" not in data


# ============================================================================
# _export_report - input/timing metadata
# ============================================================================


class TestExportReportMetadata:
    """Tests for input and timing metadata in export."""

    @pytest.mark.asyncio
    async def test_input_from_in_memory_run(self, mixin):
        runs = get_gauntlet_runs()
        runs["meta-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "meta-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
            "input_summary": "my input",
            "input_type": "code",
            "input_hash": "abc",
            "created_at": "2025-06-01T00:00:00",
            "completed_at": "2025-06-01T00:01:00",
        }
        result = await mixin._export_report("meta-1", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["input"]["summary"] == "my input"
        assert data["input"]["type"] == "code"
        assert data["input"]["hash"] == "abc"
        assert data["timing"]["created_at"] == "2025-06-01T00:00:00"
        assert data["timing"]["completed_at"] == "2025-06-01T00:01:00"

    @pytest.mark.asyncio
    async def test_input_from_storage(self, mixin, mock_storage):
        mock_storage.get.return_value = {
            "verdict": "APPROVED",
            "confidence": 0.9,
            "robustness_score": 0.9,
            "risk_score": 0.1,
            "coverage_score": 0.9,
            "total_findings": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "input_summary": "stored summary",
            "input_type": "text",
            "input_hash": "def",
        }
        result = await mixin._export_report("stored-meta", {"format": "json"}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["input"]["summary"] == "stored summary"
        # When loaded from storage, timing is empty strings
        assert data["timing"]["created_at"] == ""

    @pytest.mark.asyncio
    async def test_generated_at_present(self, mixin):
        runs = get_gauntlet_runs()
        runs["gen-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "gen-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
        }
        result = await mixin._export_report("gen-1", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert "generated_at" in data
        # Should be a valid ISO timestamp
        datetime.fromisoformat(data["generated_at"])


# ============================================================================
# _export_report - vulnerabilities compatibility
# ============================================================================


class TestExportReportVulnerabilityCompat:
    """Tests for findings/vulnerabilities compatibility in export."""

    @pytest.mark.asyncio
    async def test_findings_from_vulnerabilities_key(self, mixin):
        """When 'findings' is absent, 'vulnerabilities' is used."""
        runs = get_gauntlet_runs()
        runs["compat-1"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "compat-1",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 1,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 1,
                "vulnerabilities": [
                    {"category": "net", "severity_level": "low", "title": "Open port"},
                ],
            },
        }
        result = await mixin._export_report("compat-1", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert len(data["findings"]) == 1
        assert data["findings"][0]["title"] == "Open port"

    @pytest.mark.asyncio
    async def test_findings_preferred_over_vulnerabilities(self, mixin):
        """When both 'findings' and 'vulnerabilities' exist, 'findings' wins."""
        runs = get_gauntlet_runs()
        runs["compat-2"] = {
            "org_id": TEST_ORG,
            "gauntlet_id": "compat-2",
            "status": "completed",
            "result": {
                "verdict": "APPROVED",
                "confidence": 0.9,
                "robustness_score": 0.9,
                "risk_score": 0.1,
                "coverage_score": 0.9,
                "total_findings": 1,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 1,
                "low_count": 0,
                "findings": [
                    {"category": "a", "severity_level": "medium", "title": "Finding A"},
                ],
                "vulnerabilities": [
                    {"category": "b", "severity_level": "high", "title": "Vuln B"},
                ],
            },
        }
        result = await mixin._export_report("compat-2", {}, scope=TEST_SCOPE)
        data = _parse(result)
        assert data["findings"][0]["title"] == "Finding A"

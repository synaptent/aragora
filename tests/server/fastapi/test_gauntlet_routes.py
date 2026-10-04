"""
Tests for FastAPI gauntlet route endpoints.

Covers:
- Start gauntlet run (auth required)
- Get gauntlet status
- Get gauntlet findings
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app
from aragora.server.handlers.gauntlet import storage as gauntlet_handler_storage
from aragora.tenancy.record_scope import OrgScope, require_org_scope_fastapi

ORG_ID = "org-1"


@pytest.fixture
def app():
    """Create a test FastAPI app whose callers belong to ``ORG_ID``."""
    app = create_app()
    app.dependency_overrides[require_org_scope_fastapi] = lambda: OrgScope(
        org_id=ORG_ID, user_id="user-1", role="member"
    )
    return app


@pytest.fixture
def mock_gauntlet_storage():
    """Create a mock gauntlet storage."""
    store = MagicMock()
    store.get = MagicMock(return_value=None)
    store.get_inflight = MagicMock(return_value=None)
    store.save_inflight = MagicMock()
    store.list_recent = MagicMock(return_value=[])
    store.count = MagicMock(return_value=0)
    return store


@pytest.fixture
def client(app, mock_gauntlet_storage):
    """Create a test client with mocked context."""
    app.state.context = {
        "storage": MagicMock(),
        "elo_system": MagicMock(),
        "user_store": None,
        "rbac_checker": MagicMock(),
        "decision_service": MagicMock(),
        "gauntlet_storage": mock_gauntlet_storage,
    }
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def sample_gauntlet_result():
    """Sample gauntlet result for testing."""
    return {
        "gauntlet_id": "gauntlet-20260211-abc123",
        "status": "completed",
        "input_type": "spec",
        "input_summary": "Test input content for stress-testing",
        "persona": "security",
        "created_at": "2026-02-11T12:00:00",
        "completed_at": "2026-02-11T12:05:00",
        "result": {
            "gauntlet_id": "gauntlet-20260211-abc123",
            "verdict": "APPROVED",
            "confidence": 0.85,
            "risk_score": 0.15,
            "robustness_score": 0.85,
            "coverage_score": 0.9,
            "total_findings": 2,
            "critical_count": 0,
            "high_count": 1,
            "medium_count": 1,
            "low_count": 0,
            "findings": [
                {
                    "id": "f-001",
                    "category": "security",
                    "severity": "HIGH",
                    "severity_level": "HIGH",
                    "title": "SQL injection risk",
                    "description": "User input not sanitized",
                },
                {
                    "id": "f-002",
                    "category": "performance",
                    "severity": "MEDIUM",
                    "severity_level": "MEDIUM",
                    "title": "N+1 query",
                    "description": "Database queries not batched",
                },
            ],
        },
    }


class TestStartGauntlet:
    """Tests for POST /api/v2/gauntlet/run."""

    def test_start_gauntlet_requires_auth(self, client):
        """Start gauntlet should require authentication."""
        response = client.post(
            "/api/v2/gauntlet/run",
            json={
                "input_content": "Design a secure API",
                "input_type": "spec",
            },
        )
        # Should return 401 because no Authorization header
        assert response.status_code == 401

    def test_start_gauntlet_requires_input_content(self, client):
        """Start gauntlet requires input_content field."""
        response = client.post(
            "/api/v2/gauntlet/run",
            json={"input_type": "spec"},
        )
        # Should return 422 (validation error) or 401 (auth first)
        assert response.status_code in [401, 422]


class TestGetGauntletStatus:
    """Tests for GET /api/v2/gauntlet/{run_id}/status."""

    def test_get_status_not_found(self, client):
        """Get status for nonexistent run returns 404."""
        response = client.get("/api/v2/gauntlet/nonexistent-id/status")
        assert response.status_code == 404

    def test_get_status_from_storage(self, client, mock_gauntlet_storage):
        """Get status returns data from persistent storage."""
        mock_gauntlet_storage.get.return_value = {
            "gauntlet_id": "gauntlet-test",
            "verdict": "APPROVED",
            "confidence": 0.85,
        }

        response = client.get("/api/v2/gauntlet/gauntlet-test/status")
        assert response.status_code == 200
        data = response.json()
        assert data["gauntlet_id"] == "gauntlet-test"
        assert data["status"] == "completed"
        mock_gauntlet_storage.get.assert_called_once_with("gauntlet-test", org_id=ORG_ID)

    def test_get_status_from_inflight(self, client, mock_gauntlet_storage):
        """Get status checks inflight table for running tasks."""
        inflight_obj = MagicMock()
        inflight_obj.org_id = ORG_ID
        inflight_obj.to_dict.return_value = {
            "gauntlet_id": "gauntlet-running",
            "status": "running",
            "input_type": "spec",
            "input_summary": "Testing...",
            "persona": None,
            "created_at": "2026-02-11T12:00:00",
        }
        mock_gauntlet_storage.get_inflight.return_value = inflight_obj
        mock_gauntlet_storage.get.return_value = None

        response = client.get("/api/v2/gauntlet/gauntlet-running/status")
        assert response.status_code == 200
        data = response.json()
        assert data["gauntlet_id"] == "gauntlet-running"
        assert data["status"] == "running"


class TestGetGauntletFindings:
    """Tests for GET /api/v2/gauntlet/{run_id}/findings."""

    def test_get_findings_not_found(self, client):
        """Get findings for nonexistent run returns 404."""
        response = client.get("/api/v2/gauntlet/nonexistent-id/findings")
        assert response.status_code == 404

    def test_get_findings_from_storage(self, client, mock_gauntlet_storage):
        """Get findings returns findings from completed run."""
        mock_gauntlet_storage.get.return_value = {
            "gauntlet_id": "gauntlet-done",
            "verdict": "APPROVED",
            "confidence": 0.85,
            "findings": [
                {
                    "id": "f-001",
                    "category": "security",
                    "severity": "HIGH",
                    "severity_level": "HIGH",
                    "title": "SQL injection risk",
                    "description": "User input not sanitized",
                },
                {
                    "id": "f-002",
                    "category": "performance",
                    "severity": "MEDIUM",
                    "severity_level": "MEDIUM",
                    "title": "N+1 query",
                    "description": "Database queries not batched",
                },
            ],
        }

        response = client.get("/api/v2/gauntlet/gauntlet-done/findings")
        assert response.status_code == 200
        data = response.json()
        assert data["gauntlet_id"] == "gauntlet-done"
        assert len(data["findings"]) == 2
        assert data["total"] == 2
        assert data["verdict"] == "APPROVED"
        assert data["confidence"] == 0.85

    def test_get_findings_filter_by_severity(self, client, mock_gauntlet_storage):
        """Get findings supports severity filter."""
        mock_gauntlet_storage.get.return_value = {
            "gauntlet_id": "gauntlet-done",
            "verdict": "APPROVED",
            "confidence": 0.85,
            "findings": [
                {
                    "id": "f-001",
                    "category": "security",
                    "severity": "HIGH",
                    "severity_level": "HIGH",
                    "title": "High issue",
                    "description": "Important issue",
                },
                {
                    "id": "f-002",
                    "category": "performance",
                    "severity": "MEDIUM",
                    "severity_level": "MEDIUM",
                    "title": "Medium issue",
                    "description": "Less important",
                },
            ],
        }

        response = client.get("/api/v2/gauntlet/gauntlet-done/findings?severity=HIGH")
        assert response.status_code == 200
        data = response.json()
        assert len(data["findings"]) == 1
        assert data["findings"][0]["severity"] == "HIGH"
        assert data["total"] == 1

    def test_get_findings_pagination(self, client, mock_gauntlet_storage):
        """Get findings supports pagination."""
        findings = [
            {
                "id": f"f-{i:03d}",
                "category": "test",
                "severity": "LOW",
                "severity_level": "LOW",
                "title": f"Finding {i}",
                "description": f"Description {i}",
            }
            for i in range(10)
        ]
        mock_gauntlet_storage.get.return_value = {
            "gauntlet_id": "gauntlet-many",
            "verdict": "NEEDS_REVIEW",
            "confidence": 0.5,
            "findings": findings,
        }

        response = client.get("/api/v2/gauntlet/gauntlet-many/findings?limit=3&offset=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["findings"]) == 3
        assert data["total"] == 10
        assert data["findings"][0]["id"] == "f-002"

    def test_get_findings_empty_for_pending_run(self, client, mock_gauntlet_storage):
        """Get findings returns empty for pending/running gauntlet."""
        with patch.dict(
            gauntlet_handler_storage._gauntlet_runs,
            {"gauntlet-pending": {"status": "pending", "result": None, "org_id": ORG_ID}},
        ):
            # Make storage also not find it (so in-memory check kicks in)
            mock_gauntlet_storage.get.return_value = None

            response = client.get("/api/v2/gauntlet/gauntlet-pending/findings")
            assert response.status_code == 200
            data = response.json()
            assert len(data["findings"]) == 0
            assert data["total"] == 0

"""Tests for config validator Redis requirements."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aragora.config.validator import validate_all


@pytest.fixture
def redis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear Redis-related env vars between tests."""
    for key in (
        "ARAGORA_STATE_BACKEND",
        "ARAGORA_REDIS_URL",
        "REDIS_URL",
        "ARAGORA_REDIS_MODE",
        "ARAGORA_REDIS_SENTINEL_HOSTS",
        "ARAGORA_REDIS_CLUSTER_NODES",
        "ARAGORA_ENV",
    ):
        monkeypatch.delenv(key, raising=False)


def test_validate_all_accepts_sentinel_when_distributed(
    monkeypatch: pytest.MonkeyPatch, redis_env: None
) -> None:
    """Sentinel config should satisfy distributed-state Redis requirement."""
    monkeypatch.setenv("ARAGORA_ENV", "development")
    monkeypatch.setenv("ARAGORA_REDIS_MODE", "sentinel")
    monkeypatch.setenv(
        "ARAGORA_REDIS_SENTINEL_HOSTS",
        "sentinel-1:26379,sentinel-2:26379,sentinel-3:26379",
    )
    monkeypatch.setenv("ARAGORA_REDIS_SENTINEL_MASTER", "mymaster")

    with patch("aragora.config.validator.is_distributed_state_required", return_value=True):
        result = validate_all()

    assert result["config_summary"]["redis_configured"] is True
    assert result["config_summary"]["redis_mode"] == "sentinel"
    assert all("Distributed state required" not in err for err in result["errors"])


def test_validate_all_reports_missing_redis_for_distributed_state(
    monkeypatch: pytest.MonkeyPatch, redis_env: None
) -> None:
    """Distributed state should fail validation without Redis URL/sentinel/cluster config."""
    monkeypatch.setenv("ARAGORA_ENV", "development")

    with patch("aragora.config.validator.is_distributed_state_required", return_value=True):
        result = validate_all()

    assert any("Distributed state required" in err for err in result["errors"])

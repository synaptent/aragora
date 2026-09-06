"""Tests for aragora.reputation.manifold_bridge (AGT-03 + AGT-05 / #6064, #6066)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from aragora.reputation.manifold_bridge import (
    bridge_from_manifold_market,
    reputation_flow_enabled,
)
from aragora.reputation.types import DOMAIN_PREDICTION_MARKET

# ---------------------------------------------------------------------------
# Structural stubs — no connector import required in tests
# ---------------------------------------------------------------------------

_CLOSE_MS = 1_746_057_600_000  # 2025-05-01T00:00:00Z
_RESOLVED_MS = 1_746_144_000_000  # 2025-05-02T00:00:00Z


@dataclass(frozen=True)
class _Market:
    """Structural stand-in for ManifoldMarket — no network import needed."""

    market_id: str
    slug: str
    question: str
    creator_username: str
    created_time_ms: int
    close_time_ms: int | None
    resolution: str | None
    is_resolved: bool
    outcome_type: str
    total_liquidity: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Resolution:
    """Structural stand-in for ManifoldResolution."""

    market_id: str
    outcome: str  # "yes" | "no" | "inconclusive"
    resolved_at_ms: int | None
    raw: dict[str, Any] = field(default_factory=dict)


def _market(
    market_id: str = "mkt_abc",
    question: str = "Will Aragora ship crux-finding?",
    resolution: str | None = "YES",
    is_resolved: bool = True,
    close_time_ms: int | None = _CLOSE_MS,
) -> _Market:
    return _Market(
        market_id=market_id,
        slug="aragora-crux-finding",
        question=question,
        creator_username="alice",
        created_time_ms=1_743_465_600_000,
        close_time_ms=close_time_ms,
        resolution=resolution,
        is_resolved=is_resolved,
        outcome_type="BINARY",
    )


def _res(
    outcome: str = "yes",
    market_id: str = "mkt_abc",
    resolved_at_ms: int | None = _RESOLVED_MS,
) -> _Resolution:
    return _Resolution(
        market_id=market_id,
        outcome=outcome,
        resolved_at_ms=resolved_at_ms,
    )


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------


class TestFeatureGate:
    def test_off_by_default_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_REPUTATION_FLOW_ENABLED", raising=False)
        assert reputation_flow_enabled() is False
        with pytest.raises(RuntimeError, match="ARAGORA_REPUTATION_FLOW_ENABLED"):
            bridge_from_manifold_market(_market(), _res(), "ag", 0.8)

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE"])
    def test_truthy_values_enable(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", val)
        assert reputation_flow_enabled() is True
        claim, _ = bridge_from_manifold_market(_market(), _res(), "ag", 0.8)
        assert claim.agent_id == "ag"

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsy_values_block(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", val)
        with pytest.raises(RuntimeError):
            bridge_from_manifold_market(_market(), _res(), "ag", 0.8)

    def test_require_enabled_false_bypasses_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_REPUTATION_FLOW_ENABLED", raising=False)
        claim, resolved = bridge_from_manifold_market(
            _market(), _res(), "ag", 0.8, require_enabled=False
        )
        assert claim.agent_id == "ag"
        assert resolved.outcome == "yes"


# ---------------------------------------------------------------------------
# Outcome mapping
# ---------------------------------------------------------------------------


class TestOutcomeMapping:
    @pytest.fixture(autouse=True)
    def _on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", "1")

    def test_yes_outcome(self) -> None:
        _, r = bridge_from_manifold_market(_market(), _res(outcome="yes"), "ag", 0.8)
        assert r.outcome == "yes"

    def test_no_outcome(self) -> None:
        _, r = bridge_from_manifold_market(_market(resolution="NO"), _res(outcome="no"), "ag", 0.2)
        assert r.outcome == "no"

    @pytest.mark.parametrize("raw_outcome", ["inconclusive", "CANCEL", "mkt", "", "MKT"])
    def test_inconclusive_passthrough(self, raw_outcome: str) -> None:
        _, r = bridge_from_manifold_market(
            _market(resolution="CANCEL"), _res(outcome="inconclusive"), "ag", 0.5
        )
        assert r.outcome == "inconclusive"

    def test_unknown_outcome_is_inconclusive(self) -> None:
        _, r = bridge_from_manifold_market(_market(), _res(outcome="CHOOSE_ONE"), "ag", 0.5)
        assert r.outcome == "inconclusive"


# ---------------------------------------------------------------------------
# Claim shape
# ---------------------------------------------------------------------------


class TestClaimShape:
    @pytest.fixture(autouse=True)
    def _on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", "1")

    def test_domain_and_statement(self) -> None:
        claim, _ = bridge_from_manifold_market(
            _market(question="Will crux-finding ship?"), _res(), "ag", 0.73
        )
        assert claim.domain == DOMAIN_PREDICTION_MARKET
        assert claim.statement == "Will crux-finding ship?"
        assert claim.predicted_probability == pytest.approx(0.73)

    def test_position_derived_from_probability(self) -> None:
        yes_claim, _ = bridge_from_manifold_market(_market(), _res(), "ag", 0.5)
        no_claim, _ = bridge_from_manifold_market(_market(), _res(), "ag", 0.49)
        assert yes_claim.position == "yes"
        assert no_claim.position == "no"

    def test_resolution_source_default_and_override(self) -> None:
        c, r = bridge_from_manifold_market(_market(), _res(), "ag", 0.8)
        assert c.resolution_source == r.resolution_source == "manifold"
        c2, r2 = bridge_from_manifold_market(_market(), _res(), "ag", 0.8, resolution_source="x")
        assert c2.resolution_source == r2.resolution_source == "x"

    def test_resolution_id_is_market_id(self) -> None:
        claim, _ = bridge_from_manifold_market(_market(market_id="mkt_xyz"), _res(), "ag", 0.8)
        assert claim.resolution_id == "mkt_xyz"

    def test_provenance_keys(self) -> None:
        claim, _ = bridge_from_manifold_market(_market(), _res(), "ag", 0.8)
        for key in (
            "market_id",
            "slug",
            "outcome_type",
            "close_time_ms",
            "close_time_iso",
            "submitted_at",
        ):
            assert key in claim.provenance

    def test_evidence_keys(self) -> None:
        _, resolved = bridge_from_manifold_market(_market(), _res(), "ag", 0.8)
        for key in ("market_id", "outcome", "resolved_at_ms", "question", "creator_username"):
            assert key in resolved.evidence

    def test_evidence_market_id_matches(self) -> None:
        _, resolved = bridge_from_manifold_market(
            _market(market_id="mkt_q"), _res(market_id="mkt_q"), "ag", 0.8
        )
        assert resolved.evidence["market_id"] == "mkt_q"

    def test_claim_id_content_addressed(self) -> None:
        m = _market()
        c1, _ = bridge_from_manifold_market(m, _res(), "ag", 0.8, require_enabled=False)
        c2, _ = bridge_from_manifold_market(m, _res(), "ag", 0.8, require_enabled=False)
        assert c1.claim_id == c2.claim_id

    def test_claim_id_differs_by_agent(self) -> None:
        m = _market()
        ca, _ = bridge_from_manifold_market(m, _res(), "ag_a", 0.8, require_enabled=False)
        cb, _ = bridge_from_manifold_market(m, _res(), "ag_b", 0.8, require_enabled=False)
        assert ca.claim_id != cb.claim_id

    def test_claim_id_matches_resolved_claim_id(self) -> None:
        claim, resolved = bridge_from_manifold_market(
            _market(), _res(), "ag", 0.8, require_enabled=False
        )
        assert claim.claim_id == resolved.claim_id

    def test_resolved_at_from_ms(self) -> None:
        _, r = bridge_from_manifold_market(
            _market(), _res(resolved_at_ms=_RESOLVED_MS), "ag", 0.8, require_enabled=False
        )
        assert "2025-05-02" in r.resolved_at

    def test_resolved_at_none_falls_back_to_now(self) -> None:
        _, r = bridge_from_manifold_market(
            _market(), _res(resolved_at_ms=None), "ag", 0.8, require_enabled=False
        )
        assert r.resolved_at  # non-empty fallback

    def test_close_time_none_is_none_in_provenance(self) -> None:
        claim, _ = bridge_from_manifold_market(
            _market(close_time_ms=None), _res(), "ag", 0.7, require_enabled=False
        )
        assert claim.provenance["close_time_ms"] is None
        assert claim.provenance["close_time_iso"] is None

    def test_stake_params_forwarded(self) -> None:
        claim, r = bridge_from_manifold_market(
            _market(),
            _res(),
            "ag",
            0.8,
            stake_units=5,
            stake_policy="scaled",
            require_enabled=False,
        )
        assert claim.stake_units == 5
        assert claim.stake_policy == "scaled"
        assert claim.claim_id == r.claim_id

    def test_boundary_probabilities_valid(self) -> None:
        c0, _ = bridge_from_manifold_market(_market(), _res(), "ag", 0.0, require_enabled=False)
        c1, _ = bridge_from_manifold_market(_market(), _res(), "ag", 1.0, require_enabled=False)
        assert c0.predicted_probability == pytest.approx(0.0)
        assert c1.predicted_probability == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    @pytest.fixture(autouse=True)
    def _on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_REPUTATION_FLOW_ENABLED", "1")

    def test_unresolved_market_raises(self) -> None:
        with pytest.raises(ValueError, match="not resolved"):
            bridge_from_manifold_market(
                _market(is_resolved=False, resolution=None), _res(), "ag", 0.8
            )

    @pytest.mark.parametrize("prob", [1.001, -0.001, 2.0, -1.0])
    def test_out_of_range_probability_raises(self, prob: float) -> None:
        with pytest.raises(ValueError, match="predicted_probability"):
            bridge_from_manifold_market(_market(), _res(), "ag", prob)

    @pytest.mark.parametrize("units", [0, -1, -100])
    def test_invalid_stake_units_raises(self, units: int) -> None:
        with pytest.raises(ValueError, match="stake_units"):
            bridge_from_manifold_market(_market(), _res(), "ag", 0.8, stake_units=units)

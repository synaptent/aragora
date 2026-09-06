"""Tests for the AGT-02 A2A reputation read endpoint (issue #6063 sub-deliverable 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aragora.protocols.a2a.reputation import (
    AGENT_REPUTATION_SCHEMA_VERSION,
    ReputationEndpointError,
    read_agent_reputation,
    read_all_agents,
    reputation_endpoint_enabled,
)
from aragora.reputation.store import ReputationStore
from aragora.reputation.types import (
    DOMAIN_DEBATE_POSITION,
    DOMAIN_PREDICTION_MARKET,
    ReputationDelta,
)

_FLAG = "ARAGORA_A2A_REPUTATION_ENABLED"
_NOW = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)


def _delta(
    *,
    agent_id: str,
    domain: str,
    delta: float,
    delta_id: str = "d1",
    applied_at: str | None = None,
    decay_half_life_days: float | None = None,
) -> ReputationDelta:
    return ReputationDelta(
        delta_id=delta_id,
        agent_id=agent_id,
        domain=domain,
        claim_id="cl1",
        resolution_id="res1",
        delta=delta,
        scoring_rule="binary",
        applied_at=applied_at or datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        decay_half_life_days=decay_half_life_days,
        reason={},
    )


@pytest.fixture()
def store() -> ReputationStore:
    return ReputationStore()


@pytest.fixture()
def enabled(store: ReputationStore, monkeypatch: pytest.MonkeyPatch) -> ReputationStore:
    monkeypatch.setenv(_FLAG, "1")
    return store


# --- Feature flag ---


@pytest.mark.parametrize(
    "v,expect",
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
    ],
)
def test_flag_gate(monkeypatch: pytest.MonkeyPatch, v: str, expect: bool) -> None:
    monkeypatch.setenv(_FLAG, v)
    assert reputation_endpoint_enabled() is expect


def test_read_blocked_when_disabled(
    store: ReputationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_FLAG, raising=False)
    with pytest.raises(ReputationEndpointError, match=_FLAG):
        read_agent_reputation("a", store)


def test_read_all_blocked_when_disabled(
    store: ReputationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_FLAG, raising=False)
    with pytest.raises(ReputationEndpointError, match=_FLAG):
        read_all_agents(store)


# --- read_agent_reputation ---


def test_unknown_agent_zero(enabled: ReputationStore) -> None:
    v = read_agent_reputation("nobody", enabled)
    assert v.overall_score == 0.0 and v.delta_count == 0 and v.domains == ()
    assert v.schema_version == AGENT_REPUTATION_SCHEMA_VERSION


def test_single_domain(enabled: ReputationStore) -> None:
    enabled.record_delta(
        _delta(agent_id="a1", domain=DOMAIN_PREDICTION_MARKET, delta=0.8, delta_id="d1")
    )
    v = read_agent_reputation("a1", enabled)
    assert v.overall_score == pytest.approx(0.8)
    assert len(v.domains) == 1 and v.domains[0].domain == DOMAIN_PREDICTION_MARKET


def test_multi_domain_slices(enabled: ReputationStore) -> None:
    enabled.record_delta(
        _delta(agent_id="a1", domain=DOMAIN_PREDICTION_MARKET, delta=1.0, delta_id="d1")
    )
    enabled.record_delta(
        _delta(agent_id="a1", domain=DOMAIN_DEBATE_POSITION, delta=0.5, delta_id="d2")
    )
    v = read_agent_reputation("a1", enabled)
    assert v.overall_score == pytest.approx(1.5)
    assert {s.domain for s in v.domains} == {DOMAIN_PREDICTION_MARKET, DOMAIN_DEBATE_POSITION}
    assert v.domains == tuple(sorted(v.domains, key=lambda s: s.domain))


def test_to_dict_has_required_keys(enabled: ReputationStore) -> None:
    enabled.record_delta(
        _delta(agent_id="a1", domain=DOMAIN_PREDICTION_MARKET, delta=2.0, delta_id="d1")
    )
    d = read_agent_reputation("a1", enabled).to_dict()
    assert {
        "schema_version",
        "agent_id",
        "overall_score",
        "delta_count",
        "domains",
        "queried_at",
    } <= d.keys()


def test_decay_reduces_score(enabled: ReputationStore) -> None:
    old = (datetime.now(tz=UTC) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    enabled.record_delta(
        _delta(
            agent_id="a1",
            domain=DOMAIN_PREDICTION_MARKET,
            delta=1.0,
            delta_id="d1",
            applied_at=old,
            decay_half_life_days=7.0,
        )
    )
    assert (
        read_agent_reputation("a1", enabled, apply_decay=True).overall_score
        < read_agent_reputation("a1", enabled, apply_decay=False).overall_score
    )


def test_queried_at_uses_supplied_now(enabled: ReputationStore) -> None:
    assert "2026-05-17" in read_agent_reputation("x", enabled, now=_NOW).queried_at


def test_most_recent_delta_at(enabled: ReputationStore) -> None:
    ts = "2026-05-01T10:00:00Z"
    enabled.record_delta(
        _delta(
            agent_id="a1", domain=DOMAIN_PREDICTION_MARKET, delta=1.0, delta_id="d1", applied_at=ts
        )
    )
    assert read_agent_reputation("a1", enabled).domains[0].most_recent_delta_at == ts


def test_domain_slice_to_dict_keys(enabled: ReputationStore) -> None:
    enabled.record_delta(
        _delta(agent_id="a1", domain=DOMAIN_PREDICTION_MARKET, delta=1.0, delta_id="d1")
    )
    v = read_agent_reputation("a1", enabled)
    d = v.domains[0].to_dict()
    assert {"domain", "score", "delta_count", "most_recent_delta_at"} == d.keys()


# --- read_all_agents ---


def test_read_all_empty(enabled: ReputationStore) -> None:
    assert read_all_agents(enabled) == []


def test_read_all_sorted_desc(enabled: ReputationStore) -> None:
    enabled.record_delta(
        _delta(agent_id="low", domain=DOMAIN_PREDICTION_MARKET, delta=0.1, delta_id="d1")
    )
    enabled.record_delta(
        _delta(agent_id="high", domain=DOMAIN_PREDICTION_MARKET, delta=5.0, delta_id="d2")
    )
    views = read_all_agents(enabled)
    assert views[0].agent_id == "high"


def test_read_all_stable_sort_on_tie(enabled: ReputationStore) -> None:
    for aid in ["beta", "alpha"]:
        enabled.record_delta(
            _delta(agent_id=aid, domain=DOMAIN_PREDICTION_MARKET, delta=1.0, delta_id=f"d-{aid}")
        )
    views = read_all_agents(enabled)
    assert views[0].agent_id == "alpha"

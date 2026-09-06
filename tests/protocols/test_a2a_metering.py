"""Unit tests for aragora.protocols.a2a.metering (AGT-02).

Verifies flag-gate semantics, record creation, content-addressing, and
serialisation.  No network, no subprocess, no queue mutation.
"""

from __future__ import annotations

import json
import os

import pytest

import aragora.protocols.a2a.metering as _metering_module
from aragora.protocols.a2a.metering import (
    AgentMeteringRecord,
    METERING_SCHEMA_VERSION,
    agent_metering_enabled,
    create_metering_record,
    enable_agent_metering,
    reset_agent_metering,
)


# ---------------------------------------------------------------------------
# Autouse fixture: always restore module-level override after each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_metering_override() -> pytest.IterableFixture:  # type: ignore[type-arg]
    reset_agent_metering()
    yield
    reset_agent_metering()


# ---------------------------------------------------------------------------
# Flag-gate tests
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_AGENT_METERING_ENABLED", raising=False)
        assert not agent_metering_enabled()

    def test_enabled_via_env_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_AGENT_METERING_ENABLED", "1")
        assert agent_metering_enabled()

    def test_enabled_via_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_AGENT_METERING_ENABLED", "true")
        assert agent_metering_enabled()

    def test_enabled_via_env_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_AGENT_METERING_ENABLED", "yes")
        assert agent_metering_enabled()

    def test_enabled_via_env_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_AGENT_METERING_ENABLED", "on")
        assert agent_metering_enabled()

    def test_arbitrary_string_not_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_AGENT_METERING_ENABLED", "maybe")
        assert not agent_metering_enabled()

    def test_enable_helper_sets_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_AGENT_METERING_ENABLED", raising=False)
        enable_agent_metering()
        assert agent_metering_enabled()
        assert _metering_module._metering_enabled_override is True  # noqa: SLF001

    def test_enable_does_not_mutate_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_AGENT_METERING_ENABLED", raising=False)
        before = dict(os.environ)
        enable_agent_metering()
        assert os.environ == before

    def test_reset_clears_override(self) -> None:
        enable_agent_metering()
        reset_agent_metering()
        assert _metering_module._metering_enabled_override is None  # noqa: SLF001
        assert not agent_metering_enabled()

    def test_override_takes_priority_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_AGENT_METERING_ENABLED", raising=False)
        enable_agent_metering()
        assert agent_metering_enabled()

    def test_create_raises_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARAGORA_AGENT_METERING_ENABLED", raising=False)
        with pytest.raises(RuntimeError, match="ARAGORA_AGENT_METERING_ENABLED"):
            create_metering_record(agent_id="ag-1", session_id="sess-1")


# ---------------------------------------------------------------------------
# Record creation tests
# ---------------------------------------------------------------------------


class TestCreateMeteringRecord:
    def test_basic_round_trip(self) -> None:
        enable_agent_metering()
        rec = create_metering_record(
            agent_id="ag-123",
            session_id="sess-abc",
            compute_units=42.0,
            debate_cost_usd=0.05,
            verifier_cost_usd=0.01,
            timestamp="2026-08-25T12:00:00Z",
        )
        assert rec.agent_id == "ag-123"
        assert rec.session_id == "sess-abc"
        assert rec.compute_units == 42.0
        assert rec.debate_cost_usd == 0.05
        assert rec.verifier_cost_usd == 0.01
        assert rec.timestamp == "2026-08-25T12:00:00Z"
        assert rec.schema_version == METERING_SCHEMA_VERSION

    def test_defaults_to_zero_costs(self) -> None:
        enable_agent_metering()
        rec = create_metering_record(agent_id="ag-1", session_id="sess-1")
        assert rec.compute_units == 0.0
        assert rec.debate_cost_usd == 0.0
        assert rec.verifier_cost_usd == 0.0

    def test_content_hash_non_empty(self) -> None:
        enable_agent_metering()
        rec = create_metering_record(
            agent_id="ag-1",
            session_id="sess-1",
            timestamp="2026-08-25T00:00:00Z",
        )
        assert len(rec.content_hash) == 64  # SHA-256 hex

    def test_content_hash_deterministic(self) -> None:
        enable_agent_metering()
        kwargs = dict(
            agent_id="ag-det",
            session_id="sess-det",
            compute_units=10.0,
            debate_cost_usd=0.02,
            verifier_cost_usd=0.005,
            timestamp="2026-08-25T09:00:00Z",
        )
        r1 = create_metering_record(**kwargs)
        r2 = create_metering_record(**kwargs)
        assert r1.content_hash == r2.content_hash

    def test_different_inputs_produce_different_hashes(self) -> None:
        enable_agent_metering()
        r1 = create_metering_record(
            agent_id="ag-1",
            session_id="sess-1",
            compute_units=1.0,
            timestamp="2026-08-25T00:00:00Z",
        )
        r2 = create_metering_record(
            agent_id="ag-2",
            session_id="sess-1",
            compute_units=1.0,
            timestamp="2026-08-25T00:00:00Z",
        )
        assert r1.content_hash != r2.content_hash

    def test_timestamp_auto_generated_when_omitted(self) -> None:
        enable_agent_metering()
        rec = create_metering_record(agent_id="ag-1", session_id="sess-1")
        assert rec.timestamp.endswith("Z")
        assert "T" in rec.timestamp

    def test_raises_on_empty_agent_id(self) -> None:
        enable_agent_metering()
        with pytest.raises(ValueError, match="agent_id"):
            create_metering_record(agent_id="", session_id="sess-1")

    def test_raises_on_whitespace_agent_id(self) -> None:
        enable_agent_metering()
        with pytest.raises(ValueError, match="agent_id"):
            create_metering_record(agent_id="   ", session_id="sess-1")

    def test_raises_on_empty_session_id(self) -> None:
        enable_agent_metering()
        with pytest.raises(ValueError, match="session_id"):
            create_metering_record(agent_id="ag-1", session_id="")

    def test_raises_on_negative_compute_units(self) -> None:
        enable_agent_metering()
        with pytest.raises(ValueError, match="compute_units"):
            create_metering_record(agent_id="ag-1", session_id="s-1", compute_units=-1.0)

    def test_raises_on_negative_debate_cost(self) -> None:
        enable_agent_metering()
        with pytest.raises(ValueError, match="debate_cost_usd"):
            create_metering_record(agent_id="ag-1", session_id="s-1", debate_cost_usd=-0.01)

    def test_raises_on_negative_verifier_cost(self) -> None:
        enable_agent_metering()
        with pytest.raises(ValueError, match="verifier_cost_usd"):
            create_metering_record(agent_id="ag-1", session_id="s-1", verifier_cost_usd=-0.01)


# ---------------------------------------------------------------------------
# Property and serialisation tests
# ---------------------------------------------------------------------------


class TestAgentMeteringRecord:
    def _make(self, **kwargs: object) -> AgentMeteringRecord:
        enable_agent_metering()
        defaults: dict = dict(
            agent_id="ag-1",
            session_id="sess-1",
            timestamp="2026-08-25T00:00:00Z",
        )
        defaults.update(kwargs)
        return create_metering_record(**defaults)

    def test_total_cost_sums_debate_and_verifier(self) -> None:
        rec = self._make(debate_cost_usd=0.10, verifier_cost_usd=0.03)
        assert abs(rec.total_cost_usd - 0.13) < 1e-9

    def test_total_cost_zero_when_both_zero(self) -> None:
        rec = self._make()
        assert rec.total_cost_usd == 0.0

    def test_to_dict_has_required_keys(self) -> None:
        d = self._make().to_dict()
        required = {
            "schema_version",
            "agent_id",
            "session_id",
            "compute_units",
            "debate_cost_usd",
            "verifier_cost_usd",
            "total_cost_usd",
            "timestamp",
            "content_hash",
        }
        assert required.issubset(d.keys())

    def test_to_dict_total_cost_matches_property(self) -> None:
        rec = self._make(debate_cost_usd=0.07, verifier_cost_usd=0.02)
        d = rec.to_dict()
        assert d["total_cost_usd"] == rec.total_cost_usd

    def test_to_json_is_valid_json(self) -> None:
        rec = self._make()
        parsed = json.loads(rec.to_json())
        assert parsed["agent_id"] == "ag-1"

    def test_to_json_sorted_keys(self) -> None:
        rec = self._make()
        raw = rec.to_json()
        keys = list(json.loads(raw).keys())
        assert keys == sorted(keys)

    def test_record_is_immutable(self) -> None:
        rec = self._make()
        with pytest.raises((AttributeError, TypeError)):
            rec.compute_units = 999.0  # type: ignore[misc]

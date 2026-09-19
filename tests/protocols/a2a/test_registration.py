"""Tests for aragora.protocols.a2a.registration (AGT-02 sub-deliverable 4)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from aragora.protocols.a2a.registration import (
    AgentRegistrationRecord,
    RegistrationError,
    RegistrationStore,
    lookup_agent,
    register_agent,
    registration_enabled,
)
from aragora.protocols.a2a.types import AgentCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store() -> RegistrationStore:
    return RegistrationStore()


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_A2A_REGISTRATION_ENABLED", raising=False)
        assert registration_enabled() is False

    def test_enabled_with_1(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_A2A_REGISTRATION_ENABLED", "1")
        assert registration_enabled() is True

    def test_enabled_with_true(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_A2A_REGISTRATION_ENABLED", "true")
        assert registration_enabled() is True

    def test_enabled_with_yes(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_A2A_REGISTRATION_ENABLED", "yes")
        assert registration_enabled() is True

    def test_register_raises_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_A2A_REGISTRATION_ENABLED", raising=False)
        with pytest.raises(RegistrationError, match="ARAGORA_A2A_REGISTRATION_ENABLED"):
            register_agent("agent-x", ["debate"], store=_store())

    def test_lookup_raises_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_A2A_REGISTRATION_ENABLED", raising=False)
        with pytest.raises(RegistrationError):
            lookup_agent("agent-x", store=_store())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRegisterAgent:
    @pytest.fixture(autouse=True)
    def enable(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_A2A_REGISTRATION_ENABLED", "1")

    def test_basic_registration(self):
        store = _store()
        rec = register_agent("agent-1", ["debate", "critique"], store=store)
        assert rec.agent_id == "agent-1"
        assert "debate" in rec.capabilities
        assert "critique" in rec.capabilities
        assert rec.public_key is None
        assert rec.endpoint_url is None

    def test_with_public_key_and_endpoint(self):
        store = _store()
        rec = register_agent(
            "agent-2",
            [AgentCapability.AUDIT],
            public_key="base64keyhere==",
            endpoint_url="https://agent-2.example.com/a2a",
            store=store,
        )
        assert rec.public_key == "base64keyhere=="
        assert rec.endpoint_url == "https://agent-2.example.com/a2a"

    def test_capability_enum_coercion(self):
        store = _store()
        rec = register_agent(
            "agent-3",
            [AgentCapability.DEBATE, AgentCapability.CONSENSUS],
            store=store,
        )
        assert "debate" in rec.capabilities
        assert "consensus" in rec.capabilities

    def test_record_in_store_after_register(self):
        store = _store()
        register_agent("agent-4", ["synthesis"], store=store)
        assert len(store) == 1
        assert store.get("agent-4") is not None

    def test_duplicate_raises_by_default(self):
        store = _store()
        register_agent("agent-5", ["audit"], store=store)
        with pytest.raises(RegistrationError, match="already registered"):
            register_agent("agent-5", ["audit"], store=store)

    def test_duplicate_allowed_with_overwrite(self):
        store = _store()
        register_agent("agent-6", ["audit"], store=store)
        rec2 = register_agent("agent-6", ["debate"], store=store, overwrite=True)
        assert "debate" in rec2.capabilities
        assert len(store) == 1

    def test_empty_agent_id_raises(self):
        store = _store()
        with pytest.raises(RegistrationError, match="non-empty"):
            register_agent("", ["debate"], store=store)

    def test_whitespace_agent_id_raises(self):
        store = _store()
        with pytest.raises(RegistrationError, match="non-empty"):
            register_agent("   ", ["debate"], store=store)

    def test_no_capabilities_raises(self):
        store = _store()
        with pytest.raises(RegistrationError, match="capability"):
            register_agent("agent-7", [], store=store)

    def test_registered_at_is_utc_aware(self):
        store = _store()
        rec = register_agent("agent-8", ["debate"], store=store)
        assert rec.registered_at.tzinfo is not None

    def test_custom_registered_at(self):
        store = _store()
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        rec = register_agent("agent-9", ["debate"], store=store, registered_at=ts)
        assert rec.registered_at == ts

    def test_agent_id_whitespace_stripped(self):
        store = _store()
        rec = register_agent("  agent-10  ", ["debate"], store=store)
        assert rec.agent_id == "agent-10"


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class TestLookupAgent:
    @pytest.fixture(autouse=True)
    def enable(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_A2A_REGISTRATION_ENABLED", "1")

    def test_lookup_returns_record(self):
        store = _store()
        register_agent("agent-a", ["debate"], store=store)
        rec = lookup_agent("agent-a", store=store)
        assert rec is not None
        assert rec.agent_id == "agent-a"

    def test_lookup_missing_returns_none(self):
        store = _store()
        assert lookup_agent("unknown", store=store) is None


# ---------------------------------------------------------------------------
# RegistrationStore
# ---------------------------------------------------------------------------


class TestRegistrationStore:
    def test_put_and_get(self):
        store = _store()
        rec = AgentRegistrationRecord(
            agent_id="x",
            capabilities=frozenset(["debate"]),
            public_key=None,
            endpoint_url=None,
            registered_at=datetime.now(tz=UTC),
        )
        store.put(rec)
        assert store.get("x") is rec

    def test_len(self):
        store = _store()
        assert len(store) == 0
        store.put(
            AgentRegistrationRecord("y", frozenset(["audit"]), None, None, datetime.now(tz=UTC))
        )
        assert len(store) == 1

    def test_remove(self):
        store = _store()
        rec = AgentRegistrationRecord("z", frozenset(["debate"]), None, None, datetime.now(tz=UTC))
        store.put(rec)
        assert store.remove("z") is True
        assert store.get("z") is None

    def test_remove_missing_returns_false(self):
        store = _store()
        assert store.remove("nope") is False

    def test_all(self):
        store = _store()
        r1 = AgentRegistrationRecord("a1", frozenset(["debate"]), None, None, datetime.now(tz=UTC))
        r2 = AgentRegistrationRecord("a2", frozenset(["audit"]), None, None, datetime.now(tz=UTC))
        store.put(r1)
        store.put(r2)
        assert set(r.agent_id for r in store.all()) == {"a1", "a2"}


# ---------------------------------------------------------------------------
# AgentRegistrationRecord serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_round_trip(self):
        rec = AgentRegistrationRecord(
            agent_id="ser-1",
            capabilities=frozenset(["debate", "critique"]),
            public_key="pk123",
            endpoint_url="https://example.com",
            registered_at=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC),
        )
        d = rec.to_dict()
        assert d["agent_id"] == "ser-1"
        assert sorted(d["capabilities"]) == ["critique", "debate"]
        assert d["public_key"] == "pk123"
        assert d["endpoint_url"] == "https://example.com"

    def test_from_dict(self):
        d = {
            "agent_id": "ser-2",
            "capabilities": ["audit"],
            "public_key": None,
            "endpoint_url": None,
            "registered_at": "2026-06-01T00:00:00+00:00",
        }
        rec = AgentRegistrationRecord.from_dict(d)
        assert rec.agent_id == "ser-2"
        assert "audit" in rec.capabilities

    def test_from_dict_bad_capabilities_raises(self):
        with pytest.raises(RegistrationError, match="capabilities must be a list"):
            AgentRegistrationRecord.from_dict(
                {
                    "agent_id": "bad",
                    "capabilities": "not-a-list",
                }
            )


class TestFromDictValidation:
    """Persisted records are untrusted; malformed ones must be rejected, not coerced."""

    @staticmethod
    def _valid() -> dict[str, object]:
        return {
            "agent_id": "val-1",
            "capabilities": ["debate"],
            "public_key": None,
            "endpoint_url": None,
            "registered_at": "2026-06-01T00:00:00+00:00",
        }

    def test_valid_record_round_trips(self):
        rec = AgentRegistrationRecord.from_dict(self._valid())
        assert rec.agent_id == "val-1"
        assert rec.capabilities == frozenset({"debate"})
        assert rec.registered_at.tzinfo is not None
        assert AgentRegistrationRecord.from_dict(rec.to_dict()) == rec

    @pytest.mark.parametrize("bad_id", [None, "", "   ", 42])
    def test_bad_agent_id_raises(self, bad_id):
        d = self._valid()
        d["agent_id"] = bad_id
        with pytest.raises(RegistrationError, match="agent_id"):
            AgentRegistrationRecord.from_dict(d)

    def test_missing_agent_id_raises(self):
        d = self._valid()
        del d["agent_id"]
        with pytest.raises(RegistrationError, match="agent_id"):
            AgentRegistrationRecord.from_dict(d)

    @pytest.mark.parametrize("bad_caps", [[], [""], ["debate", "  "], [1], ["debate", None]])
    def test_bad_capabilities_raise(self, bad_caps):
        d = self._valid()
        d["capabilities"] = bad_caps
        with pytest.raises(RegistrationError, match="capabilities"):
            AgentRegistrationRecord.from_dict(d)

    @pytest.mark.parametrize("bad_ts", [None, "", "not-a-date", 1717200000, "2026-06-01T00:00:00"])
    def test_bad_registered_at_raises(self, bad_ts):
        d = self._valid()
        d["registered_at"] = bad_ts
        with pytest.raises(RegistrationError, match="registered_at"):
            AgentRegistrationRecord.from_dict(d)

    def test_missing_registered_at_raises(self):
        d = self._valid()
        del d["registered_at"]
        with pytest.raises(RegistrationError, match="registered_at"):
            AgentRegistrationRecord.from_dict(d)

    @pytest.mark.parametrize("key", ["public_key", "endpoint_url"])
    @pytest.mark.parametrize("bad", ["", "  ", 7, {"k": "v"}])
    def test_bad_optional_strings_raise(self, key, bad):
        d = self._valid()
        d[key] = bad
        with pytest.raises(RegistrationError, match=key):
            AgentRegistrationRecord.from_dict(d)

    def test_non_mapping_raises(self):
        with pytest.raises(RegistrationError, match="mapping"):
            AgentRegistrationRecord.from_dict(["agent_id"])  # type: ignore[arg-type]

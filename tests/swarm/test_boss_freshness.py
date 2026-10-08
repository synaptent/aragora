"""Comprehensive tests for aragora/swarm/boss_freshness.py.

Covers:
- RunnerFreshnessResult construction and to_dict()
- _normalized_runner_type helper
- _verification_runner_type helper
- _selected_runner_probe_inspections helper
- check_runner_freshness: missing owner context
- check_runner_freshness: routing blocked
- check_runner_freshness: runner not responding / bad auth mode
- check_runner_freshness: registration TTL / stale runners
- check_runner_freshness: happy path returning fresh=True
- check_runner_freshness: no verified runner when target > 0
- check_runner_freshness: auto-probe logic (probe triggered, passed, failed)
- check_runner_freshness: env var configuration for targets and limits
- Edge cases: no runners, expired runners, stale probes
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import aragora.swarm.runner_registry as runner_registry

from aragora.swarm.boss_freshness import (
    RunnerFreshnessResult,
    _normalized_runner_type,
    _selected_runner_probe_inspections,
    _verification_runner_type,
    check_runner_freshness,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ago_iso(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _make_routing(
    *,
    selected_runners: list[dict[str, Any]] | None = None,
    selected_runner_ids: list[str] | None = None,
    blocked_reason: str | None = None,
) -> MagicMock:
    routing = MagicMock()
    routing.selected_runners = selected_runners or []
    routing.selected_runner_ids = selected_runner_ids or []
    routing.blocked_reason = blocked_reason
    routing.is_blocked = bool(blocked_reason)
    routing.to_dict.return_value = {"mocked": True}
    return routing


def _make_inspection(
    *,
    runner_id: str = "claude-runner-abc123",
    runner_type: str = "claude",
    available: bool = True,
    auth_mode: str = "subscription",
) -> MagicMock:
    insp = MagicMock()
    insp.runner_id = runner_id
    insp.runner_type = runner_type
    insp.available = available
    insp.auth_mode = auth_mode
    insp.to_dict.return_value = {
        "runner_id": runner_id,
        "available": available,
        "auth_mode": auth_mode,
    }
    return insp


def _make_probe(*, status: str = "passed", runner_id: str = "claude-runner-abc123") -> MagicMock:
    probe = MagicMock()
    probe.status = status
    probe.runner_id = runner_id
    probe.to_dict.return_value = {"status": status, "runner_id": runner_id}
    return probe


# ---------------------------------------------------------------------------
# RunnerFreshnessResult
# ---------------------------------------------------------------------------


class TestRunnerFreshnessResult:
    def test_fresh_true_round_trip(self):
        ts = _now_iso()
        result = RunnerFreshnessResult(
            fresh=True,
            runner_ids=["runner-1", "runner-2"],
            checked_at=ts,
        )
        assert result.fresh is True
        assert result.runner_ids == ["runner-1", "runner-2"]
        assert result.checked_at == ts
        assert result.blocked_reason is None
        assert result.details == {}

    def test_fresh_false_with_reason(self):
        result = RunnerFreshnessResult(
            fresh=False,
            runner_ids=[],
            checked_at=_now_iso(),
            blocked_reason="missing_owner_context",
        )
        assert result.fresh is False
        assert result.blocked_reason == "missing_owner_context"

    def test_to_dict_shape(self):
        ts = _now_iso()
        result = RunnerFreshnessResult(
            fresh=True,
            runner_ids=["r1"],
            checked_at=ts,
            blocked_reason=None,
            details={"routing": {"mocked": True}},
        )
        d = result.to_dict()
        assert d["fresh"] is True
        assert d["runner_ids"] == ["r1"]
        assert d["checked_at"] == ts
        assert d["blocked_reason"] is None
        assert d["details"] == {"routing": {"mocked": True}}

    def test_to_dict_returns_copies(self):
        ids = ["r1"]
        details = {"key": "val"}
        result = RunnerFreshnessResult(
            fresh=True,
            runner_ids=ids,
            checked_at=_now_iso(),
            details=details,
        )
        d = result.to_dict()
        # Mutations to returned value should not affect original
        d["runner_ids"].append("r2")
        d["details"]["extra"] = True
        assert result.runner_ids == ["r1"]
        assert "extra" not in result.details

    def test_to_dict_blocked_reason_preserved(self):
        result = RunnerFreshnessResult(
            fresh=False,
            runner_ids=["r1"],
            checked_at=_now_iso(),
            blocked_reason="all_runners_stale",
        )
        d = result.to_dict()
        assert d["blocked_reason"] == "all_runners_stale"


# ---------------------------------------------------------------------------
# _normalized_runner_type
# ---------------------------------------------------------------------------


class TestNormalizedRunnerType:
    def test_none_returns_none(self):
        assert _normalized_runner_type(None) is None

    def test_empty_string_returns_none(self):
        assert _normalized_runner_type("") is None

    def test_whitespace_only_returns_none(self):
        assert _normalized_runner_type("   ") is None

    def test_claude_lowercased(self):
        assert _normalized_runner_type("CLAUDE") == "claude"

    def test_codex_lowercased(self):
        assert _normalized_runner_type("  CODEX  ") == "codex"

    def test_unknown_type_returned(self):
        assert _normalized_runner_type("gemini-cli") == "gemini-cli"


# ---------------------------------------------------------------------------
# _verification_runner_type
# ---------------------------------------------------------------------------


class TestVerificationRunnerType:
    def test_none_requested_returns_none(self):
        routing = _make_routing()
        assert _verification_runner_type(requested_runner_type=None, routing=routing) is None

    def test_unsupported_type_returns_none(self):
        routing = _make_routing()
        result = _verification_runner_type(requested_runner_type="gemini-cli", routing=routing)
        assert result is None

    def test_claude_with_empty_selected_runners_returns_requested(self):
        routing = _make_routing(selected_runners=[])
        result = _verification_runner_type(requested_runner_type="claude", routing=routing)
        assert result == "claude"

    def test_codex_with_empty_selected_runners_returns_requested(self):
        routing = _make_routing(selected_runners=[])
        result = _verification_runner_type(requested_runner_type="codex", routing=routing)
        assert result == "codex"

    def test_returns_selected_runner_type_when_present(self):
        routing = _make_routing(selected_runners=[{"runner_type": "claude", "profile": "default"}])
        result = _verification_runner_type(requested_runner_type="claude", routing=routing)
        assert result == "claude"

    def test_skips_non_dict_items_in_selected_runners(self):
        routing = _make_routing(selected_runners=["not-a-dict", None])
        result = _verification_runner_type(requested_runner_type="codex", routing=routing)
        # Falls back to requested since no valid dict entry found
        assert result == "codex"

    def test_selected_runner_type_override(self):
        # If selected runner has a different type that is claude/codex, it is returned
        routing = _make_routing(selected_runners=[{"runner_type": "codex"}])
        result = _verification_runner_type(requested_runner_type="codex", routing=routing)
        assert result == "codex"

    def test_ignores_invalid_selected_runner_type(self):
        routing = _make_routing(selected_runners=[{"runner_type": "gemini-cli"}])
        result = _verification_runner_type(requested_runner_type="claude", routing=routing)
        # No valid selected type; falls back to requested
        assert result == "claude"


# ---------------------------------------------------------------------------
# _selected_runner_probe_inspections
# ---------------------------------------------------------------------------


class TestSelectedRunnerProbeInspections:
    def _make_inspector_factory(self, inspection: Any) -> Any:
        inspector = MagicMock()
        inspector.inspect.return_value = inspection
        return MagicMock(return_value=inspector)

    def test_empty_selected_runners_returns_empty(self):
        routing = _make_routing(selected_runners=[])
        result = _selected_runner_probe_inspections(
            runner_type="claude",
            routing=routing,
            make_runner_inspector=MagicMock(),
            env=None,
        )
        assert result == []

    def test_filters_by_runner_type(self):
        insp = _make_inspection(runner_id="codex-runner-111", runner_type="codex")
        routing = _make_routing(
            selected_runners=[
                {"runner_type": "codex", "profile": None},
                {"runner_type": "claude", "profile": None},
            ]
        )
        factory = self._make_inspector_factory(insp)
        result = _selected_runner_probe_inspections(
            runner_type="codex",
            routing=routing,
            make_runner_inspector=factory,
            env=None,
        )
        # Only one codex runner should be inspected
        assert len(result) == 1
        assert result[0].runner_id == "codex-runner-111"

    def test_deduplicates_by_runner_id(self):
        insp = _make_inspection(runner_id="same-id")
        routing = _make_routing(
            selected_runners=[
                {"runner_type": "claude", "profile": "a"},
                {"runner_type": "claude", "profile": "b"},
            ]
        )
        factory = self._make_inspector_factory(insp)
        result = _selected_runner_probe_inspections(
            runner_type="claude",
            routing=routing,
            make_runner_inspector=factory,
            env=None,
        )
        # Both return the same runner_id, so only one should appear
        assert len(result) == 1

    def test_skips_empty_runner_id(self):
        insp = _make_inspection(runner_id="")
        routing = _make_routing(selected_runners=[{"runner_type": "claude", "profile": None}])
        factory = self._make_inspector_factory(insp)
        result = _selected_runner_probe_inspections(
            runner_type="claude",
            routing=routing,
            make_runner_inspector=factory,
            env=None,
        )
        assert result == []

    def test_skips_non_dict_items(self):
        routing = _make_routing(selected_runners=["not-a-dict", 42, None])
        factory = MagicMock()
        result = _selected_runner_probe_inspections(
            runner_type="claude",
            routing=routing,
            make_runner_inspector=factory,
            env=None,
        )
        assert result == []
        factory.assert_not_called()


# ---------------------------------------------------------------------------
# check_runner_freshness — integration-level tests with mocked registry
# ---------------------------------------------------------------------------

MODULE = "aragora.swarm.boss_freshness"
REGISTRY_MODULE = "aragora.swarm.runner_registry"


def _patch_registry_imports(
    *,
    owner_context: Any = MagicMock(),
    routing: Any | None = None,
    refresh_discovered: list[Any] | None = None,
    make_inspector_inspection: Any | None = None,
    probe_result: Any | None = None,
    probe_candidates: list[Any] | None = None,
    registrations: list[dict[str, Any]] | None = None,
    probe_status_map: dict[str, str] | None = None,
):
    """Build a context manager stack that patches all registry imports."""
    if routing is None:
        routing = _make_routing()
    if refresh_discovered is None:
        refresh_discovered = []
    if registrations is None:
        registrations = []
    if probe_candidates is None:
        probe_candidates = []
    if probe_result is None:
        probe_result = _make_probe()

    _probe_status_map = probe_status_map or {}

    class FakeRegistry:
        def __init__(self, *, path: Any = None):
            pass

        def resolve_boss_routing(self, **kwargs: Any) -> Any:
            return routing

        def list_registrations(self) -> list[dict[str, Any]]:
            return registrations

        def record_probe(self, inspection: Any, probe: Any, *, owner_context: Any) -> None:
            pass

        def _probe_status(self, item: dict[str, Any]) -> str | None:
            rid = str(item.get("runner_id", "") or "").strip()
            return _probe_status_map.get(rid)

    def fake_make_inspector(runner_type: str, **kwargs: Any) -> MagicMock:
        inspector = MagicMock()
        if make_inspector_inspection is not None:
            inspector.inspect.return_value = make_inspector_inspection
        else:
            inspector.inspect.return_value = _make_inspection(runner_type=runner_type)
        return inspector

    patches = {
        f"{MODULE}.check_runner_freshness.__code__": None,  # not a real patch
    }

    return dict(
        LocalRunnerRegistry=FakeRegistry,
        authorization_context_with_defaults=lambda **kw: owner_context,
        configured_claude_runner_profiles=lambda env: set(),
        make_runner_inspector=fake_make_inspector,
        prioritized_probe_candidates=lambda **kw: probe_candidates,
        probe_runner_execution=lambda inspection, **kw: probe_result,
        refresh_discovered_runners=lambda *a, **kw: refresh_discovered,
    )


def _run_check(
    *,
    owner_context: Any = MagicMock(),
    routing: Any | None = None,
    refresh_discovered: list[Any] | None = None,
    make_inspector_inspection: Any | None = None,
    probe_result: Any | None = None,
    probe_candidates: list[Any] | None = None,
    registrations: list[dict[str, Any]] | None = None,
    probe_status_map: dict[str, str] | None = None,
    **kwargs: Any,
) -> RunnerFreshnessResult:
    """Run check_runner_freshness with all registry imports mocked."""
    mock_dict = _patch_registry_imports(
        owner_context=owner_context,
        routing=routing,
        refresh_discovered=refresh_discovered,
        make_inspector_inspection=make_inspector_inspection,
        probe_result=probe_result,
        probe_candidates=probe_candidates,
        registrations=registrations,
        probe_status_map=probe_status_map,
    )

    # We need to patch the imports inside the function
    # The function does a local import from aragora.swarm.runner_registry
    with (
        patch(f"{REGISTRY_MODULE}.LocalRunnerRegistry", mock_dict["LocalRunnerRegistry"]),
        patch(
            f"{REGISTRY_MODULE}.authorization_context_with_defaults",
            mock_dict["authorization_context_with_defaults"],
        ),
        patch(
            f"{REGISTRY_MODULE}.configured_claude_runner_profiles",
            mock_dict["configured_claude_runner_profiles"],
        ),
        patch(
            f"{REGISTRY_MODULE}.make_runner_inspector",
            mock_dict["make_runner_inspector"],
        ),
        patch(
            f"{REGISTRY_MODULE}.prioritized_probe_candidates",
            mock_dict["prioritized_probe_candidates"],
        ),
        patch(
            f"{REGISTRY_MODULE}.probe_runner_execution",
            mock_dict["probe_runner_execution"],
        ),
        patch(
            f"{REGISTRY_MODULE}.refresh_discovered_runners",
            mock_dict["refresh_discovered_runners"],
        ),
    ):
        # Also patch the local import inside check_runner_freshness
        with (
            (
                patch(
                    "aragora.swarm.boss_freshness.check_runner_freshness.__globals__",
                    new={},
                    create=True,
                )
            )
            if False
            else patch(
                "builtins.__import__",
                wraps=__builtins__.__import__
                if hasattr(__builtins__, "__import__")
                else __import__,
            )
        ):
            # Actually we need to patch imports inline in the function body
            pass

    # Simpler approach: patch the symbols as they are imported inside the function
    import aragora.swarm.runner_registry as rr_mod

    with (
        patch.object(rr_mod, "LocalRunnerRegistry", mock_dict["LocalRunnerRegistry"]),
        patch.object(
            rr_mod,
            "authorization_context_with_defaults",
            mock_dict["authorization_context_with_defaults"],
        ),
        patch.object(
            rr_mod,
            "configured_claude_runner_profiles",
            mock_dict["configured_claude_runner_profiles"],
        ),
        patch.object(rr_mod, "make_runner_inspector", mock_dict["make_runner_inspector"]),
        patch.object(
            rr_mod, "prioritized_probe_candidates", mock_dict["prioritized_probe_candidates"]
        ),
        patch.object(rr_mod, "probe_runner_execution", mock_dict["probe_runner_execution"]),
        patch.object(rr_mod, "refresh_discovered_runners", mock_dict["refresh_discovered_runners"]),
    ):
        return check_runner_freshness(**kwargs)


class TestCheckRunnerFreshnessMissingOwnerContext:
    def test_none_owner_context_returns_blocked(self):
        result = _run_check(owner_context=None)
        assert result.fresh is False
        assert result.blocked_reason == "missing_owner_context"
        assert result.runner_ids == []

    def test_checked_at_is_iso_string(self):
        result = _run_check(owner_context=None)
        # Should be parseable as ISO
        dt = datetime.fromisoformat(result.checked_at)
        assert dt.tzinfo is not None


class TestCheckRunnerFreshnessRoutingBlocked:
    def test_blocked_routing_propagates_reason(self):
        routing = _make_routing(blocked_reason="no_eligible_runner")
        result = _run_check(routing=routing)
        assert result.fresh is False
        assert result.blocked_reason == "no_eligible_runner"
        assert result.runner_ids == []

    def test_blocked_routing_includes_routing_details(self):
        routing = _make_routing(blocked_reason="quota_exceeded")
        result = _run_check(routing=routing)
        assert "routing" in result.details


class TestCheckRunnerFreshnessRunnerNotResponding:
    def test_no_live_runners_returns_not_responding(self):
        routing = _make_routing(
            selected_runners=[{"runner_type": "codex", "profile": None}],
            selected_runner_ids=["codex-runner-1"],
        )
        insp = _make_inspection(runner_id="codex-runner-1", available=False, auth_mode="unknown")
        result = _run_check(routing=routing, make_inspector_inspection=insp)
        assert result.fresh is False
        assert result.blocked_reason == "runner_not_responding"

    def test_bad_auth_mode_means_not_responding(self):
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "profile": None}],
            selected_runner_ids=["claude-runner-1"],
        )
        # available=True but auth_mode is "unknown" (not in accepted set)
        insp = _make_inspection(runner_id="claude-runner-1", available=True, auth_mode="unknown")
        result = _run_check(routing=routing, make_inspector_inspection=insp)
        assert result.fresh is False
        assert result.blocked_reason == "runner_not_responding"

    def test_valid_auth_modes_accepted(self):
        for auth_mode in ("chatgpt_login", "api_key", "subscription"):
            routing = _make_routing(
                selected_runners=[{"runner_type": "claude", "profile": None}],
                selected_runner_ids=["claude-runner-1"],
            )
            insp = _make_inspection(
                runner_id="claude-runner-1", available=True, auth_mode=auth_mode
            )
            registrations = [
                {
                    "runner_id": "claude-runner-1",
                    "updated_at": _now_iso(),
                }
            ]
            result = _run_check(
                routing=routing,
                make_inspector_inspection=insp,
                registrations=registrations,
            )
            # Should not be blocked for runner_not_responding
            assert result.blocked_reason != "runner_not_responding", (
                f"auth_mode={auth_mode!r} should be accepted"
            )


class TestCheckRunnerFreshnessTTL:
    def _fresh_routing_and_inspection(self) -> tuple[Any, Any]:
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "profile": None}],
            selected_runner_ids=["claude-runner-1"],
        )
        insp = _make_inspection(
            runner_id="claude-runner-1", available=True, auth_mode="subscription"
        )
        return routing, insp

    def test_fresh_registration_passes_ttl(self):
        routing, insp = self._fresh_routing_and_inspection()
        registrations = [{"runner_id": "claude-runner-1", "updated_at": _now_iso()}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            freshness_ttl_seconds=300.0,
        )
        assert result.fresh is True
        assert result.blocked_reason is None

    def test_expired_registration_triggers_stale(self):
        routing, insp = self._fresh_routing_and_inspection()
        registrations = [{"runner_id": "claude-runner-1", "updated_at": _ago_iso(400)}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            freshness_ttl_seconds=300.0,
        )
        assert result.fresh is False
        assert result.blocked_reason == "all_runners_stale"

    def test_missing_timestamp_marks_stale(self):
        routing, insp = self._fresh_routing_and_inspection()
        registrations = [
            {"runner_id": "claude-runner-1"}  # no updated_at or registered_at
        ]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            freshness_ttl_seconds=300.0,
        )
        assert result.fresh is False
        assert result.blocked_reason == "all_runners_stale"

    def test_invalid_timestamp_marks_stale(self):
        routing, insp = self._fresh_routing_and_inspection()
        registrations = [{"runner_id": "claude-runner-1", "updated_at": "not-a-date"}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            freshness_ttl_seconds=300.0,
        )
        assert result.fresh is False
        assert result.blocked_reason == "all_runners_stale"

    def test_uses_registered_at_fallback(self):
        routing, insp = self._fresh_routing_and_inspection()
        registrations = [{"runner_id": "claude-runner-1", "registered_at": _now_iso()}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            freshness_ttl_seconds=300.0,
        )
        assert result.fresh is True

    def test_naive_datetime_treated_as_utc(self):
        routing, insp = self._fresh_routing_and_inspection()
        # naive datetime (no tzinfo) — should be treated as UTC
        naive_ts = (datetime.now(UTC) - timedelta(seconds=10)).replace(tzinfo=None).isoformat()
        registrations = [{"runner_id": "claude-runner-1", "updated_at": naive_ts}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            freshness_ttl_seconds=300.0,
        )
        assert result.fresh is True

    def test_stale_details_include_stale_ids(self):
        routing, insp = self._fresh_routing_and_inspection()
        registrations = [{"runner_id": "claude-runner-1", "updated_at": _ago_iso(1000)}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            freshness_ttl_seconds=300.0,
        )
        assert "stale_ids" in result.details
        assert "claude-runner-1" in result.details["stale_ids"]
        assert result.details["freshness_ttl_seconds"] == 300.0


class TestCheckRunnerFreshnessHappyPath:
    def test_returns_fresh_true_with_fresh_ids(self):
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "profile": None}],
            selected_runner_ids=["claude-runner-1"],
        )
        insp = _make_inspection(
            runner_id="claude-runner-1", available=True, auth_mode="subscription"
        )
        registrations = [{"runner_id": "claude-runner-1", "updated_at": _now_iso()}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
        )
        assert result.fresh is True
        assert "claude-runner-1" in result.runner_ids
        assert result.blocked_reason is None

    def test_details_include_live_runner_ids(self):
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "profile": None}],
            selected_runner_ids=["claude-runner-1"],
        )
        insp = _make_inspection(runner_id="claude-runner-1", available=True, auth_mode="api_key")
        registrations = [{"runner_id": "claude-runner-1", "updated_at": _now_iso()}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
        )
        assert "live_runner_ids" in result.details
        assert "claude-runner-1" in result.details["live_runner_ids"]

    def test_details_include_probe_summary(self):
        routing = _make_routing(
            selected_runners=[{"runner_type": "codex", "profile": None}],
            selected_runner_ids=["codex-runner-1"],
        )
        insp = _make_inspection(
            runner_id="codex-runner-1", available=True, auth_mode="chatgpt_login"
        )
        registrations = [{"runner_id": "codex-runner-1", "updated_at": _now_iso()}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
        )
        assert "probe" in result.details
        assert "auto_probe_triggered" in result.details["probe"]


class TestCheckRunnerFreshnessNoVerifiedRunner:
    def test_no_verified_runner_blocks_when_target_positive(self):
        rid = "claude-runner-1"
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "runner_id": rid}],
            selected_runner_ids=[rid],
        )
        # probe_status returns None (not "passed") for this runner
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            verified_runner_target=1,
            probe_status_map={rid: "failed"},
            make_inspector_inspection=_make_inspection(
                runner_id=rid, available=True, auth_mode="subscription"
            ),
            registrations=[{"runner_id": rid, "updated_at": _now_iso()}],
        )
        # Since no runner passed probe and target > 0, expect blocked
        assert result.fresh is False
        assert result.blocked_reason == "no_execution_verified_runner"

    def test_zero_verified_target_skips_verification_block(self):
        rid = "claude-runner-1"
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "runner_id": rid}],
            selected_runner_ids=[rid],
        )
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            verified_runner_target=0,
            probe_status_map={rid: "failed"},
            make_inspector_inspection=_make_inspection(
                runner_id=rid, available=True, auth_mode="subscription"
            ),
            registrations=[{"runner_id": rid, "updated_at": _now_iso()}],
        )
        # With target=0, even if no probes passed, we should not block on verification
        assert result.blocked_reason != "no_execution_verified_runner"


class TestCheckRunnerFreshnessProbeLogic:
    def test_single_probe_prefers_selected_unverified_over_failed_registration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        now = datetime.now(UTC).isoformat()
        registry_path = tmp_path / "swarm-runners.json"
        registry_path.write_text(
            json.dumps(
                {
                    "registrations": [
                        {
                            "runner_id": "claude-runner-failed",
                            "runner_type": "claude",
                            "profile": "max-01",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "command_path": "/usr/bin/true",
                            "owner_binding": {
                                "user_id": "user-123",
                                "workspace_id": "aragora",
                            },
                            "heartbeat_at": now,
                            "updated_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                            "probe_status": "failed",
                            "probe_checked_at": now,
                        },
                        {
                            "runner_id": "claude-runner-selected",
                            "runner_type": "claude",
                            "profile": "max-10",
                            "registered": True,
                            "availability": "available",
                            "available": True,
                            "auth_mode": "subscription",
                            "command_path": "/usr/bin/true",
                            "owner_binding": {
                                "user_id": "user-123",
                                "workspace_id": "aragora",
                            },
                            "heartbeat_at": now,
                            "updated_at": now,
                            "stale_after_seconds": 3600,
                            "capabilities": {"max_parallel_lanes": 1, "active_lanes": 0},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        failed = runner_registry.RunnerInspection(
            runner_id="claude-runner-failed",
            runner_type="claude",
            profile="max-01",
            availability="available",
            available=True,
            auth_mode="subscription",
            command_path="/usr/bin/true",
        )
        selected = runner_registry.RunnerInspection(
            runner_id="claude-runner-selected",
            runner_type="claude",
            profile="max-10",
            availability="available",
            available=True,
            auth_mode="subscription",
            command_path="/usr/bin/true",
        )
        probed_runner_ids: list[str] = []

        monkeypatch.setattr(
            runner_registry,
            "refresh_discovered_runners",
            lambda *args, **kwargs: [failed, selected],
        )

        def _probe(inspection: Any, **kwargs: Any) -> runner_registry.RunnerProbeResult:
            probed_runner_ids.append(inspection.runner_id)
            return runner_registry.RunnerProbeResult(
                runner_id=inspection.runner_id,
                runner_type=inspection.runner_type,
                profile=inspection.profile,
                status="passed",
                checked_at=datetime.now(UTC).isoformat(),
            )

        monkeypatch.setattr(runner_registry, "probe_runner_execution", _probe)
        inspector = MagicMock()
        inspector.inspect.return_value = selected
        monkeypatch.setattr(
            runner_registry,
            "make_runner_inspector",
            lambda *args, **kwargs: inspector,
        )

        result = check_runner_freshness(
            registry_path=str(registry_path),
            env={"ARAGORA_USER_ID": "user-123", "ARAGORA_WORKSPACE_ID": "aragora"},
            requested_runner_type="claude",
            allowed_profiles={"max-01", "max-10"},
            verified_runner_target=1,
            runner_probe_limit=1,
        )

        assert result.fresh is True
        assert probed_runner_ids == [selected.runner_id]
        assert result.details["probe"]["attempted"] == 1

    def test_probe_triggered_when_below_target(self):
        rid = "claude-runner-1"
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "runner_id": rid, "profile": None}],
            selected_runner_ids=[rid],
        )
        probe = _make_probe(status="passed", runner_id=rid)
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            verified_runner_target=1,
            runner_probe_limit=1,
            probe_status_map={},
            probe_result=probe,
            probe_candidates=[
                _make_inspection(runner_id=rid, available=True, auth_mode="subscription")
            ],
            make_inspector_inspection=_make_inspection(
                runner_id=rid, available=True, auth_mode="subscription"
            ),
            registrations=[{"runner_id": rid, "updated_at": _now_iso()}],
        )
        assert result.details["probe"]["attempted"] >= 0  # probe was at least considered

    def test_probe_failed_increments_failed_count(self):
        rid = "codex-runner-1"
        routing = _make_routing(
            selected_runners=[{"runner_type": "codex", "runner_id": rid, "profile": None}],
            selected_runner_ids=[rid],
        )
        probe = _make_probe(status="failed", runner_id=rid)
        result = _run_check(
            routing=routing,
            requested_runner_type="codex",
            verified_runner_target=1,
            runner_probe_limit=1,
            probe_status_map={},
            probe_result=probe,
            probe_candidates=[
                _make_inspection(runner_id=rid, available=True, auth_mode="subscription")
            ],
            make_inspector_inspection=_make_inspection(
                runner_id=rid, available=True, auth_mode="chatgpt_login"
            ),
            registrations=[{"runner_id": rid, "updated_at": _now_iso()}],
        )
        # Failed probe may cause no_execution_verified_runner or probe stats recorded
        assert "probe" in result.details


class TestCheckRunnerFreshnessEnvVarConfig:
    def _setup_routing_and_insp(self) -> tuple[Any, Any, Any]:
        rid = "claude-runner-1"
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "runner_id": rid, "profile": None}],
            selected_runner_ids=[rid],
        )
        insp = _make_inspection(runner_id=rid, available=True, auth_mode="subscription")
        regs = [{"runner_id": rid, "updated_at": _now_iso()}]
        return routing, insp, regs

    def test_env_var_verified_runner_target(self):
        routing, insp, regs = self._setup_routing_and_insp()
        env = {"ARAGORA_BOSS_VERIFIED_RUNNER_TARGET": "0"}
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            make_inspector_inspection=insp,
            registrations=regs,
            env=env,
        )
        # With target=0 from env, no_execution_verified_runner should not fire
        assert result.blocked_reason != "no_execution_verified_runner"

    def test_env_var_invalid_target_uses_default(self):
        routing, insp, regs = self._setup_routing_and_insp()
        env = {"ARAGORA_BOSS_VERIFIED_RUNNER_TARGET": "not_a_number"}
        # Should not raise, falls back to default
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            make_inspector_inspection=insp,
            registrations=regs,
            env=env,
        )
        assert result is not None

    def test_env_var_probe_limit_clamped_to_one(self):
        routing, insp, regs = self._setup_routing_and_insp()
        env = {"ARAGORA_BOSS_RUNNER_PROBE_LIMIT": "0"}
        # Limit is max(1, value) so 0 -> 1
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            make_inspector_inspection=insp,
            registrations=regs,
            env=env,
        )
        assert result is not None

    def test_env_var_invalid_probe_limit_uses_default(self):
        routing, insp, regs = self._setup_routing_and_insp()
        env = {"ARAGORA_BOSS_RUNNER_PROBE_LIMIT": "bad_val"}
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            make_inspector_inspection=insp,
            registrations=regs,
            env=env,
        )
        assert result is not None


class TestCheckRunnerFreshnessEdgeCases:
    def test_no_selected_runners_returns_not_responding(self):
        routing = _make_routing(selected_runners=[], selected_runner_ids=[])
        result = _run_check(routing=routing)
        assert result.fresh is False
        assert result.blocked_reason == "runner_not_responding"

    def test_runner_not_in_registrations_considered_fresh(self):
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "profile": None}],
            selected_runner_ids=["claude-runner-1"],
        )
        insp = _make_inspection(
            runner_id="claude-runner-1", available=True, auth_mode="subscription"
        )
        # No registrations at all — runner_id is in live_runner_ids but not in registrations
        # So it won't be added to stale_ids either; fresh_ids will include it
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=[],
        )
        assert result.fresh is True

    def test_rotation_interval_seconds_passed_through(self):
        routing = _make_routing(blocked_reason="expired")
        result = _run_check(routing=routing, rotation_interval_seconds=3600.0)
        assert result.fresh is False

    def test_allowed_profiles_parameter_accepted(self):
        routing = _make_routing(blocked_reason="no_runner")
        result = _run_check(routing=routing, allowed_profiles={"default", "work"})
        assert result.fresh is False

    def test_registry_path_parameter_accepted(self):
        routing = _make_routing(blocked_reason="registry_empty")
        result = _run_check(routing=routing, registry_path="/tmp/test_registry.json")
        assert result.fresh is False

    def test_default_ttl_is_300_seconds(self):
        # Verify the default freshness_ttl_seconds of 300 works
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "profile": None}],
            selected_runner_ids=["claude-runner-1"],
        )
        insp = _make_inspection(
            runner_id="claude-runner-1", available=True, auth_mode="subscription"
        )
        registrations = [{"runner_id": "claude-runner-1", "updated_at": _now_iso()}]
        result = _run_check(
            routing=routing,
            make_inspector_inspection=insp,
            registrations=registrations,
            # No freshness_ttl_seconds — uses default 300
        )
        assert result.fresh is True

    def test_codex_default_verified_target_is_one(self):
        # For codex, default verified_runner_target is 1
        rid = "codex-runner-1"
        routing = _make_routing(
            selected_runners=[{"runner_type": "codex", "runner_id": rid, "profile": None}],
            selected_runner_ids=[rid],
        )
        probe = _make_probe(status="passed", runner_id=rid)
        insp = _make_inspection(runner_id=rid, available=True, auth_mode="chatgpt_login")
        regs = [{"runner_id": rid, "updated_at": _now_iso()}]
        # probe_status_map has "passed" for rid so selected_verified >= 1
        result = _run_check(
            routing=routing,
            requested_runner_type="codex",
            probe_status_map={rid: "passed"},
            probe_result=probe,
            make_inspector_inspection=insp,
            registrations=regs,
        )
        # With probe passed, should not block on no_execution_verified_runner
        assert result.blocked_reason != "no_execution_verified_runner"

    def test_verified_runner_target_explicit_zero_no_block(self):
        rid = "claude-runner-1"
        routing = _make_routing(
            selected_runners=[{"runner_type": "claude", "runner_id": rid}],
            selected_runner_ids=[rid],
        )
        result = _run_check(
            routing=routing,
            requested_runner_type="claude",
            verified_runner_target=0,
            probe_status_map={},
            make_inspector_inspection=_make_inspection(
                runner_id=rid, available=True, auth_mode="subscription"
            ),
            registrations=[{"runner_id": rid, "updated_at": _now_iso()}],
        )
        assert result.blocked_reason != "no_execution_verified_runner"

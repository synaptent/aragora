"""Runner freshness checking for the Boss loop.

Verifies that at least one registered runner is fresh and eligible before
dispatching work.  Performs live re-inspection and registration age checks
against a configurable TTL.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc


@dataclass(slots=True)
class RunnerFreshnessResult:
    """Result of a runner freshness check."""

    fresh: bool
    runner_ids: list[str]
    checked_at: str
    blocked_reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fresh": self.fresh,
            "runner_ids": list(self.runner_ids),
            "checked_at": self.checked_at,
            "blocked_reason": self.blocked_reason,
            "details": dict(self.details),
        }


def _normalized_runner_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _verification_runner_type(
    *,
    requested_runner_type: str | None,
    routing: Any,
) -> str | None:
    requested = _normalized_runner_type(requested_runner_type)
    if requested not in {"claude", "codex"}:
        return None
    for item in getattr(routing, "selected_runners", []) or []:
        if not isinstance(item, dict):
            continue
        selected_type = _normalized_runner_type(item.get("runner_type"))
        if selected_type in {"claude", "codex"}:
            return selected_type
    return requested


def _selected_runner_probe_inspections(
    *,
    runner_type: str,
    routing: Any,
    make_runner_inspector: Any,
    env: dict[str, str] | None,
) -> list[Any]:
    inspections: list[Any] = []
    seen_ids: set[str] = set()
    for item in getattr(routing, "selected_runners", []) or []:
        if not isinstance(item, dict):
            continue
        if _normalized_runner_type(item.get("runner_type")) != runner_type:
            continue
        profile = str(item.get("profile", "") or "").strip() or None
        inspection = make_runner_inspector(
            runner_type,
            env=env,
            profile=profile,
            repo_root=Path.cwd(),
        ).inspect()
        runner_id = str(getattr(inspection, "runner_id", "") or "").strip()
        if not runner_id or runner_id in seen_ids:
            continue
        seen_ids.add(runner_id)
        inspections.append(inspection)
    return inspections


def check_runner_freshness(
    *,
    freshness_ttl_seconds: float = 300.0,
    registry_path: str | None = None,
    env: dict[str, str] | None = None,
    requested_runner_type: str | None = None,
    allowed_profiles: set[str] | None = None,
    rotation_interval_seconds: float = 1800.0,
    verified_runner_target: int | None = None,
    runner_probe_limit: int | None = None,
) -> RunnerFreshnessResult:
    """Verify that at least one registered runner is fresh and eligible.

    Freshness means:
    1. The runner registry resolves to at least one eligible runner
    2. A live re-inspection of the selected CLI runner confirms it is still available
    3. The runner's registration is not older than ``freshness_ttl_seconds``

    This is a synchronous check suitable for calling at each Boss loop iteration.
    """
    from aragora.swarm.runner_registry import (
        LocalRunnerRegistry,
        authorization_context_with_defaults,
        configured_claude_runner_profiles,
        make_runner_inspector,
        prioritized_probe_candidates,
        probe_runner_execution,
        refresh_discovered_runners,
    )

    now = datetime.now(UTC)
    checked_at = now.isoformat()
    owner_context = authorization_context_with_defaults(repo_root=Path.cwd(), env=env)

    if owner_context is None:
        return RunnerFreshnessResult(
            fresh=False,
            runner_ids=[],
            checked_at=checked_at,
            blocked_reason="missing_owner_context",
        )

    registry = LocalRunnerRegistry(path=registry_path) if registry_path else LocalRunnerRegistry()
    allowed_profile_set = set(allowed_profiles or configured_claude_runner_profiles(env))
    discovered_by_type: dict[str, list[Any]] = {}

    def _refresh_discovered(runner_type: str | None) -> list[Any]:
        normalized = _normalized_runner_type(runner_type)
        if not normalized:
            return []
        cached = discovered_by_type.get(normalized)
        if cached is not None:
            return cached
        discovered = refresh_discovered_runners(
            normalized,
            registry=registry,
            owner_context=owner_context,
            env=env,
            repo_root=Path.cwd(),
            profiles=allowed_profile_set or None,
        )
        discovered_by_type[normalized] = discovered
        return discovered

    if requested_runner_type:
        _refresh_discovered(requested_runner_type)
    routing = registry.resolve_boss_routing(
        owner_context=owner_context,
        requested_runner_type=requested_runner_type,
        allowed_profiles=allowed_profile_set or None,
        rotation_interval_seconds=rotation_interval_seconds,
    )
    probe_summary: dict[str, Any] = {
        "auto_probe_triggered": False,
        "attempted": 0,
        "passed": 0,
        "failed": 0,
        "verified_target": 0,
        "results": [],
    }
    verification_runner_type = _verification_runner_type(
        requested_runner_type=requested_runner_type,
        routing=routing,
    )
    probe_summary["verification_runner_type"] = verification_runner_type
    if verification_runner_type in {"claude", "codex"}:
        if verified_runner_target is None:
            default_verified_target = 2 if verification_runner_type == "claude" else 1
            try:
                verified_target = max(
                    0,
                    int(
                        str(
                            (env or os.environ).get(
                                "ARAGORA_BOSS_VERIFIED_RUNNER_TARGET",
                                str(default_verified_target),
                            )
                        )
                    ),
                )
            except ValueError:
                verified_target = default_verified_target
        else:
            verified_target = max(0, int(verified_runner_target))
        if runner_probe_limit is None:
            try:
                probe_limit = max(
                    1, int(str((env or os.environ).get("ARAGORA_BOSS_RUNNER_PROBE_LIMIT", "1")))
                )
            except ValueError:
                probe_limit = 1
        else:
            probe_limit = max(1, int(runner_probe_limit))
        selected_verified = len(
            [
                item
                for item in routing.selected_runners
                if isinstance(item, dict) and registry._probe_status(item) == "passed"
            ]
        )
        probe_summary["verified_target"] = verified_target
        if selected_verified < verified_target:
            probe_discoveries = list(_refresh_discovered(verification_runner_type))
            discovered_ids = {
                str(getattr(item, "runner_id", "") or "").strip() for item in probe_discoveries
            }
            for inspection in _selected_runner_probe_inspections(
                runner_type=verification_runner_type,
                routing=routing,
                make_runner_inspector=make_runner_inspector,
                env=env,
            ):
                runner_id = str(getattr(inspection, "runner_id", "") or "").strip()
                if not runner_id or runner_id in discovered_ids:
                    continue
                probe_discoveries.append(inspection)
                discovered_ids.add(runner_id)
            candidates = prioritized_probe_candidates(
                registry=registry,
                runner_type=verification_runner_type,
                discovered_inspections=probe_discoveries,
                owner_context=owner_context,
                selected_runners=routing.selected_runners,
            )
            for inspection in candidates[:probe_limit]:
                probe = probe_runner_execution(
                    inspection,
                    repo_root=Path.cwd(),
                )
                registry.record_probe(
                    inspection,
                    probe,
                    owner_context=owner_context,
                )
                probe_summary["results"].append(probe.to_dict())
                probe_summary["attempted"] += 1
                if probe.status == "passed":
                    probe_summary["passed"] += 1
                elif probe.status == "failed":
                    probe_summary["failed"] += 1
            if probe_summary["attempted"]:
                probe_summary["auto_probe_triggered"] = True
                routing = registry.resolve_boss_routing(
                    owner_context=owner_context,
                    requested_runner_type=requested_runner_type,
                    allowed_profiles=allowed_profile_set or None,
                    rotation_interval_seconds=rotation_interval_seconds,
                )
                verification_runner_type = _verification_runner_type(
                    requested_runner_type=requested_runner_type,
                    routing=routing,
                )
                probe_summary["verification_runner_type"] = verification_runner_type
        selected_verified = len(
            [
                item
                for item in routing.selected_runners
                if isinstance(item, dict) and registry._probe_status(item) == "passed"
            ]
        )
        if selected_verified == 0 and verified_target > 0:
            return RunnerFreshnessResult(
                fresh=False,
                runner_ids=routing.selected_runner_ids,
                checked_at=checked_at,
                blocked_reason="no_execution_verified_runner",
                details={"routing": routing.to_dict(), "probe": probe_summary},
            )

    if routing.is_blocked:
        return RunnerFreshnessResult(
            fresh=False,
            runner_ids=[],
            checked_at=checked_at,
            blocked_reason=routing.blocked_reason,
            details={"routing": routing.to_dict(), "probe": probe_summary},
        )

    # Live re-inspection: is a selected CLI runner still responding?
    live_runner_ids: list[str] = []
    live_inspections: list[dict[str, Any]] = []
    for selected in routing.selected_runners:
        runner_type = str(selected.get("runner_type", "")).strip() or "codex"
        live = make_runner_inspector(
            runner_type,
            env=env,
            profile=str(selected.get("profile", "")).strip() or None,
        ).inspect()
        live_inspections.append(live.to_dict())
        if live.available and live.auth_mode in {"chatgpt_login", "api_key", "subscription"}:
            live_runner_ids.append(live.runner_id)

    if not live_runner_ids:
        return RunnerFreshnessResult(
            fresh=False,
            runner_ids=routing.selected_runner_ids,
            checked_at=checked_at,
            blocked_reason="runner_not_responding",
            details={
                "routing": routing.to_dict(),
                "probe": probe_summary,
                "live_inspections": live_inspections,
            },
        )

    # Check registration age against TTL
    registrations = registry.list_registrations()
    stale_ids: list[str] = []
    for reg in registrations:
        runner_id = str(reg.get("runner_id", "")).strip()
        if runner_id not in routing.selected_runner_ids or runner_id not in live_runner_ids:
            continue
        updated_at = str(reg.get("updated_at") or reg.get("registered_at") or "").strip()
        if not updated_at:
            stale_ids.append(runner_id)
            continue
        try:
            reg_time = datetime.fromisoformat(updated_at)
            if reg_time.tzinfo is None:
                reg_time = reg_time.replace(tzinfo=UTC)
            age = (now - reg_time).total_seconds()
            if age > freshness_ttl_seconds:
                stale_ids.append(runner_id)
        except ValueError:
            stale_ids.append(runner_id)

    fresh_ids = [rid for rid in routing.selected_runner_ids if rid not in stale_ids]

    if not fresh_ids:
        return RunnerFreshnessResult(
            fresh=False,
            runner_ids=routing.selected_runner_ids,
            checked_at=checked_at,
            blocked_reason="all_runners_stale",
            details={
                "routing": routing.to_dict(),
                "probe": probe_summary,
                "stale_ids": stale_ids,
                "freshness_ttl_seconds": freshness_ttl_seconds,
            },
        )

    return RunnerFreshnessResult(
        fresh=True,
        runner_ids=fresh_ids,
        checked_at=checked_at,
        details={
            "routing": routing.to_dict(),
            "probe": probe_summary,
            "live_runner_ids": live_runner_ids,
            "live_inspections": live_inspections,
        },
    )

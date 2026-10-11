"""``aragora swarm runner`` subcommand.

``aragora.cli.commands.swarm`` dispatches ``swarm runner`` here and re-exports
``_run_runner_action``. The runner-registry functions are imported when the
command runs, so tests patch them on ``aragora.swarm.runner_registry``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from aragora.cli.commands.swarm_inputs import _probe_limit_arg
from aragora.cli.commands.swarm_render import _render_runner_report
from aragora.cli.commands.swarm_runner_payloads import (
    _build_multi_runner_payload,
    _build_runner_probe_payload,
    _build_runner_report_payload,
)

JsonDict = dict[str, Any]


def _run_runner_action(
    args: argparse.Namespace,
    *,
    goal: str | None,
    allowed_runner_profiles: set[str] | None,
    runner_rotation_interval: float,
    as_json: bool,
) -> None:
    """Handle ``aragora swarm runner [inspect|register|heartbeat|report|probe|maintain]``."""

    from aragora.swarm.reporter import render_runner_registration_text
    from aragora.swarm.runner_registry import (
        LocalRunnerRegistry,
        authorization_context_with_defaults,
        discover_runner_inspections,
        prioritized_probe_candidates,
        probe_runner_execution,
        refresh_discovered_runners,
    )

    payload: JsonDict

    subaction = str(goal or "inspect").strip().lower()
    if subaction not in {"inspect", "register", "heartbeat", "report", "probe", "maintain"}:
        print(
            "Error: swarm runner action must be 'inspect', 'register', 'heartbeat', "
            "'report', 'probe', or 'maintain'"
        )
        return

    runner_type = (
        str(
            getattr(args, "runner_type", None) or os.environ.get("ARAGORA_RUNNER_TYPE", "codex")
        ).strip()
        or "codex"
    )
    inspections: list[Any] = []
    probe_limit = _probe_limit_arg(args, default=1 if subaction == "maintain" else 2)
    if subaction == "register":
        inspections = discover_runner_inspections(
            runner_type,
            env=dict(os.environ),
            repo_root=Path.cwd(),
            profiles=allowed_runner_profiles or None,
        )
        owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
        payloads = [
            LocalRunnerRegistry()
            .register(
                inspection,
                owner_context=owner_context,
            )
            .to_dict()
            for inspection in inspections
        ]
        payload = (
            payloads[0]
            if len(payloads) == 1
            else _build_multi_runner_payload(subaction=subaction, runners=payloads)
        )
    elif subaction == "heartbeat":
        inspections = discover_runner_inspections(
            runner_type,
            env=dict(os.environ),
            repo_root=Path.cwd(),
            profiles=allowed_runner_profiles or None,
        )
        owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
        payloads = [
            LocalRunnerRegistry()
            .heartbeat(
                inspection,
                owner_context=owner_context,
            )
            .to_dict()
            for inspection in inspections
        ]
        payload = (
            payloads[0]
            if len(payloads) == 1
            else _build_multi_runner_payload(subaction=subaction, runners=payloads)
        )
    elif subaction == "report":
        owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
        registry = LocalRunnerRegistry()
        inspections = (
            refresh_discovered_runners(
                runner_type,
                registry=registry,
                owner_context=owner_context,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
            if owner_context is not None
            else discover_runner_inspections(
                runner_type,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
        )
        payload = _build_runner_report_payload(
            registrations=registry.list_registrations(),
            routing=registry.resolve_boss_routing(
                owner_context=owner_context,
                requested_runner_type=runner_type,
                allowed_profiles=allowed_runner_profiles,
                rotation_interval_seconds=runner_rotation_interval,
            ).to_dict(),
            discovered=[item.to_dict() for item in inspections],
        )
    elif subaction == "probe":
        owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
        registry = LocalRunnerRegistry()
        inspections = discover_runner_inspections(
            runner_type,
            env=dict(os.environ),
            repo_root=Path.cwd(),
            profiles=allowed_runner_profiles or None,
        )
        routing_before = (
            registry.resolve_boss_routing(
                owner_context=owner_context,
                requested_runner_type=runner_type,
                allowed_profiles=allowed_runner_profiles,
                rotation_interval_seconds=runner_rotation_interval,
            ).to_dict()
            if owner_context is not None
            else None
        )
        probe_payloads: list[dict[str, object]] = []
        for inspection in inspections[:probe_limit]:
            probe = probe_runner_execution(
                inspection,
                repo_root=Path.cwd(),
            )
            probe_payloads.append(
                registry.record_probe(
                    inspection,
                    probe,
                    owner_context=owner_context,
                )
            )
        routing_after = (
            registry.resolve_boss_routing(
                owner_context=owner_context,
                requested_runner_type=runner_type,
                allowed_profiles=allowed_runner_profiles,
                rotation_interval_seconds=runner_rotation_interval,
            ).to_dict()
            if owner_context is not None
            else None
        )
        payload = _build_runner_probe_payload(
            subaction=subaction,
            runners=probe_payloads,
            discovered=[item.to_dict() for item in inspections],
            routing_before=routing_before,
            routing_after=routing_after,
        )
    elif subaction == "maintain":
        owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
        registry = LocalRunnerRegistry()
        inspections = (
            refresh_discovered_runners(
                runner_type,
                registry=registry,
                owner_context=owner_context,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
            if owner_context is not None
            else discover_runner_inspections(
                runner_type,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
        )
        routing_before = (
            registry.resolve_boss_routing(
                owner_context=owner_context,
                requested_runner_type=runner_type,
                allowed_profiles=allowed_runner_profiles,
                rotation_interval_seconds=runner_rotation_interval,
            ).to_dict()
            if owner_context is not None
            else None
        )
        candidates = (
            prioritized_probe_candidates(
                registry=registry,
                runner_type=runner_type,
                discovered_inspections=inspections,
                owner_context=owner_context,
                selected_runners=(
                    list(routing_before.get("selected_runners", []))
                    if isinstance(routing_before, dict)
                    else None
                ),
            )
            if owner_context is not None
            else list(inspections)
        )
        if not candidates:
            candidates = list(inspections)
        probe_payloads = []
        for inspection in candidates[:probe_limit]:
            probe = probe_runner_execution(
                inspection,
                repo_root=Path.cwd(),
            )
            probe_payloads.append(
                registry.record_probe(
                    inspection,
                    probe,
                    owner_context=owner_context,
                )
            )
        routing_after = (
            registry.resolve_boss_routing(
                owner_context=owner_context,
                requested_runner_type=runner_type,
                allowed_profiles=allowed_runner_profiles,
                rotation_interval_seconds=runner_rotation_interval,
            ).to_dict()
            if owner_context is not None
            else None
        )
        payload = _build_runner_probe_payload(
            subaction=subaction,
            runners=probe_payloads,
            discovered=[item.to_dict() for item in inspections],
            routing_before=routing_before,
            routing_after=routing_after,
        )
    else:
        inspections = discover_runner_inspections(
            runner_type,
            env=dict(os.environ),
            repo_root=Path.cwd(),
            profiles=allowed_runner_profiles or None,
        )
        inspection_payloads = [item.to_dict() for item in inspections]
        payload = (
            inspection_payloads[0]
            if len(inspection_payloads) == 1
            else _build_multi_runner_payload(subaction=subaction, runners=inspection_payloads)
        )

    payload["mode"] = "runner"
    payload["action"] = subaction
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if subaction == "report":
            _render_runner_report(payload)
        elif subaction in {"probe", "maintain"}:
            probe_summary = (
                payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
            )
            print(
                "Runner {action} discovered={discovered} attempted={attempted} "
                "passed={passed} failed={failed}".format(
                    action=subaction,
                    discovered=probe_summary.get("discovered", 0),
                    attempted=probe_summary.get("attempted", 0),
                    passed=probe_summary.get("passed", 0),
                    failed=probe_summary.get("failed", 0),
                )
            )
            print()
            for item in [entry for entry in payload.get("runners", []) if isinstance(entry, dict)]:
                print(render_runner_registration_text(item))
                print()
        elif "runners" in payload:
            runner_summary = (
                payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
            )
            print(
                "Runner {action} count={count} available={available} registered={registered}".format(
                    action=subaction,
                    count=runner_summary.get("count", 0),
                    available=runner_summary.get("available", 0),
                    registered=runner_summary.get("registered", 0),
                )
            )
            print()
            for item in [entry for entry in payload.get("runners", []) if isinstance(entry, dict)]:
                print(render_runner_registration_text(item))
                print()
        else:
            print(render_runner_registration_text(payload))
    return

"""Plain-text renderers for review-queue packets.

Extracted from ``review_queue.py`` (#8553 extraction plan: the file sits at
its 6000-LOC bridge ceiling and must shrink, not grow). Pure presentation:
these helpers format packets for the operator terminal and hold no gate or
settlement logic. ``review_queue.py`` re-exports them under their historical
private names, so call sites and tests are unchanged.
"""

from __future__ import annotations

import sqlite3
import sys
from typing import TYPE_CHECKING, Any

from aragora.cli.commands import review_queue_unstable as unstable

if TYPE_CHECKING:
    from aragora.cli.commands.review_queue import ReviewPacket


def render_active_auto_handle_alerts() -> None:
    # Late import: review_queue imports this module at load time, and the
    # calibration-store wrapper lives there (its impl is itself lazy).
    from aragora.cli.commands.review_queue import AutoHandleCalibrationStore

    try:
        alerts = AutoHandleCalibrationStore().list_active_alerts(limit=3)
    except (OSError, RuntimeError, sqlite3.Error, ValueError, TypeError) as exc:
        print(f"warning: auto-handle calibration unavailable: {exc}", file=sys.stderr)
        return
    if not alerts:
        return
    print()
    print("ACTIVE AUTO-HANDLE DRIFT ALERTS:")
    for alert in alerts:
        current_rate = (
            f"{alert.current_success_rate:.1%}"
            if alert.current_success_rate is not None
            else "unknown"
        )
        print(
            f"  - {alert.auto_handle_path}: {alert.decision_class} "
            f"(success={current_rate}, action={alert.remediation_action})"
        )


def render_packet(packet: ReviewPacket) -> None:
    print(f"# Advisory review packet — PR #{packet.pr_number}")
    print(f"# {packet.title}")
    print(f"# {packet.url}")
    print()
    print(f"head SHA:        {packet.head_sha}")
    print(f"base SHA:        {packet.base_sha}")
    print(f"packet SHA:      {packet.packet_sha}")
    print(f"author:          {packet.author}")
    print(f"draft:           {packet.is_draft}")
    print(f"queue bucket:    {packet.queue_bucket}")
    print(
        f"diff:            +{packet.additions}/-{packet.deletions} "
        f"across {packet.changed_files} files"
    )
    print(f"checks:          {packet.checks_summary}")
    if packet.check_surfaces:
        rollup = packet.check_surfaces.get("pr_rollup") or {}
        direct = packet.check_surfaces.get("direct_commit_check_runs") or {}
        required = packet.check_surfaces.get("required_pr_checks") or {}
        print(
            "check surfaces:  "
            f"pr_rollup_available={str(bool(rollup.get('available'))).lower()} "
            f"pr_rollup_count={rollup.get('count')}"
        )
        if required:
            gate_selected = str(bool(required.get("gate_selected"))).lower()
            print(
                "                 "
                f"required_pr_checks={required.get('total', 0)} "
                f"summary={required.get('summary')} "
                f"gate_selected={gate_selected}"
            )
            gate_blocked_reason = str(required.get("gate_blocked_reason") or "").strip()
            if gate_blocked_reason:
                print(f"                 required_gate_blocker: {gate_blocked_reason}")
        non_required_rollup_sample = rollup.get("non_required_non_green_sample") or []
        if non_required_rollup_sample:
            print(
                "                 "
                "non_required_non_green_rollup="
                + ", ".join(str(item) for item in non_required_rollup_sample[:3])
            )
        optional_noise_sample = rollup.get("optional_runner_capacity_noise_sample") or []
        if optional_noise_sample:
            print(
                "                 "
                "optional_runner_capacity_noise="
                + ", ".join(str(item) for item in optional_noise_sample[:3])
            )
        long_queued_shadow_sample = (
            rollup.get("long_queued_self_hosted_shadow_without_runner_metadata_sample") or []
        )
        if long_queued_shadow_sample:
            print(
                "                 "
                "long_queued_self_hosted_shadow_without_runner_metadata="
                + ", ".join(str(item) for item in long_queued_shadow_sample[:3])
            )
        if direct:
            print(
                "                 "
                f"direct_commit_check_runs={direct.get('total', 0)} "
                f"successful_required={len(direct.get('successful_required_contexts') or [])}"
            )
        diagnosis = str(packet.check_surfaces.get("diagnosis") or "").strip()
        if diagnosis:
            print(f"                 diagnosis: {diagnosis}")
        remediation = str(packet.check_surfaces.get("remediation_prompt") or "").strip()
        if remediation:
            print(f"                 remediation: {remediation}")
    print()
    if packet.touched_subsystems:
        print("touched subsystems:")
        for sub in packet.touched_subsystems:
            print(f"  - {sub}")
        print()
    if packet.high_risk_paths_touched:
        print("HIGH-RISK PATHS TOUCHED:")
        for path in packet.high_risk_paths_touched:
            print(f"  - {path}")
        print()
    if packet.validation:
        print("validation:")
        for line in packet.validation:
            print(f"  - {line}")
        print()
    if packet.risk_flags:
        print("risk flags:")
        for flag in packet.risk_flags:
            print(f"  - {flag}")
        print()
    print(f"machine recommendation: {packet.machine_recommendation}")
    print(f"  reason: {packet.machine_recommendation_reason}")
    if packet.protocol:
        protocol = packet.protocol
        binding = protocol.get("binding") or {}
        cost_estimate = protocol.get("cost_estimate") or {}
        print()
        print("protocol:")
        print(
            f"  {protocol.get('protocol_version', 'unknown')} [{protocol.get('status', 'unknown')}]"
        )
        print(
            f"  binding: {binding.get('repo', '')} "
            f"PR #{binding.get('pr_number', packet.pr_number)} "
            f"{binding.get('base_sha', packet.base_sha)}..{binding.get('head_sha', packet.head_sha)}"
        )
        print(
            f"  confidence: {protocol.get('confidence', 0):.2f} "
            f"({protocol.get('confidence_basis', 'unknown')})"
        )
        print(f"  dissent: {protocol.get('dissent_summary', '')}")
        availability_summary = protocol.get("availability_summary") or {}
        if availability_summary:
            print(
                "  availability: "
                f"{availability_summary.get('resolved_slots', 0)}/"
                f"{availability_summary.get('total_slots', 0)} slots resolved"
            )
            unresolved_slots = availability_summary.get("unresolved_slots") or []
            if unresolved_slots:
                unresolved = ", ".join(str(slot) for slot in unresolved_slots)
                print(f"    unresolved: {unresolved}")
            opt_in_slots = availability_summary.get("opt_in_slots") or []
            if opt_in_slots:
                opt_in = ", ".join(str(slot) for slot in opt_in_slots)
                print(f"    opt-in: {opt_in}")
        print(
            f"  cost estimate: ${cost_estimate.get('low', 0):.2f}"
            f"-${cost_estimate.get('high', 0):.2f}"
        )
        top_findings = protocol.get("top_findings") or []
        if top_findings:
            print("  top findings:")
            for finding in top_findings[:3]:
                if not isinstance(finding, dict):
                    continue
                severity = str(finding.get("severity", "")).strip()
                summary = str(finding.get("summary", "")).strip()
                print(f"    - [{severity}] {summary}")
        provider_slots = protocol.get("provider_slots") or []
        if provider_slots:
            print("  provider slots:")
            for slot in provider_slots:
                if not isinstance(slot, dict):
                    continue
                selected = slot.get("selected_provider") or "unresolved"
                print(
                    f"    - {slot.get('slot_id')}: {selected} "
                    f"({slot.get('family')}/{slot.get('lens')})"
                )
    if packet.model_review_quorum:
        quorum = packet.model_review_quorum
        print()
        print("model review quorum:")
        print(f"  tier: Tier {quorum.get('tier')} ({quorum.get('tier_name', 'unknown')})")
        print(f"  status: {quorum.get('status', 'unknown')}")
        print(f"  verdict: {quorum.get('verdict', 'unknown')}")
        print(f"  admin squash allowed: {quorum.get('admin_squash_allowed', False)}")
        print(
            "  human risk settlement required: "
            f"{quorum.get('requires_human_risk_settlement', False)}"
        )
        print(
            "  signals: "
            f"{len(quorum.get('counted_reviewer_ids') or [])}/"
            f"{quorum.get('required_model_signals', 0)}"
        )
        if quorum.get("counted_reviewer_ids"):
            print(f"  counted reviewers: {', '.join(quorum.get('counted_reviewer_ids') or [])}")
        if quorum.get("unresolved_dissent"):
            print("  unresolved dissent: true")
        for reason in quorum.get("reasons") or []:
            print(f"    - {reason}")
    print()
    print(f"generated at: {packet.generated_at}")
    render_active_auto_handle_alerts()
    print()
    print(f"-- {packet.settlement_note}")


def render_merge_authorization_packet(packet: dict[str, Any]) -> None:
    from aragora.cli.commands.review_queue import MODEL_REVIEW_QUEUE_CAP

    queue = packet.get("queue_pressure") or {}
    print("# Merge authorization packet")
    print(f"generated at: {packet.get('generated_at', '')}")
    print(
        "queue pressure: "
        f"{queue.get('current_open_prs', 0)} open / cap {queue.get('cap', MODEL_REVIEW_QUEUE_CAP)} "
        f"(active={queue.get('active', False)})"
    )
    if queue.get("active"):
        print(
            "new implementation PRs: frozen; only review/dogfood/fix-existing/spec-only work allowed"
        )
    print()
    print("authorization sentence:")
    print(packet.get("authorization_sentence", ""))
    print()

    admin_order = packet.get("admin_squash_order") or []
    human_required = packet.get("human_risk_settlement_required") or []
    not_ready = packet.get("not_ready") or []
    print(f"admin squash order: {', '.join(f'#{n}' for n in admin_order) or '(none)'}")
    print(
        f"human risk settlement required: {', '.join(f'#{n}' for n in human_required) or '(none)'}"
    )
    print(f"not ready: {', '.join(f'#{n}' for n in not_ready) or '(none)'}")
    print()

    for entry in packet.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        print(
            f"#{entry.get('pr_number')} | Tier {entry.get('tier')} | "
            f"{entry.get('status')} | {entry.get('verdict')}"
        )
        print(f"  {entry.get('title', '')}")
        print(f"  head: {entry.get('head_sha', '')}")
        print(f"  checks: {entry.get('checks_summary', '')}")
        surfaces = entry.get("check_surfaces") or {}
        if isinstance(surfaces, dict) and surfaces:
            rollup = surfaces.get("pr_rollup") or {}
            direct = surfaces.get("direct_commit_check_runs") or {}
            print(
                "  check surfaces: "
                f"pr_rollup_available={str(bool(rollup.get('available'))).lower()} "
                f"pr_rollup_count={rollup.get('count')}"
            )
            if direct:
                print(
                    "  direct checks: "
                    f"total={direct.get('total', 0)}, "
                    f"successful_required={len(direct.get('successful_required_contexts') or [])}, "
                    f"non_green={direct.get('non_green_count', 0)}"
                )
            remediation = str(surfaces.get("remediation_prompt") or "").strip()
            if remediation:
                print(f"  remediation: {remediation}")
        print(
            "  evidence: "
            f"{len(entry.get('reviewer_signals') or [])} reviewer signal(s), "
            f"{len(entry.get('dogfood_evidence') or [])} dogfood note(s), "
            f"{len(entry.get('counted_reviewer_ids') or [])} counted reviewer(s)"
        )
        unstable.render_verified_cancellations(entry)
        gate_blockers = entry.get("admin_squash_gate_blockers") or []
        if gate_blockers:
            print("  admin squash live-gate blockers:")
            for blocker in gate_blockers:
                print(f"    - {blocker}")
        for reason in entry.get("reasons") or []:
            print(f"  - {reason}")
        print()
